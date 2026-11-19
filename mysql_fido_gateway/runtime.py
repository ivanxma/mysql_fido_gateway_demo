"""Installed-wheel checks and the three-in-one demo runner."""
import os
from pathlib import Path
import sys
from importlib.metadata import PackageNotFoundError, version

LIBRARY_VERSION = '0.3.1'


def check_library(root, *, required_version=LIBRARY_VERSION):
    root = Path(root).resolve()
    install = (f'{sys.executable} -m pip install --force-reinstall '
               f'"{root}/dist/mysql_browser_fido_gateway-{required_version}-py3-none-any.whl[flask]"')
    try:
        installed = version('mysql-browser-fido-gateway')
    except PackageNotFoundError:
        raise SystemExit(f'Install the Flask FIDO wheel first:\n{install}') from None
    if installed != required_version:
        raise SystemExit(f'This demo requires library {required_version}; installed: {installed}.\n{install}')
    location = Path(__file__).resolve().parent
    if location == root / 'mysql_fido_gateway':
        raise SystemExit(f'The demo requires the installed wheel. Replace the editable install:\n{install}')
    return installed, location


def run_demo_app(root, *, app_factory=None):
    """Start the installed-wheel demo with project-owned templates/static."""
    root = Path(root).resolve()
    if not sys.flags.isolated:
        os.execv(sys.executable, [sys.executable, '-I', str(root / 'app.py'), *sys.argv[1:]])
    installed, location = check_library(root)
    print(f'Using mysql-browser-fido-gateway {installed} from {location}', flush=True)
    if sys.argv[1:] == ['--check-library']:
        return
    if sys.argv[1:]:
        raise SystemExit('Usage: python app.py [--check-library]')
    from .flask_util import create_demo_app
    app = app_factory() if app_factory else create_demo_app(root)
    app.run(host='127.0.0.1', port=5001, debug=False, threaded=True)
