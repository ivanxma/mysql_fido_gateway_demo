# Tutorial 1: Create a MySQL user

Build one small Flask application containing **only a Create user form**. It provisions a real MySQL account with a password and a WebAuthn second factor. [Tutorial 2](registration-tutorial.md) enrolls that account's YubiKey; [Tutorial 3](login-main-tutorial.md) builds a separate login and main-page application.

The [combined demo](../app.py) keeps all three actions on one page. Each tutorial application has its own page, entry point, and proxy configuration.

## Step 1 Prepare the server

Use Python 3.12+, a checkout of this repository, a trusted local HTTPS proxy, and an administrator account on a test MySQL Enterprise server with the WebAuthn plugin. See the [requirements](user-manual.md#requirements). This tutorial uses MySQL at `127.0.0.1:5316`, browser origin `https://localhost`, and RP ID `localhost`.

From an administrator MySQL connection, inspect:

```sql
SELECT PLUGIN_STATUS FROM INFORMATION_SCHEMA.PLUGINS
WHERE PLUGIN_NAME = 'authentication_webauthn';
SELECT @@GLOBAL.authentication_webauthn_rp_id,
       @@GLOBAL.connect_timeout,
       @@GLOBAL.authentication_policy;
```

The plugin must be `ACTIVE`, and authentication policy must permit password plus WebAuthn factor 2. Choose the RP ID before creating accounts or registering keys. Changing it can invalidate existing registrations.

For this local test, set the RP ID and raise the connection timeout **only if it is currently below 180**:

```sql
SET PERSIST authentication_webauthn_rp_id = 'localhost';
SET PERSIST connect_timeout = 180;
```

Preserve an existing timeout above 180. This application checks the server settings; it does not install plugins or modify global settings.

## Step 2 Create your application directory

From the gateway repository root:

```bash
export GATEWAY_SOURCE="$PWD"
mkdir ../tutorial_create_user
cd ../tutorial_create_user
python3 -m venv .venv
source .venv/bin/activate
python -m pip wheel "${GATEWAY_SOURCE}" --no-deps --wheel-dir "${GATEWAY_SOURCE}/dist"
python -m pip install "${GATEWAY_SOURCE}/dist/mysql_browser_fido_gateway-0.2.0-py3-none-any.whl[flask]"
cp -R "${GATEWAY_SOURCE}/docs/examples/create_user_app/." .
```

Choose a fresh directory if it already exists. The sample contains `app.py`, one template, browser assets, an environment example, and the HTTPS proxy configuration.

## Step 3 Read the application code

The complete [app.py](examples/create_user_app/app.py) is 12 lines:

```python
from pathlib import Path
from mysql_fido_gateway.flask_util import create_action_app


def create_app(gateway=None):
    return create_action_app(Path(__file__).parent, 'create', gateway=gateway)


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5004, debug=False, threaded=True)
```

`create_action_app(root, 'create')` installs the shared Flask setup and message routes with **only user creation enabled**. Its implementation lives in [flask_util.py](../mysql_fido_gateway/flask_util.py). Your [template](examples/create_user_app/templates/index.html) defines the form. The helper validates requests, checks the administrator token, connects as root for this operation, provisions the account, and closes the connection.

## Step 4 Configure and start

Edit a copy of the environment example to match your database, then export its values:

```bash
cp config.example.env .env
set -a
source .env
set +a
export DB_ACCOUNT_HOST=localhost
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python app.py
```

Keep this terminal running. The backend listens on **5004**. In a second terminal, enter this application's directory and configure local HTTPS:

```bash
caddy reload --config Caddyfile.local --adapter caddyfile
```

If Caddy is not running, use `caddy run --config Caddyfile.local --adapter caddyfile` instead. Use an installed, trusted local CA and permission to bind HTTPS port 443, as described in the [HTTPS setup](new-application.md#step-8-point-local-https-at-the-new-application).

Open **https://localhost**. The page title must be **Create a MySQL user**, with a single form. The configured demo administrator token is visible and prefilled. A three-column page means the proxy still targets the combined demo on 5001; reload the configuration from this new project directory, which targets 5004.

The [configuration reference](configuration.md) explains the database settings. The sample opts into the explicit loopback database exception; remote MySQL requires a CA and certificate/hostname verification. `DB_ACCOUNT_HOST` must match the source host MySQL sees for the gateway.

## Step 5 Create the account

1. Use the displayed administrator token.
2. Enter the MySQL root password.
3. Keep username `demo_tutorial`, or choose another fresh `demo_` username.
4. Enter a new, unique password for that user.
5. Click **Create user**.

The helper submits a parameter-bound statement of this form:

```sql
CREATE USER 'demo_tutorial'@'localhost'
  IDENTIFIED WITH caching_sha2_password BY '<new-user-password>'
  AND IDENTIFIED WITH authentication_webauthn;
```

The activity area redacts the password. Success reports that the account was created. This does not register a key or authenticate the new user. No table privileges are needed for the later literal Hello World query.

The administrator token authorizes this demo operation; it is not the root password, new user password, or YubiKey PIN. Root credentials are used for the operation and are not stored in cookies. The displayed token is intentional for this demo.

## Step 6 Continue to enrollment

Stop the application with Ctrl+C. Keep the new username, account host, and password available. Continue with [Tutorial 2: Register a YubiKey](registration-tutorial.md), using the same database and RP ID.

Existing usernames cause an error rather than being silently replaced by this form. Use a fresh account when repeating the tutorial. The helper exposes the demo's administrator action and inherits its [limits](user-manual.md#limitations), including single-process in-memory flows and narrow server compatibility. `ADMIN_TOKEN` must be nonempty, and every POST requires the configured Origin and page CSRF token.
