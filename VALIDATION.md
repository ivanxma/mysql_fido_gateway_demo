# Validation record — library 0.3.1, 2026-11-19

**73 automated tests pass** on the cleaned source with Python 3.14.6 and Connector/Python 26.10.0, and against the rebuilt 0.3.1 release wheel installed in a separate directory. The wheel checks explicitly verify imports come from that installation. The wheel and starter ZIP include the updated documentation; the running local demo was not restarted or replaced.

## Debugging-remnant cleanup review, 19 November 2026

- Removed the second, unreachable credentials/pool/database check in `Gateway`:
  `mysql_config()` already rejects those settings before transport setup. A
  constructor-level test covers every prohibited field, including factors 2/3.
- Removed the redundant plugin-name type conversion. The private INITIATE
  reader returns bytes; compare those bytes directly and reject an unexpected
  plugin before browser interaction or FINISH.
- Reused the runtime library-version constant for the CLI wheel URL, replacing
  its unused version constant and repeated hardcoded version strings.
- Removed the catch-all RP/attestation/timeout checklist appended to every
  MySQL error. Authentication errors keep their focused guidance; registration
  error 4061 retains attestation guidance. Error numbers, safe logging and
  rejection behavior are preserved.
- Corrected the demo's stale "server compatibility unverified" label and the
  sample configuration comment claiming the demo never displays its admin token.

Retained deliberately: Browser only/shared enrollment policies, signed-extension
rejection, capability `0x02`, MySQL credential-ID requests, bounded accepted-ID
hints for accounts where MySQL omits the ID, and the INITIATE metadata-EOF reader.
These implement compatibility and validation, not temporary diagnostic bypasses.
Project-local authentication scripts are documented editable starter assets;
they are intentionally separate from the wheel's default scripts.

Source and release-wheel suites each pass 73 tests. Dependency consistency,
Python syntax, launcher shell syntax and whitespace checks pass. Wheel inspection
found no internal reports, tests, diagnostic launchers or temporary credential
files by the checked paths/names. The release wheel contains matching Python
modules and bundled documentation. The earlier, unpublished 0.3.1 artifacts were
preserved internally before rebuilding the public downloads and SHA-256 checksums.
The live local TLS helper remains outside the package and was not stopped or
deleted. Its CA-verified TLS settings are operational configuration, not redundant
code that can be removed from a running demo.

## Library and distribution checks

- Built `mysql_browser_fido_gateway-0.3.1-py3-none-any.whl` and verified its packaged modules, Flask extra, login template, JavaScript, and stylesheet.
- Installed the wheel in an isolated target and checked login rendering, all bundled assets, authentication/CSRF gates, and opaque cookie contents without copying login UI into the application.
- Checked `app.py --check-library` through direct and isolated Python startup. Both select the installed wheel; the check starts no listener and opens no database connection.
- Copied the minimal login starter to a separate directory and exercised it against the installed wheel: login, a touch-only assertion, parameterized Hello World, connection reuse, transaction commit, and logout.
- Copied the three-in-one app and its UI assets to a separate directory and exercised account creation, registration, touch-only login, and its SQL proof through the installed wheel. Administrator provisioning used a connection double; registration/login used the real connector against the protocol simulator.
- Python compilation, browser JavaScript syntax checks, dependency consistency (`pip check`), and launcher shell syntax checks pass.

## Automated behavior covered

The protocol simulator exercises password-token verification through the cached
authentication path. It does not establish first-login interoperability for a
fresh account without TLS; the real-server diagnostic below covers that case.

- Real Connector/Python TCP handshakes, MFA negotiation, and registration INITIATE/FINISH on the same restricted connection.
- Real P-256 signatures from a software authenticator, verified by the MySQL protocol simulator.
- Wrong-password/signature rejection, absent FIDO factor rejection, pending-registration rejection, fresh challenges, and assertion replay rejection.
- Exact RP/origin/challenge/type checks, cross-origin rejection, preservation of signed client bytes, and unsupported attestation rejection.
- Owner-bound expiring flows, one-use replies, bounded queues, and HTTP Origin/CSRF checks.
- Combined-demo registration switch: both choices reach the real connector with the matching resident-key policy, without changing the gateway default. Invalid modes fail before any flow/connection; other registration apps retain their configured policy.
- Packaged Flask login UI, protected pages/actions, cookie rotation, no credentials in cookies, missing-server-state rejection, expiry, and logout cleanup.
- SQL bound parameters (including quoted values), writes, batch execution, dictionary results, and transaction commit/rollback.
- Application/native callback errors rolling back without discarding an otherwise healthy login; failed commit cleanup revoking the session.
- Retained connection reuse, different-user isolation, worker thread ownership, and prevention of statement interleaving during the same user's transaction.
- Rejection of connection facade use after context exit, plus native-driver callbacks running on their owning worker.

## Template-based frontend checks

- Desktop (1440px) and mobile (390px) Chrome previews inspected for sign-in and registration pages.
- Browser test follows the registration link, submits existing-account credentials, completes software-key registration, returns to sign in, authenticates with a touch-only assertion, runs application SQL, and logs out.
- Shared JavaScript runs with the application Content Security Policy; no browser errors, failed asset requests, or horizontal mobile overflow were observed.
- The sample includes editable base/login/registration Jinja templates and application CSS. The starter ZIP was extracted and rendered against the installed wheel.
- Registration requires MySQL acceptance, never authorizes the main page by itself, and has independent owner-bound flow IDs. Tests cover wrong passwords, cancellation/retry, CSRF checks, and login/registration route isolation.

## Browser demonstration and verification limits

A Chrome walkthrough was recorded using the actual application UI, synthetic credentials, a protocol test fixture, and illustrated security-key prompts. It demonstrates visible user steps. The prompts and software authenticator do not establish native browser WebAuthn or physical-key interoperability.

## Live compatibility result, 19 November 2026

- Native MySQL 26.10.0-commercial client registration and login passed against
  MySQL 26.10.0-commercial, RP ID `localhost`. The temporary native test account
  and credential option files were removed.
- Original browser enrollment reached FINISH and failed with MySQL error 4061.
  The real packed ES256/x5c attestation signature was valid; signed JSON already
  used the expected compact challenge format, and server challenge replacement
  did not change its bytes. The earlier whitespace hypothesis did not explain
  this captured failure.
- MySQL's bundled libfido2 1.15.0 returned `FIDO_ERR_INVALID_PARAM` for that
  response, whose authenticator flags indicated signed extensions. The RP and
  presence checks passed, narrowing the rejection to extension expectations.
  An independent signed software credential with `credProtect` reproduced the
  same parameter failure; the captured original extension's name was not saved.
- Credential-ID-based browser enrollment was then accepted by MySQL: capability
  `0x02`, authenticator flags `0x45`, no signed extensions, and bundled libfido2
  verification result 0. Optional browser `credProps.rk` was absent and was not
  required. PIN/user verification and the original signed bytes were retained.
- Browser login with the same real account/key was accepted by MySQL after
  adding `hints=['security-key']` and `usb`/`nfc`/`ble` transports to the supplied
  credential ID. This capture recorded authentication acceptance without SQL
  output; the later user-confirmed Chrome SQL checks are recorded below.
- Diagnostics recorded booleans, error codes and format/flag metadata, not
  passwords, PINs, credential IDs, full client JSON, or attestation payloads.

This is a single physical-key/browser path. Browser version, OS version, and
YubiKey model/firmware were not collected; do not generalize the result.

Still unverified:

- MySQL 27.1.0, other server builds, and Community-specific packaging/runtime.
- Other physical keys, browser/OS versions, attestation formats and policies.
- Production deployment, multi-process session architecture, load testing, or an external security review.

Simulator OK packets and passing library tests are not commercial-server or hardware certification. Follow the [live compatibility checklist](docs/user-manual.md#validate-a-target-deployment) before claiming compatibility with a target deployment.

## User-confirmed Chrome Browser only checks, 19 November 2026

After the MySQL TLS correction, the user confirmed successful login and supplied
the application's `hello world` output in both a normal Chrome window and an
Incognito window. This followed the requested Browser only workflow.

| Check | User-supplied result | Assessment |
| --- | --- | --- |
| Valid credentials, normal window | `hello world`; proof query displayed | Login and SQL success confirmed |
| Same registered account/key, Incognito | `hello world`; proof query displayed | Fresh browser-session login confirmed |
| Incorrect password | MySQL 1045; no SQL sent; no application-authentication fallback | Expected rejection confirmed |
| Cancel security-key prompt | `NotAllowedError`; no SQL command shown | Expected cancellation failure confirmed |

The displayed proof query was:

```sql
SELECT 'hello world', CURRENT_USER(), CONNECTION_ID(), @@version;
```

These are user-reported application results, not a new instrumented browser
capture. Exact Chrome/key versions, authenticator flags/extensions, PIN behavior,
returned account/version values and a separate FINISH registration transcript
were not supplied. The user's description identifies the cancellation;
`NotAllowedError` alone can also mean timeout or refusal. Incognito changes
browser session state but does not clear the gateway's credential-hint cache.
This confirms the tested browser-only login path and its two rejection checks;
it does not establish Chrome shared-mode or native-client compatibility.

## Public-install and licensing preparation

The original 0.3.0 release introduced an interactive `newapp` command, explicit MySQL host/port validation, generated code assignments, start launchers, MIT project metadata, a personal-project/non-Oracle disclaimer, and unmodified dependency license texts. Tests cover required MySQL settings, password/config separation, safe folder generation, prompts, overwrite refusal, and non-executing dotenv handling. Versioned wheel/ZIP/checksum files are prepared under `downloads/0.3.1/`; public URLs require pushing those files and making the repository public.

## Fresh-account password authentication and MySQL TLS

On 19 November 2026, a diagnostic restart had explicitly set `ssl_disabled=True`
in the local demo, unlike the reference `app.py` and the TLS hardware test.
A fresh temporary account reproduced the reported 1045 with its correct password:

| Database connection | Registration mode | Result |
| --- | --- | --- |
| Plaintext, password not cached | `browser` | 1045 before SQL |
| Plaintext, password not cached | `shared` | 1045 before SQL |
| CA-verified TLS 1.3 | `browser` | INITIATE succeeded; browser challenge reached |
| Plaintext after successful TLS password authentication | `browser` | Browser challenge reached using the warmed password cache |
| CA-verified TLS 1.3 | `shared` | INITIATE succeeded; browser challenge reached |

The pinned pure-Python connector lacks RSA password exchange for uncached
`caching_sha2_password` authentication. The live demo was restarted with the
CA-verified TLS transport used by the hardware test. Its local development
profile verifies the CA but does not verify the hostname of MySQL's generated
certificate; remote deployments still require both checks. Existing accounts,
plugins and server settings were unchanged, and the temporary account was
removed. The diagnostic stopped at the browser challenge; it did not register
a key or establish Chrome shared-mode compatibility. A database restart is not
needed to apply the gateway's TLS correction.

## Stock-client interoperability and remote-user constraint

The earlier successful native baseline used a separate natively enrolled account,
not the browser-enrolled demo_x account. A later native CLI attempt for demo_x
failed with 1045; the server logged an authentication signature-verification
failure. PATH resolves mysql 9.7.2, while the command selected the commercial
26.10 plugin directory, so a same-version repeat for that browser-created account
was not captured. Native plugin source also establishes a credential-selection
difference: keys with credential-management support use resident discovery rather
than the stored-ID request used by the gateway.

A separate stock 26.10 test natively enrolled a temporary account and passed native
login/SQL. The user subsequently reported browser Hello World after the test, but
the copied output did not include CURRENT_USER(), so this record does not
independently bind that output to the temporary account. The account was removed.
This diagnostic path is not an acceptable remote-user onboarding proposal: remote
users must register entirely in the browser and cannot reach private MySQL. Both
product plugins must stay unchanged. Shared browser-created credential/native
client compatibility was subsequently demonstrated with the opt-in `shared`
profile below; the earlier default-browser/native failure is not reclassified
as a success.

The local gateway candidate additionally learns bounded, process-local public
credential-ID hints after MySQL acceptance. Automated tests cover cold discovery
followed by explicit ID selection, account isolation, rejection/stale-hint
handling, LRU eviction and disabled caching. This can avoid repeated discovery
within a process; it does not guarantee no PIN across restart or override browser
or key policy. It does not make a non-discoverable credential discoverable to the
stock native client.

## Discoverable browser enrollment profile

The library now accepts `registration_mode='shared'`; Flask applications also
read `REGISTRATION_MODE=shared`. It requests a discoverable credential with
required registration verification, retains MySQL's credential-ID storage via
capability `0x02`, and leaves login verification discouraged. It rejects signed
extensions and explicitly reported non-discoverable results without falling
back to browser-only enrollment. Eight additional automated tests cover the
profile, signed-byte preservation, extension rejection, browser login after a
gateway restart, environment configuration, and the HTTP downgrade/error path.

Offline synthetic verification against the installed MySQL libfido2 1.15.0
accepts extension-free packed attestation and rejects `credProtect` values 1,
2 and 3 with `FIDO_ERR_INVALID_PARAM`, in both full and legacy input formats.
Configuring the matching expected extension in an isolated diagnostic verifier
makes each synthetic signature pass. Neither product plugin was changed.

**The shared profile passed the physical-key acceptance test on 19 November
2026.** Enrollment used only the browser. The same account and credential then
authenticated in the browser and the stock native MySQL client.

| Check | Observed result |
| --- | --- |
| Browser/OS | Firefox 160.0.1, macOS 26.7.2; separate profile with `security.webauthn.enable_macos_passkeys=false` |
| Database/client | MySQL 26.10.0-commercial on loopback port 5316; matching native 26.10 binary and plugin |
| Key | User's physical YubiKey; model/firmware not independently collected |
| Browser registration | `residentKey=required`, `credProps.rk=true`, packed attestation, flags `0x45`, no signed extensions; MySQL FINISH OK |
| Browser login | Fresh Gateway with credential hint caching disabled; ID supplied by MySQL; `userVerification=discouraged`; assertion flags `0x01` (presence, no verification) |
| Browser SQL identity | `demo_shared_da55ebbf@localhost`; server version `26.10.0-commercial` |
| Native SQL identity | Same `demo_shared_da55ebbf@localhost`; explicit success marker; exit 0 |
| Native prompts | No PIN prompt and no account-selection prompt |
| Product changes | No MySQL server or client plugin modification; no native registration performed |

The physical test used the updated source library; all 68 automated tests also
passed against the rebuilt installed wheel from outside the source tree. The
fresh Gateway/no-cache browser check demonstrates that this login path does not
depend on a previously learned process-local ID.

The test harness explicitly selected TLS 1.3 with CA certificate verification.
Python 3.14's default SSL context initially rejected the local MySQL-generated
certificate because its Authority Key Identifier was missing; the explicit
Connector/Python TLS context verified the configured CA chain successfully.
An unrelated-CA negative control was rejected. This was a loopback test using
CA verification, not a hostname-verified remote deployment test. No server
certificate or database setting was changed.

This establishes one shared browser/native path, not browser-wide compatibility.
Chrome/Edge discoverable enrollment still adds an incompatible signed extension
with this key/server profile. Safari, stock macOS passkey services, Firefox on
other platforms, other keys, and other MySQL builds need separate acceptance
tests. The default `browser` mode remains available.
