"""Login-to-main tutorial: real connector and signed software-key assertions."""
import json
import os
from pathlib import Path
import runpy
import threading
import time
import unittest
from unittest.mock import patch

from mysql_fido_gateway import Gateway
from tests.fake_mysql import FakeMySQL
from tests.software_key import SoftwareKey


STARTER = Path(__file__).resolve().parents[1] / 'docs/examples/login_app'
create_app = runpy.run_path(str(STARTER / 'app.py'))['create_app']


class LoginAppTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeMySQL()
        self.gateway = Gateway(
            {'host': '127.0.0.1', 'port': self.server.port, 'ssl_disabled': True},
            'https://localhost', 'localhost', allow_loopback_plaintext=True)
        self.key = SoftwareKey()
        self.gateway.register('demo_tutorial', 'correct-password', self.key)
        self.key.user_verified = False
        self.now = [time.monotonic()]
        with patch.dict(os.environ, {'FLASK_SECRET_KEY': 'synthetic-login-test-only',
                                    'BROWSER_ORIGIN': 'https://localhost', 'RP_ID': 'localhost'}):
            self.app = create_app(self.gateway, clock=lambda: self.now[0], session_seconds=300)
        self.auth = self.app.extensions['gateway_login']
        self.client = self.app.test_client()
        response = self.client.get('/login', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.refresh_csrf()

    def refresh_csrf(self):
        with self.client.session_transaction() as state:
            self.headers = {'Origin': 'https://localhost', 'X-CSRF-Token': state['csrf']}
            self.owner = state['owner']

    def tearDown(self):
        self.auth.close()
        self.server.close()
        self.assertEqual(self.server.errors, [])

    def get(self, path, client=None):
        return (client or self.client).get(path, base_url='https://localhost')

    def post(self, path, body=None):
        return self.client.post(path, base_url='https://localhost', headers=self.headers, json=body or {})

    def login(self, password='correct-password'):
        response = self.post('/api/login', {'username': 'demo_tutorial', 'password': password})
        self.assertEqual(response.status_code, 202)
        path = '/api/login/' + response.json['flow_id']
        saw_key = False
        for _ in range(12):
            event = self.get(path).json
            if event['type'] == 'waiting':
                continue
            if event['type'] == 'webauthn':
                saw_key = True
                # A browser challenge alone must not authorize the session.
                self.assertFalse(any(login.ready for login in self.auth.logins.values()))
                credential = self.key(event['operation'], event['publicKey'])
                self.assertEqual(self.post(path + '/respond', {
                    'request_id': event['request_id'], 'credential': credential}).status_code, 200)
            else:
                if event['type'] == 'success':
                    self.assertTrue(saw_key)
                    self.refresh_csrf()
                return event
        self.fail('Login never completed')

    def test_login_main_button_reuses_connection_and_logout_revokes(self):
        self.assertEqual(self.get('/main').status_code, 302)
        self.get('/login')
        self.refresh_csrf()
        old_cookie = self.client.get_cookie('gateway_login_session').value
        with patch.object(self.gateway, 'connect', wraps=self.gateway.connect) as connect:
            self.assertEqual(self.login()['type'], 'success')
            self.assertEqual(self.get('/main').status_code, 200)
            self.assertFalse(any(q.startswith("SELECT 'Hello World'") for q in self.server.commands))
            first = self.post('/api/hello')
            second = self.post('/api/hello')
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json['message'], 'Hello World')
            self.assertEqual(first.json['mysql_account'], 'demo_tutorial@localhost')
            self.assertEqual(first.json['connection_id'], second.json['connection_id'])
            self.assertEqual(connect.call_count, 1)
        with self.client.session_transaction() as state:
            self.assertEqual(set(state), {'owner', 'csrf'})
            self.assertNotIn('correct-password', json.dumps(dict(state)))
            self.assertNotIn('demo_tutorial', json.dumps(dict(state)))
        other = self.app.test_client()
        other.set_cookie('gateway_login_session', old_cookie)
        self.assertEqual(self.get('/main', other).status_code, 302)
        login = self.auth.logins[self.owner]
        self.assertEqual(self.post('/api/logout').status_code, 200)
        self.assertTrue(login.closed.wait(2))
        self.assertEqual(self.get('/main').status_code, 302)
        self.get('/login')
        self.refresh_csrf()
        self.assertEqual(self.post('/api/hello').status_code, 401)

    def test_password_and_signature_rejections_never_run_hello(self):
        self.assertEqual(self.login(password='wrong')['type'], 'error')
        self.server.reject_signature = True
        self.assertEqual(self.login()['type'], 'error')
        self.assertEqual(self.get('/main').status_code, 302)
        self.assertFalse(any(q.startswith("SELECT 'Hello World'") for q in self.server.commands))

    def test_connection_context_parameters_writes_and_multiple_rows(self):
        from flask import jsonify
        from mysql_fido_gateway.flask_login import getConnection
        self.assertEqual(self.login()['type'], 'success')
        borrowed = []
        value = "O'Reilly; -- value, not SQL"

        def business_route():
            with getConnection() as connection:
                borrowed.append(connection)
                with connection.cursor() as cursor:
                    cursor.execute("INSERT INTO example(value) VALUES (%s)", (value,))
                    cursor.executemany("INSERT INTO example(value) VALUES (%s)", [('one',), ('two',)])
                    cursor.execute("SELECT 'Hello World' AS message, CURRENT_USER() AS mysql_account, "
                                   "CONNECTION_ID() AS connection_id WHERE %s = %s", (value, value))
                    rows = cursor.fetchall()
                    self.assertEqual(cursor.rowcount, 1)
            return jsonify(rows=rows)

        self.app.view_functions['hello'] = self.auth.login_required(business_route)
        response = self.post('/api/hello')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['rows'][0]['mysql_account'], 'demo_tutorial@localhost')
        statements = self.server.commands
        self.assertTrue(any("O\\'Reilly" in sql for sql in statements))
        self.assertIn('COMMIT', [sql.upper() for sql in statements])
        with self.assertRaisesRegex(RuntimeError, 'context'):
            borrowed[0].cursor()

    def test_transaction_error_rolls_back_and_session_can_be_reused(self):
        from flask import jsonify
        self.assertEqual(self.login()['type'], 'success')
        original = self.app.view_functions['hello']
        start = len(self.server.commands)

        def business_route():
            try:
                with self.auth.get_connection() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute('UPDATE example SET value = %s', ('changed',))
                    raise ValueError('Application validation failed')
            except ValueError:
                return jsonify(error='validation'), 409

        self.app.view_functions['hello'] = self.auth.login_required(business_route)
        self.assertEqual(self.post('/api/hello').status_code, 409)
        statements = [sql.upper() for sql in self.server.commands[start:]]
        self.assertIn('ROLLBACK', statements)
        self.assertNotIn('COMMIT', statements)
        self.app.view_functions['hello'] = original
        self.assertEqual(self.post('/api/hello').status_code, 200)

    def test_native_callback_runs_on_worker_and_sql_errors_roll_back(self):
        from flask import jsonify
        import mysql.connector
        self.assertEqual(self.login()['type'], 'success')
        seen = []

        def business_route():
            request_thread = threading.get_ident()
            def work(connection):
                seen.append(threading.get_ident())
                self.assertNotEqual(threading.get_ident(), request_thread)
                with connection.cursor(dictionary=True, buffered=True) as cursor:
                    cursor.execute("SELECT 'Hello World' AS message, CURRENT_USER() AS mysql_account, CONNECTION_ID() AS connection_id")
                    return cursor.fetchall()
            rows = self.auth.run(work)
            def rejected(connection):
                raise mysql.connector.ProgrammingError('Synthetic SQL error')
            with self.assertRaises(mysql.connector.ProgrammingError):
                self.auth.run(rejected)
            return jsonify(rows=rows, still_alive=self.auth.query('SELECT 1 AS alive', many=True))

        self.app.view_functions['hello'] = self.auth.login_required(business_route)
        result = self.post('/api/hello')
        self.assertEqual(result.status_code, 200)
        self.assertTrue(seen)
        self.assertEqual(result.json['still_alive'], [{'alive': '1'}])

    def test_same_user_requests_cannot_interleave_with_a_transaction(self):
        from flask import jsonify
        self.assertEqual(self.login()['type'], 'success')
        login = self.auth.logins[self.owner]
        entered, release, other_done = threading.Event(), threading.Event(), threading.Event()
        responses, errors = [], []

        def business_route():
            with self.auth.get_connection():
                entered.set()
                if not release.wait(2):
                    raise AssertionError('Test did not release transaction')
            return jsonify(ok=True)

        def first():
            try: responses.append(self.post('/api/hello').status_code)
            except Exception as error: errors.append(error)

        def second():
            try: login.query('SELECT 1 AS alive')
            except Exception as error: errors.append(error)
            finally: other_done.set()

        self.app.view_functions['hello'] = self.auth.login_required(business_route)
        one = threading.Thread(target=first)
        two = threading.Thread(target=second)
        one.start()
        try:
            self.assertTrue(entered.wait(2))
            two.start()
            self.assertFalse(other_done.wait(.15))
        finally:
            release.set()
            one.join(2)
            if two.ident is not None: two.join(2)
        self.assertEqual(errors, [])
        self.assertEqual(responses, [200])
        self.assertTrue(other_done.is_set())

    def test_packaged_login_assets_work_without_starter_assets(self):
        page = self.get('/login')
        self.assertIn(b'/_gateway/static/login.js', page.data)
        for name in ('common.js', 'login.js', 'style.css'):
            with self.get('/_gateway/static/' + name) as asset:
                self.assertEqual(asset.status_code, 200)

    def test_failed_commit_revokes_session_instead_of_reusing_uncertain_state(self):
        import mysql.connector
        self.assertEqual(self.login()['type'], 'success')
        login = self.auth.logins[self.owner]

        def business_route():
            def work(connection):
                def failed_commit():
                    raise mysql.connector.InterfaceError('Synthetic disconnect during commit')
                connection.commit = failed_commit
            self.auth.run(work)
            self.fail('Failed transaction cleanup must not return success')

        self.app.view_functions['hello'] = self.auth.login_required(business_route)
        self.assertEqual(self.post('/api/hello').status_code, 401)
        self.assertTrue(login.closed.wait(2))
        self.assertEqual(self.get('/main').status_code, 302)

    def test_expiry_closes_idle_connection_and_missing_state_rejects_cookie(self):
        self.assertEqual(self.login()['type'], 'success')
        login = self.auth.logins[self.owner]
        self.now[0] += 301
        self.assertTrue(login.closed.wait(2))  # No HTTP request needed to clean up.
        self.assertEqual(self.get('/main').status_code, 302)
        self.get('/login')
        self.refresh_csrf()
        self.assertEqual(self.login()['type'], 'success')
        cookie = self.client.get_cookie('gateway_login_session').value
        self.auth.close()  # Simulates restart: signed cookie remains valid.
        other = self.app.test_client()
        other.set_cookie('gateway_login_session', cookie)
        self.assertEqual(self.get('/main', other).status_code, 302)

    def test_origin_csrf_flow_ownership_and_templates(self):
        self.assertEqual(self.client.post('/api/login', base_url='https://localhost', json={}).status_code, 403)
        response = self.client.post('/api/login', base_url='https://localhost',
                                    headers={**self.headers, 'Origin': 'https://evil.example'}, json={})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.post('/api/login', {'username': 'root', 'password': 'unused'}).status_code, 400)
        flow = self.auth.broker.create(self.owner)
        other = self.app.test_client()
        self.assertEqual(self.get('/api/login/' + flow.id, other).status_code, 400)
        with self.get('/static/main.js') as asset:
            self.assertEqual(asset.status_code, 200)

    def test_two_sessions_have_separate_connections_owned_by_worker_threads(self):
        connections, errors = [], []

        class Connection:
            def __init__(self, username):
                self.username = username
                self.thread = threading.get_ident()
                self.closed = threading.Event()
                self.sql = []
                self.fail = False
                self.autocommit = True

            def check_thread(self):
                if threading.get_ident() != self.thread:
                    errors.append('Connection used outside its worker')

            def cursor(self, **kwargs):
                self.check_thread()
                parent = self
                class Cursor:
                    def __enter__(self): return self
                    def __exit__(self, *args): self.close()
                    def execute(self, sql, params=None): parent.execute(sql)
                    def fetchone(self): return parent.fetchone()
                    def close(self): parent.check_thread()
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def execute(self, sql):
                self.check_thread()
                if self.fail:
                    raise RuntimeError('Synthetic lost database connection')
                self.sql.append(sql)

            def fetchone(self):
                return dict(message='Hello World', mysql_account=self.username,
                            connection_id=id(self))

            def close(self):
                self.check_thread()
                self.closed.set()

            def commit(self):
                self.check_thread()

            def rollback(self):
                self.check_thread()

        class AcceptedGateway:
            # Transport isolation only; real WebAuthn is covered by other tests.
            def connect(self, username, password, ask):
                connection = Connection(username)
                connections.append(connection)
                return connection

        with patch.dict(os.environ, {'FLASK_SECRET_KEY': 'synthetic-isolation-test'}):
            app = create_app(AcceptedGateway())
        auth = app.extensions['gateway_login']
        try:
            clients, headers, results = [], [], []
            for name in ('alice', 'bob'):
                client = app.test_client()
                client.get('/login', base_url='https://localhost')
                def csrf():
                    with client.session_transaction() as state:
                        return {'Origin': 'https://localhost', 'X-CSRF-Token': state['csrf']}
                response = client.post('/api/login', base_url='https://localhost', headers=csrf(),
                                       json={'username': name, 'password': 'synthetic'})
                path = '/api/login/' + response.json['flow_id']
                self.assertEqual(client.get(path, base_url='https://localhost').json['type'], 'success')
                clients.append(client)
                headers.append(csrf())
                result = client.post('/api/hello', base_url='https://localhost', headers=csrf(), json={})
                results.append(result.json)
            self.assertNotEqual(results[0]['connection_id'], results[1]['connection_id'])
            self.assertEqual([r['mysql_account'] for r in results], ['alice', 'bob'])
            clients[0].post('/api/logout', base_url='https://localhost', headers=headers[0], json={})
            self.assertTrue(connections[0].closed.wait(2))
            self.assertFalse(connections[1].closed.is_set())
            self.assertEqual(clients[1].post('/api/hello', base_url='https://localhost',
                                           headers=headers[1], json={}).status_code, 200)
            connections[1].fail = True
            self.assertEqual(clients[1].post('/api/hello', base_url='https://localhost',
                                           headers=headers[1], json={}).status_code, 401)
            self.assertTrue(connections[1].closed.wait(2))
        finally:
            auth.close()
        self.assertTrue(all(c.closed.is_set() for c in connections))
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
