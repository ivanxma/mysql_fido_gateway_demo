"""Protocol test double, NOT an Enterprise MySQL compatibility claim.

Accepts real signed synthetic WebAuthn credentials and speaks MySQL packets so
Connector/Python's actual handshake, sandbox, SQL parsing and MFA paths execute.
"""
import base64
import hashlib
import json
import re
import secrets
import socket
import threading

import cbor2
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from mysql.connector.constants import ClientFlag

from mysql_fido_gateway.codec import Reader, lc_bytes, unb64u


def recv_exact(sock, n):
    result = b''
    while len(result) < n:
        chunk = sock.recv(n - len(result))
        if not chunk:
            raise EOFError
        result += chunk
    return result


def recv(sock):
    head = recv_exact(sock, 4)
    return head[3], recv_exact(sock, int.from_bytes(head[:3], 'little'))


def send(sock, seq, data):
    sock.sendall(len(data).to_bytes(3, 'little') + bytes([seq]) + data)


def ok(sock, seq):
    send(sock, seq, b'\0\0\0\x02\0\0\0')


def error(sock, seq, message):
    send(sock, seq, b'\xff\x15\x04#28000' + message.encode())


def resultset(sock, columns, values, *, metadata_eof=True):
    seq = 1
    send(sock, seq, bytes([len(columns)])); seq += 1
    for name in columns:
        field = b''.join(lc_bytes(v) for v in [b'def', b'', b'', b'', name.encode(), name.encode()])
        field += b'\x0c\x21\0' + (65535).to_bytes(4, 'little') + b'\xfd\0\0\0\0\0'
        send(sock, seq, field); seq += 1
    if metadata_eof:
        send(sock, seq, b'\xfe\0\0\x02\0'); seq += 1
    send(sock, seq, b''.join(lc_bytes(str(v).encode()) for v in values)); seq += 1
    send(sock, seq, b'\xfe\0\0\x02\0')


class FakeMySQL:
    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.listener.settimeout(.2)
        self.port = self.listener.getsockname()[1]
        self.stop = threading.Event()
        self.key = None
        self.credential_id = None
        self.credential_id_reply = None
        self.commands = []
        self.fido = True
        self.reject_signature = False
        self.registration_metadata_eof = False
        self.query_attributes = False
        self.errors = []
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(3)
        self.listener.close()

    def run(self):
        while not self.stop.is_set():
            try:
                sock, _ = self.listener.accept()
            except socket.timeout:
                continue
            with sock:
                sock.settimeout(3)
                try:
                    self.handle(sock)
                except (EOFError, ConnectionError):
                    pass
                except Exception as error_:
                    self.errors.append(error_)

    def handle(self, sock):
        caps = ClientFlag.get_default() | ClientFlag.MULTI_FACTOR_AUTHENTICATION | ClientFlag.PLUGIN_AUTH
        caps &= ~(ClientFlag.SSL | ClientFlag.COMPRESS | ClientFlag.SESSION_TRACK)
        if self.query_attributes:
            caps |= ClientFlag.CLIENT_QUERY_ATTRIBUTES
        nonce = b'01234567890123456789'
        handshake = (b'\x0a8.4.0-protocol-fixture\0' + (987).to_bytes(4, 'little') + nonce[:8] + b'\0'
                     + (caps & 65535).to_bytes(2, 'little') + b'\x2d\x02\0'
                     + (caps >> 16).to_bytes(2, 'little') + b'\x15' + bytes(10)
                     + nonce[8:] + b'\0caching_sha2_password\0')
        send(sock, 0, handshake)
        _, initial = recv(sock)
        # Verify the initial caching_sha2_password token, not just a dummy password.
        end_user = initial.index(0, 32)
        user = initial[32:end_user].decode()
        reader = Reader(initial[end_user + 1:]); token = reader.blob()
        p1 = hashlib.sha256(b'correct-password').digest()
        p2 = hashlib.sha256(p1).digest()
        p3 = hashlib.sha256(p2 + nonce).digest()
        expected = bytes(a ^ b for a, b in zip(p1, p3))
        if token != expected:
            error(sock, 2, 'Wrong password'); return
        salt = secrets.token_bytes(32)
        challenge = b'\x01' + lc_bytes(salt) + lc_bytes(b'localhost')
        if not self.fido:
            ok(sock, 2)
        elif self.key is None:
            send(sock, 2, b'\x02authentication_webauthn_client\0')
            ok(sock, 3)
        else:
            send(sock, 2, b'\x02authentication_webauthn_client\0' + challenge)
            sequence, packet = recv(sock)
            if packet == b'\x01':
                body = lc_bytes(self.credential_id) if self.credential_id_reply is None else self.credential_id_reply
                send(sock, sequence + 1, b'\x01' + body)
                sequence, packet = recv(sock)
            try:
                if self.reject_signature:
                    raise ValueError('Intentional test rejection')
                r = Reader(packet)
                assert r.take(1) == b'\x02' and r.integer() == 1
                auth = cbor2.loads(r.blob()); signature = r.blob(); client = r.blob(); r.end()
                self.validate_client(client, salt, 'webauthn.get')
                self.key.verify(signature, auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
                ok(sock, sequence + 1)
            except Exception:
                error(sock, sequence + 1, 'Invalid assertion'); return
        autocommit = True
        while True:
            _, packet = recv(sock)
            if packet[0] == 1:
                return
            if packet[0] == 14:  # COM_PING
                ok(sock, 1); continue
            assert packet[0] == 3, packet
            query_data = packet[1:]
            if self.query_attributes:
                assert query_data[:2] == b'\x00\x01'
                query_data = query_data[2:]
            query = query_data.decode()
            self.commands.append(query)
            if 'INITIATE REGISTRATION' in query:
                encoded = base64.b64encode(challenge + lc_bytes((user + '@localhost').encode())).decode()
                resultset(sock, ['challenge', 'client_plugin'], [encoded, 'authentication_webauthn_client'],
                          metadata_eof=self.registration_metadata_eof)
            elif 'FINISH REGISTRATION' in query:
                encoded = re.search(r"AS '([^']+)'", query).group(1)
                # Clearing RESIDENT_KEYS asks MySQL to retain the credential ID.
                r = Reader(base64.b64decode(encoded)); assert r.take(1) == b'\x02'
                auth = cbor2.loads(r.blob()); signature = r.blob(); cert = r.blob(); client = r.blob()
                statement = cbor2.loads(r.blob()); assert r.blob() == b'packed'; r.end()
                self.validate_client(client, salt, 'webauthn.create')
                assert statement['sig'] == signature and statement['x5c'][0] == cert
                x509.load_der_x509_certificate(cert).public_key().verify(
                    signature, auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
                size = int.from_bytes(auth[53:55], 'big')
                self.credential_id = auth[55:55 + size]
                cose = cbor2.loads(auth[55 + size:])
                self.key = ec.EllipticCurvePublicNumbers(int.from_bytes(cose[-2], 'big'),
                            int.from_bytes(cose[-3], 'big'), ec.SECP256R1()).public_key()
                ok(sock, 1)
            elif query == 'SELECT 1 AS alive':
                resultset(sock, ['alive'], [1])
            elif query == 'SELECT @@session.autocommit':
                resultset(sock, ['autocommit'], [int(autocommit)])
            elif query == 'SELECT @@session.sql_mode':
                resultset(sock, ['sql_mode'], [''])
            elif query.startswith('SET @@session.autocommit = '):
                autocommit = query.endswith('ON')
                ok(sock, 1)
            elif query.startswith("SELECT 'Hello World' AS message"):
                resultset(sock, ['message', 'mysql_account', 'connection_id'],
                          ['Hello World', user + '@localhost', 987])
            elif query.startswith("SELECT 'hello world'"):
                resultset(sock, ['hello', 'account', 'connection_id', 'version'],
                          ['hello world', user + '@localhost', 987, '8.4.0-protocol-fixture'])
            else:
                ok(sock, 1)

    @staticmethod
    def validate_client(raw, salt, ceremony):
        data = json.loads(raw)
        assert data['type'] == ceremony
        assert data['origin'] == 'https://localhost'
        assert unb64u(data['challenge']) == salt
