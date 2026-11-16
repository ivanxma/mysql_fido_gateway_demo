"""Single-process, bounded browser ceremony transport. No credentials in cookies."""
import queue
import secrets
import threading
import time

from .codec import BridgeError


class Flow:
    def __init__(self, owner, ttl=150):
        self.owner = owner
        self.id = secrets.token_urlsafe(24)
        self.deadline = time.monotonic() + ttl
        self.events = queue.Queue(maxsize=8)
        self.replies = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.expected = None
        self.done = False

    def ask(self, operation, options):
        token = secrets.token_urlsafe(24)
        with self.lock:
            if self.done or self.expected:
                raise BridgeError('Invalid ceremony state')
            self.expected = token
        self.events.put_nowait({'type': 'webauthn', 'operation': operation,
                               'request_id': token, 'publicKey': options})
        try:
            reply = self.replies.get(timeout=max(0, self.deadline - time.monotonic()))
        except queue.Empty:
            raise BridgeError('Browser ceremony expired; start again') from None
        if 'error' in reply:
            raise BridgeError('Browser cancelled or could not complete WebAuthn: ' + str(reply['error'])[:120])
        credential = reply.get('credential')
        if not isinstance(credential, dict):
            raise BridgeError('Missing browser credential')
        return credential

    def respond(self, token, reply):
        with self.lock:
            if self.done or time.monotonic() > self.deadline:
                raise BridgeError('Expired ceremony')
            if not self.expected or not secrets.compare_digest(str(token).encode('utf-8'), self.expected.encode('ascii')):
                raise BridgeError('Wrong or replayed ceremony response')
            self.expected = None
            self.replies.put_nowait(reply)

    def finish(self, event):
        with self.lock:
            self.done = True
            self.expected = None
        self.events.put_nowait(event)


class Broker:
    def __init__(self, max_flows=32):
        self.flows = {}
        self.lock = threading.Lock()
        self.max_flows = max_flows

    def create(self, owner):
        with self.lock:
            now = time.monotonic()
            for key, value in list(self.flows.items()):
                if value.deadline < now:
                    del self.flows[key]
            if len(self.flows) >= self.max_flows:
                raise BridgeError('Gateway is busy. Retry after pending ceremonies expire.')
            if any(f.owner == owner and not f.done for f in self.flows.values()):
                raise BridgeError('Finish or wait for your existing ceremony to expire')
            flow = Flow(owner)
            self.flows[flow.id] = flow
            return flow

    def get(self, flow_id, owner):
        with self.lock:
            flow = self.flows.get(flow_id)
            if not flow or not secrets.compare_digest(flow.owner, owner):
                raise BridgeError('Unknown ceremony')
            if time.monotonic() > flow.deadline:
                raise BridgeError('Expired ceremony')
            return flow
