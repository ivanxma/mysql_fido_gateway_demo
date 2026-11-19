"""Downloadable starter bootstrap. No database account or server is provisioned."""
import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
import webbrowser

VERSION = '0.3.1'
WHEEL = f'mysql_browser_fido_gateway-{VERSION}-py3-none-any.whl'
ROOT = Path(__file__).resolve().parent
WHEEL_URL = ('https://raw.githubusercontent.com/ivanxma/mysql_fido_gateway_demo/'
             'main/downloads/0.3.1/' + WHEEL)


def load_environment(root, inherited=None):
    """Read simple dotenv assignments without executing shell code."""
    env = dict(os.environ if inherited is None else inherited)
    config = root / '.env'
    if not config.exists():
        shutil.copyfile(root / 'config.example.env', config)
    config.chmod(0o600)
    loaded = {}
    for line in config.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:]
        key, sep, value = line.partition('=')
        key = key.strip()
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise ValueError('Use KEY=value assignments in .env')
        values = shlex.split(value, comments=True)
        if len(values) > 1:
            raise ValueError(f'Quote values containing spaces in .env: {key}')
        env[key] = values[0] if values else ''
        loaded[key] = env[key]
    for key, label in [('DB_HOST', 'MySQL host'), ('DB_PORT', 'MySQL port')]:
        if not env.get(key):
            if not sys.stdin.isatty():
                raise ValueError(f'Set {key} explicitly in .env before starting; no default is assumed')
            env[key] = input(label + ' (required; no default): ').strip()
            if not env[key]:
                raise ValueError(f'{key} is required')
    try:
        port = int(env['DB_PORT'])
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError('DB_PORT must be between 1 and 65535') from None
    local = env['DB_HOST'] in {'localhost', '127.0.0.1', '::1'}
    if not env.get('DB_SSL_CA') and not (local and env.get('ALLOW_LOOPBACK_DB_PLAINTEXT') == '1'):
        if not sys.stdin.isatty():
            raise ValueError('Set DB_SSL_CA for verified TLS, or explicitly allow the loopback development exception')
        allow = local and input('Use the loopback development TLS exception? [y/N]: ').lower() in {'y', 'yes'}
        if allow:
            env['ALLOW_LOOPBACK_DB_PLAINTEXT'] = '1'
        else:
            env['DB_SSL_CA'] = input('MySQL CA certificate path (required): ').strip()
            if not env['DB_SSL_CA']:
                raise ValueError('MySQL CA certificate path is required')
    keys = ['DB_HOST', 'DB_PORT', 'DB_SSL_CA', 'ALLOW_LOOPBACK_DB_PLAINTEXT']
    if any(loaded.get(key) != env.get(key, '') for key in keys):
        with config.open('a') as target:
            target.write('\n# Connection settings confirmed by starter\n')
            for key in keys:
                target.write(key + '=' + shlex.quote(env.get(key, '')) + '\n')
    if not env.get('FLASK_SECRET_KEY'):
        import secrets
        secret = root / '.flask_secret_key'
        try:
            fd = os.open(secret, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'w') as target:
                target.write(secrets.token_hex(32) + '\n')
        secret.chmod(0o600)
        env['FLASK_SECRET_KEY'] = secret.read_text().strip()
        if not env['FLASK_SECRET_KEY']:
            raise ValueError('The saved Flask signing key is empty')
    return env


def prepare(root, *, wheel_url=None, reinstall=False):
    env = load_environment(root)
    python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Creating the application Python environment…', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', str(root / '.venv')], check=True)
    probe = subprocess.run([str(python), '-I', '-c',
        "from importlib.metadata import version; from mysql_fido_gateway.flask_login import create_gateway_app; "
        f"assert version('mysql-browser-fido-gateway') == '{VERSION}'"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode or reinstall or wheel_url:
        local = root / 'wheels' / WHEEL
        if wheel_url:
            url = urlsplit(wheel_url)
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ValueError('--wheel-url must be HTTPS without embedded credentials')
            requirement = 'mysql-browser-fido-gateway[flask] @ ' + wheel_url
        elif local.exists():
            requirement = str(local) + '[flask]'
        else:
            requirement = 'mysql-browser-fido-gateway[flask] @ ' + WHEEL_URL
        print('Installing the Flask FIDO wheel and its dependencies…', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '--force-reinstall', requirement], check=True)
        verify = subprocess.run([str(python), '-I', '-c',
            "from importlib.metadata import version; "
            f"assert version('mysql-browser-fido-gateway') == '{VERSION}'"], check=False)
        if verify.returncode:
            raise ValueError('The installed wheel version does not match this starter')
    return python, env


def main(argv=None):
    parser = argparse.ArgumentParser(description='Set up and start the template-based Flask FIDO app')
    parser.add_argument('--wheel-url', help='Install the project wheel from a public HTTPS URL')
    parser.add_argument('--reinstall', action='store_true', help='Reinstall the bundled wheel')
    parser.add_argument('--setup-only', action='store_true', help='Prepare files/dependencies without starting services')
    parser.add_argument('--no-open', action='store_true', help='Start without opening a browser')
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error('Python 3.10 or newer is required; Python 3.12+ is recommended')
    try:
        python, env = prepare(ROOT, wheel_url=args.wheel_url, reinstall=args.reinstall)
        if args.setup_only:
            print('Setup ready. Review .env and run the starter again. No MySQL settings were changed.')
            return
        origin = env.get('BROWSER_ORIGIN', 'https://localhost').rstrip('/')
        if origin == 'https://localhost':
            caddy = shutil.which('caddy')
            if not caddy:
                raise ValueError('Install and trust Caddy for https://localhost first; see GETTING_STARTED.md.')
            config = str(ROOT / 'Caddyfile.local')
            result = subprocess.run([caddy, 'reload', '--config', config, '--adapter', 'caddyfile'])
            if result.returncode:
                subprocess.run([caddy, 'start', '--config', config, '--adapter', 'caddyfile'], check=True)
        try:
            with socket.create_connection(('127.0.0.1', 5003), timeout=.3):
                raise ValueError('Port 5003 is already in use. Stop the existing starter before restarting.')
        except OSError:
            pass
        print(f'Opening {origin}/login. Stop this application with Ctrl+C.', flush=True)
        process = subprocess.Popen([str(python), '-I', str(ROOT / 'app.py')], env=env, cwd=ROOT)
        try:
            if not args.no_open:
                for _ in range(50):
                    if process.poll() is not None:
                        raise RuntimeError('Flask exited before startup; read the error above')
                    try:
                        with socket.create_connection(('127.0.0.1', 5003), timeout=.2):
                            webbrowser.open(origin + '/login')
                            break
                    except OSError:
                        time.sleep(.1)
            process.wait()
            if process.returncode:
                raise RuntimeError(f'Application exited with status {process.returncode}')
        except KeyboardInterrupt:
            process.terminate()
            process.wait()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Startup stopped: {error}\n')


if __name__ == '__main__':
    main()
