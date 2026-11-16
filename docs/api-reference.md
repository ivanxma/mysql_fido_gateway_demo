# Gateway API reference

## Exported package interface

```python
from mysql_fido_gateway import Gateway, BridgeError
```

These are the two names in the package's `__all__`. The Gateway constructor and its `register()` and `connect()` methods form the reusable authentication interface. The callback contracts below are part of that interface. There are no top-level exported convenience functions such as `login()` or `create_user()`.

The reusable methods do not apply the demo HTTP route's username regex, `demo_` prefix, or root-name block. Those are application-layer policies, documented under the HTTP endpoints.

Broker/Flow, codec utilities, adapter classes, Flask routes, and browser functions are separate supporting interfaces. Their availability for explicit import does not make them additional package-level exports or a stable external API.

## Gateway constructor

```python
Gateway(db_config, origin, rp_id, *, allow_loopback_plaintext=False)
```

| Parameter | Type | Required/default | Description |
| --- | --- | --- | --- |
| `db_config` | Mapping of Connector/Python options | Required | Non-shared database transport settings; copied into a new dictionary |
| `origin` | `str` | Required | Exact expected browser origin, currently `https://` followed by `rp_id`, without a port/path |
| `rp_id` | `str` | Required | Expected relying-party ID in MySQL's challenge and the authenticator RP hash |
| `allow_loopback_plaintext` | `bool`, keyword only | `False` | Permit unverified/plaintext DB transport only when the configured host is exactly `127.0.0.1`, `::1`, or `localhost` |

Construction returns a `Gateway` object. It checks the installed connector version, origin profile, database TLS policy, and forbidden shared-credential/pool/database keys. It does not open a database connection, confirm server variables, or test the CA file against a server.

`Gateway` reads **no environment variables**. See [configuration](configuration.md) for how the reference application builds its arguments.

Example for a remote database:

```python
bridge = Gateway(
    {
        "host": "mysql.example.com",
        "port": 3306,
        "ssl_ca": "/secure/mysql-ca.pem",
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
        "connection_timeout": 10,
        "read_timeout": 180,
        "write_timeout": 15,
    },
    origin="https://fido.example.com",
    rp_id="fido.example.com",
)
```

For a disposable local database, use `host='127.0.0.1'`, the desired DB port, and explicitly set `allow_loopback_plaintext=True`. That exception concerns **database transport**, not the browser origin.

The object exposes `db_config`, `origin`, and `rp_id` attributes. Treat them as configuration fixed for the lifetime of the instance; do not mutate shared configuration during concurrent requests.

**Errors:** `BridgeError` for the constructor's policy/version checks. Invalid Python argument types may also raise ordinary Python exceptions. Actual network or server errors happen later, when an operation connects.

## Gateway register

```python
bridge.register(username, password, ask, *, on_command=None)
```

| Parameter | Type | Required/default | Description |
| --- | --- | --- | --- |
| `username` | `str` | Required | Existing MySQL account username; it is not an application username lookup |
| `password` | `str` | Required | That account's password factor 1, not root's password or the key PIN |
| `ask` | Callable | Required | Blocking browser exchange callback described below; registration calls it with operation `create` |
| `on_command` | Callable or `None`, keyword only | `None` | Optional SQL-display callback receiving a single display string before each registration statement is attempted |

The account must already exist and require WebAuthn factor 2. The operation opens a fresh connection, enters pending-registration mode, runs INITIATE, calls the browser, validates the returned response shape, and runs FINISH on the same connection. It closes the connection before returning, including when registration fails after the connection was established.

**Return value on acceptance:**

```python
{"registered": True, "verified_by": "MySQL FINISH REGISTRATION OK"}
```

The reference app adds its own `message` field after this return. The package does not create users, install plugins, set server variables, grant privileges, delete key passkeys, or retain a root session.

**Errors:** `BridgeError` for unsupported/mismatched protocol data or an already enrolled account; `mysql.connector.Error` subclasses for database/connector failures. Exceptions from your callbacks propagate too. Do not treat a browser-created credential as successful enrollment without the returned MySQL result.

### Registration command callback

```python
def on_command(display_sql):
    # Example: send a bounded, owner-scoped UI event.
    flow.events.put_nowait({"type": "command", "sql": display_sql})
```

The callback receives INITIATE and a FINISH display template whose challenge response is replaced with `<redacted>`. It returns no meaningful value. It is called before execution and is not a server acknowledgement or an opportunity to replace the actual SQL.

Keep it fast and do not append credentials. A callback exception, including a full event queue, can abort the operation. This parameter is available on `register()`, not `connect()`.

## Gateway connect

```python
connection = bridge.connect(username, password, ask)
```

| Parameter | Type | Description |
| --- | --- | --- |
| `username` | `str` | MySQL username to authenticate |
| `password` | `str` | Password factor 1 for that account |
| `ask` | Callable | Blocking exchange callback; login calls it with operation `get` |

Returns a connected `BrowserConnection`, a Connector/Python `MySQLConnection` subclass, only after MySQL requested WebAuthn factor 2, a browser assertion was sent, and the connection completed. Normal connector session initialization occurs after the accepted assertion. This call does not run the demo proof query itself.

**Ownership:** the caller must close the returned connection. Do not share it with another user, put it into a shared-account pool, or assume an HTTP session retains it.

```python
connection = bridge.connect(username, password, flow.ask)
try:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 'hello world', CURRENT_USER()")
        row = cursor.fetchone()
finally:
    connection.close()
```

**Errors:** `BridgeError` for a missing/wrong factor, pending registration, unsupported response, or policy mismatch; connector errors for access denial, protocol, network, or server failures; callback errors can also propagate. A failed connection is shut down by the adapter. Reconnection is a new authentication operation and may require another browser gesture.

## Browser exchange callback

Both methods use this synchronous contract:

```python
credential = ask(operation, public_key_options)
```

| Argument/result | Description |
| --- | --- |
| `operation` | `create` for enrollment or `get` for authentication |
| `public_key_options` | JSON-compatible public-key options. Binary values are base64url strings, not Python byte objects |
| Return value | The serialized browser credential dictionary, **not** the entire HTTP reply wrapper |

Run the operation in a worker. `ask()` must send options to the same user's browser and block until its matching, expiring response arrives. `Flow.ask` implements this pattern. It must not invoke a USB key on the gateway machine or ask the remote user for a PIN in a terminal.

For creation, options include `challenge`, `rp`, `user`, ES256 algorithm `-7`, a 120-second hint, direct attestation, cross-platform attachment, required resident key, and required user verification. For login they include `challenge`, `rpId`, the same timeout hint, discouraged verification, and `allowCredentials` when MySQL supplied an ID.

All byte strings in the following illustrative shape are base64url without padding:

```json
{
  "id": "<credential-id>",
  "rawId": "<base64url-credential-id>",
  "type": "public-key",
  "response": {
    "clientDataJSON": "<base64url-original-client-data>",
    "attestationObject": "<base64url-attestation>"
  },
  "clientExtensionResults": {}
}
```

For an assertion, `response` contains `clientDataJSON`, `authenticatorData`, `signature`, and `userHandle` (base64url or `null`), rather than `attestationObject`. The supplied serializer also returns registration transports when available. These are shape examples, not usable credentials.

## BridgeError

```python
raise BridgeError("A useful failure message")
```

`BridgeError` subclasses Python `Exception` without adding custom constructor parameters or attributes. Its normal `args`/string message are available; it has no connector `errno` or `sqlstate` fields. Catch it separately from `mysql.connector.Error`.

The reference app translates a synchronous `BridgeError` into HTTP 400 JSON, and a worker `BridgeError` into an `error` flow event. When integrating, ensure callback/browser failure never becomes an authenticated session or a successful SQL result.

## Supporting broker interfaces

Explicit import:

```python
from mysql_fido_gateway.broker import Broker, Flow
```

These are in-memory reference transport helpers, not package-level exports. Keep one Broker for the process; use a fresh Flow for each action. Owners must be trusted session-derived strings, not user-supplied ownership claims.

### Broker methods

| Signature | Parameters | Return and behavior | Failure conditions |
| --- | --- | --- | --- |
| `Broker(max_flows=32)` | `max_flows`: integer capacity | Broker with an initially empty registry and a lock | Invalid argument types are not normalized |
| `broker.create(owner)` | `owner`: session-derived string | New default-150-second Flow; cleans expired registry entries first | `BridgeError` if capacity is reached or this owner has an unfinished flow |
| `broker.get(flow_id, owner)` | Flow ID and the requesting session's owner string | That owner's unexpired Flow, including a completed flow whose final events may still be polled | `BridgeError` for unknown/wrong-owner/expired flows |

Finished flows count toward capacity until their expiration and cleanup on a subsequent `create()`. There is no background cleanup thread. Broker does not read environment variables and does not provide a TTL constructor option.

### Flow methods

| Signature | Parameters | Return and behavior |
| --- | --- | --- |
| `Flow(owner, ttl=150)` | Owner string; lifetime in seconds | Creates an ID, monotonic deadline, event/reply queues, and a lock. Normally obtain it from Broker |
| `flow.ask(operation, options)` | Operation string and JSON-compatible options | Enqueues a `webauthn` event, waits for a matching reply until deadline, and returns its `credential` dictionary |
| `flow.respond(token, reply)` | One-use request token; dictionary containing `credential` or `error` | Returns `None`; validates the deadline/token, consumes the token, and queues the reply |
| `flow.finish(event)` | Final event dictionary, normally `success` or `error` | Returns `None`; marks the flow done and queues the event. Call exactly once |

`ask()` raises `BridgeError` for an invalid ceremony state, timeout, browser-reported error, or a missing/non-dictionary credential. `respond()` raises it for completed/expired flows and wrong/replayed tokens. Reply error text is limited to 120 characters when included in `ask()`'s error.

`finish()` is not an idempotent retry API. Event/reply queues use non-blocking insertion with capacities 8 and 1; `queue.Full` can propagate. Poll events promptly and keep additional telemetry bounded.

Useful read-only integration fields are `flow.id`, `flow.owner`, `flow.deadline`, and `flow.done`. The HTTP poll handler consumes `flow.events.get(timeout=1)` and converts `queue.Empty` to a `waiting` event. Do not manipulate `expected`, `replies`, or locks to bypass ownership/replay checks.

## Flask application factory

```python
from app import create_app
app = create_app(gateway=None)
```

`gateway` optionally supplies a truthy compatible gateway object for testing/integration. It must offer the methods/signatures used by the routes, including `register(..., on_command=...)`. With no injected object, the factory creates Gateway from environment configuration. The factory returns Flask and does not start its listener. Running the module as a script starts the fixed loopback development listener.

The created app exposes `app.extensions['browser_gateway']` and `app.extensions['ceremony_broker']`. Administrator routes still use the environment-derived `db_config` and a separate root connection, even with a supplied gateway object.

## HTTP endpoints

The reference routes are a specific browser transport, not methods on Gateway. They require a session established by `GET /`. Every POST requires the exact configured `Origin`, a valid `X-CSRF-Token` from the page's meta tag, and the matching session cookie. The browser sends its Origin; do not hardcode another user's cookie or CSRF token.

### Start an action

`POST /api/flows` accepts a JSON object:

| Action | Required fields | Optional fields | Effect |
| --- | --- | --- | --- |
| `setup` | `action`, `admin_token`, `root_password` | None | Check plugin; persist RP ID and timeout; verify by read-back |
| `create` | `action`, `admin_token`, `root_password`, `username`, `password` | `reset`: JSON boolean, default false | Provision the demo account, optionally after an explicit drop |
| `register` | `action`, `username`, `password` | None | Enroll the existing account's key |
| `login` | `action`, `username`, `password` | None | Authenticate and execute the proof query |

Usernames must match `[A-Za-z0-9_]{1,32}`; `root` is rejected case-insensitively for user actions. Create additionally requires the case-sensitive `demo_` prefix. User passwords must be nonempty strings of at most 1,024 characters. The API only treats `reset` as enabled when its decoded JSON value is exactly `true`.

Example browser request using the supplied `jsonRequest` helper:

```javascript
const {flow_id} = await jsonRequest('/api/flows', {
  action: 'register', username: enteredUsername, password: enteredPassword
});
```

An accepted start returns HTTP 202 with `{"flow_id": "<opaque-id>"}`. No SQL or authentication success is implied by acceptance.

### Poll an action

`GET /api/flows/<flow_id>` uses the same session and returns one event:

| Event `type` | Other fields | Meaning |
| --- | --- | --- |
| `waiting` | None | No event became available within the poll wait |
| `command` | `sql` | Safe display template for a statement being attempted; not necessarily the literal SQL/parameter values |
| `webauthn` | `operation`, `request_id`, `publicKey` | Perform `create` or `get` in the browser and respond once |
| `success` | `result` | Worker completed the action successfully |
| `error` | `message` | Worker failed; do not treat this as authentication success |

These events normally use HTTP 200 even when `type='error'`. Wrong-owner/unknown/expired-flow checks instead raise a synchronous BridgeError and return HTTP 400.

Setup success returns a message plus `rp_id` and `connect_timeout`. Create success returns a message. Register success extends the package result with a message. Login success returns `message`, `mysql_account`, `connection_id`, `server_version`, and `verified_by`.

### Respond to WebAuthn

`POST /api/flows/<flow_id>/respond` accepts either:

```json
{"request_id": "<one-use-id>", "credential": {"<serialized credential fields>": "..."}}
```

or:

```json
{"request_id": "<one-use-id>", "error": "NotAllowedError: user cancelled"}
```

The credential example is schematic; use `serialize()` to produce the actual object. A valid response is acknowledged with HTTP 200 and `{"accepted": true}`. This acknowledges transport delivery, not database acceptance.

### HTTP error handling

Route validation commonly returns 400 JSON; Origin, CSRF, and administrator authorization failures return 403. Oversized requests can return Flask's 413 response. Framework errors such as untrusted hosts and missing routes may be HTML, so custom clients should not assume every non-success response is JSON. The application limits POST bodies to 131,072 bytes.

## Browser reference helpers

`static/gateway.js` is a normal browser script, not an ES module with exported functions. It expects the demo DOM, including the CSRF meta tag, activity elements, sections, and action forms. Extract/adapt its helpers when integrating with a different UI.

| Function | Parameters | Return/behavior |
| --- | --- | --- |
| `decode(value)` | Base64url string | `Uint8Array` for WebAuthn binary fields |
| `encode(value)` | ArrayBuffer or compatible bytes | Unpadded base64url string |
| `creationOptions(json)` | JSON creation options | Deep-cloned options with challenge, user ID, and excluded credential IDs decoded |
| `requestOptions(json)` | JSON assertion options | Deep-cloned options with challenge and allowed credential IDs decoded |
| `serialize(credential)` | Browser PublicKeyCredential | JSON-compatible credential dictionary with response bytes encoded |
| `jsonRequest(url, body)` | Same-origin URL; optional JSON body | Promise for parsed JSON; GET when body is absent, POST with CSRF header otherwise; throws on HTTP failure |
| `notify(message, state='')` | Display text; optional class such as `error`/`success` | Updates the top activity message using `textContent` |
| `wait(ms)` | Milliseconds | Promise resolving after that delay |

Helpers do not store credentials in browser storage. `jsonRequest` relies on the page's existing session and browser Origin behavior; it does not establish administrator authorization by itself.

## Low level codec utilities

These are explicit-import implementation helpers in `mysql_fido_gateway.codec`, not package-level exports. Most application developers should use Gateway rather than construct wire packets.

| Signature | Parameters | Result and checks |
| --- | --- | --- |
| `b64u(data)` | Bytes | Unpadded base64url string |
| `unb64u(value)` | Encoded string, maximum 180,000 characters | Decoded bytes; rejects invalid/oversized encoding with BridgeError |
| `lc_int(value)` | Nonnegative integer fitting an unsigned 64-bit length | MySQL length-encoded integer bytes; negative values raise BridgeError; out-of-range/type misuse can raise Python errors |
| `lc_bytes(data)` | Bytes | Length prefix followed by those bytes |
| `cbor_value(raw)` | One CBOR value as bytes | Decoded Python value; rejects invalid or trailing CBOR |
| `client_data(credential, challenge, origin, ceremony)` | Credential dictionary; Challenge; exact origin; `webauthn.create` or `webauthn.get` | Original client-data bytes after type, challenge, exact-origin, and cross-origin checks |
| `auth_data(raw, rp_id, registration=False)` | Authenticator bytes; RP ID; registration flag | `None` after RP hash/presence checks; enrollment additionally requires verification and attested-credential data |
| `assertion_packet(credential, challenge, origin)` | Browser assertion; Challenge; origin | MySQL binary assertion payload with one assertion; does not independently verify the signature against a credential registry |
| `registration_packet(credential, challenge, origin)` | Browser creation credential; Challenge; origin | **Standard base64** response string for FINISH, after packed ES256/x5c and credential-ID checks |

`Reader(data)` copies bytes into a bounded protocol reader. `take(count)` returns the next count bytes, `integer()` consumes a valid non-NULL MySQL length integer, `blob()` consumes a length-prefixed byte string, and `end()` returns `None` only when no trailing bytes remain. Malformed/truncated payloads raise BridgeError.

`Challenge(flags, salt, rp_id, account=b'')` is a frozen dataclass. `flags` is the capability byte, `salt` the challenge bytes, `rp_id` the ASCII domain, and `account` the registration account bytes. Prefer `Challenge.parse(raw, registration=False)`: it decodes MySQL challenge bytes, or standard-base64 registration input, validates a 32-byte salt and RP field, and consumes the full payload. `challenge.options(expected_rp, registration=False)` verifies RP equality and returns JSON-compatible creation/assertion options. The registration browser user ID is a SHA-256 digest of the account bytes.

`Exchange`, `BrowserPlugin`, `BrowserAuthenticator`, `BrowserConnection`, and its `initiate_registration()` reader are private adapter machinery in `mysql_bridge.py`. Their connector hooks and constructor details are not extension points. `TESTED_CONNECTOR` is the internal version constant, not an environment override. Changing these internals requires protocol-level validation with the target connector/server.
