"""Software authenticator for tests only; never imported by the application."""
import datetime
import hashlib
import json

import cbor2
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from mysql_fido_gateway.codec import b64u


class SoftwareKey:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.attestation_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = bytes(range(64))
        self.counter = 0
        self.user_verified = True
        self.authenticator_extensions = {}
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'TEST KEY ONLY')])
        now = datetime.datetime.now(datetime.timezone.utc)
        self.cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                     .public_key(self.attestation_key.public_key()).serial_number(1)
                     .not_valid_before(now - datetime.timedelta(days=1))
                     .not_valid_after(now + datetime.timedelta(days=1))
                     .sign(self.attestation_key, hashes.SHA256())
                     .public_bytes(serialization.Encoding.DER))

    def __call__(self, operation, options):
        self.counter += 1
        create = operation == 'create'
        client = json.dumps({'type': 'webauthn.create' if create else 'webauthn.get',
                             'challenge': options['challenge'], 'origin': 'https://localhost',
                             'crossOrigin': False, 'extra_browser_field': 'preserved'},
                            separators=(',', ':')).encode()
        flags = 0x45 if create else (5 if self.user_verified else 1)
        raw = hashlib.sha256(b'localhost').digest() + bytes([flags]) + self.counter.to_bytes(4, 'big')
        if create:
            numbers = self.key.public_key().public_numbers()
            cose = {1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big')}
            raw += bytes(16) + len(self.credential_id).to_bytes(2, 'big') + self.credential_id + cbor2.dumps(cose)
            if self.authenticator_extensions:
                raw = raw[:32] + bytes([raw[32] | 0x80]) + raw[33:]
                raw += cbor2.dumps(self.authenticator_extensions)
            signature = self.attestation_key.sign(raw + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
            statement = {'alg': -7, 'sig': signature, 'x5c': [self.cert]}
            response = {'attestationObject': b64u(cbor2.dumps({'fmt': 'packed', 'authData': raw, 'attStmt': statement})),
                        'clientDataJSON': b64u(client)}
        else:
            signature = self.key.sign(raw + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
            response = {'authenticatorData': b64u(raw), 'signature': b64u(signature), 'clientDataJSON': b64u(client)}
        return {'type': 'public-key', 'id': b64u(self.credential_id),
                'rawId': b64u(self.credential_id), 'response': response}
