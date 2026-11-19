# MySQL FIDO Flask starter

A Flask application with browser security-key registration, login, and a
protected main page. MySQL checks the password and WebAuthn factor; application
SQL runs on that user's authenticated connection through `auth.getConnection()`.
The security key stays on the user's computer.

The starter includes a minimal `app.py`, editable Jinja templates, CSS,
JavaScript, and launchers. It uses `mysql_fido_gateway.flask_login` from the
**0.3.1 wheel**. See `docs/flask-wheel.md` for the API and SQL examples.

## Start

Follow `GETTING_STARTED.md` to install the raw wheel URL and run
`python -m mysql_fido_gateway newapp`, or download and extract the starter ZIP.
The generator asks for an application name, MySQL host/port, and TLS choice.
It writes explicit `MYSQL_HOST` and `MYSQL_PORT` assignments in `app.py` and a
`.env` connection profile. No MySQL account password is stored.

You need Python 3.10+, Caddy with its local CA trusted, a compatible external
FIDO2 key, and a prepared MySQL account with WebAuthn factor 2. The launcher does
not install MySQL, create accounts, or change server policy.

| Platform | Start inside the application folder |
| --- | --- |
| macOS | Open `start.command`, or run `python3 start.py` |
| Windows | Open `start.bat`, or run `py -3 start.py` |
| Linux | Run `bash start.sh` or `python3 start.py` |

The launcher installs dependencies in `.venv`, configures Caddy, and opens
`https://localhost/login`. Keep the terminal open; Ctrl+C stops Flask.
Use `python3 start.py --setup-only` to prepare the application without starting
services. Other launcher options and remote TLS settings are in
`GETTING_STARTED.md`.

## Register and sign in

1. On the login page, choose **Register a passkey**.
2. Enter the provisioned MySQL username/password and complete the key's
   PIN/touch prompts. MySQL must accept registration before success is shown.
3. Return to login, enter the same account credentials, and touch the key.
   Login requests no PIN; browser/key policy can still require one.
4. On the protected main page, choose **Retrieve Hello World**, then log out.

Default `browser` mode supports the tested Chrome browser flow. To enroll a
credential for both browser and stock MySQL client login, set
`REGISTRATION_MODE=shared` in `.env`, restart, and follow the compatible Firefox
setup in `docs/user-manual.md`. Changing this setting does not convert an
existing credential. General platform/cloud passkeys are outside this
prototype's supported profile. See `VALIDATION.md` for the tested scope.

## Customize

| File or folder | Change |
| --- | --- |
| `app.py` | Explicit MySQL host/port and protected business routes |
| `.env` | Database TLS, RP/origin, and registration mode |
| `templates/auth/` | Banner, layout, login and registration forms |
| `static/auth.css` | Colors and styling |
| `static/auth/*.js` | Browser interactions |
| `templates/main.html`, `static/main.js` | The application page |

Keep the form IDs, field names, action URLs, and status elements used by the
scripts when changing the layout. Use one Python process: authenticated
connections and sessions are held in memory. Detailed requirements and limits
are in `docs/user-manual.md` and `docs/configuration.md`.

This is a personal MIT-licensed prototype/tutorial by ivanxma, not an Oracle
product or support offering. See `LICENSE`, `DISCLAIMER.md`, and
`THIRD_PARTY_LICENSES.md` in the generated/extracted application.
