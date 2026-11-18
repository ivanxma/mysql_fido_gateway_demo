"""Three-in-one demo using the installed Flask FIDO library."""
from pathlib import Path
import os

from mysql_fido_gateway.flask_util import create_demo_app
from mysql_fido_gateway.runtime import run_demo_app

ROOT = Path(__file__).resolve().parent
MYSQL_HOST = None  # Required: set here or export DB_HOST.
MYSQL_PORT = None  # Required: set here or export DB_PORT.


def create_app(gateway=None, *, db_config=None, allow_loopback_plaintext=None):
    if gateway is None and db_config is None:
        ca = os.environ.get('DB_SSL_CA')
        db_config = {'host': os.environ.get('DB_HOST') or MYSQL_HOST,
                     'port': os.environ.get('DB_PORT') or MYSQL_PORT,
                     'ssl_ca': ca, 'ssl_verify_cert': bool(ca), 'ssl_verify_identity': bool(ca)}
    return create_demo_app(ROOT, gateway=gateway, db_config=db_config,
                           allow_loopback_plaintext=allow_loopback_plaintext)


if __name__ == '__main__':
    run_demo_app(ROOT, app_factory=create_app)
