"""Three-column reference application for the reusable MySQL browser gateway."""
import os
import queue
import re
import secrets
import threading
from urllib.parse import urlsplit

import mysql.connector
from flask import Flask, jsonify, render_template, request, session

from mysql_fido_gateway import BridgeError, Gateway
from mysql_fido_gateway.broker import Broker


def create_app(gateway=None):
    app = Flask(__name__)
    origin = os.environ.get('BROWSER_ORIGIN', 'https://localhost').rstrip('/')
    rp_id = os.environ.get('RP_ID', 'localhost')
    # Narrow compatibility profile: match the origin produced by MySQL's native
    # WebAuthn client. Never rewrite the browser's signed clientDataJSON.
    if origin != 'https://' + rp_id:
        raise BridgeError('This profile requires BROWSER_ORIGIN=https://RP_ID on HTTPS port 443')
    app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=True,
                      SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=131072,
                      TRUSTED_HOSTS=[urlsplit(origin).hostname])
    db_config = {'host': os.environ.get('DB_HOST', '127.0.0.1'),
                 'port': int(os.environ.get('DB_PORT', '5316')),
                 'connection_timeout': 10, 'read_timeout': 180, 'write_timeout': 15}
    if os.environ.get('DB_SSL_CA'):
        db_config.update(ssl_ca=os.environ['DB_SSL_CA'], ssl_verify_cert=True, ssl_verify_identity=True)
    gateway = gateway or Gateway(db_config, origin, rp_id,
                                allow_loopback_plaintext=os.environ.get('ALLOW_LOOPBACK_DB_PLAINTEXT') == '1')
    broker = Broker()
    app.extensions.update(browser_gateway=gateway, ceremony_broker=broker)

    @app.before_request
    def protect():
        session.setdefault('owner', secrets.token_urlsafe(32))
        session.setdefault('csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if request.headers.get('Origin') != origin:
                return jsonify(error='Origin mismatch'), 403
            if not secrets.compare_digest(request.headers.get('X-CSRF-Token', '').encode('utf-8'), session['csrf'].encode('ascii')):
                return jsonify(error='Invalid form token; reload this page'), 403

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'X-Frame-Options': 'DENY',
                                 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.get('/')
    def index():
        return render_template('index.html', csrf=session['csrf'], origin=origin, rp_id=rp_id,
                               admin_enabled=bool(os.environ.get('ADMIN_TOKEN')))

    @app.errorhandler(BridgeError)
    def bridge_error(error):
        return jsonify(error=str(error)), 400

    @app.post('/api/flows')
    def start():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error='Expected a JSON object'), 400
        action, username, password = (body.get(k) for k in ('action', 'username', 'password'))
        if action not in {'create', 'register', 'login'}:
            return jsonify(error='Unknown action'), 400
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', username):
            return jsonify(error='Use a MySQL username of 1–32 letters, numbers, or underscores'), 400
        if username.lower() == 'root':
            return jsonify(error='Root is not an end-user login in this demo'), 400
        if not isinstance(password, str) or not password or len(password) > 1024:
            return jsonify(error='Enter a database password'), 400
        admin_password = None
        if action == 'create':
            expected = os.environ.get('ADMIN_TOKEN', '')
            supplied = body.get('admin_token', '')
            if not expected or not isinstance(supplied, str) or not secrets.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8')):
                return jsonify(error='Account provisioning requires the configured administrator token'), 403
            if not username.startswith('demo_'):
                return jsonify(error='Provisioning is restricted to demo_ usernames'), 400
            admin_password = body.get('root_password')
            if not isinstance(admin_password, str) or not admin_password:
                return jsonify(error='Enter the root password'), 400
        flow = broker.create(session['owner'])
        reset = body.get('reset') is True
        # Request data is deliberately not placed in Flask's client-side cookie.
        def worker():
            connection = None
            dropped = False
            try:
                if action == 'create':
                    connection = mysql.connector.connect(user='root', password=admin_password,
                                                         use_pure=True, **db_config)
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT PLUGIN_STATUS FROM INFORMATION_SCHEMA.PLUGINS WHERE PLUGIN_NAME='authentication_webauthn'")
                        if cursor.fetchone() != ('ACTIVE',):
                            raise BridgeError('MySQL WebAuthn plugin is not ACTIVE; nothing was dropped')
                        cursor.execute('SELECT @@GLOBAL.authentication_webauthn_rp_id, @@GLOBAL.connect_timeout')
                        server_rp, timeout = cursor.fetchone()
                        if server_rp != rp_id or timeout < 150:
                            raise BridgeError('Set MySQL RP ID to RP_ID and connect_timeout >= 150 before provisioning')
                        host = os.environ.get('DB_ACCOUNT_HOST', 'localhost')
                        if reset:
                            cursor.execute('DROP USER IF EXISTS %s@%s', (username, host))
                            dropped = True
                        cursor.execute('CREATE USER %s@%s IDENTIFIED WITH caching_sha2_password BY %s '
                                       'AND IDENTIFIED WITH authentication_webauthn', (username, host, password))
                    result = {'message': f'Created {username}@{host}. Register its YubiKey next.'}
                elif action == 'register':
                    result = gateway.register(username, password, flow.ask)
                    result['message'] = 'MySQL accepted registration. Test login next.'
                else:
                    connection = gateway.connect(username, password, flow.ask)
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 'hello world', CURRENT_USER(), CONNECTION_ID(), @@version")
                        row = cursor.fetchone()
                    result = {'message': row[0], 'mysql_account': row[1], 'connection_id': row[2],
                              'server_version': row[3], 'verified_by': 'MySQL authentication OK + SQL query'}
                flow.finish({'type': 'success', 'result': result})
            except BridgeError as error:
                flow.finish({'type': 'error', 'message': str(error)})
            except mysql.connector.Error as error:
                # Do not return connector SQL text or passwords in error messages.
                app.logger.warning('MySQL operation failed: errno=%s action=%s', error.errno, action)
                message = f'MySQL rejected {action} (error {error.errno}). '
                if dropped:
                    message += 'The old account was dropped; recreation failed. '
                message += ('Check the server error log, RP/origin compatibility, attestation support, '
                            'account host, password, and server timeouts. No application-authentication fallback was used.')
                flow.finish({'type': 'error', 'message': message})
            except Exception as error:
                app.logger.warning('Gateway failure: %s', type(error).__name__)
                flow.finish({'type': 'error', 'message': 'Gateway failed (' + type(error).__name__ + '); no authentication fallback was used.'})
            finally:
                if connection is not None:
                    connection.close()
        threading.Thread(target=worker, daemon=True).start()
        return jsonify(flow_id=flow.id), 202

    @app.get('/api/flows/<flow_id>')
    def poll(flow_id):
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
            raise BridgeError('Invalid browser response')
        flow.respond(reply['request_id'], reply)
        return jsonify(accepted=True)

    return app


if __name__ == '__main__':
    # HTTPS terminates at the configured reverse proxy, never at a remote terminal.
    create_app().run(host='127.0.0.1', port=5000, debug=False, threaded=True)
