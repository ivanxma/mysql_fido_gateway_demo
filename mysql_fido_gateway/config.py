"""Explicit MySQL transport configuration for the optional Flask factories."""
import os
from .codec import BridgeError, check_registration_mode


def registration_mode(value=None):
    """Resolve the deployment's enrollment policy, never a browser-supplied flag."""
    return check_registration_mode(os.environ.get('REGISTRATION_MODE', 'browser') if value is None else value)


def mysql_config(config=None, *, read_timeout=15, write_timeout=10):
    if config is None:
        config = {'host': os.environ.get('DB_HOST'), 'port': os.environ.get('DB_PORT')}
        if os.environ.get('DB_SSL_CA'):
            config.update(ssl_ca=os.environ['DB_SSL_CA'], ssl_verify_cert=True, ssl_verify_identity=True)
    else:
        config = dict(config)
    if not isinstance(config.get('host'), str) or not config['host'].strip():
        raise BridgeError('Specify MySQL host explicitly in db_config["host"] or DB_HOST')
    try:
        if isinstance(config.get('port'), bool):
            raise ValueError
        port = int(config.get('port'))
        if not 1 <= port <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        raise BridgeError('Specify MySQL port explicitly (1–65535) in db_config["port"] or DB_PORT') from None
    if any(key in config for key in ('user', 'password', 'password1', 'password2', 'password3',
                                      'pool_name', 'pool_size', 'database')):
        raise BridgeError('db_config contains transport settings only; supply username/password through the user login or registration')
    config.update(host=config['host'].strip(), port=port)
    config.setdefault('connection_timeout', 10)
    config.setdefault('read_timeout', read_timeout)
    config.setdefault('write_timeout', write_timeout)
    return config


def loopback_allowed(value=None):
    if value is None:
        return os.environ.get('ALLOW_LOOPBACK_DB_PLAINTEXT') == '1'
    if not isinstance(value, bool):
        raise BridgeError('allow_loopback_plaintext must be True or False')
    return value
