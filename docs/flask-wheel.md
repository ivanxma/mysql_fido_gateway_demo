# Flask FIDO wheel and application SQL

For a first install, use [Getting started without cloning](../GETTING_STARTED.md). It installs the public wheel URL and generates a named application with explicit MySQL host/port, editable frontend files, and start launchers.

The wheel includes the FIDO transport, Flask login/session utility, and linked login/registration templates, shared WebAuthn JavaScript, and stylesheet. Applications can use their authenticated user's connection for application SQL.

```bash
python -m pip install './dist/mysql_browser_fido_gateway-0.3.1-py3-none-any.whl[flask]'
```

Use the actual path to the wheel in another project. The existing `[demo]` extra also works; core `Gateway` imports remain independent of Flask. Have an explicitly configured MySQL target and provisioned account first, and use the environment and HTTPS settings in [the login tutorial](login-main-tutorial.md#step-3-set-the-environment).

## Package contents and choosing an entry point

| Import | Use | UI supplied by the wheel |
| --- | --- | --- |
| `mysql_fido_gateway.Gateway` | Framework-independent `register()` / `connect()` with a browser callback | None; the application implements the transport |
| `mysql_fido_gateway.flask_util.create_demo_app` | Three-in-one setup/create/register/login demo | Application supplies its `templates/` and `static/` directories |
| `mysql_fido_gateway.flask_util.create_action_app` | Single-purpose create-user or registration form | Application supplies the form template and browser assets |
| `mysql_fido_gateway.flask_login.create_gateway_app` | Retained Flask login plus application SQL | Overridable login/registration templates, WebAuthn transport scripts, and shared stylesheet |

The wheel contains library modules and the bundled authentication templates and assets. The repository's `app.py`, three-column demo assets, Caddy configuration, tutorials, and tests are separate application/development files. The three-in-one demo still closes each connection after its form action; `auth.getConnection()` belongs to the retained-login API.

### Run the three-in-one demo

From the repository root with `.venv` created:

```bash
.venv/bin/python -m pip install --force-reinstall "./dist/mysql_browser_fido_gateway-0.3.1-py3-none-any.whl[flask]"
.venv/bin/python app.py --check-library
./start.sh
```

`--check-library` prints version 0.3.1 and the package's installed location without starting Flask or connecting to MySQL. The direct script and launcher use isolated Python imports so the source package beside `app.py` does not shadow the installed wheel. The launcher checks the wheel before changing the HTTPS proxy. Follow the [manual](user-manual.md#install-and-start-the-local-reference-application) for MySQL and HTTPS prerequisites.

### Upgrade or rebuild the library

After changing library source, run from the source checkout:

```bash
.venv/bin/python scripts/build_release.py
.venv/bin/python -m pip install --force-reinstall "./dist/mysql_browser_fido_gateway-0.3.1-py3-none-any.whl[flask]"
.venv/bin/python app.py --check-library
```

Stop the running Flask process and restart it after installation; already imported code remains in memory until restart. Reinstall the wheel in each application's virtual environment, using its actual wheel path. `--force-reinstall` also handles rebuilding the same development version. This release pins Connector/Python 26.10.0 and cbor2 5.9.0; the `[flask]` and compatible `[demo]` extras add Flask 3.1.3. There is no need to install Flask for core-only custom transports.

When upgrading a generated 0.3.0 starter, update its `start.py` version/download
path and `requirements.txt` to 0.3.1 as well. Replace its local wheel when using
the ZIP's `wheels/` directory. Otherwise the old launcher's version check may
reinstall 0.3.0. Preserve application configuration and customized frontend files.

The default `browser` registration mode discourages discoverable credentials, retains the
credential ID at MySQL, and rejects unsupported signed authenticator extensions
before FINISH. It does not change signed JSON or authenticator data. Optional
`credProps.rk` metadata is not required. Security-key hints and external-key
transports also guide login away from the phone/QR flow. Existing server-accepted
registrations are not deleted by the upgrade; test login before considering any
deliberate re-enrollment.

For discoverable enrollment intended for both browser and native-client use,
set `REGISTRATION_MODE=shared` before startup, or pass `registration_mode='shared'`
to `create_gateway_app`, `create_demo_app`, or `create_action_app`. Existing
injected `Gateway` objects keep their own configured mode. This changes new
registration only and requires the [compatible browser setup](user-manual.md#shared-browser-and-native-client-enrollment).

For a copied application outside the source checkout, check its interpreter's installed version and location with:

```bash
python -c "from importlib.metadata import version; import mysql_fido_gateway; print(version('mysql-browser-fido-gateway')); print(mysql_fido_gateway.__file__)"
```

## Editable web frontend

The library includes a complete Jinja/JavaScript frontend. The [sample application](examples/login_app/app.py) shows how to customize it:

```text
templates/auth/base.html      # Shared page layout/branding override
templates/auth/login.html     # Editable sign-in form
templates/auth/register.html  # Editable registration form
static/auth.css              # Application styles
static/auth/common.js        # Editable JSON/CSRF transport
static/auth/webauthn.js      # Editable browser credential handling
static/auth/login.js         # Editable sign-in behavior
static/auth/register.js      # Editable registration behavior
static/main.js               # Application business-page behavior
```

Select project templates when creating the app:

```python
app, auth = create_gateway_app(
    Path(__file__).parent,
    auth_base_template='auth/base.html',
    login_template='auth/login.html',
    registration_template='auth/register.html',
)
```

The sample base extends `mysql_fido_gateway/auth_base.html`; form templates extend the corresponding library pages and override their `form` blocks. Customize `brand`, `heading`, `introduction`, `styles`, `content`, or `footer` blocks through Jinja inheritance. Without template options, the library defaults render a working frontend.

Login links to `/register`; registration returns to `/login` after MySQL accepts enrollment. Registration uses the existing MySQL account and its password. The browser invokes `navigator.credentials.create()` and handles the security-key PIN/touch locally. It creates neither a new MySQL account nor a logged-in application session. The supported credential remains a compatible external FIDO2 key with packed ES256/x5c attestation.

`gateway_auth.static` serves `common.js`, `webauthn.js`, `login.js`, `register.js`, and `style.css`. The starter also supplies editable copies under `static/auth/` and overrides the template script blocks to load them. Use the package defaults or customize these project files. Shared WebAuthn code serializes both ceremonies; each page script owns its form state, polling, error messages, and success behavior. Password fields clear on submission. Keep script tags external to satisfy the Content Security Policy.

When customizing forms, preserve `id="login"` or `id="register"`, `name="username"`, `name="password"`, the form `action` generated by `url_for('start_login')` / `url_for('start_register')`, a submit button, and the `#status` live region. Registration also uses `#registration-complete` with its sign-in link. No PIN field belongs in application HTML; browser/device UI collects the PIN.

[Desktop sign-in preview](preview/login-desktop.png) · [Registration preview](preview/register-desktop.png) · [Mobile preview](preview/login-mobile.png)

## Application example

```python
from pathlib import Path
from flask import jsonify, request
from mysql_fido_gateway.flask_login import create_gateway_app

app, auth = create_gateway_app(
    Path(__file__).parent,
    db_config={'host': 'db.example.com', 'port': 3307,
               'ssl_ca': '/path/to/mysql-ca.pem',
               'ssl_verify_cert': True, 'ssl_verify_identity': True},
)

@app.get('/main')
@auth.login_required
def main():
    return 'Signed in'

@app.get('/api/orders')
@auth.login_required
def orders():
    customer_id = request.args.get('customer_id', type=int)
    # Apply business authorization for this customer before querying.
    with auth.getConnection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT id, total FROM shop.orders WHERE customer_id = %s',
                (customer_id,),
            )
            rows = cursor.fetchall()
    return jsonify(rows)

@app.post('/api/orders/<int:order_id>/status')
@auth.login_required
def change_status(order_id):
    # Validate and authorize the requested change before executing SQL.
    status = request.get_json()['status']
    with auth.get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE shop.orders SET status = %s WHERE id = %s',
                (status, order_id),
            )
            changed = cursor.rowcount
    return jsonify(changed=changed)
```

POST routes require the exact `Origin` and page `X-CSRF-Token` headers. The authenticated MySQL account needs the appropriate table privileges. Keep SQL in application code and bind request values as parameters. There is no HTTP endpoint accepting arbitrary SQL.

## Connection API

`auth.getConnection()` and `auth.get_connection()` are equivalent context managers. Module-level `getConnection()` and `get_connection()` are also available from `mysql_fido_gateway.flask_login` inside protected routes.

The context borrows a connection facade for the current user. It reuses the MySQL connection that passed password and FIDO authentication. Native calls stay on that connection's original worker. Requests for the same session wait while a context is active, preventing their statements from interleaving with its transaction. Different sessions have separate workers and connections.

The context disables autocommit, commits on success, rolls back on exceptions, closes cursors, and restores autocommit. MySQL statements that implicitly commit, such as many DDL statements, retain their normal semantics. Do not nest connection contexts, retain facades/cursors after exit, or pass them to another thread. Ordinary SQL/application errors propagate to the application; after successful rollback, a healthy login can be reused.

| Interface | Behavior |
| --- | --- |
| `connection.cursor(*, dictionary=True, buffered=True, **options)` | Worker-owned cursor, dictionary rows and buffering by default; supports `with` |
| `cursor.execute(sql, params=None)` | Execute with Connector/Python parameter binding |
| `cursor.executemany(sql, params)` | Execute a parameter sequence |
| `cursor.fetchone()`, `fetchmany(size=1)`, `fetchall()` | Fetch one, some, or all rows |
| `cursor.nextset()` | Advance result sets; consume all results before closing unbuffered cursors |
| `cursor.rowcount`, `lastrowid`, `description` | Driver metadata |
| `cursor.close()` | Close the cursor; context exit also closes it |
| `connection.commit()`, `rollback()` | Explicit transaction control; an earlier commit cannot be undone at context exit |
| `auth.query(sql, params=None, *, many=False)` | Convenience SELECT; one dictionary row, or all rows with `many=True` |

For full Connector/Python functionality, use `auth.run(callback)`. Its callback receives the native connection inside a managed transaction, on the worker:

```python
@app.get('/api/report')
@auth.login_required
def report():
    report_id = request.args.get('id', type=int)

    def load(connection):
        with connection.cursor(dictionary=True, buffered=True) as cursor:
            cursor.callproc('shop.load_report', (report_id,))
            return [result.fetchall() for result in cursor.stored_results()]

    return jsonify(auth.run(load))
```

Capture validated request values before the callback; Flask `request`, `g`, and `session` are unavailable on its worker. Close native cursors and return detached application data, never connection/cursor objects. Leave autocommit, authentication, and lifecycle configuration to the utility.

## Migrate an existing copied Flask application

1. Install this wheel with `[flask]` in the application's own virtual environment.
2. Replace `from lib.flask_util import create_gateway_app` with `from mysql_fido_gateway.flask_login import create_gateway_app`. Keep the existing `app, auth` factory result and `@auth.login_required` decorators.
3. Load the shared stylesheet and JSON transport script from the library's blueprint in your main-page template:

   ```html
   <link rel="stylesheet" href="{{ url_for('gateway_auth.static', filename='style.css') }}">
   <script src="{{ url_for('gateway_auth.static', filename='common.js') }}" defer></script>
   <script src="{{ url_for('static', filename='main.js') }}" defer></script>
   ```

4. The library renders login and registration templates and supplies their shared scripts. Override the template paths to use the editable pages from the current starter. Your application retains its own main-page template, `main.js`, configuration, and business routes. The current [starter](examples/login_app/app.py) has no local Python `lib/` helper; its editable Jinja forms extend the library frontend.
5. Existing `auth.query(sql)` calls still work. Add bound parameters and `many=True` for SELECT convenience, or use a `with auth.getConnection()` block for cursor operations and transactions.
6. Keep the same RP ID, browser origin, MySQL account, and key registration. Restart and sign in again after the library update; in-memory login state is not migrated between processes. Installing a wheel does not modify MySQL accounts or registrations.

For error handling and the distinction between the native connection and the request-scoped facade, see the [API reference](api-reference.md#flask-login-and-sql-api).

## Packaging and runtime

Build with `python scripts/build_release.py`. Import `mysql_fido_gateway.flask_login` directly in application projects; copying the tutorial's `lib/` is no longer needed. The current starter replaces the old Python helper with template inheritance and shared JavaScript. When migrating an older copied application, replace `from lib.flask_util import create_gateway_app` with `from mysql_fido_gateway.flask_login import create_gateway_app` and load shared browser assets through `gateway_auth.static`.

The utility retains one process and in-memory sessions: one authenticated worker/connection per login, at most 32 sessions, an absolute default lifetime of 300 seconds, and a 20-second wait for each queued operation. Logout, expiry, failed health checks, restart, and uncertain cleanup require a new login. It never caches passwords or reconnects automatically. A timed-out write can have an uncertain outcome; inspect application state before retrying. Live connections cannot be serialized into cookies or distributed session stores.

The wheel retains the [experimental MySQL/YubiKey interoperability limits](user-manual.md#limitations).
