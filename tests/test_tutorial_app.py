"""Exercise the tutorial's complete HTTP transport with the real connector."""
import json
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from mysql_fido_gateway import Gateway
from tests.fake_mysql import FakeMySQL
from tests.software_key import SoftwareKey


STARTER = Path(__file__).resolve().parents[1] / 'docs' / 'examples' / 'new_app' / 'app.py'
create_app = runpy.run_path(str(STARTER))['create_app']


class TutorialAppTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeMySQL()
        gateway = Gateway(
            {'host': '127.0.0.1', 'port': self.server.port, 'ssl_disabled': True},
            'https://localhost', 'localhost', allow_loopback_plaintext=True,
        )
        with patch.dict(os.environ, {
            'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost',
            'FLASK_SECRET_KEY': 'synthetic-tutorial-test-secret-only',
        }):
            self.app = create_app(gateway=gateway)
        self.client = self.app.test_client()
        response = self.client.get('/', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Gateway hello world', response.data)
        self.assertNotIn(b'root_password', response.data)
        with self.client.get('/static/auth.js', base_url='https://localhost') as asset:
            self.assertEqual(asset.status_code, 200)
        with self.client.session_transaction() as state:
            self.csrf = state['csrf']
            self.owner = state['owner']
        self.headers = {'Origin': 'https://localhost', 'X-CSRF-Token': self.csrf}
        self.key = SoftwareKey()

    def tearDown(self):
        self.server.close()
        self.assertEqual(self.server.errors, [])

    def perform(self, action, password='correct-password'):
        response = self.client.post(
            '/api/flows', base_url='https://localhost', headers=self.headers,
            json={'action': action, 'username': 'demo_tutorial', 'password': password},
        )
        self.assertEqual(response.status_code, 202)
        path = '/api/flows/' + response.json['flow_id']
        for _ in range(12):
            event = self.client.get(path, base_url='https://localhost').json
            if event['type'] in {'waiting', 'command'}:
                continue
            if event['type'] == 'webauthn':
                credential = self.key(event['operation'], event['publicKey'])
                reply = self.client.post(
                    path + '/respond', base_url='https://localhost', headers=self.headers,
                    json={'request_id': event['request_id'], 'credential': credential},
                )
                self.assertEqual(reply.status_code, 200)
            else:
                return event
        self.fail('Tutorial ceremony did not finish')

    def test_complete_registration_login_and_rejection(self):
        self.assertEqual(self.perform('register')['type'], 'success')
        self.key.user_verified = False
        result = self.perform('login')
        self.assertEqual(result['type'], 'success')
        self.assertEqual(result['result']['message'], 'hello world')
        self.assertEqual(result['result']['mysql_account'], 'demo_tutorial@localhost')
        commands_before = list(self.server.commands)
        self.assertEqual(self.perform('login', password='wrong')['type'], 'error')
        self.assertEqual(self.server.commands, commands_before)
        self.server.reject_signature = True
        self.assertEqual(self.perform('login')['type'], 'error')
        self.assertEqual(self.server.commands, commands_before)
        with self.client.session_transaction() as state:
            self.assertEqual(set(state), {'owner', 'csrf'})
            visible = json.dumps(dict(state))
        self.assertNotIn('correct-password', visible)
        self.assertNotIn('demo_tutorial', visible)

    def test_origin_csrf_owner_and_account_guards(self):
        body = {'action': 'login', 'username': 'demo_tutorial', 'password': 'correct-password'}
        missing_csrf = self.client.post('/api/flows', base_url='https://localhost', json=body)
        self.assertEqual(missing_csrf.status_code, 403)
        wrong_origin = self.client.post(
            '/api/flows', base_url='https://localhost',
            headers={**self.headers, 'Origin': 'https://evil.example'}, json=body,
        )
        self.assertEqual(wrong_origin.status_code, 403)
        root_attempt = self.client.post(
            '/api/flows', base_url='https://localhost', headers=self.headers,
            json={**body, 'username': 'root'},
        )
        self.assertEqual(root_attempt.status_code, 400)
        flow = self.app.extensions['ceremony_broker'].create(self.owner)
        other = self.app.test_client()
        other.get('/', base_url='https://localhost')
        rejected_poll = other.get('/api/flows/' + flow.id, base_url='https://localhost')
        self.assertEqual(rejected_poll.status_code, 400)
        redirect = self.client.get('/', base_url='http://127.0.0.1:5002')
        self.assertEqual(redirect.status_code, 302)
        self.assertEqual(redirect.headers['Location'], 'https://localhost/')
        self.assertEqual(self.server.commands, [])


if __name__ == '__main__':
    unittest.main()
