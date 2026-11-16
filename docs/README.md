# MySQL browser gateway documentation

The gateway lets a browser use a local YubiKey for MySQL's password plus WebAuthn authentication. MySQL verifies the account and signature; the Python service transports the ceremony.

| Document | Contents |
| --- | --- |
| [User manual](user-manual.md) | Overview, requirements, installation, operating steps, message flows, troubleshooting, and limitations |
| [API reference](api-reference.md) | Exported Python API, callbacks, broker helpers, HTTP endpoints, browser helpers, and protocol utilities |
| [Configuration reference](configuration.md) | Every application environment variable, launcher behavior, database parameters, and fixed limits |
| [Tutorial 1: Create user](create-user-tutorial.md) | Build a single-purpose create-user page with a minimal app.py |
| [Tutorial 2: Register YubiKey](registration-tutorial.md) | Build a separate registration page using the account from Tutorial 1 |
| [Tutorial 3: Login and main page](login-main-tutorial.md) | Build a login page leading to a protected main page and Hello World button |
| [Terms and references](terms-and-references.md) | Scope, responsibilities, glossary, source files, and external technical references |

These documents describe package version `0.1.0` and the current repository implementation. The simplified HTTP-localhost option in the internal presentation has not been implemented in the application: the current gateway still requires the configured HTTPS origin on port 443.

Start with the manual's [requirements](user-manual.md#requirements), [component diagram](user-manual.md#overview), [registration flow](user-manual.md#registration-sequence), [login flow](user-manual.md#login-sequence), and [limitations](user-manual.md#limitations). Diagrams include rendered SVGs and editable Mermaid sources.

The demo combines create user, registration, and login in three columns on one page. The tutorials above teach each action separately, using small application entry points and shared Flask utilities. The earlier [combined registration/login example](new-application.md) remains available as a supplementary sample.
