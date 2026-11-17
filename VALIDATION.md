# Validation record — library 0.2.0, 2026-11-17

**40 automated tests pass** with Python 3.14.6 and Connector/Python 26.10.0. The full suite was also run against the installed 0.2.0 wheel, with library imports verified under the virtual environment's `site-packages`.

## Library and distribution checks

- Built `mysql_browser_fido_gateway-0.2.0-py3-none-any.whl` and verified its packaged modules, Flask extra, login template, JavaScript, and stylesheet.
- Installed the wheel in an isolated target and checked login rendering, all bundled assets, authentication/CSRF gates, and opaque cookie contents without copying login UI into the application.
- Checked `app.py --check-library` through direct and isolated Python startup. Both select the installed wheel; the check starts no listener and opens no database connection.
- Copied the minimal login starter to a separate directory and exercised it against the installed wheel: login, a touch-only assertion, parameterized Hello World, connection reuse, transaction commit, and logout.
- Copied the three-in-one app and its UI assets to a separate directory and exercised account creation, registration, touch-only login, and its SQL proof through the installed wheel. Administrator provisioning used a connection double; registration/login used the real connector against the protocol simulator.
- Python compilation, browser JavaScript syntax checks, dependency consistency (`pip check`), and launcher shell syntax checks pass.

## Automated behavior covered

- Real Connector/Python TCP handshakes, MFA negotiation, and registration INITIATE/FINISH on the same restricted connection.
- Real P-256 signatures from a software authenticator, verified by the MySQL protocol simulator.
- Wrong-password/signature rejection, absent FIDO factor rejection, pending-registration rejection, fresh challenges, and assertion replay rejection.
- Exact RP/origin/challenge/type checks, cross-origin rejection, preservation of signed client bytes, and unsupported attestation rejection.
- Owner-bound expiring flows, one-use replies, bounded queues, and HTTP Origin/CSRF checks.
- Packaged Flask login UI, protected pages/actions, cookie rotation, no credentials in cookies, missing-server-state rejection, expiry, and logout cleanup.
- SQL bound parameters (including quoted values), writes, batch execution, dictionary results, and transaction commit/rollback.
- Application/native callback errors rolling back without discarding an otherwise healthy login; failed commit cleanup revoking the session.
- Retained connection reuse, different-user isolation, worker thread ownership, and prevention of statement interleaving during the same user's transaction.
- Rejection of connection facade use after context exit, plus native-driver callbacks running on their owning worker.

## Browser demonstration and verification limits

A Chrome walkthrough was recorded using the actual application UI, synthetic credentials, a protocol test fixture, and illustrated security-key prompts. It demonstrates visible user steps. The prompts and software authenticator do not establish native browser WebAuthn or physical-key interoperability.

Still unverified:

- MySQL Enterprise 27.1.0 or any actual Enterprise WebAuthn server plugin.
- A physical YubiKey, its actual browser/OS PIN dialog, or hardware-produced attestation.
- A real browser-generated hardware ceremony accepted by a live Enterprise MySQL server.
- Production deployment, multi-process session architecture, load testing, or an external security review.

Simulator OK packets and passing library tests are not commercial-server or hardware certification. Follow the [live compatibility checklist](README.md#tests-and-live-compatibility-checklist) before claiming compatibility with a target deployment.
