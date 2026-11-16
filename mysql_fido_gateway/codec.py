"""Strict browser/MySQL WebAuthn payload adapter (experimental protocol profile)."""
import base64
import hashlib
import io
import json
from dataclasses import dataclass

import cbor2


class BridgeError(Exception):
    """A closed-failure protocol, policy, or compatibility error."""


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def unb64u(value):
    if not isinstance(value, str) or len(value) > 180000:
        raise BridgeError('Invalid or oversized browser byte string')
    try:
        return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except (ValueError, TypeError) as error:
        raise BridgeError('Invalid base64url encoding') from error


def lc_int(value):
    if value < 0:
        raise BridgeError('Negative length')
    if value < 251:
        return bytes([value])
    if value < 65536:
        return b'\xfc' + value.to_bytes(2, 'little')
    if value < 16777216:
        return b'\xfd' + value.to_bytes(3, 'little')
    return b'\xfe' + value.to_bytes(8, 'little')


def lc_bytes(data):
    return lc_int(len(data)) + data


class Reader:
    def __init__(self, data):
        self.data, self.pos = bytes(data), 0

    def take(self, count):
        if count < 0 or self.pos + count > len(self.data):
            raise BridgeError('Truncated MySQL WebAuthn payload')
        out = self.data[self.pos:self.pos + count]
        self.pos += count
        return out

    def integer(self):
        first = self.take(1)[0]
        if first < 251:
            return first
        sizes = {252: 2, 253: 3, 254: 8}
        if first not in sizes:
            raise BridgeError('NULL/invalid length in WebAuthn payload')
        return int.from_bytes(self.take(sizes[first]), 'little')

    def blob(self):
        return self.take(self.integer())

    def end(self):
        if self.pos != len(self.data):
            raise BridgeError('Unexpected trailing MySQL WebAuthn data')


def cbor_value(raw):
    try:
        stream = io.BytesIO(raw)
        value = cbor2.CBORDecoder(stream).decode()
        if stream.read(1):
            raise BridgeError('Trailing CBOR data')
        return value
    except (ValueError, cbor2.CBORDecodeError) as error:
        raise BridgeError('Invalid CBOR attestation') from error


@dataclass(frozen=True)
class Challenge:
    flags: int
    salt: bytes
    rp_id: str
    account: bytes = b''

    @classmethod
    def parse(cls, raw, registration=False):
        if registration:
            try:
                raw = base64.b64decode(b''.join(raw.encode('ascii').split()) if isinstance(raw, str) else b''.join(raw.split()), validate=True)
            except (ValueError, TypeError) as error:
                raise BridgeError('Registration challenge is not standard base64') from error
        reader = Reader(raw)
        flags = reader.take(1)[0]
        salt = reader.blob()
        try:
            rp = reader.blob().decode('ascii')
        except UnicodeError as error:
            raise BridgeError('RP ID is not an ASCII domain') from error
        account = reader.blob() if registration else b''
        reader.end()
        if len(salt) != 32 or not rp or len(rp) > 253:
            raise BridgeError('Invalid MySQL challenge or RP ID')
        return cls(flags, salt, rp, account)

    def options(self, expected_rp, registration=False):
        if self.rp_id != expected_rp:
            raise BridgeError('MySQL RP ID differs from RP_ID. Do not rewrite signed challenges.')
        if registration:
            return {
                'challenge': b64u(self.salt),
                'rp': {'id': self.rp_id, 'name': 'MySQL Browser Gateway Prototype'},
                'user': {'id': b64u(hashlib.sha256(self.account).digest()),
                         'name': self.account.decode('utf-8', errors='replace'),
                         'displayName': self.account.decode('utf-8', errors='replace')},
                'pubKeyCredParams': [{'type': 'public-key', 'alg': -7}],
                'timeout': 120000, 'attestation': 'direct',
                'authenticatorSelection': {'authenticatorAttachment': 'cross-platform',
                                          'residentKey': 'required',
                                          'requireResidentKey': True,
                                          'userVerification': 'required'},
            }
        return {'challenge': b64u(self.salt), 'rpId': self.rp_id,
                'timeout': 120000, 'userVerification': 'required'}


def client_data(credential, challenge, origin, ceremony):
    try:
        if credential['type'] != 'public-key':
            raise BridgeError('Expected a public-key credential')
        raw = unb64u(credential['response']['clientDataJSON'])
        data = json.loads(raw)
        if (data.get('type') != ceremony or data.get('origin') != origin
                or unb64u(data.get('challenge')) != challenge.salt
                or data.get('crossOrigin', False) is not False
                or data.get('topOrigin') is not None):
            raise BridgeError('Browser origin, challenge, or ceremony mismatch')
        return raw
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        raise BridgeError('Invalid browser clientDataJSON') from error


def auth_data(raw, rp_id, registration=False):
    if not isinstance(raw, bytes) or len(raw) < 37:
        raise BridgeError('Truncated authenticator data')
    if raw[:32] != hashlib.sha256(rp_id.encode('ascii')).digest():
        raise BridgeError('Authenticator RP ID hash mismatch')
    flags = raw[32]
    if flags & 5 != 5:
        raise BridgeError('User presence and verification are required')
    if registration and not flags & 64:
        raise BridgeError('Attested credential data is missing')


def assertion_packet(credential, challenge, origin):
    data = client_data(credential, challenge, origin, 'webauthn.get')
    try:
        raw = unb64u(credential['response']['authenticatorData'])
        signature = unb64u(credential['response']['signature'])
    except KeyError as error:
        raise BridgeError('Incomplete assertion response') from error
    auth_data(raw, challenge.rp_id)
    if not signature:
        raise BridgeError('Missing signature')
    # libfido2/MySQL uses a CBOR byte-string wrapper around authenticator data.
    # Keep clientDataJSON byte-for-byte unchanged: it is covered by the signature.
    return b'\x02' + lc_int(1) + lc_bytes(cbor2.dumps(raw)) + lc_bytes(signature) + lc_bytes(data)


def registration_packet(credential, challenge, origin):
    data = client_data(credential, challenge, origin, 'webauthn.create')
    try:
        attestation = cbor_value(unb64u(credential['response']['attestationObject']))
        raw = attestation['authData']
        statement = attestation['attStmt']
        fmt = attestation['fmt']
    except (KeyError, TypeError) as error:
        raise BridgeError('Incomplete registration attestation') from error
    auth_data(raw, challenge.rp_id, registration=True)
    # Deliberately narrow, testable compatibility profile: YubiKey FIDO2 packed
    # ES256 attestation with x5c. No conversion of 'none' to fabricated attestation.
    if (fmt != 'packed' or statement.get('alg') != -7
            or not statement.get('x5c') or not statement.get('sig')):
        raise BridgeError('This prototype requires packed ES256 attestation with x5c. '
                          'The browser may have withheld attestation. No credential was sent to MySQL.')
    credential_id = unb64u(credential.get('rawId', ''))
    if len(raw) < 55:
        raise BridgeError('Missing attested credential ID')
    size = int.from_bytes(raw[53:55], 'big')
    if not size or raw[55:55 + size] != credential_id:
        raise BridgeError('Credential ID differs from attested ID')
    fields = [cbor2.dumps(raw), statement['sig'], statement['x5c'][0], data,
              cbor2.dumps(statement), fmt.encode('ascii')]
    # RESIDENT_KEYS | SEND_FULL_ATTESTATION_BLOB, matching the native client's profile.
    return base64.b64encode(b'\x03' + b''.join(lc_bytes(value) for value in fields)).decode('ascii')
