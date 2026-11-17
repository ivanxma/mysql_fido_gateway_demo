# Flask FIDO wheel and application SQL

The wheel includes the FIDO transport, Flask login/session utility, and bundled login page, JavaScript, and stylesheet. Applications can use their authenticated user's connection for application SQL.

```bash
python -m pip install './dist/mysql_browser_fido_gateway-0.2.0-py3-none-any.whl[flask]'
```

Use the actual path to the wheel in another project. The existing `[demo]` extra also works; core `Gateway` imports remain independent of Flask. Provision and register the key first, and use the environment and HTTPS settings in [the login tutorial](login-main-tutorial.md#step-3-set-the-environment).

## Package contents and choosing an entry point

| Import | Use | UI supplied by the wheel |
| --- | --- | --- |
| `mysql_fido_gateway.Gateway` | Framework-independent `register()` / `connect()` with a browser callback | None; the application implements the transport |
| `mysql_fido_gateway.flask_util.create_demo_app` | Three-in-one setup/create/register/login demo | Application supplies its `templates/` and `static/` directories |
| `mysql_fido_gateway.flask_util.create_action_app` | Single-purpose create-user or registration form | Application supplies the form template and browser assets |
| `mysql_fido_gateway.flask_login.create_gateway_app` | Retained Flask login plus application SQL | Bundled login template, login transport scripts, and shared stylesheet |

The wheel contains library modules and the bundled login assets. The repository's `app.py`, three-column demo assets, Caddy configuration, tutorials, and tests are separate application/development files. The three-in-one demo still closes each connection after its form action; `auth.getConnection()` belongs to the retained-login API.

### Run the three-in-one demo

From the repository root with `.venv` created:

```bash
.venv/bin/python -m pip install --force-reinstall "./dist/mysql_browser_fido_gateway-0.2.0-py3-none-any.whl[flask]"
.venv/bin/python app.py --check-library
./start.sh
```

`--check-library` prints version 0.2.0 and the package's installed location without starting Flask or connecting to MySQL. The direct script and launcher use isolated Python imports so the source package beside `app.py` does not shadow the installed wheel. The launcher checks the wheel before changing the HTTPS proxy. Follow the [manual](user-manual.md#install-and-start-the-local-reference-application) for MySQL and HTTPS prerequisites.

### Upgrade or rebuild the library

After changing library source, run from the source checkout:

```bash
.venv/bin/python -m pip wheel . --no-deps --wheel-dir dist
.venv/bin/python -m pip install --force-reinstall "./dist/mysql_browser_fido_gateway-0.2.0-py3-none-any.whl[flask]"
.venv/bin/python app.py --check-library
```

Stop the running Flask process and restart it after installation; already imported code remains in memory until restart. Reinstall the wheel in each application's virtual environment, using its actual wheel path. `--force-reinstall` also handles rebuilding the same development version. This release pins Connector/Python 26.10.0 and cbor2 5.9.0; the `[flask]` and compatible `[demo]` extras add Flask 3.1.3. There is no need to install Flask for core-only custom transports.

For a copied application outside the source checkout, check its interpreter's installed version and location with:

```bash
python -c "from importlib.metadata import version; import mysql_fido_gateway; print(version('mysql-browser-fido-gateway')); print(mysql_fido_gateway.__file__)"
```

## Application example

```python
from pathlib import Path
from flask import jsonify, request
from mysql_fido_gateway.flask_login import create_gateway_app

app, auth = create_gateway_app(Path(__file__).parent)

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

4. The library renders `mysql_fido_gateway/login.html` and supplies its login script. Your application retains its own main-page template, `main.js`, configuration, and business routes. The current [starter](examples/login_app/app.py) has no local `lib/` helper or duplicate login assets.
5. Existing `auth.query(sql)` calls still work. Add bound parameters and `many=True` for SELECT convenience, or use a `with auth.getConnection()` block for cursor operations and transactions.
6. Keep the same RP ID, browser origin, MySQL account, and key registration. Restart and sign in again after the library update; in-memory login state is not migrated between processes. Installing a wheel does not modify MySQL accounts or registrations.

For error handling and the distinction between the native connection and the request-scoped facade, see the [API reference](api-reference.md#flask-login-and-sql-api).

## Packaging and runtime

Build with `python -m pip wheel . --no-deps --wheel-dir dist`. Import `mysql_fido_gateway.flask_login` directly in application projects; copying the tutorial's `lib/` is no longer needed. The current starter omits the old `lib/` helper and duplicate login assets. When migrating an older copied application, replace `from lib.flask_util import create_gateway_app` with `from mysql_fido_gateway.flask_login import create_gateway_app` and load shared browser assets through `gateway_auth.static`.

The utility retains one process and in-memory sessions: one authenticated worker/connection per login, at most 32 sessions, an absolute default lifetime of 300 seconds, and a 20-second wait for each queued operation. Logout, expiry, failed health checks, restart, and uncertain cleanup require a new login. It never caches passwords or reconnects automatically. A timed-out write can have an uncertain outcome; inspect application state before retrying. Live connections cannot be serialized into cookies or distributed session stores.

The wheel retains the [experimental MySQL/YubiKey interoperability limits](../README.md#status-and-exact-limits).
