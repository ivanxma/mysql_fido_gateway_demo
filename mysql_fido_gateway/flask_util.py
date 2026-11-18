"""Shared Flask setup and message flows for the demo and action tutorials.

Install the demo extra to use these optional Flask helpers.
"""
import os
import queue
import re
import secrets
import threading
from urllib.parse import urlsplit

import mysql.connector
from flask import Flask, jsonify, redirect, render_template, request, session

from mysql_fido_gateway import BridgeError, Gateway
from mysql_fido_gateway.broker import Broker
from mysql_fido_gateway.config import mysql_config, loopback_allowed


def _create_app(root, actions, gateway=None, *, db_config=None, allow_loopback_plaintext=None):
    app = Flask(__name__, root_path=str(root.resolve()))
    origin = os.environ.get('BROWSER_ORIGIN', 'https://localhost').rstrip('/')
    rp_id = os.environ.get('RP_ID', 'localhost')
    # Narrow compatibility profile: match the origin produced by MySQL's native
    # WebAuthn client. Never rewrite the browser's signed clientDataJSON.
    if origin != 'https://' + rp_id:
        raise BridgeError('This profile requires BROWSER_ORIGIN=https://RP_ID on HTTPS port 443')
    app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_NAME='gateway_' + '_'.join(sorted(actions)),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=True,
                      SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=131072,
                      TRUSTED_HOSTS=([urlsplit(origin).hostname, '127.0.0.1']
                                     if origin == 'https://localhost' else [urlsplit(origin).hostname]))
    db_config = mysql_config(db_config if db_config is not None else getattr(gateway, 'db_config', None),
                             read_timeout=180, write_timeout=15)
    gateway = gateway or Gateway(db_config, origin, rp_id,
                                allow_loopback_plaintext=loopback_allowed(allow_loopback_plaintext))
    broker = Broker()
    app.extensions.update(browser_gateway=gateway, ceremony_broker=broker)

    @app.before_request
    def protect():
        # The development server prints its loopback URL. Send navigation from
        # that address to the HTTPS origin needed by WebAuthn and secure cookies.
        # Caddy preserves Host: localhost, so proxied visits do not redirect.
        if (origin == 'https://localhost' and request.method in {'GET', 'HEAD'}
                and request.host != 'localhost'):
            return redirect(origin + '/', code=302)
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
                               admin_enabled=bool(os.environ.get('ADMIN_TOKEN')),
                               admin_token=os.environ.get('ADMIN_TOKEN', '') if 'create' in actions else '',
                               db_host=db_config['host'], db_port=db_config['port'])

    @app.errorhandler(BridgeError)
    def bridge_error(error):
        return jsonify(error=str(error)), 400

    @app.post('/api/flows')
    def start():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error='Expected a JSON object'), 400
        action, username, password = (body.get(k) for k in ('action', 'username', 'password'))
        if action not in actions:
            return jsonify(error='Unknown action'), 400
        if action != 'setup' and (not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', username)):
            return jsonify(error='Use a MySQL username of 1–32 letters, numbers, or underscores'), 400
        if action != 'setup' and username.lower() == 'root':
            return jsonify(error='Root is not an end-user login in this demo'), 400
        if action != 'setup' and (not isinstance(password, str) or not password or len(password) > 1024):
            return jsonify(error='Enter a database password'), 400
        admin_password = None
        if action in {'setup', 'create'}:
            expected = os.environ.get('ADMIN_TOKEN', '')
            supplied = body.get('admin_token', '')
            if not expected or not isinstance(supplied, str) or not secrets.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8')):
                return jsonify(error='Administrator operations require the configured administrator token'), 403
            if action == 'create' and not username.startswith('demo_'):
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
            command_started = False
            def report_command(sql):
                nonlocal command_started
                command_started = True
                flow.events.put_nowait({'type': 'command', 'sql': sql})

            def execute(cursor, sql, params=None, display=None):
                report_command(display or sql)
                if params is None:
                    return cursor.execute(sql)
                return cursor.execute(sql, params)

            try:
                if action in {'setup', 'create'}:
                    connection = mysql.connector.connect(user='root', password=admin_password,
                                                         use_pure=True, **db_config)
                    with connection.cursor() as cursor:
                        execute(cursor, "SELECT PLUGIN_STATUS FROM INFORMATION_SCHEMA.PLUGINS WHERE PLUGIN_NAME='authentication_webauthn'")
                        if cursor.fetchone() != ('ACTIVE',):
                            raise BridgeError('MySQL WebAuthn plugin is not ACTIVE; no changes were made')
                        execute(cursor, 'SELECT @@GLOBAL.authentication_webauthn_rp_id, @@GLOBAL.connect_timeout')
                        server_rp, timeout = cursor.fetchone()
                        if action == 'setup':
                            execute(cursor, 'SET PERSIST authentication_webauthn_rp_id = %s', (rp_id,),
                                    display=f'SET PERSIST authentication_webauthn_rp_id = {rp_id!r}')
                            execute(cursor, 'SET PERSIST connect_timeout = %s', (max(180, timeout),),
                                    display=f'SET PERSIST connect_timeout = {max(180, timeout)}')
                            execute(cursor, 'SELECT @@GLOBAL.authentication_webauthn_rp_id, @@GLOBAL.connect_timeout')
                            verified_rp, verified_timeout = cursor.fetchone()
                            if verified_rp != rp_id or verified_timeout < 150:
                                raise BridgeError('MySQL settings verification failed; check the server settings before retrying')
                            result = {'message': f'MySQL is ready. RP ID: {verified_rp}; connect_timeout: {verified_timeout}s. Create a user below.',
                                      'rp_id': verified_rp, 'connect_timeout': verified_timeout}
                        else:
                            if server_rp != rp_id or timeout < 150:
                                raise BridgeError('Use the server setup banner above to set the MySQL RP ID and connection timeout')
                            host = os.environ.get('DB_ACCOUNT_HOST', 'localhost')
                            if reset:
                                execute(cursor, 'DROP USER IF EXISTS %s@%s', (username, host))
                                dropped = True
                            execute(cursor, 'CREATE USER %s@%s IDENTIFIED WITH caching_sha2_password BY %s '
                                           'AND IDENTIFIED WITH authentication_webauthn', (username, host, password),
                                    display="CREATE USER %s@%s IDENTIFIED WITH caching_sha2_password BY '<redacted>' "
                                            'AND IDENTIFIED WITH authentication_webauthn')
                            result = {'message': f'Created {username}@{host}. Register its YubiKey next.'}
                elif action == 'register':
                    result = gateway.register(username, password, flow.ask, on_command=report_command)
                    result['message'] = 'MySQL accepted registration. Test login next.'
                else:
                    connection = gateway.connect(username, password, flow.ask)
                    with connection.cursor() as cursor:
                        execute(cursor, "SELECT 'hello world', CURRENT_USER(), CONNECTION_ID(), @@version")
                        row = cursor.fetchone()
                    result = {'message': row[0], 'mysql_account': row[1], 'connection_id': row[2],
                              'server_version': row[3], 'verified_by': 'MySQL authentication OK + SQL query'}
                flow.finish({'type': 'success', 'result': result})
            except BridgeError as error:
                flow.finish({'type': 'error', 'message': str(error)})
            except mysql.connector.Error as error:
                # Do not return connector SQL text or passwords in error messages.
                stage = 'SQL execution' if command_started else 'database authentication'
                app.logger.warning('MySQL operation failed: errno=%s class=%s action=%s stage=%s',
                                   error.errno, type(error).__name__, action, stage)
                if error.errno == -1:
                    message = f'Connector/Python failed during {action} ({type(error).__name__}; code -1). '
                    safe_details = {'Expected EOF packet', 'Failed parsing EOF packet.',
                                    'Failed parsing column information', 'Illegal result set', 'Empty response'}
                    if error.msg in safe_details:
                        message += error.msg + '. '
                else:
                    message = f'MySQL rejected {action} (error {error.errno}). '
                if error.errno == 1045 and not command_started:
                    if action in {'register', 'login'}:
                        message += ('Access denied before any SQL command was sent. Enter the MySQL username '
                                    'and the new user password chosen in Create database user. '
                                    'The root password and administrator token do not authenticate this account. '
                                    'If those credentials are correct, ask the administrator to check the account host and authentication configuration. ')
                    else:
                        message += 'Access denied while connecting as root. Check the MySQL root password and root account host. '
                if action == 'setup':
                    message += 'Setup may be partially applied. Check root privileges, SET PERSIST support, and the server settings before retrying. '
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


def create_demo_app(root, gateway=None, *, db_config=None, allow_loopback_plaintext=None):
    """Return the combined demo, using templates/static under the Path root."""
    return _create_app(root, {'setup', 'create', 'register', 'login'}, gateway,
                       db_config=db_config, allow_loopback_plaintext=allow_loopback_plaintext)


def create_action_app(root, action, gateway=None, *, db_config=None, allow_loopback_plaintext=None):
    """Return a single-action tutorial: create user or register a YubiKey.

    root is a Path containing templates and static. action is 'create' or
    'register'. gateway can be injected for tests. Other actions are rejected
    by the server even if a client submits them manually.
    """
    if action not in {'create', 'register'}:
        raise BridgeError('Choose the create or register tutorial')
    return _create_app(root, {action}, gateway, db_config=db_config,
                       allow_loopback_plaintext=allow_loopback_plaintext)
