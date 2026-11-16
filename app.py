"""Combined create-user, YubiKey registration, and login demo."""
from pathlib import Path

from mysql_fido_gateway.flask_util import create_demo_app


def create_app(gateway=None):
    return create_demo_app(Path(__file__).parent, gateway=gateway)


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5001, debug=False, threaded=True)
