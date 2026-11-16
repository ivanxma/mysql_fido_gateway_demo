import base64
import copy
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

import mysql.connector

from mysql_fido_gateway import BridgeError, Gateway
from mysql_fido_gateway.broker import Broker, Flow
from mysql_fido_gateway.codec import Challenge, Reader, assertion_packet, b64u, lc_bytes, lc_int, registration_packet
from tests.fake_mysql import FakeMySQL
from tests.software_key import SoftwareKey


class CodecTests(unittest.TestCase):
    def setUp(self):
        self.challenge = Challenge(1, bytes(range(32)), 'localhost', b'demo_test@localhost')
        self.key = SoftwareKey()

    def test_lengths_and_truncation(self):
        for value in [0, 250, 251, 65535, 65536, 16777215, 16777216]:
            self.assertEqual(Reader(lc_int(value)).integer(), value)
        for data in [b'', b'\xfc', b'\xfb', b'\x04abc']:
            with self.assertRaises(BridgeError): Reader(data).blob()

    def test_rp_mismatch(self):
        with self.assertRaises(BridgeError): self.challenge.options('example.com')

    def test_assertion_preserves_client_bytes(self):
        credential = self.key('get', self.challenge.options('localhost'))
        packet = assertion_packet(credential, self.challenge, 'https://localhost')
        reader = Reader(packet); self.assertEqual(reader.take(1), b'\x02'); self.assertEqual(reader.integer(), 1)
        reader.blob(); reader.blob()
        self.assertIn(b'extra_browser_field', reader.blob()); reader.end()

    def test_wrong_origin_challenge_or_type_rejected(self):
        credential = self.key('get', self.challenge.options('localhost'))
        for field, value in [('origin', 'https://evil.example'), ('challenge', b64u(bytes(32))),
                             ('type', 'webauthn.create'), ('crossOrigin', True)]:
            bad = copy.deepcopy(credential)
            raw = json.loads(base64.urlsafe_b64decode(bad['response']['clientDataJSON'] + '=='))
            raw[field] = value; bad['response']['clientDataJSON'] = b64u(json.dumps(raw).encode())
            with self.assertRaises(BridgeError): assertion_packet(bad, self.challenge, 'https://localhost')

    def test_none_attestation_rejected(self):
        import cbor2
        credential = self.key('create', self.challenge.options('localhost', registration=True))
        raw = cbor2.loads(base64.urlsafe_b64decode(credential['response']['attestationObject'] + '=='))
        raw.update(fmt='none', attStmt={})
        credential['response']['attestationObject'] = b64u(cbor2.dumps(raw))
        with self.assertRaises(BridgeError): registration_packet(credential, self.challenge, 'https://localhost')


class BrokerTests(unittest.TestCase):
    def test_owner_replay_and_concurrent_isolation(self):
        broker = Broker(); first = broker.create('alice'); second = broker.create('bob')
        with self.assertRaises(BridgeError): broker.get(first.id, 'bob')
        results = []
        threads = [threading.Thread(target=lambda f=f: results.append(f.ask('get', {'rpId': 'localhost'})))
                   for f in [first, second]]
        for t in threads: t.start()
        one, two = first.events.get(timeout=1), second.events.get(timeout=1)
        with self.assertRaises(BridgeError): second.respond(one['request_id'], {})
        first.respond(one['request_id'], {'credential': {'id': 'alice'}})
        with self.assertRaises(BridgeError): first.respond(one['request_id'], {'credential': {}})
        second.respond(two['request_id'], {'credential': {'id': 'bob'}})
        for t in threads: t.join(1); self.assertFalse(t.is_alive())
        self.assertCountEqual(results, [{'id': 'alice'}, {'id': 'bob'}])

    def test_expiration(self):
        flow = Flow('alice', ttl=0)
        with self.assertRaises(BridgeError): flow.ask('get', {})
        with self.assertRaises(BridgeError): flow.respond('x', {})


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeMySQL()
        self.gateway = Gateway({'host': '127.0.0.1', 'port': self.server.port, 'ssl_disabled': True},
                               'https://localhost', 'localhost', allow_loopback_plaintext=True)
        self.key = SoftwareKey()

    def tearDown(self):
        self.server.close()
        self.assertEqual(self.server.errors, [])

    def test_real_connector_registration_then_login(self):
        result = self.gateway.register('demo_test', 'correct-password', self.key)
        self.assertTrue(result['registered'])
        with self.gateway.connect('demo_test', 'correct-password', self.key) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 'hello world', CURRENT_USER(), CONNECTION_ID(), @@version")
                self.assertEqual(cursor.fetchone()[0:2], ('hello world', 'demo_test@localhost'))
        initiate = next(i for i,q in enumerate(self.server.commands) if 'INITIATE' in q)
        finish = next(i for i,q in enumerate(self.server.commands) if 'FINISH' in q)
        self.assertEqual(finish, initiate + 1)  # no sandbox SET/PING between steps

    def test_password_rejected_by_mysql(self):
        with self.assertRaises(mysql.connector.Error):
            self.gateway.register('demo_test', 'wrong', self.key)

    def test_signature_rejected_by_mysql(self):
        self.gateway.register('demo_test', 'correct-password', self.key)
        other_key = SoftwareKey()
        with self.assertRaises(mysql.connector.Error):
            self.gateway.connect('demo_test', 'correct-password', other_key)

    def test_replayed_assertion_new_connection(self):
        self.gateway.register('demo_test', 'correct-password', self.key)
        saved = []
        def capture(operation, options):
            reply = self.key(operation, options)
            saved.append(reply)
            return reply
        connection = self.gateway.connect('demo_test', 'correct-password', capture)
        connection.close()
        with self.assertRaises(BridgeError):
            self.gateway.connect('demo_test', 'correct-password', lambda *args: saved[0])

    def test_no_fido_no_success(self):
        self.server.fido = False
        with self.assertRaises(BridgeError):
            self.gateway.connect('demo_test', 'correct-password', self.key)

    def test_pending_registration_cannot_login(self):
        with self.assertRaises(BridgeError):
            self.gateway.connect('demo_test', 'correct-password', self.key)


class WebTests(unittest.TestCase):
    def test_origin_csrf_and_cross_session(self):
        from app import create_app
        with patch.dict(os.environ, {'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost'}):
            app = create_app(gateway=object())
        first, second = app.test_client(), app.test_client()
        self.assertEqual(first.get('/', base_url='https://localhost').status_code, 200)
        self.assertEqual(first.post('/api/flows', base_url='https://localhost', json={}).status_code, 403)
        with first.session_transaction() as s: csrf, owner = s['csrf'], s['owner']
        headers = {'Origin': 'https://localhost', 'X-CSRF-Token': csrf}
        response = first.post('/api/flows', base_url='https://localhost', headers=headers,
                              json={'action': 'create', 'username': 'demo_test', 'password': 'secret'})
        self.assertEqual(response.status_code, 403)  # administrator access is never public
        flow = app.extensions['ceremony_broker'].create(owner)
        response = second.get('/api/flows/' + flow.id, base_url='https://localhost')
        self.assertEqual(response.status_code, 400)


class WebProtocolTests(unittest.TestCase):
    def test_http_registration_and_login_use_real_connector(self):
        from app import create_app
        server = FakeMySQL()
        try:
            gateway = Gateway({'host': '127.0.0.1', 'port': server.port, 'ssl_disabled': True},
                              'https://localhost', 'localhost', allow_loopback_plaintext=True)
            with patch.dict(os.environ, {'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost'}):
                app = create_app(gateway=gateway)
            browser = app.test_client()
            browser.get('/', base_url='https://localhost')
            with browser.session_transaction() as state: csrf = state['csrf']
            headers = {'Origin': 'https://localhost', 'X-CSRF-Token': csrf}
            key = SoftwareKey()
            def action(name, password='correct-password'):
                response = browser.post('/api/flows', base_url='https://localhost', headers=headers,
                                        json={'action': name, 'username': 'demo_test', 'password': password})
                self.assertEqual(response.status_code, 202)
                path = '/api/flows/' + response.json['flow_id']
                for _ in range(10):
                    event = browser.get(path, base_url='https://localhost').json
                    if event['type'] == 'waiting': continue
                    if event['type'] == 'webauthn':
                        credential = key(event['operation'], event['publicKey'])
                        reply = browser.post(path + '/respond', base_url='https://localhost', headers=headers,
                                             json={'request_id': event['request_id'], 'credential': credential})
                        self.assertEqual(reply.status_code, 200)
                    else: return event
                self.fail('HTTP ceremony did not finish')
            self.assertEqual(action('register')['type'], 'success')
            result = action('login')
            self.assertEqual(result['result']['message'], 'hello world')
            self.assertEqual(result['result']['mysql_account'], 'demo_test@localhost')
            server.reject_signature = True
            self.assertEqual(action('login')['type'], 'error')
            self.assertEqual(action('login', 'wrong')['type'], 'error')
        finally:
            server.close()
        self.assertEqual(server.errors, [])


if __name__ == '__main__': unittest.main()
