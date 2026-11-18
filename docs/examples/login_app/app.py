"""YubiKey login → protected main page → Hello World."""
from pathlib import Path
import os

from flask import jsonify, render_template

from mysql_fido_gateway.flask_login import create_gateway_app


HELLO_SQL = "SELECT %s AS message, CURRENT_USER() AS mysql_account, CONNECTION_ID() AS connection_id"

# Required connection assignments. The newapp CLI replaces these with your
# chosen host/port. Environment variables can override them at deployment.
MYSQL_HOST = None
MYSQL_PORT = None


def create_app(gateway=None, **options):
    if gateway is None and 'db_config' not in options:
        ca = os.environ.get('DB_SSL_CA')
        options['db_config'] = {
            'host': os.environ.get('DB_HOST') or MYSQL_HOST,
            'port': os.environ.get('DB_PORT') or MYSQL_PORT,
            'ssl_ca': ca,
            'ssl_verify_cert': bool(ca),
            'ssl_verify_identity': bool(ca),
        }
        options['allow_loopback_plaintext'] = os.environ.get('ALLOW_LOOPBACK_DB_PLAINTEXT') == '1'
    # These editable project templates extend the library's default pages.
    options.setdefault('auth_base_template', 'auth/base.html')
    options.setdefault('login_template', 'auth/login.html')
    options.setdefault('registration_template', 'auth/register.html')
    app, auth = create_gateway_app(Path(__file__).parent, gateway=gateway, **options)

    @app.get('/main')
    @auth.login_required
    def main():
        return render_template('main.html')

    @app.post('/api/hello')
    @auth.login_required
    def hello():
        with auth.getConnection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(HELLO_SQL, ('Hello World',))
                result = cursor.fetchone()
        return jsonify(result)

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5003, debug=False, threaded=True)
