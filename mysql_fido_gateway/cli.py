"""Generate an editable Flask application from the installed wheel."""
import argparse
from importlib import resources
from pathlib import Path
import re
import shlex
import shutil

from .runtime import LIBRARY_VERSION

WHEEL_URL = ('https://raw.githubusercontent.com/ivanxma/mysql_fido_gateway_demo/'
             f'main/downloads/{LIBRARY_VERSION}/mysql_browser_fido_gateway-{LIBRARY_VERSION}-py3-none-any.whl')


def required(value, label):
    while not value:
        value = input(label + ': ').strip()
    return value


def copy_tree(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name in {'__pycache__', '.env', '.venv', '.flask_secret_key'}:
            continue
        target = destination / item.name
        if item.is_dir():
            copy_tree(item, target)
        else:
            target.write_bytes(item.read_bytes())
            if target.suffix in {'.sh', '.command'}:
                target.chmod(0o755)


def newapp(args):
    name = required(args.name, 'Application name / folder')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', name):
        raise ValueError('Use a folder name starting with a letter, followed by letters, digits, _ or -')
    parent = Path(args.parent).resolve()
    destination = parent / name
    if destination.exists() or destination.is_symlink():
        raise ValueError(f'Refusing to overwrite an existing path: {destination}')
    host = required(args.db_host, 'MySQL host (required; no default)')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+', host):
        raise ValueError('Specify a hostname or IP address, without a URL, username, or path')
    port = int(required(args.db_port, 'MySQL port (required; no default)'))
    if not 1 <= port <= 65535:
        raise ValueError('MySQL port must be between 1 and 65535')
    local = host in {'localhost', '127.0.0.1', '::1'}
    plaintext = args.allow_loopback_plaintext
    ca = args.db_ssl_ca
    if plaintext and not local:
        raise ValueError('--allow-loopback-plaintext is restricted to a loopback MySQL host')
    if not plaintext and not ca:
        if local and not args.non_interactive:
            plaintext = input('Use the loopback development TLS exception? [y/N]: ').strip().lower() in {'y', 'yes'}
        if not plaintext:
            ca = required(None, 'MySQL CA certificate path') if not args.non_interactive else None
    if not plaintext and not ca:
        raise ValueError('Supply --db-ssl-ca or explicitly allow loopback development plaintext')
    source = resources.files('mysql_fido_gateway').joinpath('starter')
    if not source.is_dir():
        raise ValueError('Starter assets are missing. Install the complete release wheel or build with scripts/build_release.py.')
    destination.mkdir()
    try:
        copy_tree(source, destination)
        app = destination / 'app.py'
        text = app.read_text().replace('MYSQL_HOST = None', f'MYSQL_HOST = {host!r}')
        text = text.replace('MYSQL_PORT = None', f'MYSQL_PORT = {port}')
        app.write_text(text)
        for name_template in ['base.html', 'login.html', 'register.html']:
            template = destination / 'templates' / 'auth' / name_template
            text = template.read_text().replace('APPLICATION DEMO', name.upper()).replace('My application', name)
            template.write_text(text)
        env = ['# Explicit MySQL transport. User credentials are entered in the browser.',
               f'DB_HOST={shlex.quote(host)}', f'DB_PORT={port}',
               'RP_ID=localhost', 'BROWSER_ORIGIN=https://localhost', 'REGISTRATION_MODE=browser',
               f'ALLOW_LOOPBACK_DB_PLAINTEXT={1 if plaintext else 0}',
               f'DB_SSL_CA={shlex.quote(ca or "")}', 'SESSION_TTL_SECONDS=300', '']
        config = destination / '.env'
        config.write_text('\n'.join(env));config.chmod(0o600)
        (destination / 'requirements.txt').write_text('mysql-browser-fido-gateway[flask] @ ' + WHEEL_URL + '\n')
    except Exception:
        shutil.rmtree(destination)
        raise
    print(f'Created {destination}')
    print(f'MySQL target: {host}:{port}')
    print('No MySQL username or password was saved. Enter those on the sign-in/registration page.')
    print(f'Next: cd {name} and run python start.py (or open start.command on macOS / start.bat on Windows).')
    print('A prepared MySQL WebAuthn account and trusted HTTPS are prerequisites. See GETTING_STARTED.md.')
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(prog='mysql-fido', description='Personal MySQL FIDO prototype/tutorial tools')
    sub = parser.add_subparsers(dest='command', required=True)
    new = sub.add_parser('newapp', help='Ask for a name and MySQL target, then generate a Flask frontend')
    new.add_argument('name', nargs='?')
    new.add_argument('--parent', default='.')
    new.add_argument('--db-host')
    new.add_argument('--db-port')
    new.add_argument('--db-ssl-ca')
    new.add_argument('--allow-loopback-plaintext', action='store_true')
    new.add_argument('--non-interactive', action='store_true')
    args = parser.parse_args(argv)
    if args.non_interactive and not all([args.name, args.db_host, args.db_port]):
        parser.error('--non-interactive requires name, --db-host and --db-port')
    try:
        newapp(args)
    except (OSError, ValueError, EOFError) as error:
        parser.exit(1, f'Generation stopped: {error}\n')
