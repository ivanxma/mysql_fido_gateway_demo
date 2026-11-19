import base64
import copy
import json
import os
import threading
import time
import unittest
from unittest.mock import MagicMock, call, patch

import mysql.connector

from mysql_fido_gateway import BridgeError, Gateway
from mysql_fido_gateway.broker import Broker, Flow
from mysql_fido_gateway.codec import Challenge, Reader, assertion_packet, auth_data, b64u, lc_bytes, lc_int, registration_packet
from tests.fake_mysql import FakeMySQL
from tests.software_key import SoftwareKey


class CodecTests(unittest.TestCase):
    def test_presence_required_but_verification_only_required_for_registration(self):
        import hashlib
        prefix = hashlib.sha256(b'localhost').digest()
        auth_data(prefix + b'\x01' + bytes(4), 'localhost')
        with self.assertRaisesRegex(BridgeError, 'presence'):
            auth_data(prefix + b'\x04' + bytes(4), 'localhost')
        with self.assertRaisesRegex(BridgeError, 'verification'):
            auth_data(prefix + b'\x41' + bytes(4), 'localhost', registration=True)

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

    def test_registration_uses_credential_id_profile_with_required_verification(self):
        options = self.challenge.options('localhost', registration=True)
        self.assertEqual(options['authenticatorSelection'], {
            'authenticatorAttachment': 'cross-platform', 'residentKey': 'discouraged',
            'requireResidentKey': False, 'userVerification': 'required'})
        self.assertEqual(options['extensions'], {'credProps': True})
        self.assertEqual(options['hints'], ['security-key'])
        self.assertEqual(self.challenge.options('localhost')['hints'], ['security-key'])

    def test_registration_keeps_signed_bytes_without_requiring_credential_properties(self):
        credential = self.key('create', self.challenge.options('localhost', registration=True))
        for properties in [None, {'credProps': {'rk': False}}, {'credProps': {'rk': True}}]:
            with self.subTest(properties=properties):
                reply = copy.deepcopy(credential)
                if properties is not None:
                    reply['clientExtensionResults'] = properties
                packet = registration_packet(reply, self.challenge, 'https://localhost')
                reader = Reader(base64.b64decode(packet))
                self.assertEqual(reader.take(1), b'\x02')
                import cbor2
                attestation = cbor2.loads(base64.urlsafe_b64decode(reply['response']['attestationObject'] + '=='))
                self.assertEqual(cbor2.loads(reader.blob()), attestation['authData'])
                self.assertEqual(reader.blob(), attestation['attStmt']['sig'])
                self.assertEqual(reader.blob(), attestation['attStmt']['x5c'][0])
                self.assertEqual(reader.blob(), base64.urlsafe_b64decode(reply['response']['clientDataJSON'] + '=='))

    def test_shared_enrollment_requires_resident_key_and_preserves_login_policy(self):
        options = self.challenge.options('localhost', registration=True, registration_mode='shared')
        self.assertEqual(options['authenticatorSelection'], {
            'authenticatorAttachment': 'cross-platform', 'residentKey': 'required',
            'requireResidentKey': True, 'userVerification': 'required'})
        self.assertEqual(options['extensions'], {'credProps': True})
        self.assertEqual(self.challenge.options('localhost')['userVerification'], 'discouraged')

    def test_shared_packet_retains_server_id_without_rewriting_signed_data(self):
        options = self.challenge.options('localhost', registration=True, registration_mode='shared')
        credential = self.key('create', options)
        before = copy.deepcopy(credential)
        for properties in ({}, {'credProps': {'rk': True}}):
            credential['clientExtensionResults'] = properties
            shared = registration_packet(credential, self.challenge, 'https://localhost', registration_mode='shared')
            normal = registration_packet(credential, self.challenge, 'https://localhost')
            self.assertEqual(shared, normal)
            self.assertEqual(base64.b64decode(shared)[0], 2)
        self.assertEqual(credential['response'], before['response'])

    def test_shared_enrollment_rejects_explicit_nonresident_result(self):
        credential = self.key('create', self.challenge.options('localhost', registration=True))
        credential['clientExtensionResults'] = {'credProps': {'rk': False}}
        with self.assertRaisesRegex(BridgeError, 'requires a discoverable credential'):
            registration_packet(credential, self.challenge, 'https://localhost', registration_mode='shared')

    def test_signed_authenticator_extensions_are_rejected_without_rewriting(self):
        self.key.authenticator_extensions = {'credProtect': 2}
        credential = self.key('create', self.challenge.options('localhost', registration=True))
        before = copy.deepcopy(credential)
        with self.assertRaisesRegex(BridgeError, 'signed authenticator extensions'):
            registration_packet(credential, self.challenge, 'https://localhost')
        self.assertEqual(credential, before)

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

    def test_registration_with_conventional_metadata_eof(self):
        self.server.registration_metadata_eof = True
        self.assertTrue(self.gateway.register('demo_test', 'correct-password', self.key)['registered'])

    def test_shared_enrollment_survives_gateway_restart_without_key_discovery(self):
        def fresh_gateway():
            return Gateway(self.gateway.db_config, 'https://localhost', 'localhost',
                           allow_loopback_plaintext=True, registration_mode='shared')
        gateway = fresh_gateway()
        def register(operation, options):
            self.assertEqual(options['authenticatorSelection']['residentKey'], 'required')
            credential = self.key(operation, options)
            credential['clientExtensionResults'] = {'credProps': {'rk': True}}
            return credential
        self.assertEqual(gateway.register('demo_test', 'correct-password', register)['registration_mode'], 'shared')
        self.key.user_verified = False
        def login(operation, options):
            self.assertEqual(options['allowCredentials'][0]['id'], b64u(self.key.credential_id))
            self.assertEqual(options['userVerification'], 'discouraged')
            return self.key(operation, options)
        fresh_gateway().connect('demo_test', 'correct-password', login).close()

    def test_shared_enrollment_never_falls_back_on_extension_failure(self):
        self.gateway.registration_mode = 'shared'
        self.key.authenticator_extensions = {'credProtect': 1}
        with self.assertRaisesRegex(BridgeError, 'Shared registration cannot use signed authenticator extensions'):
            self.gateway.register('demo_test', 'correct-password', self.key)
        self.assertFalse(any('FINISH' in query for query in self.server.commands))
        self.assertEqual(self.gateway._credential_hint('demo_test'), b'')

    def test_invalid_registration_mode_fails_before_connecting(self):
        for value in (None, '', 'auto', True, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(BridgeError, 'registration_mode'):
                Gateway(self.gateway.db_config, 'https://localhost', 'localhost',
                        allow_loopback_plaintext=True, registration_mode=value)

    def test_invalid_per_call_registration_mode_fails_before_connecting(self):
        with patch('mysql_fido_gateway.mysql_bridge.BrowserConnection') as connection:
            for value in ('', 'auto', True, [], {}):
                with self.subTest(value=value), self.assertRaisesRegex(BridgeError, 'registration_mode'):
                    self.gateway.register('demo_test', 'correct-password', self.key, registration_mode=value)
            connection.assert_not_called()
        self.assertEqual(self.gateway.registration_mode, 'browser')

    def test_unexpected_registration_plugin_is_rejected_before_browser_and_finish(self):
        with patch('mysql_fido_gateway.mysql_bridge.BrowserConnection') as factory:
            connection = factory.return_value
            connection.initiate_registration.return_value = (b'challenge', b'other_client_plugin')
            browser = MagicMock()
            with self.assertRaisesRegex(BridgeError, 'different client plugin'):
                self.gateway.register('demo_test', 'correct-password', browser)
            browser.assert_not_called()
            connection.cmd_query.assert_not_called()
            connection.close.assert_called_once()

    def test_touch_only_login_uses_mysql_credential_id(self):
        self.assertEqual(self.gateway.rp_id, 'localhost')
        self.gateway.register('demo_test', 'correct-password', self.key)
        self.key.user_verified = False
        def touch_only(operation, options):
            self.assertEqual(operation, 'get')
            self.assertEqual(options['userVerification'], 'discouraged')
            self.assertEqual(options['hints'], ['security-key'])
            self.assertEqual(options['allowCredentials'], [{
                'type': 'public-key', 'id': b64u(self.key.credential_id),
                'transports': ['usb', 'nfc', 'ble']}])
            return self.key(operation, options)
        with self.gateway.connect('demo_test', 'correct-password', touch_only) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 'hello world', CURRENT_USER(), CONNECTION_ID(), @@version")
                self.assertEqual(cursor.fetchone()[0], 'hello world')

    def test_login_without_server_credential_id_uses_browser_discovery(self):
        self.gateway.register('demo_test', 'correct-password', self.key)
        for body in (b'', b'\x00'):
            with self.subTest(body=body):
                self.server.credential_id_reply = body
                self.gateway.clear_credential_hint('demo_test')
                def discover(operation, options):
                    self.assertNotIn('allowCredentials', options)
                    self.assertEqual(options['userVerification'], 'discouraged')
                    return self.key(operation, options)
                self.gateway.connect('demo_test', 'correct-password', discover).close()

    def test_native_style_discovery_is_remembered_for_later_explicit_key_selection(self):
        self.gateway.register('demo_test', 'correct-password', self.key)
        self.gateway.clear_credential_hint('demo_test')
        self.server.credential_id_reply = b''
        options_seen = []
        def browser(operation, options):
            options_seen.append(copy.deepcopy(options))
            return self.key(operation, options)
        self.gateway.connect('demo_test', 'correct-password', browser).close()
        self.gateway.connect('demo_test', 'correct-password', browser).close()
        self.assertNotIn('allowCredentials', options_seen[0])
        self.assertEqual(options_seen[1]['allowCredentials'][0]['id'], b64u(self.key.credential_id))
        self.assertEqual(options_seen[1]['userVerification'], 'discouraged')

    def test_failed_mysql_assertion_does_not_populate_credential_hint(self):
        self.gateway.register('demo_test', 'correct-password', self.key)
        self.gateway.clear_credential_hint('demo_test')
        self.server.credential_id_reply = b''
        self.server.reject_signature = True
        with self.assertRaises(mysql.connector.Error):
            self.gateway.connect('demo_test', 'correct-password', self.key)
        self.assertEqual(self.gateway._credential_hint('demo_test'), b'')

    def test_credential_hint_is_scoped_to_account_and_stale_rejection_clears_it(self):
        self.gateway.register('demo_test', 'correct-password', self.key)
        self.assertEqual(self.gateway._credential_hint('demo_other'), b'')
        self.server.credential_id_reply = b''
        self.server.reject_signature = True
        with self.assertRaises(mysql.connector.Error):
            self.gateway.connect('demo_test', 'correct-password', self.key)
        self.assertEqual(self.gateway._credential_hint('demo_test'), b'')

    def test_credential_hint_has_bounded_lru_storage_and_can_be_disabled(self):
        self.gateway._credential_hint_capacity = 2
        self.gateway._remember_credential('one', b'1')
        self.gateway._remember_credential('two', b'2')
        self.assertEqual(self.gateway._credential_hint('one'), b'1')
        self.gateway._remember_credential('three', b'3')
        self.assertEqual(self.gateway._credential_hint('two'), b'')
        self.assertEqual(self.gateway._credential_hint('one'), b'1')
        self.gateway._credential_hint_capacity = 0
        self.gateway._remember_credential('four', b'4')
        self.assertEqual(self.gateway._credential_hint('four'), b'')

    def test_credential_hint_capacity_is_explicitly_validated(self):
        for capacity in [True, -1, 1025, '128']:
            with self.subTest(capacity=capacity), self.assertRaisesRegex(BridgeError, 'credential_hint_capacity'):
                Gateway(self.gateway.db_config, 'https://localhost', 'localhost',
                        allow_loopback_plaintext=True, credential_hint_capacity=capacity)

    def test_malformed_credential_id_response_is_rejected(self):
        self.gateway.register('demo_test', 'correct-password', self.key)
        self.server.credential_id_reply = b'\x10short'
        browser = MagicMock()
        with self.assertRaisesRegex(BridgeError, 'Malformed MySQL credential-ID response'):
            self.gateway.connect('demo_test', 'correct-password', browser)
        browser.assert_not_called()

    def test_registration_with_query_attributes_capability(self):
        self.server.query_attributes = True
        self.assertTrue(self.gateway.register('demo_test', 'correct-password', self.key)['registered'])

    def test_standard_query_reader_reproduces_missing_metadata_eof_error(self):
        from mysql_fido_gateway.mysql_bridge import BrowserConnection, Exchange
        connection = BrowserConnection(Exchange('https://localhost', 'localhost', self.key, registering=True),
                                       user='demo_test', password1='correct-password', **self.gateway.db_config)
        try:
            with self.assertRaisesRegex(mysql.connector.InterfaceError, 'Expected EOF packet') as caught:
                connection.cmd_query('ALTER USER USER() 2 FACTOR INITIATE REGISTRATION')
            self.assertEqual(caught.exception.errno, -1)
        finally:
            connection.shutdown()

    def test_password_rejected_by_mysql(self):
        with self.assertRaises(mysql.connector.Error):
            self.gateway.register('demo_test', 'wrong', self.key)

    def test_extension_incompatibility_stops_before_mysql_finish(self):
        self.key.authenticator_extensions = {'credProtect': 2}
        with self.assertRaisesRegex(BridgeError, 'signed authenticator extensions'):
            self.gateway.register('demo_test', 'correct-password', self.key)
        self.assertTrue(any('INITIATE' in query for query in self.server.commands))
        self.assertFalse(any('FINISH' in query for query in self.server.commands))
        self.assertIsNone(self.server.key)

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
    def test_demo_rejects_invalid_registration_choice_before_starting_a_flow(self):
        from app import create_app
        gateway = MagicMock(registration_mode='shared', db_config={
            'host': '127.0.0.1', 'port': 5316, 'ssl_disabled': True})
        with patch.dict(os.environ, {'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost'}):
            app = create_app(gateway=gateway)
        client = app.test_client()
        client.get('/', base_url='https://localhost')
        with client.session_transaction() as state:
            headers = {'Origin': 'https://localhost', 'X-CSRF-Token': state['csrf']}
        with patch.object(app.extensions['ceremony_broker'], 'create') as start_flow:
            for value in (None, '', 'auto', True, [], {}):
                with self.subTest(value=value):
                    result = client.post('/api/flows', base_url='https://localhost', headers=headers,
                                         json={'action': 'register', 'username': 'demo_test',
                                               'password': 'correct-password', 'registration_mode': value})
                    self.assertEqual(result.status_code, 400)
                    self.assertIn('registration_mode', result.json['error'])
            start_flow.assert_not_called()
        gateway.register.assert_not_called()

    def test_admin_setup_and_redacted_command_events(self):
        from app import create_app
        for timeout in (10, 300):
            with self.subTest(timeout=timeout):
                with patch.dict(os.environ, {'DB_HOST': '127.0.0.1', 'DB_PORT': '5316', 'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost',
                                             'ADMIN_TOKEN': 'test-admin-token'}):
                    app = create_app(gateway=object())
                    client = app.test_client()
                    page = client.get('/', base_url='https://localhost')
                    self.assertIn(b'id="admin-token">test-admin-token</code>', page.data)
                    self.assertEqual(page.data.count(b'value="test-admin-token"'), 2)
                    with client.session_transaction() as s:
                        csrf = s['csrf']
                    headers = {'Origin': 'https://localhost', 'X-CSRF-Token': csrf}
                    payload = {'action': 'setup', 'root_password': 'test-root-password',
                               'admin_token': 'test-admin-token'}
                    cursor = MagicMock()
                    cursor.fetchone.side_effect = [('ACTIVE',), ('old.example.com', timeout),
                                                   ('localhost', max(180, timeout))]
                    connection = MagicMock()
                    connection.cursor.return_value.__enter__.return_value = cursor
                    with patch('mysql_fido_gateway.flask_util.mysql.connector.connect', return_value=connection) as connect:
                        rejected = client.post('/api/flows', base_url='https://localhost', headers=headers,
                                               json={**payload, 'admin_token': 'wrong'})
                        self.assertEqual(rejected.status_code, 403)
                        connect.assert_not_called()
                        response = client.post('/api/flows', base_url='https://localhost', headers=headers, json=payload)
                        self.assertEqual(response.status_code, 202)
                        events = []
                        for _ in range(10):
                            event = client.get('/api/flows/' + response.json['flow_id'],
                                               base_url='https://localhost').json
                            events.append(event)
                            if event['type'] in {'success', 'error'}:
                                break
                    self.assertEqual(events[-1]['type'], 'success')
                    self.assertEqual(len([e for e in events if e['type'] == 'command']), 5)
                    cursor.execute.assert_has_calls([
                        call('SET PERSIST authentication_webauthn_rp_id = %s', ('localhost',)),
                        call('SET PERSIST connect_timeout = %s', (max(180, timeout),))], any_order=False)
                    connection.close.assert_called_once()
                    with client.session_transaction() as s:
                        visible = json.dumps(dict(s)) + json.dumps(events)
                    self.assertNotIn('test-root-password', visible)
                    self.assertNotIn('test-admin-token', visible)

    def test_admin_setup_reports_mysql_failure(self):
        from app import create_app
        with patch.dict(os.environ, {'DB_HOST': '127.0.0.1', 'DB_PORT': '5316', 'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost',
                                     'ADMIN_TOKEN': 'test-admin-token'}):
            client = create_app(gateway=object()).test_client()
            client.get('/', base_url='https://localhost')
            with client.session_transaction() as s:
                csrf = s['csrf']
            with patch('mysql_fido_gateway.flask_util.mysql.connector.connect', side_effect=mysql.connector.Error('secret detail', errno=1045)):
                response = client.post('/api/flows', base_url='https://localhost',
                                       headers={'Origin': 'https://localhost', 'X-CSRF-Token': csrf},
                                       json={'action': 'setup', 'admin_token': 'test-admin-token',
                                             'root_password': 'test-root-password'})
                event = client.get('/api/flows/' + response.json['flow_id'], base_url='https://localhost').json
            self.assertEqual(event['type'], 'error')
            self.assertIn('1045', event['message'])
            self.assertNotIn('secret detail', event['message'])

    def test_local_navigation_redirects_to_https_origin(self):
        from app import create_app
        with patch.dict(os.environ, {'DB_HOST': '127.0.0.1', 'DB_PORT': '5316', 'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost'}):
            client = create_app(gateway=object()).test_client()
        for address in ('http://127.0.0.1:5001', 'http://localhost:5001'):
            response = client.get('/', base_url=address)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers['Location'], 'https://localhost/')
        self.assertEqual(client.get('/', base_url='https://localhost').status_code, 200)
        self.assertEqual(client.get('/', base_url='https://evil.example').status_code, 400)
        self.assertEqual(client.post('/api/flows', base_url='http://127.0.0.1:5001',
                                     json={}).status_code, 403)

    def test_origin_csrf_and_cross_session(self):
        from app import create_app
        with patch.dict(os.environ, {'DB_HOST': '127.0.0.1', 'DB_PORT': '5316', 'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost'}):
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
    def test_demo_choice_controls_one_registration_without_changing_gateway_default(self):
        from app import create_app
        for default, choice in (('shared', 'browser'), ('browser', 'shared'), ('shared', None)):
            with self.subTest(default=default, choice=choice):
                server = FakeMySQL()
                try:
                    gateway = Gateway({'host': '127.0.0.1', 'port': server.port, 'ssl_disabled': True},
                                      'https://localhost', 'localhost', allow_loopback_plaintext=True,
                                      registration_mode=default)
                    with patch.dict(os.environ, {'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost'}):
                        app = create_app(gateway=gateway)
                    client = app.test_client()
                    page = client.get('/', base_url='https://localhost')
                    self.assertIn(f'value="{default}" checked'.encode(), page.data)
                    with client.session_transaction() as state:
                        headers = {'Origin': 'https://localhost', 'X-CSRF-Token': state['csrf']}
                    body = {'action': 'register', 'username': 'demo_test', 'password': 'correct-password'}
                    if choice is not None:
                        body['registration_mode'] = choice
                    response = client.post('/api/flows', base_url='https://localhost', headers=headers, json=body)
                    self.assertEqual(response.status_code, 202)
                    path = '/api/flows/' + response.json['flow_id']
                    mode = choice or default
                    key = SoftwareKey()
                    for _ in range(12):
                        event = client.get(path, base_url='https://localhost').json
                        if event['type'] == 'webauthn':
                            selection = event['publicKey']['authenticatorSelection']
                            self.assertEqual(selection['residentKey'], 'required' if mode == 'shared' else 'discouraged')
                            self.assertEqual(selection['requireResidentKey'], mode == 'shared')
                            self.assertEqual(selection['userVerification'], 'required')
                            self.assertEqual(gateway.registration_mode, default)
                            credential = key(event['operation'], event['publicKey'])
                            credential['clientExtensionResults'] = {'credProps': {'rk': mode == 'shared'}}
                            reply = client.post(path + '/respond', base_url='https://localhost', headers=headers,
                                                json={'request_id': event['request_id'], 'credential': credential})
                            self.assertEqual(reply.status_code, 200)
                        elif event['type'] in {'success', 'error'}:
                            break
                    self.assertEqual(event['type'], 'success', event)
                    self.assertEqual(event['result']['registration_mode'], mode)
                    self.assertEqual(gateway.registration_mode, default)
                    with client.session_transaction() as state:
                        self.assertEqual(set(state), {'owner', 'csrf'})
                finally:
                    server.close()
                self.assertEqual(server.errors, [])

    def test_http_registration_and_login_use_real_connector(self):
        from app import create_app
        server = FakeMySQL()
        try:
            gateway = Gateway({'host': '127.0.0.1', 'port': server.port, 'ssl_disabled': True},
                              'https://localhost', 'localhost', allow_loopback_plaintext=True)
            with patch.dict(os.environ, {'DB_HOST': '127.0.0.1', 'DB_PORT': '5316', 'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost'}):
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
                    elif event['type'] != 'command': return event
                self.fail('HTTP ceremony did not finish')
            self.assertEqual(action('register')['type'], 'success')
            result = action('login')
            self.assertEqual(result['result']['message'], 'hello world')
            self.assertEqual(result['result']['mysql_account'], 'demo_test@localhost')
            server.reject_signature = True
            self.assertEqual(action('login')['type'], 'error')
            denied = action('login', 'wrong')
            self.assertEqual(denied['type'], 'error')
            self.assertIn('Access denied before any SQL command was sent', denied['message'])
            self.assertIn('new user password', denied['message'])
            self.assertNotIn('attestation support', denied['message'])
            self.assertNotIn('RP/origin compatibility', denied['message'])
            self.assertIn('No application-authentication fallback was used', denied['message'])
        finally:
            server.close()
        self.assertEqual(server.errors, [])


if __name__ == '__main__': unittest.main()
