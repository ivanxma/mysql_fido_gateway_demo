# Browser → MySQL FIDO gateway prototype

**Independent personal prototype/tutorial by ivanxma. Not an Oracle product, endorsement, support offering, or warranty.** See [DISCLAIMER.md](DISCLAIMER.md).

**Start without cloning:** [install the public wheel URL and generate an app](GETTING_STARTED.md), or download the starter ZIP and open its start launcher. MySQL host and port are explicitly supplied by the operator.

See the [gateway documentation](docs/README.md) for the user manual, requirements and limitations, API and configuration references, integration samples, and glossary.

For reusable Flask applications, see [the wheel and `getConnection()` guide](docs/flask-wheel.md). The package includes editable login/registration templates and browser JavaScript, parameterized SQL, multiple rows, and transaction contexts on each user's authenticated connection.

Build applications using three separate tutorials: [1. Create user](docs/create-user-tutorial.md), [2. Register YubiKey](docs/registration-tutorial.md), and [3. Login and main page](docs/login-main-tutorial.md). Each has a minimal `app.py` and delegates Flask setup and message handling to utility modules. The login tutorial ends on a protected main page with a Hello World button.

A reusable Python transport and three-column Flask demo for this goal:

**A remote user registers their own YubiKey in their browser; MySQL's existing
`authentication_webauthn` server plugin stores the credential and decides whether
subsequent FIDO authentication succeeds.** No YubiKey is needed on the Python
server. No `mysql` executable or native client plugin is needed on that server.

## Status and exact limits

This is an **experimental interoperability prototype**, not a validated MySQL
feature or production authentication gateway. It has been tested with the real
Connector/Python 26.10.0 network stack, a synthetic cryptographic authenticator,
and a MySQL protocol simulator. **It has not been tested against Enterprise
MySQL 27.1.0, a physical YubiKey, or an actual browser-generated hardware
attestation.** The commercial server plugin is unavailable in this workspace.

The first real registration and login are compatibility tests. MySQL may reject
the browser's `clientDataJSON`, origin, flags, or attestation even when the
adapter's wire format is valid. Such a rejection is a genuine interoperability
blocker: collect the server diagnostics and adapt the protocol or server plugin.
The demo never silently switches to application-only WebAuthn authentication.

Supported prototype profile:

- Password (`caching_sha2_password`) as factor 1; WebAuthn as factor 2.
- External FIDO2 authenticator and discoverable credential. Registration requires
  user presence and verification (PIN/biometric). Login requires presence (touch)
  and discourages verification, using the credential ID requested from MySQL
  when available to avoid credential discovery. If MySQL returns no ID, login
  uses browser discovery. Browser/key policy may still require a PIN.
- Packed ES256 attestation with an X.509 attestation certificate (`x5c`). Requesting
  direct attestation does not guarantee the browser will supply it. `none`,
  self-attestation, legacy U2F, and other formats fail with a clear error.
- `BROWSER_ORIGIN=https://RP_ID` at HTTPS port 443. Exact host match, no custom port.
  This matches the origin constructed by the native MySQL client; signed browser
  client data is preserved byte-for-byte, including extra browser fields.
- Connector/Python **26.10.0**, pure Python connection with a per-connection
  authentication adapter. Private connector APIs are used and the version is
  deliberately pinned. No global plugin-loader patches and no USB access.
- Single Python process, in-memory ceremony state, at most 32 live/recent flows,
  150-second expiry, response ownership and one-use request tokens. Restarting
  loses pending ceremonies; the actual credentials remain in MySQL/YubiKey.
- In the three-in-one demo, one fresh MySQL connection per action. Registration INITIATE and FINISH use
  the **same connection**. A login's `hello world` query uses that user's
  MySQL-accepted connection, then closes it. No shared-account pool.

## Library 0.3.0

The wheel provides three application interfaces:

| Use | Import | Connection lifetime |
| --- | --- | --- |
| Three-in-one demo or create/register forms | `mysql_fido_gateway.flask_util` | A separate connection for each form action |
| Protected Flask application with SQL | `mysql_fido_gateway.flask_login` | One authenticated connection per login, retained until logout, expiry, or failure |
| Custom framework/browser transport | `Gateway` from `mysql_fido_gateway` | Application owns the connection returned by `Gateway.connect()` |

For Flask application SQL, use `auth.getConnection()` in a protected route. It provides parameterized cursors, multiple-row results, and transaction cleanup; `auth.run(callback)` exposes the native driver on its owning worker. See the [library guide](docs/flask-wheel.md) for installation, upgrade, and migration examples, and the [API reference](docs/api-reference.md#flask-login-and-sql-api) for signatures and errors.

## 1. Prepare the test MySQL server (administrator)

Use a disposable test instance with the Enterprise WebAuthn server plugin ACTIVE.
Before provisioning or registering credentials, choose your final RP ID and keep
it stable. A public browser at `https://demo.example.com` needs RP ID
`demo.example.com`, not `mysql.com` or `127.0.0.1`.

```sql
SHOW PLUGINS;
SHOW GLOBAL VARIABLES LIKE 'authentication_webauthn_rp_id';
SHOW GLOBAL VARIABLES LIKE 'connect_timeout';
SHOW GLOBAL VARIABLES LIKE 'authentication_policy';

-- Example for the remote demo. Use localhost for https://localhost testing.
SET PERSIST authentication_webauthn_rp_id = 'demo.example.com';
SET PERSIST connect_timeout = 180;
```

Changing the RP ID can invalidate existing registrations; use a dedicated test
instance or coordinate with its DBA. The longer connection timeout gives the
remote user time to complete the browser's FIDO prompts during authentication.
Ensure the authentication policy permits the two factors.

Create the account through the administrator column, or have the DBA run:

```sql
CREATE USER 'demo_fido'@'localhost'
  IDENTIFIED WITH caching_sha2_password BY '<strong-unique-password>'
  AND IDENTIFIED WITH authentication_webauthn;
```

The host is the **gateway's source host as seen by MySQL**, not the remote
browser's address. Adjust it if the gateway runs on another machine. Avoid a
broad host wildcard when you know the gateway's address. No data privileges are
needed for `SELECT 'hello world'`; grant only the application's actual needs.

## 2. Install and configure Python

For the local demo, after installing the dependencies below, run `./start.sh`.
It uses `.venv` and requires the actual MySQL `DB_HOST` and `DB_PORT`; neither is assumed. The loopback database TLS exception must be explicitly configured for local development. It prints a temporary administrator token for
the Create user form. The token changes on each start unless you configure one.
Stop with Ctrl+C. Install Caddy first; the launcher reloads or starts it to serve
`https://localhost`. Visits to the local Flask address redirect to that HTTPS URL.
The default local mode sets `RP_ID=localhost` and
`BROWSER_ORIGIN=https://localhost`, including when remote example values remain
exported in your shell. Use `./start.sh --remote` to honor your configured public
RP ID and browser origin. MySQL's WebAuthn RP ID must match the selected RP ID.

The launcher loads an optional project `.env` file as shell configuration;
only use a file you control. You can copy `config.example.env` to `.env` and
customize it. Set `ADMIN_TOKEN=''` to disable provisioning, or set a stable token
to reuse it. Remote databases still require verified TLS.

```bash
python3 -m venv .venv
source .venv/bin/activate
python scripts/build_release.py
python -m pip install --force-reinstall "./dist/mysql_browser_fido_gateway-0.3.0-py3-none-any.whl[flask]"
python app.py --check-library

export DB_HOST=127.0.0.1
export DB_PORT=5316
export RP_ID=demo.example.com
export BROWSER_ORIGIN=https://demo.example.com
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

The three-in-one `app.py` uses `create_demo_app()` from the installed **0.3.0 wheel**. Its template and browser assets remain in this project. Both direct startup and `start.sh` use isolated Python imports to keep the adjacent source package from shadowing the installed library. `--check-library` prints the selected version and install location without starting Flask or connecting to MySQL. Skip the build command when installing a supplied wheel; rebuild and reinstall after changing library code.

For a local loopback database during testing, explicitly allow the development
exception to mandatory DB certificate validation:

```bash
export ALLOW_LOOPBACK_DB_PLAINTEXT=1
```

For a database on another machine, use verified TLS instead:

```bash
export DB_HOST=mysql.example.com
export DB_SSL_CA=/absolute/path/to/mysql-ca.pem
unset ALLOW_LOOPBACK_DB_PLAINTEXT
```

Use a DB hostname matching its certificate. No MySQL user password is stored in
these environment variables; the browser submits each user's password over
HTTPS. The gateway necessarily receives that password to perform MySQL factor 1,
so it remains a trusted component. YubiKey PINs and private keys never reach it.

Optional administrator provisioning column:

```bash
export ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export DB_ACCOUNT_HOST=localhost
```

The administrator enters this token and the MySQL root password in the top
server setup banner to apply and verify the required persistent RP ID and
connection timeout. The RP ID matches the app's `RP_ID`; the timeout is set to
at least 180 seconds, preserving larger values. Changing the RP ID can invalidate
existing registrations. This requires an ACTIVE WebAuthn plugin and privileges
to run `SET PERSIST`; failed setup may leave some settings applied.

The same credentials authorize account provisioning in column 1.
Without `ADMIN_TOKEN`, both operations are disabled. Root is used only for
server setup and provisioning, never for end-user registration/login. Only `demo_` accounts
can be provisioned. Dropping an existing account is an explicit checkbox;
root/system accounts cannot be targeted. Dropping removes its grants and MySQL
registration, **not** passkeys stored on the YubiKey. Delete those manually.
A failed CREATE after DROP leaves the old account removed; the UI reports this.
For remote demonstrations, keep provisioning on an administrator-controlled
network/route; the token is a prototype access gate, not a full admin identity
system. End users do not need it.

```bash
python app.py
```

Python listens only at `127.0.0.1:5001` (avoiding macOS AirPlay's port 5000). Do not expose the Flask development server
as the public listener.

## 3. Put HTTPS in front

Use the included Caddy configuration as a starting point, or an existing trusted
HTTPS reverse proxy. Install Caddy separately using its official instructions.

For remote users, replace `demo.example.com` in `Caddyfile.remote` with a DNS name
you control. Set `BROWSER_ORIGIN`/`RP_ID` and MySQL's RP ID to that name. Run:

```bash
caddy run --config Caddyfile.remote
```

Serve the demo at **https://demo.example.com**. A localhost address entered on a
remote user's machine refers to that user's machine, not your server.

For local testing only, use RP ID `localhost`, origin `https://localhost`, and
`Caddyfile.local`. Trust Caddy's local root CA in the OS/browser rather than
clicking through certificate warnings. Access port 443, not Flask's port 5001.

## 4. Try the three columns

Use the top server setup banner first if the MySQL RP ID or timeout is not yet
configured. Each form submission shows progress, SQL commands, and its result
in the top MySQL activity banner. Passwords and credential responses are redacted;
bound account parameters appear as placeholders. Authentication itself uses the
MySQL handshake rather than a SQL login command. Root credentials are not saved.

1. **Administrator:** provision `demo_fido` with a password (or use the DBA-created
   account). Existing accounts are preserved unless the drop checkbox is selected.
2. **Remote user:** open the HTTPS website on their own computer. Enter the
   MySQL username/password in Register, click the button, choose their external
   YubiKey, and complete the browser's PIN/touch/attestation prompts.
3. Registration is successful only after MySQL returns OK for FINISH REGISTRATION.
4. In Login, enter the same username/password and use the registered key.
5. A successful login shows `hello world`, `CURRENT_USER()`, `CONNECTION_ID()`,
   the server version, and an explanation that MySQL accepted the connection.

There are no terminal prompts for remote users. The gateway never invokes
`getpass()`, a local USB authenticator, or the MySQL CLI. The browser invokes
`navigator.credentials.create()`/`get()` on the user's computer.

## Reuse in another app

For a custom transport, install the core wheel without the optional Flask extra:

```bash
python -m pip install "./dist/mysql_browser_fido_gateway-0.3.0-py3-none-any.whl"
```

For a Flask application, install the same wheel with `[flask]` and follow the [login/main tutorial](docs/login-main-tutorial.md).

```python
from mysql_fido_gateway import Gateway

bridge = Gateway(
    {"host": "mysql.example.com", "port": 3306,
     "ssl_ca": "/path/to/ca.pem", "ssl_verify_cert": True,
     "ssl_verify_identity": True, "connection_timeout": 10},
    origin="https://demo.example.com", rp_id="demo.example.com",
)

# This callback runs in a worker and must relay the options to the same user's
# browser, then block until that browser's one-use response arrives. The demo's
# Flow.ask plus static/gateway.js is a reusable reference implementation.
def ask_browser(operation, public_key_options):
    return your_browser_transport(operation, public_key_options)

# Enrollment: closes the temporary registration connection after MySQL's result.
bridge.register(username, password, ask_browser)

# Later, during login: keep this connection private to this user's operation.
connection = bridge.connect(username, password, ask_browser)
try:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 'hello world'")
        print(cursor.fetchone()[0])
finally:
    connection.close()
```

`ask_browser()` returns the JSON credential shape emitted by the included JS
serializer. Reuse `Flow`/`Broker` or implement an equivalent authenticated,
origin-bound, expiring transport. Do not expose arbitrary SQL as an unauthenticated
HTTP endpoint. Do not place one user's connection into a shared-user pool.

## What is verified where?

The adapter checks the configured origin, server RP ID, challenge, ceremony type,
RP hash, user presence/verification flags, and response shape. This prevents
cross-session confusion and refuses unsupported encodings. It has no credential
public-key database. **MySQL remains responsible for verifying the attestation/
assertion and matching the registered account key.** Only MySQL OK allows success.
The adapter does not independently certify the manufacturer as Yubico; another
compatible external authenticator can meet this profile. Production YubiKey-only
policy would require trusted metadata/attestation policy and validation.

## Tests and live compatibility checklist

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Tests use a real Connector/Python socket handshake against a purpose-built
protocol simulator. The simulator verifies actual EC signatures from a software
key; **it is not Enterprise MySQL**. Cases cover same-connection registration,
password and signature rejection, absent FIDO factor rejection, sandbox behavior,
RP/origin/challenge validation, replay, cross-session isolation, expiry, and HTTP
CSRF/admin gates. Do not use the test authenticator outside tests.

Before claiming compatibility with your actual server, record:

- MySQL `@@version`, server plugin state, RP ID, and connect timeout.
- Browser/OS, YubiKey model/firmware, connector version (26.10.0).
- Registration returned packed ES256 with x5c, and MySQL accepted FINISH.
- Login returned MySQL OK and SQL executed under the expected `CURRENT_USER()`.
- Wrong password and a different key fail; cancelling does not log in.
- Replayed browser responses fail; two simultaneous users stay separate.
- Restart the gateway: pending ceremonies vanish; a previously registered key
  can still log in because its credential lives in MySQL.

If registration fails after a browser created a credential, that credential may
remain on the YubiKey. Remove it manually if appropriate. Do not reset the whole
key as part of troubleshooting.

No production readiness is claimed: add operator authentication, rate limiting,
durable/distributed ceremony/session management, connection lifecycle handling,
observability without secrets, external review, and a validated server profile
before considering production. The live MySQL/YubiKey gate is unresolved here.

## Protocol references

- https://dev.mysql.com/doc/dev/mysql-server/latest/page_webauthn_authentication_exchanges.html
- https://dev.mysql.com/doc/refman/26.10/en/webauthn-pluggable-authentication.html
- https://github.com/mysql/mysql-server/blob/trunk/client/common/user_registration.cc
- https://github.com/mysql/mysql-server/blob/trunk/libmysql/authentication_webauthn/webauthn_registration.cc
- https://github.com/mysql/mysql-server/blob/trunk/libmysql/authentication_webauthn/webauthn_assertion.cc
- https://developer.mozilla.org/en-US/docs/Web/API/Web_Authentication_API

No Oracle source code is bundled. The prototype uses the installed
Connector/Python dependency and documented/inspected protocol behavior; review
that dependency's license terms for your intended distribution.

## License and third-party software

Original source, templates, JavaScript, and documentation are [MIT licensed](LICENSE), copyright 2026 ivanxma. Dependencies retain their [own licenses](THIRD_PARTY_LICENSES.md), including Connector/Python’s GPLv2 with Universal FOSS Exception. No Oracle authorship, endorsement, support, or warranty is claimed. See the [personal-project disclaimer](DISCLAIMER.md).
