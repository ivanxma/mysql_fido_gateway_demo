# Tutorial: YubiKey login, main page, and Hello World

Build a separate Flask application with a login page requiring a MySQL password and registered YubiKey. After MySQL accepts both factors, the browser opens a protected main page. Clicking **Retrieve Hello World** runs SQL on that user's authenticated connection.

The runnable starter is in [examples/login_app](examples/login_app/app.py). Its `app.py` contains only application creation, the protected main page, and the Hello World action. [lib/flask_util.py](examples/login_app/lib/flask_util.py) contains Flask configuration, WebAuthn message transport, session handling, and connection cleanup. Copy the entire starter, including `lib/`.

## Step 1 Prepare an enrolled account

Complete the [first tutorial's server and account setup](new-application.md#step-5-prepare-mysql-and-a-fresh-user) and [register its YubiKey](new-application.md#step-9-register-the-users-key) before switching applications. Alternatively use the reference web app's setup, create-user, and registration forms.

You need:

- Python 3.12+, the pinned Connector/Python version installed by this repository, and MySQL Enterprise with the supported WebAuthn plugin and password + WebAuthn factor 2 account.
- A supported FIDO2 YubiKey already registered to that account. See the [full requirements](user-manual.md#requirements).
- MySQL's RP ID and application `RP_ID` both set to `localhost`, with `connect_timeout` at least 180 seconds (preserve higher values).
- A WebAuthn browser opening trusted `https://localhost` on port 443. The current gateway validates that exact HTTPS origin. Other hostnames and ports are different origins. A different RP ID requires corresponding server configuration and registration.

This tutorial defaults to MySQL `127.0.0.1:5316`, Flask `127.0.0.1:5003`, and an enrolled `demo_tutorial` account. It contains no root or registration interface.

## Step 2 Create a new project

From the gateway repository root:

```bash
export GATEWAY_SOURCE="$PWD"
mkdir ../gateway_login_app
cd ../gateway_login_app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e "${GATEWAY_SOURCE}[demo]"
cp -R "${GATEWAY_SOURCE}/docs/examples/login_app/." .
```

Choose a different empty project directory if that name already exists. The editable package installation points at your checkout; use a reviewed package build for deployment.

```text
gateway_login_app/
  app.py
  lib/
    __init__.py
    flask_util.py
  templates/
    login.html
    main.html
  static/
    common.js
    login.js
    main.js
    style.css
  config.example.env
  Caddyfile.local
```

## Step 3 Set the environment

```bash
cp config.example.env .env
set -a
source .env
set +a
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

Edit `.env` to match your database before sourcing it. Never put end-user or root passwords in this file. The user types their password on the login page.

| Variable | Default / purpose |
| --- | --- |
| `FLASK_SECRET_KEY` | Required; signs the opaque session cookie. Keep private and stable for the process |
| `BROWSER_ORIGIN` | `https://localhost`; must equal `https://` plus `RP_ID`, without a custom port |
| `RP_ID` | `localhost`; must match the server's WebAuthn RP ID and the registered credential |
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `5316`; MySQL target |
| `DB_SSL_CA` | Optional CA path; when set enables certificate and hostname verification |
| `ALLOW_LOOPBACK_DB_PLAINTEXT` | Only `1` permits the development exception for exact loopback host strings; the sample enables it |
| `SESSION_TTL_SECONDS` | `300`; absolute authenticated lifetime in seconds, allowed range 1–3600 |

For a remote MySQL server, use a certificate-matching database hostname and `DB_SSL_CA`, and remove the loopback exception. Browser HTTPS and database TLS are separate connections.

## Step 4 Start Flask

```bash
python app.py
```

Keep this terminal open. Flask listens at `127.0.0.1:5003`. The application reads exported environment variables, and does not load `.env` by itself.

## Step 5 Point local HTTPS at this application

In another terminal, enter your new project directory. If Caddy is already serving the earlier tutorial or reference app:

```bash
caddy reload --config Caddyfile.local --adapter caddyfile
```

Otherwise start it in the foreground:

```bash
caddy run --config Caddyfile.local --adapter caddyfile
```

Use the existing trusted local Caddy installation from the [first tutorial's HTTPS setup](new-application.md#step-8-point-local-https-at-the-new-application). Local certificate trust and permission to bind port 443 must already be configured. This changes the local `https://localhost` target to backend 5003; stop the old Flask process if it is no longer needed. See [Caddy's command documentation](https://caddyserver.com/docs/command-line).

Open **https://localhost**. You should see **Sign in with your YubiKey**. Opening the raw backend redirects to the configured HTTPS origin.

## Step 6 Sign in using the key

1. Insert your registered YubiKey.
2. Enter the enrolled MySQL username and its password.
3. Click **Sign in with YubiKey**.
4. Follow the browser's prompt and touch the key.
5. Wait for MySQL to verify the assertion. Success opens `/main`.

The gateway requests touch-only login (`userVerification: discouraged`), although browser/key policy may still request a PIN. A PIN is entered in the browser/authenticator prompt and never sent to Python. Wrong passwords, cancelled prompts, and rejected signatures leave the main page inaccessible.

## Step 7 Retrieve Hello World

Click **Retrieve Hello World** on the main page. The route executes:

```sql
SELECT 'Hello World' AS message,
       CURRENT_USER() AS mysql_account,
       CONNECTION_ID() AS connection_id
```

The response shows `Hello World`, your effective MySQL account, and the connection ID. Click again: the same authenticated connection is reused, so this action does not start a second key ceremony. The server runs `SELECT 1 AS alive` before using the retained connection.

The response comes from MySQL. Sending a request body containing SQL does not change the query; `/api/hello` always uses the SQL defined in `app.py`.

## Step 8 Log out and check protection

Click **Log out**. The browser returns to `/login`, server access is revoked immediately, and the worker closes its connection. Directly visiting `/main` now returns to login. The same happens after the configured absolute session lifetime or a failed database health check.

Restarting Flask loses all in-memory sessions. A remaining signed cookie alone cannot authorize access. Sign in with the key again after restart, expiry, logout, or database disconnection.

## How the components interact

![Login and retained connection](diagrams/login-session.svg)

[Sequence source](diagrams/login-session.mmd).

1. `login.js` posts the password over HTTPS. A background worker calls `Gateway.connect(username, password, flow.ask)`.
2. MySQL issues its WebAuthn challenge. The callback publishes a broker event; the browser polls, invokes `navigator.credentials.get`, and sends the signed assertion back.
3. MySQL verifies the assertion. Only then does the worker receive a usable connection. Polling the success event rotates the opaque cookie owner and CSRF token and redirects to `/main`.
4. The protected page and Hello World requests use a bounded task queue. The original worker owns all use of its MySQL connection, including closure. Flask request threads never share the Connector/Python object.
5. Logout, expiry, or query failure ends the session. The helper does not cache a password or reconnect automatically, and there is no shared-account fallback. Connector/Python's connection object stays in server memory for the session's lifetime.

The browser cookie contains only random `owner` and `csrf` values. Passwords, user names, key material, and database connections are absent from its payload. The earlier [registration/login starter](new-application.md) closes its connection after each proof query; this example introduces a bounded connection lifetime for a multi-page app.

## What stays in app.py

```python
app, auth = create_gateway_app(Path(__file__).parent)

@app.get('/main')
@auth.login_required
def main():
    return render_template('main.html')

@app.post('/api/hello')
@auth.login_required
def hello():
    return jsonify(auth.query(HELLO_SQL))
```

See the complete [app.py](examples/login_app/app.py) for imports, the SQL constant, app factory, and entry point. Business routes stay here; authentication plumbing stays in `lib/flask_util.py`.

## Helper reference

These are local tutorial utilities, separate from the package's [exported Gateway API](api-reference.md).

| Helper | Parameters and result |
| --- | --- |
| `create_gateway_app(root, gateway=None, *, session_seconds=None, clock=time.monotonic)` | `root`: `Path` containing templates/static. Optional `gateway`: injected Gateway-compatible object for tests. `session_seconds`: override the environment lifetime. `clock`: monotonic clock, injectable for expiry tests. Returns `(Flask app, GatewayLogin auth)` |
| `auth.login_required(view)` | Decorator for protected pages/actions. Requires an active server session and performs a database health check; failure clears login and redirects pages or returns API 401 |
| `auth.query(sql)` | Called inside a protected route with **server-owned read-only SQL**. Executes on the user's worker, returns one dictionary row. It accepts no bound parameters and is deliberately limited to this example's fixed queries |
| `auth.close()` | Stops this process's sessions and waits up to two seconds for workers. Registered at process exit; useful for tests. A pending browser prompt can remain until its separate deadline |

Internal worker, registry, route, and message methods implement these helpers; applications should use the tabled interface. `auth` is also available through `app.extensions['gateway_login']` for tests and lifecycle integration.

| Utility HTTP endpoint | Operation |
| --- | --- |
| `GET /`, `GET /login` | Choose the login or protected main page |
| `POST /api/login` | JSON `username`, `password`; returns 202 and `flow_id` |
| `GET /api/login/<flow_id>` | Owner-bound events: `waiting`, `webauthn`, `success`, `error`; success sets the rotated cookie |
| `POST /api/login/<flow_id>/respond` | JSON `request_id` plus `credential` or `error`; validates the pending browser reply |
| `POST /api/logout` | Revoke the current session and return the login redirect |

All POST requests require the exact `Origin` and page `X-CSRF-Token`. `static/common.js` supplies the token. Login's success response updates the HttpOnly cookie; the new main page supplies the rotated CSRF token. Protected application endpoints are `GET /main` and `POST /api/hello`.

## Extend and verify

Add a protected route in `app.py` and a button in `main.html`; call the route using `jsonRequest` from `main.js`. Keep SQL fixed on the server. For real tables, extend the helper to support bound parameters and appropriate result sizes. Add application authorization using the authenticated database privileges and business rules. Login success alone does not grant administrator rights.

From the gateway source checkout, run:

```bash
.venv/bin/python -m unittest tests.test_login_app -v
```

The tests exercise actual Connector/Python packets and signed software-key assertions, including rejection paths, page protection, connection reuse, cookie rotation, expiry, cleanup, Origin/CSRF checks, and missing server state. A separate test checks two-session isolation and worker thread ownership with a connection double. These checks do not certify a physical YubiKey or commercial MySQL deployment.

## Requirements and limits

- Use one Python process, threaded requests, and no development reloader. Broker queues and authenticated connections live in process memory. Multiple WSGI processes require a different routing/state architecture; live connections cannot be serialized into a shared cookie or database.
- Maximum 32 pending/active session entries, 32 broker flows retained until their 150-second deadline, and eight queued tasks per session. A worker thread and MySQL connection are retained for each successful login until logout, expiry, or failure. Plan database connection capacity accordingly.
- Authenticated lifetime defaults to five minutes and is absolute, independent of browser activity. Cleanup checks run every 250 ms while idle. In-flight database operations can delay closure until their read/write timeout. A pending browser prompt has its own 150-second deadline.
- Database connect/read/write timeouts are 10/15/10 seconds. A query response waits up to 20 seconds. Timed-out requests invalidate the session rather than reconnecting with retained credentials.
- The helper uses autocommit and returns a single dictionary row. It provides no transaction, arbitrary SQL, pooling, registration, provisioning, profile manager, or distributed session implementation.
- The Flask development server and local internal certificate support this tutorial. Production use needs an appropriate WSGI server, trusted HTTPS, access/rate controls, and deliberate process and session lifecycle management. See the [general limitations](user-manual.md#limitations).

To restore the original demo after finishing, reload `Caddyfile.local` from the gateway repository root (backend 5001), or the first tutorial's project configuration (backend 5002).
