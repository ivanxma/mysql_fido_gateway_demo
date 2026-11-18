# MySQL FIDO application starter

This is a personal MIT-licensed prototype/tutorial by ivanxma, not an Oracle
product or an Oracle-supported service. See `LICENSE`, `DISCLAIMER.md`, and
`THIRD_PARTY_LICENSES.md` in the generated/extracted application.

## Download and start

No repository clone is required. Follow `GETTING_STARTED.md`: install the
public raw wheel URL and run `python -m mysql_fido_gateway newapp`, or extract
the complete starter ZIP.

The CLI asks for the application name, actual MySQL host and port, and TLS
choice. It writes visible `MYSQL_HOST` and `MYSQL_PORT` assignments in
`app.py`, plus `.env`. No MySQL account password is stored.

- macOS: open `start.command`, or run `python3 start.py`.
- Windows: open `start.bat`, or run `py -3 start.py`.
- Linux: run `bash start.sh` or `python3 start.py`.

The launcher creates a local `.venv`, installs the wheel, loads the explicit
connection profile, saves a private Flask signing key, configures the local
Caddy proxy, starts the application, and opens `https://localhost/login`.
`python3 start.py --setup-only` prepares files/dependencies without starting
services. `--reinstall` refreshes a replaced wheel; `--wheel-url HTTPS_URL`
selects the public wheel directly. Ctrl+C stops Flask.

Python 3.10+ (3.12+ recommended), Caddy with a trusted local CA, and a prepared
MySQL server/account are prerequisites. The launcher does not install MySQL,
create an account, change server policy, or configure database grants. Read
`GETTING_STARTED.md` for the exact prerequisites and remote-TLS profile.

## Connection settings and credentials

`app.py` explicitly passes a mapping to the library:

```python
app, auth = create_gateway_app(
    Path(__file__).parent,
    db_config={
        'host': MYSQL_HOST,
        'port': MYSQL_PORT,
        'ssl_ca': '/path/to/mysql-ca.pem',
        'ssl_verify_cert': True,
        'ssl_verify_identity': True,
    },
)
```

Use the real CA path for remote MySQL. For deliberate local development,
explicitly opt into the loopback exception instead. No host, port, username,
or password is assumed. Users enter their individual MySQL username/password
on the login or registration page, and the browser/device handles key PINs.

## Register and use the app

On `/login`, choose **Register a passkey** for a provisioned account with an
unregistered WebAuthn factor. Enter the account credentials and complete the
security key's browser PIN/touch ceremony. MySQL must accept enrollment before
the app reports success. Return to sign-in, enter the username/password, and
touch the registered key. The protected main page demonstrates application SQL
on that user's authenticated connection. Log out when finished.

Edit `templates/auth/` for layout/forms, `static/auth.css` for styling,
`static/auth/*.js` for browser behavior, and the protected routes in `app.py`
for application SQL. Startup/version checks stay in the library. Keep the
form IDs, username/password names, action URLs, and live-status elements
used by the browser scripts intact.

This experimental profile supports compatible external FIDO2 security keys
and packed ES256/x5c attestation; general platform/cloud passkeys are not
supported. Simulator tests do not certify a live Enterprise MySQL/physical-key
deployment. Use one Python process because sessions/connections are in memory.
