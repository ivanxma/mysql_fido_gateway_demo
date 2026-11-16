# Build an application using the gateway

## Choose the integration model

Use the package for MySQL authentication and keep your application's routes, business authorization, and UI. Start from the working flow transport in [app.py](../app.py) and adapt the [browser helpers](../static/gateway.js). The package installation does not install a standalone Flask application, templates, or static files into your new project.

Use one Gateway configuration and one Broker per process. Start one worker and one fresh owner-bound Flow per action. Registration owns and closes its restricted connection; login returns a connection that your worker must close.

The current package requires an origin such as `https://orders.example.com` with RP ID `orders.example.com`. Plan MySQL's global RP namespace before enrolling users. HTTP localhost/custom browser ports need implementation changes and separate compatibility validation; they are not enabled by installing the package.

## Install the package

Run in your new project directory, substituting your gateway checkout path:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '/path/to/mysql_browser_gateway[demo]'
```

The `demo` extra installs Flask. The base package installs the pinned connector and CBOR library. You can distribute a reviewed package wheel internally instead of using a local checkout.

Configure MySQL's plugin, account factors, RP ID, timeout, source-host matching, and grants as described in the [user manual](user-manual.md#prepare-the-server-and-account). Root provisioning is an administrative workflow; do not expose the demo root form as an ordinary end-user feature.

## Configure the bridge explicitly

```python
from mysql_fido_gateway import Gateway
from mysql_fido_gateway.broker import Broker

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
    origin="https://orders.example.com",
    rp_id="orders.example.com",
)
broker = Broker()
```

Do not put account passwords, root credentials, pools, or an initial database into `db_config`. The origin must be the browser's origin; it is not the DB connection hostname.

## Implement one worker per action

This example is an integration component, not a complete HTTP server. It assumes the `bridge` above and a Flow created for a validated browser session. Invoke it off the request thread and expose owner-checked polling/respond routes as in the reference app.

```python
import mysql.connector
from mysql_fido_gateway import BridgeError


def authentication_worker(flow, action, username, password):
    connection = None
    try:
        if action == "register":
            result = bridge.register(
                username,
                password,
                flow.ask,
                on_command=lambda sql: flow.events.put_nowait(
                    {"type": "command", "sql": sql}
                ),
            )
        elif action == "login":
            connection = bridge.connect(username, password, flow.ask)
            with connection.cursor() as cursor:
                cursor.execute("SELECT %s, CURRENT_USER()", ("hello world",))
                greeting, account = cursor.fetchone()
            result = {"message": greeting, "mysql_account": account}
        else:
            raise BridgeError("Unknown authentication action")
        flow.finish({"type": "success", "result": result})
    except BridgeError as error:
        flow.finish({"type": "error", "message": str(error)})
    except mysql.connector.Error as error:
        flow.finish({
            "type": "error",
            "message": f"MySQL operation failed (error {error.errno})",
        })
    except Exception:
        flow.finish({"type": "error", "message": "Authentication operation failed"})
    finally:
        if connection is not None:
            connection.close()
```

Start it after your route has validated Origin, CSRF, action, and submitted credentials:

```python
import threading


def begin_action(owner, action, username, password):
    # owner comes from your validated session, not from submitted JSON.
    flow = broker.create(owner)
    threading.Thread(
        target=authentication_worker,
        args=(flow, action, username, password),
        daemon=True,
    ).start()
    return {"flow_id": flow.id}  # Your route returns this with HTTP 202.
```

Do not call `begin_action()` for arbitrary unvalidated owner strings. In a real application, also bound thread creation and apply appropriate request/rate controls. This reference broker is for one process; independent workers do not share it.

## Connect the browser transport

Implement the [three HTTP endpoints](api-reference.md#http-endpoints) with these responsibilities:

1. Start an action using an owner from the current session and return its `flow_id`.
2. On every poll, call `broker.get(flow_id, current_owner)` before reading an event. Convert a one-second `queue.Empty` wait to `{"type": "waiting"}`.
3. On every response POST, check Origin/CSRF and owner, then call `flow.respond(reply['request_id'], reply)`.

The browser polls until `success`, `error`, or the deadline. For `webauthn` events, use the supplied encoding/serialization helpers:

```javascript
async function answerWebAuthn(flowId, event) {
  let reply;
  try {
    const credential = event.operation === 'create'
      ? await navigator.credentials.create({
          publicKey: creationOptions(event.publicKey)})
      : await navigator.credentials.get({
          publicKey: requestOptions(event.publicKey)});
    if (!credential) throw new Error('No credential returned');
    reply = {request_id: event.request_id, credential: serialize(credential)};
  } catch (error) {
    reply = {request_id: event.request_id, error: error.name + ': ' + error.message};
  }
  await jsonRequest(`/api/flows/${flowId}/respond`, reply);
}
```

This snippet depends on `creationOptions`, `requestOptions`, `serialize`, and your session/CSRF-aware `jsonRequest`. Do not copy the whole demo script without adapting its DOM selectors and form handlers. Do not add a YubiKey PIN field or change the browser's returned `clientDataJSON`.

Render worker events as text. Preserve the distinction between action acceptance, browser-response delivery, and actual database authentication success. Display only redacted SQL templates.

## Execute application SQL

Run application queries on the connection returned by `bridge.connect()`. Select a business schema only after authentication or use authorized fully qualified table names. Bind values as parameters, and validate any identifiers your app allows the user to choose.

Provision only the grants required by the app. A browser-session owner identifies the ceremony transport; the authenticated MySQL account and your business authorization determine what the user may do. Do not fall back to a shared database user after a failed challenge.

The demo closes the connection after one operation. If your application needs a longer session, define per-user server-side connection ownership, expiry, cleanup, and reauthentication explicitly. Do not place passwords or connection objects in Flask's signed client cookie.

## Validate before adding more screens

First validate a complete account-create/register/login/query path with the target MySQL server and a physical key. Confirm `CURRENT_USER()`, wrong-password rejection, wrong-key rejection, cancellation, expiry, replay rejection, and cross-user isolation. Check what happens if the app restarts during a ceremony.

Keep the [requirements and limitations](user-manual.md#requirements) in scope when choosing browser/key support, deployment topology, and operational controls.
