"""Flask transport settings must be provided explicitly, separate from user credentials."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from mysql_fido_gateway import BridgeError
from mysql_fido_gateway.config import mysql_config
from mysql_fido_gateway.flask_login import create_gateway_app


class ExplicitMySQLTests(unittest.TestCase):
    def test_missing_address_port_and_invalid_ports_fail(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(BridgeError, 'host explicitly'):
                mysql_config()
        for config in [{'host': 'db.example'}, {'host': 'db.example', 'port': 0},
                       {'host': 'db.example', 'port': True}, {'host': 'db.example', 'port': 65536}]:
            with self.assertRaisesRegex(BridgeError, 'port explicitly'):
                mysql_config(config)

    def test_explicit_mapping_overrides_environment_and_rejects_credentials(self):
        with patch.dict(os.environ, {'DB_HOST': 'other.example', 'DB_PORT': '1111'}):
            config = mysql_config({'host': 'db.example', 'port': 3307})
        self.assertEqual((config['host'], config['port']), ('db.example', 3307))
        with self.assertRaisesRegex(BridgeError, 'username/password'):
            mysql_config({'host': 'db.example', 'port': 3307, 'password': 'must-not-be-saved'})

    def test_flask_factory_passes_explicit_transport_to_gateway(self):
        config = {'host': 'db.example', 'port': 3307, 'ssl_ca': '/certs/ca.pem',
                  'ssl_verify_cert': True, 'ssl_verify_identity': True}
        with patch.dict(os.environ, {'FLASK_SECRET_KEY': 'config-test-only'}):
            with patch('mysql_fido_gateway.flask_login.Gateway') as gateway:
                app, auth = create_gateway_app(Path(__file__).parent, db_config=config)
        try:
            self.assertEqual(gateway.call_args.args[0]['host'], 'db.example')
            self.assertEqual(gateway.call_args.args[0]['port'], 3307)
            self.assertNotIn('password', gateway.call_args.args[0])
        finally:
            auth.close()


if __name__ == '__main__':
    unittest.main()
