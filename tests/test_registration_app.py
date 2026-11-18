"""Public registration UI uses real protocol transport, never an app-only key DB."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from mysql_fido_gateway import Gateway
from tests.fake_mysql import FakeMySQL
from tests.software_key import SoftwareKey

create_app = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                               'docs/examples/login_app/app.py'))['create_app']


class RegistrationAppTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeMySQL()
        self.key = SoftwareKey()
        self.gateway = Gateway({'host': '127.0.0.1', 'port': self.server.port, 'ssl_disabled': True},
                               'https://localhost', 'localhost', allow_loopback_plaintext=True)
        with patch.dict(os.environ, {'FLASK_SECRET_KEY': 'synthetic-registration-only',
                                    'RP_ID': 'localhost', 'BROWSER_ORIGIN': 'https://localhost'}):
            self.app = create_app(self.gateway)
        self.auth = self.app.extensions['gateway_login']
        self.client = self.app.test_client()
        self.get('/login')

    def tearDown(self):
        self.auth.close()
        self.server.close()
        self.assertEqual(self.server.errors, [])

    def get(self, path, client=None):
        return (client or self.client).get(path, base_url='https://localhost')

    def post(self, path, body):
        # A protected-page redirect clears the old cookie; following it to the
        # login page establishes the new form token, as a browser would do.
        with self.client.session_transaction() as state:
            missing = 'csrf' not in state
        if missing:
            self.get('/login')
        with self.client.session_transaction() as state:
            headers = {'Origin': 'https://localhost', 'X-CSRF-Token': state['csrf']}
        return self.client.post(path, base_url='https://localhost', headers=headers, json=body)

    def start(self, kind='register', **changes):
        body = dict(username='demo_registered', password='correct-password')
        body.update(changes)
        response = self.post('/api/' + kind, body)
        self.assertEqual(response.status_code, 202)
        return '/api/' + kind + '/' + response.json['flow_id']

    def finish(self, path, *, cancel=False):
        for _ in range(20):
            event = self.get(path).json
            if event['type'] == 'webauthn':
                reply = {'request_id': event['request_id']}
                if cancel:
                    reply['error'] = 'NotAllowedError'
                else:
                    if event['operation'] == 'create':
                        self.assertEqual(event['publicKey']['authenticatorSelection']['userVerification'], 'required')
                    else:
                        self.assertEqual(event['publicKey']['userVerification'], 'discouraged')
                    reply['credential'] = self.key(event['operation'], event['publicKey'])
                self.assertEqual(self.post(path + '/respond', reply).status_code, 200)
            elif event['type'] in {'success', 'error'}:
                return event
        self.fail('Ceremony did not complete')

    def test_linked_templates_shared_assets_and_editable_project_forms(self):
        login = self.get('/login')
        self.assertIn(b'href="/register"', login.data)
        self.assertIn(b'/static/auth/login.js', login.data)
        self.assertIn(b'MYSQL \xc2\xb7 APPLICATION DEMO', login.data)
        page = self.get('/register')
        self.assertIn(b'id="register" action="/api/register"', page.data)
        self.assertIn(b'/static/auth/register.js', page.data)
        self.assertIn(b'href="/login"', page.data)
        self.assertNotIn(b'name="root_password"', page.data)
        self.assertNotIn(b'name="admin_token"', page.data)
        self.assertNotIn(b'name="pin"', page.data)
        for path in ['/_gateway/static/webauthn.js', '/_gateway/static/register.js', '/static/auth.css']:
            with self.get(path) as response:
                self.assertEqual(response.status_code, 200)

    def test_register_then_touch_only_login_and_sql(self):
        self.assertEqual(self.get('/main').status_code, 302)
        event = self.finish(self.start())
        self.assertEqual(event['type'], 'success')
        self.assertTrue(event['result']['registered'])
        self.assertFalse(self.auth.logins)
        self.assertEqual(self.get('/main').status_code, 302)
        self.get('/login')
        self.assertTrue(any('FINISH REGISTRATION' in sql for sql in self.server.commands))
        with self.client.session_transaction() as state:
            self.assertEqual(set(state), {'owner', 'csrf'})
        self.key.user_verified = False
        self.assertEqual(self.finish(self.start('login'))['type'], 'success')
        self.assertEqual(self.get('/main').status_code, 200)
        result = self.post('/api/hello', {})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['mysql_account'], 'demo_registered@localhost')
        self.assertEqual(self.post('/api/register', {'username': 'demo_registered', 'password': 'correct-password'}).status_code, 409)

    def test_wrong_password_cancellation_and_retry_do_not_authorize_login(self):
        self.assertEqual(self.finish(self.start(password='wrong'))['type'], 'error')
        self.assertIsNone(self.server.key)
        self.assertEqual(self.finish(self.start(), cancel=True)['type'], 'error')
        self.assertIsNone(self.server.key)
        self.assertFalse(self.auth.logins)
        self.assertEqual(self.get('/main').status_code, 302)
        self.assertEqual(self.finish(self.start())['type'], 'success')

    def test_csrf_owner_route_isolation_and_concurrent_action_guards(self):
        self.assertEqual(self.client.post('/api/register', base_url='https://localhost', json={}).status_code, 403)
        self.assertEqual(self.post('/api/register', {'username': 'root', 'password': 'x'}).status_code, 400)
        path = self.start()
        flow_id = path.rsplit('/', 1)[1]
        self.assertEqual(self.get(path, self.app.test_client()).status_code, 400)
        self.assertEqual(self.get('/api/login/' + flow_id).status_code, 400)
        self.assertEqual(self.post('/api/login/' + flow_id + '/respond', {'request_id': 'x'}).status_code, 400)
        self.assertEqual(self.post('/api/login', {'username': 'demo_registered', 'password': 'correct-password'}).status_code, 400)
        self.assertEqual(self.finish(path)['type'], 'success')


if __name__ == '__main__':
    unittest.main()
