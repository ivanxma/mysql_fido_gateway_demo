"""YubiKey login → protected main page → Hello World."""
from pathlib import Path

from flask import jsonify, render_template

from mysql_fido_gateway.flask_login import create_gateway_app


HELLO_SQL = "SELECT %s AS message, CURRENT_USER() AS mysql_account, CONNECTION_ID() AS connection_id"


def create_app(gateway=None, **options):
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
