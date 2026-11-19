"""Generated apps visibly declare the operator's MySQL target and store no password."""
import argparse
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
from mysql_fido_gateway.cli import newapp
from mysql_fido_gateway.runtime import LIBRARY_VERSION


class NewAppTests(unittest.TestCase):
    def args(self, parent, **changes):
        values = dict(name='myapp', parent=str(parent), db_host='127.0.0.1', db_port='3307',
                      db_ssl_ca=None, allow_loopback_plaintext=True, non_interactive=True)
        values.update(changes)
        return argparse.Namespace(**values)

    def test_generated_files_explicit_assignments_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder)
            result = newapp(args)
            app = (result/'app.py').read_text()
            self.assertIn("MYSQL_HOST = '127.0.0.1'", app)
            self.assertIn('MYSQL_PORT = 3307', app)
            self.assertIn('DB_HOST=127.0.0.1', (result/'.env').read_text())
            self.assertIn('DB_PORT=3307', (result/'.env').read_text())
            self.assertNotIn('DB_PASSWORD=', (result/'.env').read_text())
            self.assertIn(f'/downloads/{LIBRARY_VERSION}/mysql_browser_fido_gateway-{LIBRARY_VERSION}-py3-none-any.whl',
                          (result/'requirements.txt').read_text())
            for file in ['start.py','start.command','start.bat','LICENSE',
                         'templates/auth/login.html','templates/auth/register.html',
                         'static/auth/register.js','static/auth/login.js']:
                self.assertTrue((result/file).is_file(), file)
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                newapp(args)

    def test_generator_asks_for_name_host_and_port(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder, name=None, db_host=None, db_port=None, non_interactive=False)
            with patch('builtins.input', side_effect=['askapp','127.0.0.1','4411']) as prompt:
                result = newapp(args)
            self.assertEqual(prompt.call_count, 3)
            self.assertIn('MYSQL_PORT = 4411', (result/'app.py').read_text())

    def test_remote_plaintext_and_bad_port_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'loopback'):
                newapp(self.args(folder, db_host='db.example'))
            with self.assertRaisesRegex(ValueError, 'port'):
                newapp(self.args(folder, db_port='70000'))
            self.assertFalse((Path(folder)/'myapp').exists())

    def test_launcher_config_is_data_and_secret_is_stable(self):
        starter = runpy.run_path(str(Path(__file__).resolve().parents[1]/'docs/examples/login_app/start.py'))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'.env').write_text('DB_HOST=127.0.0.1\nDB_PORT=3307\nALLOW_LOOPBACK_DB_PLAINTEXT=1\nEXAMPLE="$(do-not-execute)"\n')
            first = starter['load_environment'](root, {})
            second = starter['load_environment'](root, {})
            self.assertEqual(first['EXAMPLE'], '$(do-not-execute)')
            self.assertEqual(first['FLASK_SECRET_KEY'], second['FLASK_SECRET_KEY'])
            self.assertEqual((root/'.flask_secret_key').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
