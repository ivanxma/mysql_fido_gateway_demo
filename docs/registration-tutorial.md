# Tutorial 2: Register a YubiKey

Build a separate application containing **only a YubiKey registration form**. Use the MySQL account created in [Tutorial 1](create-user-tutorial.md). This application neither creates accounts nor logs users into a main page; [Tutorial 3](login-main-tutorial.md) handles login.

## Step 1 Confirm the prerequisites

Use the same MySQL server, RP ID `localhost`, browser origin `https://localhost`, username, and **new user password** from Tutorial 1. The account must have password factor 1 and an unregistered WebAuthn factor 2.

You need a supported FIDO2 YubiKey on the browser computer, a WebAuthn browser, and trusted HTTPS. Registration requires discoverable credentials, user verification/PIN, and packed ES256 attestation with an X.509 certificate. See the [requirements](user-manual.md#requirements) and [registration sequence](user-manual.md#registration-sequence).

## Step 2 Create the registration application

From the gateway repository root:

```bash
export GATEWAY_SOURCE="$PWD"
mkdir ../tutorial_register_key
cd ../tutorial_register_key
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e "${GATEWAY_SOURCE}[demo]"
cp -R "${GATEWAY_SOURCE}/docs/examples/register_app/." .
```

Use a fresh directory. The copied project is independent of the combined demo and the create-user application.

## Step 3 Read the application code

The complete [app.py](examples/register_app/app.py) is 12 lines:

```python
from pathlib import Path
from mysql_fido_gateway.flask_util import create_action_app


def create_app(gateway=None):
    return create_action_app(Path(__file__).parent, 'register', gateway=gateway)


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5002, debug=False, threaded=True)
```

`create_action_app(root, 'register')` installs the shared Flask utilities with **only registration enabled**. The [template](examples/register_app/templates/index.html) provides one form, and [auth.js](examples/register_app/static/auth.js) handles browser WebAuthn messages. Other actions are rejected by the server, even if someone submits their JSON manually.

The helper performs this gateway call on a background worker:

```python
result = gateway.register(username, password, flow.ask, on_command=report_command)
```

`flow.ask` publishes creation options to the browser and waits for its response. The browser calls `navigator.credentials.create`. The gateway sends MySQL's INITIATE and FINISH registration statements on **the same restricted connection**, then closes it. The Flask boilerplate and broker handling live in [flask_util.py](../mysql_fido_gateway/flask_util.py).

## Step 4 Configure and start

Edit `.env` for the same database as Tutorial 1:

```bash
cp config.example.env .env
set -a
source .env
set +a
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python app.py
```

The backend listens on **5002**. Stop the previous tutorial's backend when finished with it. In another terminal, enter the registration project directory and switch the local proxy:

```bash
caddy reload --config Caddyfile.local --adapter caddyfile
```

If no Caddy process is running, use `caddy run --config Caddyfile.local --adapter caddyfile`. This configuration must target `127.0.0.1:5002`. As before, use trusted HTTPS on port 443.

Open **https://localhost**. You must see **Register your YubiKey**, one username/password form, and **Register YubiKey**. No root password or administrator token is requested. If you see three columns or two Register/Login forms, reload the configuration from this registration project's directory.

## Step 5 Register the key

1. Insert your YubiKey into the browser computer.
2. Enter `demo_tutorial`, or the username you chose in Tutorial 1.
3. Enter that user's new MySQL password.
4. Click **Register YubiKey**.
5. Complete the browser's PIN/verification and touch prompts.

The PIN stays in the browser/authenticator interaction. Python receives the serialized public credential response, not the PIN. The MySQL activity area shows registration SQL templates while redacting credential responses.

**Success means MySQL accepted FINISH REGISTRATION**, with `registered: true` and `verified_by: MySQL FINISH REGISTRATION OK`. A browser prompt completing by itself is not proof that MySQL stored the credential.

## Step 6 Continue to login

Stop the registration app with Ctrl+C. Continue with [Tutorial 3: Login and main page](login-main-tutorial.md). Use the same account, password, YubiKey, database, and RP ID. Registration is normally done once, not before every login.

Wrong passwords, cancelled prompts, unsupported attestation, or MySQL rejection produce an error. The helper does not substitute application-only authentication. It inherits the [gateway limitations](user-manual.md#limitations), including one process, 150-second ceremonies, and limited attestation support. Changing the RP ID or dropping/recreating the account requires deliberate re-enrollment; deleting a server registration does not remove a passkey from the physical key.
