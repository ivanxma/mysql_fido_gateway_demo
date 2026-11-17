"""Three-in-one UI using the installed mysql-browser-fido-gateway Flask wheel.

Install dist/mysql_browser_fido_gateway-0.2.0-py3-none-any.whl[flask], then run
./start.sh (or python app.py with the documented environment/HTTPS setup).
"""
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
LIBRARY_VERSION = '0.2.0'


def _check_library():
    from importlib.metadata import PackageNotFoundError, version

    install = (f'{sys.executable} -m pip install --force-reinstall '
               f'"{ROOT}/dist/mysql_browser_fido_gateway-{LIBRARY_VERSION}-py3-none-any.whl[flask]"')
    try:
        installed = version('mysql-browser-fido-gateway')
    except PackageNotFoundError:
        raise SystemExit(f'Install the Flask FIDO wheel first:\n{install}') from None
    if installed != LIBRARY_VERSION:
        raise SystemExit(f'This demo requires library {LIBRARY_VERSION}; installed: {installed}.\n{install}')
    import mysql_fido_gateway
    location = Path(mysql_fido_gateway.__file__).resolve().parent
    if location == ROOT / 'mysql_fido_gateway':
        raise SystemExit(f'The demo requires the installed wheel. Replace the editable install:\n{install}')
    return installed, location


if __name__ == '__main__':
    # The source package lives beside app.py. Isolated imports select the
    # virtual environment's installed wheel instead of this checkout's code.
    if not sys.flags.isolated:
        os.execv(sys.executable, [sys.executable, '-I', str(Path(__file__).resolve()), *sys.argv[1:]])
    _check_library()

from mysql_fido_gateway.flask_util import create_demo_app


def create_app(gateway=None):
    # All provisioning, WebAuthn transport, and SQL handling is in the wheel.
    # This project owns the three-column template and its browser assets.
    return create_demo_app(ROOT, gateway=gateway)


def main():
    installed, location = _check_library()
    print(f'Using mysql-browser-fido-gateway {installed} from {location}', flush=True)
    if sys.argv[1:] == ['--check-library']:
        return
    if sys.argv[1:]:
        raise SystemExit('Usage: python app.py [--check-library]')
    create_app().run(host='127.0.0.1', port=5001, debug=False, threaded=True)


if __name__ == '__main__':
    main()
