"""Flask wiring, browser message transport, and per-user MySQL workers.

This is a single-process tutorial helper, not part of the Gateway package API.
Connections are created, queried, and closed exclusively by their own worker.
"""
import atexit
from concurrent.futures import Future, TimeoutError
from functools import wraps
import os
import queue
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

import mysql.connector
from flask import Flask, g, jsonify, redirect, render_template, request, session

from mysql_fido_gateway import BridgeError, Gateway
from mysql_fido_gateway.broker import Broker


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

    def alive(self):
        return not self.stop.is_set() and self.clock() < self.deadline

    def query(self, sql):
        if not self.alive():
            raise SessionEnded()
        result = Future()
        try:
            self.tasks.put_nowait((sql, result))
            return result.result(timeout=20)
        except (queue.Full, TimeoutError):
            self.stop.set()
            raise SessionEnded() from None

    @staticmethod
    def fetch(connection, sql):
        with connection.cursor(dictionary=True, buffered=True) as cursor:
            cursor.execute(sql)
            return cursor.fetchone()

    def serve(self, connection):
        while self.alive():
            try:
                sql, result = self.tasks.get(timeout=.25)
            except queue.Empty:
                continue
            try:
                if not self.alive():
                    raise SessionEnded()
                # Never reconnect automatically: a new connection needs the key.
                self.fetch(connection, 'SELECT 1 AS alive')
                value = self.fetch(connection, sql) if sql else None
                if not self.alive():
                    raise SessionEnded()
                result.set_result(value)
            except Exception:
                result.set_exception(SessionEnded())
                break

    def finish(self):
        self.stop.set()
        while True:
            try:
                _, result = self.tasks.get_nowait()
                result.set_exception(SessionEnded())
            except queue.Empty:
                break
        self.closed.set()


class GatewayLogin:
    """Register login/logout routes and expose login_required and query(sql)."""

    def __init__(self, app, gateway, origin, *, session_seconds=300, clock=time.monotonic):
        self.app, self.gateway, self.origin = app, gateway, origin
        self.session_seconds, self.clock = session_seconds, clock
        self.broker = Broker()
        self.logins = {}
        self.lock = threading.Lock()
        app.add_url_rule('/', 'index', self.index)
        app.add_url_rule('/login', 'login', self.login)
        app.add_url_rule('/api/login', 'start_login', self.start_login, methods=['POST'])
        app.add_url_rule('/api/login/<flow_id>', 'poll_login', self.poll_login)
        app.add_url_rule('/api/login/<flow_id>/respond', 'respond_login', self.respond_login, methods=['POST'])
        app.add_url_rule('/api/logout', 'logout', self.logout, methods=['POST'])
        app.before_request(self.protect)
        app.context_processor(lambda: {'csrf': session['csrf']})
        app.register_error_handler(SessionEnded, self.session_ended)
        app.register_error_handler(BridgeError, lambda error: (jsonify(error=str(error)), 400))
        atexit.register(self.close)

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

    def query(self, sql):
        """Execute server-owned read-only SQL on this user's authenticated worker.

        Never pass SQL from a request. This tutorial returns one dictionary row.
        """
        return g.mysql_login.query(sql)

    def index(self):
        return redirect('/main' if self.current() else '/login')

    def login(self):
        return redirect('/main') if self.current() else render_template('login.html')

    def start_login(self):
        if self.current():
            return jsonify(error='Log out before signing in again.'), 409
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise BridgeError('Expected a JSON object')
        username, password = body.get('username'), body.get('password')
        if (not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', username)
                or username.lower() == 'root'):
            raise BridgeError('Use a provisioned non-root MySQL username')
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise BridgeError('Enter your MySQL password')
        with self.lock:
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


def create_gateway_app(root, gateway=None, *, session_seconds=None, clock=time.monotonic):
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
        config = dict(host=os.environ.get('DB_HOST', '127.0.0.1'),
                      port=int(os.environ.get('DB_PORT', '5316')),
                      connection_timeout=10, read_timeout=15, write_timeout=10)
        if os.environ.get('DB_SSL_CA'):
            config.update(ssl_ca=os.environ['DB_SSL_CA'], ssl_verify_cert=True, ssl_verify_identity=True)
        gateway = Gateway(config, origin, rp_id,
                          allow_loopback_plaintext=os.environ.get('ALLOW_LOOPBACK_DB_PLAINTEXT') == '1')
    auth = GatewayLogin(app, gateway, origin, session_seconds=ttl, clock=clock)
    app.extensions['gateway_login'] = auth

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'X-Frame-Options': 'DENY', 'Content-Security-Policy':
                                 "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    return app, auth
