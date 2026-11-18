"""Per-connection browser transport for MySQL's native WebAuthn plugin.

Private Connector/Python API: pinned to 26.10.0. No global monkey patches.
MySQL, never this adapter, decides whether the signature authenticates the user.
"""
from dataclasses import dataclass
from typing import Callable

import mysql.connector
from mysql.connector.authentication import MySQLAuthenticator
from mysql.connector.connection import MySQLConnection
from mysql.connector.constants import ClientFlag, ServerCmd
from mysql.connector.errors import get_exception
from mysql.connector.plugins import MySQLAuthPlugin

from .codec import BridgeError, Challenge, Reader, assertion_packet, b64u, registration_packet

TESTED_CONNECTOR = '26.10.0'


@dataclass
class Exchange:
    origin: str
    rp_id: str
    ask: Callable
    registering: bool = False
    pending: bool = False
    asserted: bool = False
    factor: int = 0


class BrowserPlugin(MySQLAuthPlugin):
    name = 'authentication_webauthn_client'
    requires_ssl = False  # Transport TLS policy is enforced by Gateway below.

    def auth_response(self, auth_data, **kwargs):
        raise BridgeError('WebAuthn must be factor 2, after the password')

    def auth_switch_response(self, sock, auth_data, **kwargs):
        exchange = self.exchange
        if not auth_data:
            if not exchange.registering:
                raise BridgeError('This account needs YubiKey registration first')
            exchange.pending = True
            # Empty WebAuthn challenge is MySQL's pending-registration sandbox.
            # Do not fabricate or send an authentication response.
            return bytes(sock.recv())
        if exchange.registering:
            raise BridgeError('The account already has a registered key. '
                              'An administrator must explicitly unregister it before replacement.')
        challenge = Challenge.parse(auth_data)
        options = challenge.options(exchange.rp_id)
        # Request the stored credential ID from MySQL, as the native client's
        # non-discovery path does. A concrete allow-list avoids resident-key
        # discovery, which can require PIN even when UV is discouraged.
        sock.send(b'\x01')
        credential_packet = bytes(sock.recv())
        if len(credential_packet) < 5:
            raise BridgeError('Incomplete MySQL credential-ID response')
        if credential_packet[4] == 0xff:
            raise get_exception(credential_packet)
        if credential_packet[4] != 0x01:
            raise BridgeError('Expected MySQL AuthMoreData for credential-ID response')
        # Connector's auth_more_response normally receives packet[5:], with
        # both the four-byte header and AuthMoreData tag already removed.
        body = credential_packet[5:]
        credential_id = b''
        if body:
            try:
                reader = Reader(body)
                credential_id = reader.blob()
                reader.end()
            except BridgeError as error:
                raise BridgeError('Malformed MySQL credential-ID response') from error
        # MySQL may omit the ID for resident credentials. Browser discovery is
        # then necessary, and browser/key policy may require PIN despite UV
        # being discouraged. Never invent a credential ID or alter signed data.
        if credential_id:
            options['allowCredentials'] = [{'type': 'public-key', 'id': b64u(credential_id)}]
        credential = exchange.ask('get', options)
        payload = assertion_packet(credential, challenge, exchange.origin)
        sock.send(payload)
        exchange.asserted = True
        return bytes(sock.recv())


class BrowserAuthenticator(MySQLAuthenticator):
    def __init__(self, exchange):
        super().__init__()
        self.exchange = exchange

    def _switch_auth_strategy(self, new_strategy_name, strategy_class=None,
                              username=None, password_factor=1):
        if new_strategy_name == 'authentication_webauthn_client':
            if password_factor != 2:
                raise BridgeError('This profile supports password factor 1 + WebAuthn factor 2 only')
            self.exchange.factor = password_factor
            plugin = BrowserPlugin(username or self._username, '', ssl_enabled=self.ssl_enabled)
            plugin.exchange = self.exchange
            self._auth_strategy = plugin
        else:
            if new_strategy_name not in {'caching_sha2_password', 'sha256_password'}:
                raise BridgeError('Unsupported authentication method in the browser gateway')
            super()._switch_auth_strategy(new_strategy_name, strategy_class, username, password_factor)


class BrowserConnection(MySQLConnection):
    def initiate_registration(self):
        """Read INITIATE's special result, which can omit the metadata EOF.

        sql_user.cc sends this result with SEND_NUM_ROWS, without SEND_EOF.
        Keep this exception local to registration; normal SQL uses the connector.
        """
        query = b'ALTER USER USER() 2 FACTOR INITIATE REGISTRATION'
        if self._client_flags & ClientFlag.CLIENT_QUERY_ATTRIBUTES:
            query = b'\x00\x01' + query  # zero attributes, one parameter set
        packet = self._send_cmd(ServerCmd.QUERY, query)
        if packet[4] == 0xff:
            raise get_exception(packet)
        if self._protocol.parse_column_count(packet) != 2:
            raise BridgeError('Unexpected INITIATE result shape; expected two columns')
        for _ in range(2):
            column = self._socket.recv(self._read_timeout)
            if column[4] == 0xff:
                raise get_exception(column)
            self._protocol.parse_column(column, self.python_charset)
        packet = self._socket.recv(self._read_timeout)
        # Also accept conventional result sets with a metadata EOF separator.
        if packet[4] == 0xfe and len(packet) < 13:
            self._handle_eof(packet)
            packet = self._socket.recv(self._read_timeout)
        if packet[4] == 0xff:
            raise get_exception(packet)
        row = Reader(packet[4:])
        values = (row.blob(), row.blob())
        row.end()
        eof = self._socket.recv(self._read_timeout)
        self._handle_eof(eof)
        return values

    def __init__(self, exchange, **config):
        super().__init__()
        self.exchange = exchange
        self._authenticator = BrowserAuthenticator(exchange)
        try:
            self.connect(**config)
            if exchange.factor != 2:
                raise BridgeError('MySQL did not request WebAuthn factor 2; connection rejected')
            if not exchange.registering and not exchange.asserted:
                raise BridgeError('No browser assertion was sent; connection rejected')
            if exchange.registering and not exchange.pending:
                raise BridgeError('MySQL did not enter pending-registration mode')
        except BaseException:
            self.shutdown()
            raise

    def _post_connection(self):
        # SET NAMES/autocommit and COM_PING are forbidden in registration sandbox.
        # Authentication has completed in MySQL before normal setup is allowed.
        if not self.exchange.registering:
            if self.exchange.factor != 2 or not self.exchange.asserted:
                raise BridgeError('MySQL did not complete browser WebAuthn factor 2')
            super()._post_connection()


class Gateway:
    def __init__(self, db_config, origin, rp_id, *, allow_loopback_plaintext=False):
        if mysql.connector.__version__ != TESTED_CONNECTOR:
            raise BridgeError(f'Private connector API: install mysql-connector-python=={TESTED_CONNECTOR}')
        if origin != 'https://' + rp_id:
            raise BridgeError('This protocol profile requires origin=https://RP_ID on port 443')
        from .config import mysql_config
        if db_config is None:
            raise BridgeError('Gateway requires an explicit MySQL transport mapping with host and port')
        self.db_config = mysql_config(db_config)
        self.origin, self.rp_id = origin, rp_id
        host = self.db_config['host']
        if not (allow_loopback_plaintext and host in {'127.0.0.1', '::1', 'localhost'}):
            if self.db_config.get('ssl_disabled') or not (self.db_config.get('ssl_ca') and self.db_config.get('ssl_verify_cert')
                    and self.db_config.get('ssl_verify_identity')):
                if host in {'127.0.0.1', '::1', 'localhost'}:
                    raise BridgeError('Local MySQL requires verified TLS or the explicit development setting '
                                      'ALLOW_LOOPBACK_DB_PLAINTEXT=1')
                raise BridgeError('Remote MySQL requires DB_SSL_CA and certificate/hostname verification')
        if any(key in self.db_config for key in ('user', 'password', 'password1', 'pool_name', 'pool_size', 'database')):
            raise BridgeError('Gateway configuration must not contain shared credentials, pools, or an initial database')

    def connect(self, username, password, ask):
        """Return this user's MySQL-accepted connection; caller owns and closes it."""
        exchange = Exchange(self.origin, self.rp_id, ask)
        return BrowserConnection(exchange, user=username, password1=password, **self.db_config)

    def register(self, username, password, ask, *, on_command=None):
        """Run INITIATE and FINISH on the same restricted connection; no key stored here."""
        exchange = Exchange(self.origin, self.rp_id, ask, registering=True)
        connection = BrowserConnection(exchange, user=username, password1=password, **self.db_config)
        try:
            if on_command:
                on_command('ALTER USER USER() 2 FACTOR INITIATE REGISTRATION')
            encoded, plugin = connection.initiate_registration()
            if isinstance(plugin, bytes):
                plugin = plugin.decode('ascii')
            if plugin != 'authentication_webauthn_client':
                raise BridgeError('INITIATE returned a different client plugin')
            challenge = Challenge.parse(encoded, registration=True)
            options = challenge.options(self.rp_id, registration=True)
            credential = ask('create', options)
            response = registration_packet(credential, challenge, self.origin)
            # base64 alphabet contains no SQL quote/backslash characters.
            if on_command:
                on_command("ALTER USER USER() 2 FACTOR FINISH REGISTRATION SET CHALLENGE_RESPONSE AS '<redacted>'")
            result = connection.cmd_query(
                "ALTER USER USER() 2 FACTOR FINISH REGISTRATION "
                "SET CHALLENGE_RESPONSE AS '" + response + "'"
            )
            if 'affected_rows' not in result:
                raise BridgeError('MySQL did not return an OK result for FINISH REGISTRATION')
            return {'registered': True, 'verified_by': 'MySQL FINISH REGISTRATION OK'}
        finally:
            connection.close()
