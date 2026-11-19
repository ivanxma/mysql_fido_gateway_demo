# Get started without cloning

This is a personal MIT-licensed prototype/tutorial by ivanxma, not an Oracle
product or an Oracle-supported service. See [DISCLAIMER.md](DISCLAIMER.md)
and [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

The public download links below use versioned files in this repository's
`downloads/0.3.1/` directory. They become available when those files are pushed
and the repository is public. An unavailable link is not a reason to install
an unrelated package from a package index.

## Before starting

- Install Python 3.10 or newer (3.12+ recommended), including pip and venv.
- Have a MySQL server with the WebAuthn plugin ACTIVE, password
  factor 1 plus WebAuthn factor 2, and the chosen RP ID configured by its DBA.
  Community availability starts with MySQL 26.10; the live test for this release
  used MySQL 26.10.0-commercial.
- Know the **actual MySQL host and port**. No database address, port,
  username, or password is assumed by the Flask utility.
- For remote MySQL, have its CA certificate and a certificate-matching host.
  Only a loopback database can use the explicitly selected development TLS
  exception.
- For the local browser profile, [install Caddy](https://caddyserver.com/docs/install) and trust its local HTTPS CA ([local HTTPS documentation](https://caddyserver.com/docs/automatic-https#local-https)).
  The browser URL is `https://localhost` on port 443, with MySQL's RP ID set
  to `localhost` and its connection timeout at least 180 seconds. A remote
  browser hostname needs matching RP/origin settings and an HTTPS proxy.

The starter does not install or configure a MySQL server, create database
accounts, change the server RP ID, or collect a security-key PIN.

These installation steps are for the application operator on a host that can
reach MySQL. A remote end user accesses the deployed HTTPS site only; their
computer need not reach MySQL or have a native MySQL client. The current 0.3.1
default browser enrollment has a stock-native-client compatibility limit.
For the opt-in discoverable profile, set `REGISTRATION_MODE=shared` in the
generated `.env`, restart, and follow the [compatible Firefox setup and validation status](docs/user-manual.md#shared-browser-and-native-client-enrollment).
Both product plugins remain unchanged.

## Option A: install the wheel URL and generate a new app

In a terminal, choose a working directory. On macOS/Linux:

```bash
python3 -m venv gateway-tools
gateway-tools/bin/python -m pip install 'mysql-browser-fido-gateway[flask] @ https://raw.githubusercontent.com/ivanxma/mysql_fido_gateway_demo/main/downloads/0.3.1/mysql_browser_fido_gateway-0.3.1-py3-none-any.whl'
gateway-tools/bin/python -m mysql_fido_gateway newapp
```

On Windows (PowerShell), use:

```powershell
py -3 -m venv gateway-tools
.\gateway-tools\Scripts\python.exe -m pip install "mysql-browser-fido-gateway[flask] @ https://raw.githubusercontent.com/ivanxma/mysql_fido_gateway_demo/main/downloads/0.3.1/mysql_browser_fido_gateway-0.3.1-py3-none-any.whl"
.\gateway-tools\Scripts\python.exe -m mysql_fido_gateway newapp
```

The installed console command is also available as `mysql-fido newapp` when
the tools environment is activated.

The CLI asks for:

1. **Application name**, used as the new folder name. Existing folders are
   never overwritten.
2. **MySQL host** and **port**, both required.
3. **TLS**: a CA certificate path, or an affirmative loopback-development
   exception when the host is `localhost`, `127.0.0.1`, or `::1`.

It writes `MYSQL_HOST` and `MYSQL_PORT` assignments in `app.py`, then creates the application, Jinja templates, CSS/JavaScript, launchers,
documentation/licenses, and a non-secret `.env` connection profile. It stores
no MySQL username or password. Those are entered in the browser per user.

For example, a noninteractive local development generation is:

```bash
gateway-tools/bin/python -m mysql_fido_gateway newapp my_app --db-host 127.0.0.1 --db-port 3306 --allow-loopback-plaintext --non-interactive
```

`3306` above is an explicit example supplied to the command, not a default.
Use your own port. For a remote database, use `--db-ssl-ca /path/to/ca.pem`
instead of the loopback exception.

## Option B: download the complete starter ZIP

[Download the starter ZIP](https://raw.githubusercontent.com/ivanxma/mysql_fido_gateway_demo/main/downloads/0.3.1/mysql_fido_flask_starter-0.3.1.zip)
and extract it. It includes the wheel, editable application files, templates,
JavaScript, license notices, and launchers. No git checkout is required.

Open `.env` if already generated, or fill the MySQL settings when the starter
asks. The first run creates `.env` from the example if needed.

## Start the application

Inside the generated/extracted folder:

| Platform | Start |
| --- | --- |
| macOS | Open `start.command`, or run `python3 start.py` |
| Windows | Open `start.bat` (requires the Python launcher), or run `py -3 start.py` |
| Linux | Run `bash start.sh` or `python3 start.py` |

The launcher creates the application's own `.venv`, installs the bundled
wheel (or downloads the versioned wheel when generated by the CLI), reads
the explicitly configured MySQL target, and saves a random Flask signing key
in `.flask_secret_key` with owner-only permissions on POSIX systems (protect the application folder using your account permissions on Windows). It configures the
local Caddy proxy to backend `127.0.0.1:5003`, starts Flask, and opens
`https://localhost/login`. Keep its terminal open. Stop Flask with Ctrl+C;
Caddy and MySQL remain separate processes.

To prepare files/dependencies without starting services:

```bash
python3 start.py --setup-only
```

Use `--reinstall` after replacing the same-version wheel, `--wheel-url
HTTPS_URL` to select a public project wheel explicitly, or `--no-open` to
start without opening a browser. The Windows wrapper is supplied; desktop
verification for this release was performed on macOS, not Windows.

## Register, sign in, and run SQL

1. Use an account provisioned by the DBA with an unregistered WebAuthn factor.
2. Choose **Register a passkey** on the login page. Enter that account's
   MySQL username and password. Use a compatible external FIDO2 security key;
   its PIN/touch prompts are handled by the browser/device.
3. After MySQL accepts registration, return to sign-in. Enter the username
   and password, then touch the registered key. The app requests touch-only
   login; no PIN field exists in the web application.
4. The protected main page can run **Retrieve Hello World** on that user's
   authenticated connection. **Log out** revokes the session.

The key is not needed on the Python server. General platform/cloud passkeys
are not supported by the prototype's packed ES256/x5c profile.

## Where to customize

- `app.py`: minimal application creation and business routes.
- `.env`: explicit host, port, CA/TLS choice, RP/origin; no database password.
- `templates/auth/base.html`, `login.html`, `register.html`: editable layout,
  branding, and forms.
- `static/auth/*.js`, `static/auth.css`: editable browser flow and styles.
- `templates/main.html`, `static/main.js`: your application page.
- `with auth.getConnection()`: application SQL under the authenticated user's
  grants, with bound parameters and transaction cleanup.

For explicit Python configuration, API signatures, and lifecycle/error
behavior, see the [library guide](docs/flask-wheel.md), [user manual](docs/user-manual.md),
[API reference](docs/api-reference.md), and [configuration reference](docs/configuration.md).
Cloning/building from source is a contributor workflow, not required to run
the downloaded starter.

## Upgrade from 0.3.0

Install the 0.3.1 wheel in every application's virtual environment and restart
the application, then refresh the browser. No MySQL restart is required. For a
previously generated starter, update `0.3.0` to `0.3.1` in its `start.py` and
`requirements.txt` too, so the launcher does not reinstall the old wheel. Keep
your `.env`, templates and CSS. A copied local `wheels/` directory must contain
the new wheel if the launcher uses that path. See the [upgrade guide](docs/flask-wheel.md#upgrade-or-rebuild-the-library).

Version 0.3.1's default `browser` mode uses credential-ID-based security-key enrollment and supplies
physical-key hints for login. If registration previously failed with MySQL 4061,
upgrade before retrying. A passkey entry on the YubiKey does not prove MySQL
accepted it; conversely, a credential used by ID may not appear in the key's
discoverable-passkey list. Once MySQL accepts enrollment, use login rather than
registering the account again. See [troubleshooting](docs/user-manual.md#troubleshooting).

## Downloads and licensing

[Wheel](https://raw.githubusercontent.com/ivanxma/mysql_fido_gateway_demo/main/downloads/0.3.1/mysql_browser_fido_gateway-0.3.1-py3-none-any.whl)
· [SHA-256 checksums](https://raw.githubusercontent.com/ivanxma/mysql_fido_gateway_demo/main/downloads/0.3.1/SHA256SUMS)
· [Project MIT license](LICENSE)

Dependency terms remain separate, particularly Connector/Python's GPLv2 and
Universal FOSS Exception. This personal project has no Oracle endorsement,
support, warranty, or certification. One browser/YubiKey registration and login
path was accepted by MySQL 26.10.0-commercial; broader compatibility remains
unverified. See [VALIDATION.md](VALIDATION.md).
