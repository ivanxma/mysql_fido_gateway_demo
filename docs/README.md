# MySQL browser gateway documentation

The gateway lets a browser use a local YubiKey for MySQL's password plus WebAuthn authentication. MySQL verifies the account and signature; the Python service transports the ceremony.

| Document | Contents |
| --- | --- |
| [User manual](user-manual.md) | Overview, requirements, installation, operating steps, message flows, troubleshooting, and limitations |
| [API reference](api-reference.md) | Exported Python API, callbacks, broker helpers, HTTP endpoints, browser helpers, and protocol utilities |
| [Flask wheel and application SQL](flask-wheel.md) | Installable Flask utility, `getConnection()`, bound parameters, transactions, and native-driver callbacks |
| [Configuration reference](configuration.md) | Every application environment variable, launcher behavior, database parameters, and fixed limits |
| [Tutorial 1: Create user](create-user-tutorial.md) | Build a single-purpose create-user page with a minimal app.py |
| [Tutorial 2: Register YubiKey](registration-tutorial.md) | Build a separate registration page using the account from Tutorial 1 |
| [Tutorial 3: Login and main page](login-main-tutorial.md) | Build a login page leading to a protected main page and Hello World button |
| [Terms and references](terms-and-references.md) | Scope, responsibilities, glossary, source files, and external technical references |

These documents describe package version `0.2.0` and the current repository implementation. The simplified HTTP-localhost option in the internal presentation has not been implemented in the application: the current gateway still requires the configured HTTPS origin on port 443.

Choose your starting point:

- **Run all three actions on one page:** install the wheel and follow the [reference application setup](user-manual.md#install-and-start-the-local-reference-application). Use `python app.py --check-library` to check its installed version and location.
- **Build a Flask application:** follow the [library and SQL guide](flask-wheel.md), then the [login/main tutorial](login-main-tutorial.md). The library supplies login UI and transport; application routes use `auth.getConnection()`.
- **Integrate another framework:** use [`Gateway.register()` and `Gateway.connect()`](api-reference.md) and provide the browser exchange callback.

The demo and action helpers close each operation's connection. The Flask login utility retains a private connection per authenticated session, supports transactions, and closes it on logout, expiry, or failure.

Start with the manual's [requirements](user-manual.md#requirements), [component diagram](user-manual.md#overview), [registration flow](user-manual.md#registration-sequence), [login flow](user-manual.md#login-sequence), and [limitations](user-manual.md#limitations). Diagrams include rendered SVGs and editable Mermaid sources.

The demo combines create user, registration, and login in three columns on one page. The tutorials above teach each action separately, using small application entry points and shared Flask utilities. The earlier [combined registration/login example](new-application.md) remains available as a supplementary sample.
