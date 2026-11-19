# MySQL browser gateway documentation

The gateway lets users register and sign in to MySQL with a security key in their browser. MySQL verifies the password and WebAuthn proof. Remote users need only the HTTPS website; the gateway connects to the database.

Start with the [overview](user-manual.md#overview) and [deployment models](deployment.md), then [install the wheel and generate an app](../GETTING_STARTED.md). These guides describe library **0.3.1**.

| Document | Contents |
| --- | --- |
| [Getting started without cloning](../GETTING_STARTED.md) | Public wheel URL, interactive `newapp`, explicit MySQL target, download-and-start launchers |
| [User manual](user-manual.md) | Overview, requirements, installation, operating steps, message flows, troubleshooting, and limitations |
| [Deployment models](deployment.md) | Local development and remote browsers connecting through the gateway to private MySQL |
| [API reference](api-reference.md) | Exported Python API, callbacks, broker helpers, HTTP endpoints, browser helpers, and protocol utilities |
| [Flask wheel and application SQL](flask-wheel.md) | Installable Flask utility, `getConnection()`, bound parameters, transactions, and native-driver callbacks |
| [Configuration reference](configuration.md) | Every application environment variable, launcher behavior, database parameters, and fixed limits |
| [Tutorial 1: Create user](create-user-tutorial.md) | Build a single-purpose create-user page with a minimal app.py |
| [Tutorial 2: Register YubiKey](registration-tutorial.md) | Build a separate registration page using the account from Tutorial 1 |
| [Tutorial 3: Login and main page](login-main-tutorial.md) | Build a login page leading to a protected main page and Hello World button |
| [Terms and references](terms-and-references.md) | Scope, responsibilities, glossary, source files, and external technical references |

Choose an application path:

- **Run all three actions on one page:** install the wheel and follow the [reference application setup](user-manual.md#install-and-start-the-local-reference-application). Use `python app.py --check-library` to check its installed version and location.
- **Build a Flask application:** follow the [library and SQL guide](flask-wheel.md), then the [login/main tutorial](login-main-tutorial.md). The library supplies linked login/registration templates and browser JavaScript; application routes use `auth.getConnection()`.
- **Integrate another framework:** use [`Gateway.register()` and `Gateway.connect()`](api-reference.md) and provide the browser exchange callback.

The demo and action helpers close each operation's connection. The Flask login utility retains a private connection per authenticated session, supports transactions, and closes it on logout, expiry, or failure.

For protocol details, see the manual's [registration flow](user-manual.md#registration-sequence) and [login flow](user-manual.md#login-sequence). For browser compatibility, see the [Chrome/Firefox modes](user-manual.md#shared-browser-and-native-client-enrollment), [limitations](user-manual.md#limitations), and [validation record](../VALIDATION.md).

The [combined registration/login example](new-application.md) is a supplementary sample. The three tutorials above teach each action separately.

This is a personal MIT-licensed prototype/tutorial, not an Oracle product. See [LICENSE](../LICENSE), [third-party licenses](../THIRD_PARTY_LICENSES.md), and [DISCLAIMER.md](../DISCLAIMER.md).
