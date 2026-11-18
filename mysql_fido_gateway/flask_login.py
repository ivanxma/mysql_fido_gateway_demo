"""Flask login sessions and SQL access on each user's authenticated worker."""
import atexit
from concurrent.futures import Future, TimeoutError
from contextlib import contextmanager
from functools import wraps
import os
import queue
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

import mysql.connector
from flask import Blueprint, Flask, current_app, g, jsonify, redirect, render_template, request, session

from mysql_fido_gateway import BridgeError, Gateway
from mysql_fido_gateway.broker import Broker
from mysql_fido_gateway.config import mysql_config, loopback_allowed


class SessionEnded(Exception):
    pass


class _Login:
    def __init__(self, flow, clock):
        self.flow = flow
        self.clock = clock
        self.deadline = clock() + 150
        self.tasks = queue.Queue(maxsize=8)
        self.stop = threading.Event()
        self.closed = threading.Event()
        self.ready = False
        self.access = threading.RLock()
        self.borrowed = False

    def alive(self):
        return not self.stop.is_set() and self.clock() < self.deadline

    def run(self, operation, *, check=True):
        if not self.access.acquire(timeout=20):
            self.stop.set()
            raise SessionEnded()
        try:
            return self._submit(operation, check=check)
        finally:
            self.access.release()

    def _submit(self, operation, *, check):
        if not self.alive():
            raise SessionEnded()
        result = Future()
        try:
            self.tasks.put_nowait((operation, check, result))
            return result.result(timeout=20)
        except (queue.Full, TimeoutError):
            self.stop.set()
            raise SessionEnded() from None

    @staticmethod
    def fetch(connection, sql, params=None, *, many=False):
        with connection.cursor(dictionary=True, buffered=True) as cursor:
            cursor.execute(sql, params) if params is not None else cursor.execute(sql)
            return cursor.fetchall() if many else cursor.fetchone()

    def query(self, sql, params=None, *, many=False):
        return self.run(lambda connection: self.fetch(connection, sql, params, many=many) if sql else None)

    def serve(self, connection):
        while self.alive():
            try:
                operation, check, result = self.tasks.get(timeout=.25)
            except queue.Empty:
                continue
            try:
                if not self.alive():
                    raise SessionEnded()
                # Never reconnect automatically: a new connection needs the key.
                if check:
                    self.fetch(connection, 'SELECT 1 AS alive')
            except Exception:
                result.set_exception(SessionEnded())
                break
            try:
                value = operation(connection)
                if not self.alive():
                    raise SessionEnded()
                result.set_result(value)
            except SessionEnded:
                result.set_exception(SessionEnded())
                break
            except Exception as error:
                # SQL/business errors belong to the application; a failed health
                # check or expired session still revokes the connection.
                result.set_exception(error)

    def finish(self):
        self.stop.set()
        while True:
            try:
                _, _, result = self.tasks.get_nowait()
                result.set_exception(SessionEnded())
            except queue.Empty:
                break
        self.closed.set()


class _Connection:
    """Request-scoped facade; native objects are used exclusively by the worker."""
    def __init__(self, login):
        self.login = login
        self.active = True
        self.thread = threading.get_ident()
        self.cursors = []

    def _call(self, operation):
        if not self.active or threading.get_ident() != self.thread:
            raise RuntimeError('Connection is valid only inside its borrowing request/context')
        return self.login.run(operation, check=False)

    def _begin(self):
        def begin(connection):
            self.autocommit = connection.autocommit
            connection.autocommit = False
        try:
            self.login.run(begin)
        except Exception:
            self.login.stop.set()
            raise SessionEnded() from None

    def _finish(self, *, commit):
        def finish(connection):
            try:
                # Close cursors before transaction commands. Applications must
                # consume pending results from explicit unbuffered cursors.
                for cursor in self.cursors:
                    cursor._close_native()
                if commit:
                    connection.commit()
                else:
                    connection.rollback()
                connection.autocommit = self.autocommit
            except Exception:
                self.login.stop.set()
                raise SessionEnded() from None
        self._call(finish)

    def cursor(self, *, dictionary=True, buffered=True, **options):
        cursor = _Cursor(self)
        def create(connection):
            cursor.native = connection.cursor(dictionary=dictionary, buffered=buffered, **options)
        self._call(create)
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self._call(lambda connection: connection.commit())

    def rollback(self):
        self._call(lambda connection: connection.rollback())


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.native = None
        self.closed = False

    def _call(self, operation):
        if self.closed:
            raise RuntimeError('Cursor is closed')
        return self.connection._call(lambda connection: operation(self.native))

    def execute(self, sql, params=None):
        def execute(cursor):
            cursor.execute(sql, params) if params is not None else cursor.execute(sql)
        self._call(execute)

    def executemany(self, sql, params):
        def execute(cursor):
            cursor.executemany(sql, params)
        self._call(execute)

    def fetchone(self):
        return self._call(lambda cursor: cursor.fetchone())

    def fetchall(self):
        return self._call(lambda cursor: cursor.fetchall())

    def fetchmany(self, size=1):
        return self._call(lambda cursor: cursor.fetchmany(size))

    def nextset(self):
        return self._call(lambda cursor: cursor.nextset())

    @property
    def rowcount(self):
        return self._call(lambda cursor: cursor.rowcount)

    @property
    def lastrowid(self):
        return self._call(lambda cursor: cursor.lastrowid)

    @property
    def description(self):
        return self._call(lambda cursor: cursor.description)

    def _close_native(self):
        if not self.closed:
            self.native.close()
            self.closed = True

    def close(self):
        if not self.closed:
            self.connection._call(lambda connection: self._close_native())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class GatewayLogin:
    """Install FIDO login routes and per-user, worker-owned SQL access."""

    def __init__(self, app, gateway, origin, *, session_seconds=300, clock=time.monotonic,
                 login_template='mysql_fido_gateway/login.html',
                 registration_template='mysql_fido_gateway/register.html',
                 auth_base_template='mysql_fido_gateway/auth_base.html'):
        self.app, self.gateway, self.origin = app, gateway, origin
        self.login_template = login_template
        self.registration_template = registration_template
        self.auth_base_template = auth_base_template
        self.session_seconds, self.clock = session_seconds, clock
        self.broker = Broker()
        self.registration_broker = Broker()
        self.logins = {}
        self.lock = threading.Lock()
        app.register_blueprint(Blueprint('gateway_auth', __name__,
                               template_folder='templates', static_folder='static',
                               static_url_path='/_gateway/static'))
        app.add_url_rule('/', 'index', self.index)
        app.add_url_rule('/login', 'login', self.login)
        app.add_url_rule('/register', 'register', self.register)
        app.add_url_rule('/api/register', 'start_register', self.start_register, methods=['POST'])
        app.add_url_rule('/api/register/<flow_id>', 'poll_register', self.poll_register)
        app.add_url_rule('/api/register/<flow_id>/respond', 'respond_register', self.respond_register, methods=['POST'])
        app.add_url_rule('/api/login', 'start_login', self.start_login, methods=['POST'])
        app.add_url_rule('/api/login/<flow_id>', 'poll_login', self.poll_login)
        app.add_url_rule('/api/login/<flow_id>/respond', 'respond_login', self.respond_login, methods=['POST'])
        app.add_url_rule('/api/logout', 'logout', self.logout, methods=['POST'])
        app.before_request(self.protect)
        app.context_processor(self.template_context)
        app.register_error_handler(SessionEnded, self.session_ended)
        app.register_error_handler(BridgeError, lambda error: (jsonify(error=str(error)), 400))
        atexit.register(self.close)

    def template_context(self):
        target = getattr(self.gateway, 'db_config', {})
        if not isinstance(target, dict):
            target = {}
        return {'csrf': session['csrf'], 'auth_base_template': self.auth_base_template,
                'mysql_target': target.get('host'), 'mysql_port': target.get('port')}

    def current(self):
        with self.lock:
            login = self.logins.get(session['owner'])
            return login if login and login.ready and login.alive() else None

    def revoke(self):
        with self.lock:
            login = self.logins.pop(session.get('owner'), None)
            if login:
                login.stop.set()
        session.clear()

    def close(self):
        """Stop this process's sessions (also used by tests and shutdown)."""
        with self.lock:
            logins = list(self.logins.values())
            self.logins.clear()
        for login in logins:
            login.stop.set()
        # Pending browser prompts have their own 150-second deadline.
        deadline = time.monotonic() + 2
        for login in logins:
            login.closed.wait(max(0, deadline - time.monotonic()))

    def protect(self):
        if request.method in {'GET', 'HEAD'} and request.host != urlsplit(self.origin).netloc:
            return redirect(self.origin + '/')
        session.setdefault('owner', secrets.token_urlsafe(32))
        session.setdefault('csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            supplied = request.headers.get('X-CSRF-Token', '')
            if (request.headers.get('Origin') != self.origin or not secrets.compare_digest(
                    supplied.encode(), session['csrf'].encode())):
                return jsonify(error='Origin or CSRF mismatch. Reload the login page.'), 403

    def session_ended(self, error):
        self.revoke()
        if request.path.startswith('/api/'):
            return jsonify(error='Session ended. Sign in again.', redirect='/login'), 401
        return redirect('/login')

    def login_required(self, view):
        @wraps(view)
        def protected(*args, **kwargs):
            g.mysql_login = self.current()
            if g.mysql_login is None:
                raise SessionEnded()
            g.mysql_login.query(None)  # Health check before every protected action.
            return view(*args, **kwargs)
        return protected

    def _request_login(self):
        login = getattr(g, 'mysql_login', None)
        if login is None or login is not self.current():
            raise SessionEnded()
        return login

    def query(self, sql, params=None, *, many=False):
        """Execute application-owned SELECT SQL with bound parameters."""
        return self._request_login().query(sql, params, many=many)

    @contextmanager
    def get_connection(self):
        """Borrow this user's connection facade for a managed transaction.

        The context commits on success, rolls back on error, and closes its
        cursors. All driver calls stay on the owning worker. Do not retain the
        facade/cursors outside this context or share them across request threads.
        """
        login = self._request_login()
        if not login.access.acquire(timeout=20):
            login.stop.set()
            raise SessionEnded()
        if login.borrowed:
            login.access.release()
            raise RuntimeError('Nested connection contexts are not supported')
        login.borrowed = True
        connection = _Connection(login)
        try:
            connection._begin()
            try:
                yield connection
            except BaseException:
                connection._finish(commit=False)
                raise
            else:
                connection._finish(commit=True)
        finally:
            connection.active = False
            login.borrowed = False
            login.access.release()

    getConnection = get_connection

    def run(self, operation):
        """Run a complete transaction with the native Connector/Python object.

        operation(connection) runs on the worker, without Flask request context.
        Return detached application data, never the connection or its cursors.
        """
        with self.get_connection() as connection:
            return connection._call(operation)

    def index(self):
        return redirect('/main' if self.current() else '/login')

    def login(self):
        return redirect('/main') if self.current() else render_template(self.login_template)

    def register(self):
        return redirect('/main') if self.current() else render_template(self.registration_template)

    @staticmethod
    def credentials():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise BridgeError('Expected a JSON object')
        username, password = body.get('username'), body.get('password')
        if (not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', username)
                or username.lower() == 'root'):
            raise BridgeError('Use a provisioned non-root MySQL username')
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise BridgeError('Enter your MySQL password')
        return username, password

    def start_register(self):
        if self.current():
            return jsonify(error='Log out before registering a key.'), 409
        username, password = self.credentials()
        owner = session['owner']
        # A separate broker prevents a registration event being consumed by the
        # login endpoint and accidentally authorizing/rotating a login session.
        with self.lock:
            login = self.logins.get(owner)
            if login and login.alive():
                raise BridgeError('Finish the current login before registering a key')
            flow = self.registration_broker.create(owner)
        threading.Thread(target=self.registration_worker,
                         args=(flow, username, [password]), daemon=True).start()
        return jsonify(flow_id=flow.id), 202

    def registration_worker(self, flow, username, credentials):
        password = credentials.pop()
        try:
            result = self.gateway.register(username, password, flow.ask)
            if result.get('registered') is not True:
                raise BridgeError('MySQL did not accept registration')
            flow.finish({'type': 'success', 'result': {
                'registered': True, 'message': 'Your passkey is registered. You can now sign in.'}})
        except Exception as error:
            message = (f'MySQL registration failed (error {error.errno}). Check your account details.'
                       if isinstance(error, mysql.connector.Error)
                       else 'Registration was cancelled or could not be completed. Try again with a compatible security key.')
            flow.finish({'type': 'error', 'message': message})
        finally:
            password = None

    def poll_register(self, flow_id):
        flow = self.registration_broker.get(flow_id, session['owner'])
        try:
            event = flow.events.get(timeout=1)
        except queue.Empty:
            event = {'type': 'waiting'}
        return jsonify(event)

    def respond_register(self, flow_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('request_id'), str):
            raise BridgeError('Expected request_id and browser response')
        self.registration_broker.get(flow_id, session['owner']).respond(body['request_id'], body)
        return jsonify(accepted=True)

    def start_login(self):
        if self.current():
            return jsonify(error='Log out before signing in again.'), 409
        username, password = self.credentials()
        with self.lock:
            with self.registration_broker.lock:
                if any(flow.owner == session['owner'] and not flow.done and time.monotonic() < flow.deadline
                       for flow in self.registration_broker.flows.values()):
                    raise BridgeError('Finish the current registration before signing in')
            if len(self.logins) >= 32:
                raise BridgeError('All sessions are busy. Try again later.')
            flow = self.broker.create(session['owner'])
            login = _Login(flow, self.clock)
            previous = self.logins.get(session['owner'])
            if previous:
                previous.stop.set()
            self.logins[session['owner']] = login
        threading.Thread(target=self.worker, args=(login, username, [password]), daemon=True).start()
        return jsonify(flow_id=flow.id), 202

    def worker(self, login, username, credentials):
        # Empty the thread's argument container so it cannot retain the password.
        password = credentials.pop()
        connection = None
        try:
            connection = self.gateway.connect(username, password, login.flow.ask)
            password = None
            # No SQL is available until MySQL has accepted both factors.
            connection.autocommit = True
            with self.lock:
                if not login.alive() or self.logins.get(login.flow.owner) is not login:
                    raise SessionEnded()
            login.flow.finish({'type': 'success', 'redirect': '/main'})
            login.serve(connection)
        except Exception as error:
            if not login.flow.done:
                message = (f'MySQL login failed (error {error.errno})'
                           if isinstance(error, mysql.connector.Error)
                           else 'Login failed or expired. Try again with your registered key.')
                login.flow.finish({'type': 'error', 'message': message})
        finally:
            password = None
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            login.finish()
            with self.lock:
                for owner, candidate in list(self.logins.items()):
                    if candidate is login:
                        del self.logins[owner]

    def poll_login(self, flow_id):
        flow = self.broker.get(flow_id, session['owner'])
        try:
            event = flow.events.get(timeout=1)
        except queue.Empty:
            event = {'type': 'waiting'}
        if event['type'] == 'success':
            with self.lock:
                login = self.logins.get(session['owner'])
                if not login or login.flow is not flow or not login.alive():
                    raise SessionEnded()
                del self.logins[session['owner']]
                session.clear()  # Rotate the browser's owner and CSRF after login.
                session.update(owner=secrets.token_urlsafe(32), csrf=secrets.token_urlsafe(32))
                login.deadline = self.clock() + self.session_seconds
                login.ready = True
                self.logins[session['owner']] = login
        return jsonify(event)

    def respond_login(self, flow_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('request_id'), str):
            raise BridgeError('Expected request_id and browser response')
        self.broker.get(flow_id, session['owner']).respond(body['request_id'], body)
        return jsonify(accepted=True)

    def logout(self):
        self.revoke()
        return jsonify(redirect='/login')


def get_connection():
    """Borrow the authenticated connection inside a login_required Flask route."""
    return current_app.extensions['gateway_login'].get_connection()


getConnection = get_connection


def create_gateway_app(root, gateway=None, *, db_config=None, allow_loopback_plaintext=None,
                       session_seconds=None, clock=time.monotonic,
                       login_template='mysql_fido_gateway/login.html',
                       registration_template='mysql_fido_gateway/register.html',
                       auth_base_template='mysql_fido_gateway/auth_base.html'):
    """Create Flask, configure Gateway from the environment, and install login routes.

    Return (app, auth). root contains templates/static. gateway and clock can be
    injected for tests. session_seconds overrides SESSION_TTL_SECONDS (1–3600).
    """
    app = Flask(__name__, root_path=str(root.resolve()))
    origin = os.environ.get('BROWSER_ORIGIN', 'https://localhost').rstrip('/')
    rp_id = os.environ.get('RP_ID', 'localhost')
    if origin != 'https://' + rp_id:
        raise BridgeError('Set BROWSER_ORIGIN=https://RP_ID without a custom port')
    secret = os.environ.get('FLASK_SECRET_KEY')
    if not secret:
        raise BridgeError('Set FLASK_SECRET_KEY before starting')
    ttl = int(os.environ.get('SESSION_TTL_SECONDS', '300')) if session_seconds is None else session_seconds
    if not 1 <= ttl <= 3600:
        raise BridgeError('SESSION_TTL_SECONDS must be between 1 and 3600')
    app.config.update(SECRET_KEY=secret, SESSION_COOKIE_NAME='gateway_login_session',
                      SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=131072,
                      TRUSTED_HOSTS=[rp_id, '127.0.0.1'] if rp_id == 'localhost' else [rp_id])
    if gateway is None:
        config = mysql_config(db_config)
        gateway = Gateway(config, origin, rp_id,
                          allow_loopback_plaintext=loopback_allowed(allow_loopback_plaintext))
    auth = GatewayLogin(app, gateway, origin, session_seconds=ttl, clock=clock,
                        login_template=login_template, registration_template=registration_template,
                        auth_base_template=auth_base_template)
    app.extensions['gateway_login'] = auth

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'X-Frame-Options': 'DENY', 'Content-Security-Policy':
                                 "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    return app, auth
