"""Build the wheel, generated-app assets, starter ZIP, and public raw downloads."""
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r'^version = "([^"]+)"', (ROOT / 'pyproject.toml').read_text(), re.M).group(1)


def copy_clean(source, destination):
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            if item.name not in {'.env', '.venv', '.flask_secret_key', '__pycache__', 'wheels'}:
                copy_clean(item, destination / item.name)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main():
    starter = ROOT / 'mysql_fido_gateway/starter'
    if starter.exists():
        shutil.rmtree(starter)
    copy_clean(ROOT / 'docs/examples/login_app', starter)
    for name in ['LICENSE', 'DISCLAIMER.md', 'THIRD_PARTY_LICENSES.md', 'GETTING_STARTED.md', 'VALIDATION.md']:
        copy_clean(ROOT / name, starter / name)
    copy_clean(ROOT / 'licenses', starter / 'licenses')
    copy_clean(ROOT / 'docs', starter / 'docs')
    subprocess.run([sys.executable, '-m', 'pip', 'wheel', str(ROOT), '--no-deps',
                    '--wheel-dir', str(ROOT / 'dist')], check=True)
    wheel = ROOT / 'dist' / f'mysql_browser_fido_gateway-{VERSION}-py3-none-any.whl'
    archive = ROOT / 'dist' / f'mysql_fido_flask_starter-{VERSION}.zip'
    with ZipFile(archive, 'w', ZIP_DEFLATED) as output:
        for file in starter.rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts:
                output.write(file, 'mysql_fido_flask_starter/' + str(file.relative_to(starter)))
        output.write(wheel, 'mysql_fido_flask_starter/wheels/' + wheel.name)
        output.writestr('mysql_fido_flask_starter/requirements.txt', './wheels/' + wheel.name + '[flask]\n')
    destination = ROOT / 'downloads' / VERSION
    destination.mkdir(parents=True, exist_ok=True)
    checksums = []
    for file in [wheel, archive]:
        shutil.copy2(file, destination / file.name)
        checksums.append(hashlib.sha256(file.read_bytes()).hexdigest() + '  ' + file.name)
    (destination / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n')
    print('Release files ready:', destination)


if __name__ == '__main__':
    main()
