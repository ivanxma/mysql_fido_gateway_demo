"""Small register/login application used by docs/new-application.md."""
import os
from pathlib import Path
import queue
import re
import secrets
import threading
from urllib.parse import urlsplit

import mysql.connector
from flask import Flask, jsonify, redirect, render_template, request, session

from mysql_fido_gateway import BridgeError, Gateway
from mysql_fido_gateway.broker import Broker


PROOF_SQL = "SELECT 'hello world', CURRENT_USER(), CONNECTION_ID(), @@version"


def create_app(gateway=None):
    app = Flask(__name__, root_path=str(Path(__file__).resolve().parent))
    origin = os.environ.get('BROWSER_ORIGIN', 'https://localhost').rstrip('/')
    rp_id = os.environ.get('RP_ID', 'localhost')
    if origin != 'https://' + rp_id:
        raise BridgeError('Set BROWSER_ORIGIN=https://RP_ID without a custom port')
    secret = os.environ.get('FLASK_SECRET_KEY')
    if not secret:
        raise BridgeError('Set FLASK_SECRET_KEY before starting the tutorial app')
    app.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_NAME='gateway_tutorial_session',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE='Strict',
        MAX_CONTENT_LENGTH=131072,
        TRUSTED_HOSTS=[rp_id, '127.0.0.1'] if rp_id == 'localhost' else [rp_id],
    )
    db_config = {
        'host': os.environ.get('DB_HOST', '127.0.0.1'),
        'port': int(os.environ.get('DB_PORT', '5316')),
        'connection_timeout': 10,
        'read_timeout': 180,
        'write_timeout': 15,
    }
    if os.environ.get('DB_SSL_CA'):
        db_config.update(ssl_ca=os.environ['DB_SSL_CA'],
                         ssl_verify_cert=True, ssl_verify_identity=True)
    if gateway is None:
        gateway = Gateway(
            db_config, origin, rp_id,
            allow_loopback_plaintext=os.environ.get('ALLOW_LOOPBACK_DB_PLAINTEXT') == '1',
        )
    broker = Broker()
    app.extensions.update(browser_gateway=gateway, ceremony_broker=broker)

    @app.before_request
    def protect():
        if (rp_id == 'localhost' and request.method in {'GET', 'HEAD'}
                and request.host != urlsplit(origin).netloc):
            return redirect(origin + '/')
        session.setdefault('owner', secrets.token_urlsafe(32))
        session.setdefault('csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if request.headers.get('Origin') != origin:
                return jsonify(error='Origin mismatch'), 403
            supplied = request.headers.get('X-CSRF-Token', '')
            if not secrets.compare_digest(supplied.encode('utf-8'), session['csrf'].encode('ascii')):
                return jsonify(error='Reload the page and try again: invalid CSRF token'), 403

    @app.after_request
    def response_headers(response):
        response.headers.update({
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; "
                                       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })
        return response

    @app.errorhandler(BridgeError)
    def bridge_error(error):
        return jsonify(error=str(error)), 400

    @app.get('/')
    def index():
        return render_template('index.html', csrf=session['csrf'], origin=origin, rp_id=rp_id)

    def worker(flow, action, username, password):
        try:
            def show_command(sql):
                flow.events.put_nowait({'type': 'command', 'sql': sql})

            if action == 'register':
                result = gateway.register(username, password, flow.ask, on_command=show_command)
                result['message'] = 'MySQL accepted registration. Try Login next.'
            else:
                # Authentication completes before this context exposes a connection.
                # The context closes it before the success event is emitted.
                with gateway.connect(username, password, flow.ask) as connection:
                    with connection.cursor() as cursor:
                        show_command(PROOF_SQL)
                        cursor.execute(PROOF_SQL)
                        greeting, account, connection_id, version = cursor.fetchone()
                result = {
                    'message': greeting,
                    'mysql_account': account,
                    'connection_id': connection_id,
                    'server_version': version,
                    'verified_by': 'MySQL authentication OK + SQL query',
                }
            event = {'type': 'success', 'result': result}
        except BridgeError as error:
            event = {'type': 'error', 'message': str(error)}
        except mysql.connector.Error as error:
            # Connector errors may include SQL or credential data; report only the number.
            event = {'type': 'error', 'message': f'MySQL operation failed (error {error.errno})'}
        except Exception:
            event = {'type': 'error', 'message': 'The operation failed; no authentication fallback was used'}
        flow.finish(event)

    @app.post('/api/flows')
    def start_flow():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error='Expected a JSON object'), 400
        action = body.get('action')
        username = body.get('username')
        password = body.get('password')
        if action not in {'register', 'login'}:
            return jsonify(error='Choose register or login'), 400
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', username):
            return jsonify(error='Use a MySQL username of 1–32 letters, digits, or underscores'), 400
        if username.lower() == 'root':
            return jsonify(error='Use the tutorial user, not root'), 400
        if not isinstance(password, str) or not password or len(password) > 1024:
            return jsonify(error='Enter the password chosen for this MySQL user'), 400
        flow = broker.create(session['owner'])
        threading.Thread(target=worker, args=(flow, action, username, password), daemon=True).start()
        return jsonify(flow_id=flow.id), 202

    @app.get('/api/flows/<flow_id>')
    def poll_flow(flow_id):
        flow = broker.get(flow_id, session['owner'])
        try:
            event = flow.events.get(timeout=1)
        except queue.Empty:
            event = {'type': 'waiting'}
        return jsonify(event)

    @app.post('/api/flows/<flow_id>/respond')
    def respond(flow_id):
        flow = broker.get(flow_id, session['owner'])
        reply = request.get_json(silent=True)
        if not isinstance(reply, dict) or not isinstance(reply.get('request_id'), str):
            raise BridgeError('Expected a browser reply with request_id')
        flow.respond(reply['request_id'], reply)
        return jsonify(accepted=True)

    return app


if __name__ == '__main__':
    print('Open the configured HTTPS origin in your browser (local default: https://localhost).')
    create_app().run(host='127.0.0.1', port=5002, debug=False, threaded=True)
