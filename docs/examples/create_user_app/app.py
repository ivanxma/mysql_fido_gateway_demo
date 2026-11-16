"""Single-purpose create tutorial application."""
from pathlib import Path

from mysql_fido_gateway.flask_util import create_action_app


def create_app(gateway=None):
    return create_action_app(Path(__file__).parent, 'create', gateway=gateway)


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5004, debug=False, threaded=True)
