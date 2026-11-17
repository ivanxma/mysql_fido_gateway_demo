# Gateway terms and references

## Terms of reference

**Purpose:** enable a user with a browser-local security key to complete the MySQL server's password plus WebAuthn authentication, then execute SQL under that user's accepted database account.

**Scope:** library 0.2.0: the authentication adapter and browser callback contract, broker/HTTP transport, demo setup/create/register/login actions, retained Flask login sessions and transaction/cursor API, wheel installation, and the supported prototype profile.

**Responsibilities:**

- The database administrator manages plugin availability, server policy, RP ID, accounts, source-host matching, privileges, and recovery/unregistration procedures.
- The application operator manages the browser endpoint, HTTPS trust, app secrets, gateway access, database transport, and process lifecycle.
- The application developer chooses the packaged Flask transport or implements a custom browser callback, then handles errors, per-user SQL access, transaction boundaries, and business authorization.
- The user controls the local key gesture and verification prompt. The application must not collect the key PIN.
- MySQL makes the final account authentication decision and applies database grants. The gateway does not replace that decision with application-only passkey authentication.

**Success criteria:** enrollment is successful only after MySQL accepts FINISH REGISTRATION. Login is successful only after MySQL accepts the password/WebAuthn connection; the demo additionally requires its proof query to succeed under the expected account.

Production certification, arbitrary authentication-factor combinations, general identity federation, all-attestation support, and complete key recovery/management are outside this prototype's implemented scope. See the [limitations](user-manual.md#limitations).

## Glossary

| Term | Meaning in this project |
| --- | --- |
| Account host | MySQL's host portion in `user@host`, matched against the connection's source as the server observes it |
| Administrator token | Application gate for setup/provisioning; distinct from root's MySQL password and from an authenticator PIN |
| Assertion | A login proof containing signed authenticator data and browser client data |
| Attestation | Registration evidence about a newly created credential; this prototype requires packed ES256 with x5c |
| Authenticator | The component performing key creation/signing and local presence/verification; the intended device is a YubiKey |
| AuthMoreData | MySQL authentication-protocol message type; raw connector packets include a tag that must be stripped before reading plugin bytes |
| Base64url | URL-safe binary encoding used for browser JSON fields; not the standard-base64 encoding used for FINISH's complete MySQL response string |
| Broker | Process-local registry connecting session owners with active/recent flows |
| CBOR | Binary structured-data encoding used in WebAuthn attestation and parts of the adapter's wire format |
| Ceremony | One registration or authentication interaction, including challenge, browser response, and server decision |
| Challenge | Fresh server-provided random data that binds a response to the current ceremony |
| Client data JSON | Browser-produced `clientDataJSON` containing ceremony type, challenge, origin, and related fields; preserved byte-for-byte |
| Connection facade | Request-scoped SQL interface returned by `auth.getConnection()`; forwards driver operations to the authenticated connection's owning worker |
| Credential ID | Reference identifying a registered credential; not the private key. MySQL may not provide one for resident credentials |
| CSRF | Cross-site request forgery; the demo checks a session-bound token and exact POST Origin |
| Discoverable credential | Credential discoverable by the authenticator for an RP without the caller supplying a credential ID; also called resident credential |
| EOF | End-of-file protocol marker used in traditional MySQL result sets; the registration metadata separator can be absent |
| ES256 | ECDSA with P-256 and SHA-256; WebAuthn algorithm identifier `-7` |
| Factor | One step in MySQL's configured authentication chain; the supported profile uses a password first and WebAuthn second |
| FIDO2 | Standards supporting authenticator-based public-key credentials, including browser WebAuthn and client-to-authenticator interaction |
| Flow | One expiring, owner-bound operation with event/reply queues and a one-use expected response token |
| Gateway | Python transport adapter relaying MySQL WebAuthn challenges to a browser; does not store an independent user passkey registry |
| INITIATE and FINISH | MySQL registration statements executed in order on one restricted connection |
| Origin | Scheme, hostname, and effective port of the browser page; a path is not part of it |
| Owner | Opaque session-derived identifier used to isolate ceremony transport; not a replacement for MySQL account authentication |
| Packed | WebAuthn attestation format required by the current registration codec |
| Passkey | Public-key credential used with WebAuthn; this application still requires the separate MySQL password factor |
| PIN | Key-local user-verification secret; not sent to the Flask service |
| RP and RP ID | Relying party and its identifier. The identifier scopes the credential; in this app it must match MySQL's configured RP domain |
| RP hash | SHA-256 hash of the RP ID carried in authenticator data and checked by the adapter |
| Sandbox | MySQL's restricted pending-registration connection state; normal initialization and business SQL are withheld |
| Transaction context | `with auth.getConnection()` scope that commits on success, rolls back on exceptions, closes its cursors, and restores autocommit, subject to MySQL commit semantics |
| UP | User presence, normally a touch or equivalent gesture indicating local interaction |
| UV | User verification, such as PIN/biometric verification performed locally by the authenticator |
| Wheel | Installable Python `.whl` distribution; this release ships library modules and the login UI assets, while demo application files remain in the repository |
| x5c | Attestation certificate-chain field; this adapter requires an attestation certificate and signature |

Presence and verification are separate concepts. Requiring a touch does not necessarily require a PIN, and discouraging verification does not prohibit a browser/key from performing it. See [Yubico's explanation](https://developers.yubico.com/WebAuthn/WebAuthn_Developer_Guide/User_Presence_vs_User_Verification.html).

## Implementation references

| Source | Authority for |
| --- | --- |
| [Package exports](../mysql_fido_gateway/__init__.py) | Package-level `Gateway` and `BridgeError` exports |
| [MySQL adapter](../mysql_fido_gateway/mysql_bridge.py) | Connector version pin, transport/origin policy, factor negotiation, registration and connection lifecycle |
| [Codec](../mysql_fido_gateway/codec.py) | Challenge/options conversion, data checks, attestation restrictions, and wire encoding |
| [Broker](../mysql_fido_gateway/broker.py) | Flow ownership, capacity, expiry, queues, and response tokens |
| [Reference app entry point](../app.py) | Installed-wheel selection, version/location check, three-in-one factory delegation, and loopback listener |
| [Demo/action utilities](../mysql_fido_gateway/flask_util.py) | Environment mapping, per-action connections, setup/provisioning, Origin/CSRF checks, errors, and proof query |
| [Flask login utility](../mysql_fido_gateway/flask_login.py) | Retained sessions, worker ownership, `getConnection()`, parameterized queries, transactions, cleanup, and packaged login UI |
| [Library guide](flask-wheel.md) | Wheel installation, upgrade, migration, and application SQL examples |
| [Browser script](../static/gateway.js) | Browser byte conversion, WebAuthn calls, polling, response transport, and notifications |
| [Launcher](../start.sh) | `.env` sourcing, local/remote defaults, administrator token behavior, and local HTTPS setup |
| [Example environment](../config.example.env) | Non-secret example settings |
| [Package metadata](../pyproject.toml) | Python minimum version, package version, dependencies, and extras |
| [Protocol/HTTP tests](../tests/test_gateway.py) | Authentication, transport, and negative-path coverage |
| [Flask login tests](../tests/test_login_app.py) | Bound SQL, transaction cleanup, connection reuse, thread/session isolation, expiry, packaged assets, and logout; simulator results are not hardware certification |
| [Validation record](../VALIDATION.md) | Current automated and installed-wheel checks, with the remaining live hardware/server limits |

## External technical references

- [MySQL WebAuthn authentication](https://dev.mysql.com/doc/refman/26.10/en/webauthn-pluggable-authentication.html) describes the server/client feature, account enrollment, and authenticator interaction.
- [MySQL multifactor authentication](https://dev.mysql.com/doc/refman/26.10/en/multifactor-authentication.html) describes factor configuration and server authentication policy.
- [MySQL WebAuthn protocol exchanges](https://dev.mysql.com/doc/dev/mysql-server/latest/page_webauthn_authentication_exchanges.html) describes registration and assertion messages. The adapter's packet layout follows this protocol profile.
- [Connector/Python connection arguments](https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html) documents database connection/TLS options. This adapter additionally enforces its own narrower policy and version pin.
- [WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/) defines browser ceremonies, RP IDs, origins, and authenticator data. Browser capabilities are broader than this repository's supported profile.
- [W3C Secure Contexts](https://www.w3.org/TR/secure-contexts/) describes browser secure-context requirements and local-origin treatment. It does not remove the current application's HTTPS-origin check.
- [Yubico presence and verification guidance](https://developers.yubico.com/WebAuthn/WebAuthn_Developer_Guide/User_Presence_vs_User_Verification.html) explains UP/UV and why PIN prompts can differ between registration and authentication.

Use the local implementation as the reference for this prototype's exact signatures and restrictions. Consult the primary specifications for protocol semantics and validate the actual server/browser/key combination before making compatibility claims.
