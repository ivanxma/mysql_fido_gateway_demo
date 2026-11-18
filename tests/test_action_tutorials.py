"""The first two tutorial apps expose only their selected action."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import MagicMock, patch

from mysql_fido_gateway import Gateway
from tests.fake_mysql import FakeMySQL
from tests.software_key import SoftwareKey


EXAMPLES = Path(__file__).resolve().parents[1] / 'docs/examples'


class ActionTutorialTests(unittest.TestCase):
    def browser(self, folder, gateway):
        factory = runpy.run_path(str(EXAMPLES / folder / 'app.py'))['create_app']
        with patch.dict(os.environ, {'DB_HOST': '127.0.0.1', 'DB_PORT': '5316', 'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost',
                                    'ADMIN_TOKEN': 'synthetic-demo-token', 'DB_ACCOUNT_HOST': 'localhost'}):
            app = factory(gateway)
            client = app.test_client()
            page = client.get('/', base_url='https://localhost')
        with client.session_transaction() as state:
            headers = {'Origin': 'https://localhost', 'X-CSRF-Token': state['csrf']}
        return app, client, page, headers

    def test_create_user_only_with_bound_password_and_connection_cleanup(self):
        app, client, page, headers = self.browser('create_user_app', object())
        self.assertIn(b'Create a MySQL user', page.data)
        self.assertIn(b'synthetic-demo-token', page.data)
        self.assertEqual(page.data.count(b'<form'), 1)
        self.assertNotIn(b'data-action="register"', page.data)
        self.assertNotIn(b'data-action="login"', page.data)
        body = dict(action='create', username='demo_tutorial', password='synthetic-user-password',
                    root_password='synthetic-root-password', admin_token='synthetic-demo-token')
        for action in ('setup', 'register', 'login'):
            response = client.post('/api/flows', base_url='https://localhost', headers=headers,
                                   json={**body, 'action': action})
            self.assertEqual(response.status_code, 400)
        with patch.dict(os.environ, {'ADMIN_TOKEN': 'synthetic-demo-token', 'DB_ACCOUNT_HOST': 'localhost'}):
            self.assertEqual(client.post('/api/flows', base_url='https://localhost', headers=headers,
                                         json={**body, 'admin_token': 'wrong'}).status_code, 403)
            connection = MagicMock()
            cursor = connection.cursor.return_value.__enter__.return_value
            cursor.fetchone.side_effect = [('ACTIVE',), ('localhost', 180)]
            with patch('mysql_fido_gateway.flask_util.mysql.connector.connect', return_value=connection):
                response = client.post('/api/flows', base_url='https://localhost', headers=headers, json=body)
                self.assertEqual(response.status_code, 202)
                path = '/api/flows/' + response.json['flow_id']
                for _ in range(10):
                    event = client.get(path, base_url='https://localhost').json
                    if event['type'] in {'success', 'error'}:
                        break
                self.assertEqual(event['type'], 'success')
        connection.close.assert_called_once()
        self.assertEqual(cursor.execute.call_args.args[1],
                         ('demo_tutorial', 'localhost', 'synthetic-user-password'))
        with client.session_transaction() as state:
            self.assertEqual(set(state), {'owner', 'csrf'})

    def test_registration_only_uses_real_connector_and_software_key(self):
        server = FakeMySQL()
        try:
            gateway = Gateway({'host': '127.0.0.1', 'port': server.port, 'ssl_disabled': True},
                              'https://localhost', 'localhost', allow_loopback_plaintext=True)
            app, client, page, headers = self.browser('register_app', gateway)
            self.assertEqual(page.data.count(b'<form'), 1)
            self.assertIn(b'Register your YubiKey', page.data)
            self.assertNotIn(b'data-action="login"', page.data)
            self.assertNotIn(b'synthetic-demo-token', page.data)
            key = SoftwareKey()
            body = dict(action='register', username='demo_tutorial', password='correct-password')
            for action in ('setup', 'create', 'login'):
                self.assertEqual(client.post('/api/flows', base_url='https://localhost', headers=headers,
                                             json={**body, 'action': action}).status_code, 400)
            response = client.post('/api/flows', base_url='https://localhost', headers=headers, json=body)
            self.assertEqual(response.status_code, 202)
            path = '/api/flows/' + response.json['flow_id']
            for _ in range(12):
                event = client.get(path, base_url='https://localhost').json
                if event['type'] == 'webauthn':
                    self.assertEqual(event['operation'], 'create')
                    credential = key(event['operation'], event['publicKey'])
                    self.assertEqual(client.post(path + '/respond', base_url='https://localhost',
                                                 headers=headers, json={'request_id': event['request_id'],
                                                                        'credential': credential}).status_code, 200)
                elif event['type'] in {'success', 'error'}:
                    break
            self.assertEqual(event['type'], 'success')
            self.assertTrue(event['result']['registered'])
            self.assertTrue(any('FINISH REGISTRATION' in sql for sql in server.commands))
            self.assertFalse(any("SELECT 'hello world'" in sql for sql in server.commands))
        finally:
            server.close()
        self.assertEqual(server.errors, [])


if __name__ == '__main__':
    unittest.main()
