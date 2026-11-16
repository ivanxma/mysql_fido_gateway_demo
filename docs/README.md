# MySQL browser gateway documentation

The gateway lets a browser use a local YubiKey for MySQL's password plus WebAuthn authentication. MySQL verifies the account and signature; the Python service transports the ceremony.

| Document | Contents |
| --- | --- |
| [User manual](user-manual.md) | Overview, requirements, installation, operating steps, message flows, troubleshooting, and limitations |
| [API reference](api-reference.md) | Exported Python API, callbacks, broker helpers, HTTP endpoints, browser helpers, and protocol utilities |
| [Configuration reference](configuration.md) | Every application environment variable, launcher behavior, database parameters, and fixed limits |
| [New application tutorial](new-application.md) | Twelve ordered steps, complete runnable starter files, expected results, and troubleshooting checkpoints |
| [Login and main page tutorial](login-main-tutorial.md) | Minimal app.py, reusable Flask helper, YubiKey login, protected main page, and a Hello World button |
| [Terms and references](terms-and-references.md) | Scope, responsibilities, glossary, source files, and external technical references |

These documents describe package version `0.1.0` and the current repository implementation. The simplified HTTP-localhost option in the internal presentation has not been implemented in the application: the current gateway still requires the configured HTTPS origin on port 443.

Start with the manual's [requirements](user-manual.md#requirements), [component diagram](user-manual.md#overview), [registration flow](user-manual.md#registration-sequence), [login flow](user-manual.md#login-sequence), and [limitations](user-manual.md#limitations). Diagrams include rendered SVGs and editable Mermaid sources.
