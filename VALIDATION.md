# Validation record — 2026-11-16

Result: **15 automated tests passed** with Python 3.14.6 and MySQL
Connector/Python 26.10.0. Browser JavaScript passed `node --check`.
Python source compilation, `pip check`, and a fresh package wheel build also
passed.

The files selected for publication were reviewed for personal identifiers,
local user paths, MAC addresses, embedded credentials, and private keys. No
such values were found. Test passwords are synthetic fixtures, and test
private keys are generated at runtime. Local environments, build artifacts,
environment files, and key files are excluded through `.gitignore`.

The protocol tests use actual Connector/Python TCP handshakes, MFA negotiation,
MySQL result sets and SQL operations against a purpose-built protocol simulator.
A separate synthetic authenticator produces real P-256 attestation and assertion
signatures; the simulator verifies them cryptographically.

The HTTP test exercises the Flask ceremony transport, reusable bridge, browser
credential JSON shape, registration, login and returned SQL result together.
It is an HTTP client test, not a real browser/YubiKey test.

Covered:

- Registration INITIATE/FINISH on the same sandbox connection.
- Login and query under the authenticated user's connection.
- Database-side rejection of a wrong password and a different signing key.
- Refusal when MySQL does not request FIDO factor 2.
- Refusal to log in before registration.
- Fresh random server challenges and rejection of an old assertion in a new flow.
- RP ID, exact origin, challenge, ceremony type and cross-origin validation.
- Preservation of signed browser client-data bytes and extra fields.
- Unsupported `none` attestation rejection.
- Length-encoded protocol values and truncated-payload rejection.
- One-use replies, ceremony ownership, concurrent user isolation and expiration.
- HTTP origin/CSRF checks and disabled-by-default administrator provisioning.

Not verified:

- MySQL Enterprise 27.1.0 (or any actual Enterprise server plugin).
- A physical YubiKey, its PIN dialog, or hardware-produced browser attestation.
- Real-browser end-to-end behavior or visual rendering. A Chromium executable
  was unavailable in the workspace; only the JavaScript syntax and HTML response
  were checked.
- Production deployment, multi-process operation, load or security review.

Do not equate the protocol simulator's OK packets with certification of the
commercial server plugin. Follow README's live compatibility checklist before
claiming this prototype works with the target deployment.
