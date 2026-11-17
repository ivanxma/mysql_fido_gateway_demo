'use strict';
const form = document.querySelector('#login');
const status = document.querySelector('#status');

function decode(value) {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(normalized + '='.repeat((4 - normalized.length % 4) % 4)), c => c.charCodeAt(0));
}
function encode(value) {
  return btoa(Array.from(new Uint8Array(value), n => String.fromCharCode(n)).join(''))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
async function assertion(event) {
  if (event.operation !== 'get') throw new Error('Expected a login assertion');
  const publicKey = structuredClone(event.publicKey);
  publicKey.challenge = decode(publicKey.challenge);
  if (publicKey.allowCredentials) publicKey.allowCredentials.forEach(c => c.id = decode(c.id));
  const credential = await navigator.credentials.get({publicKey});
  if (!credential) throw new Error('No credential returned');
  const r = credential.response;
  return {id: credential.id, rawId: encode(credential.rawId), type: credential.type,
    response: {clientDataJSON: encode(r.clientDataJSON), authenticatorData: encode(r.authenticatorData),
      signature: encode(r.signature), userHandle: r.userHandle ? encode(r.userHandle) : null},
    clientExtensionResults: credential.getClientExtensionResults()};
}
async function completeLogin(flowId) {
  const path = `/api/login/${flowId}`;
  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    const event = await jsonRequest(path);
    if (event.type === 'waiting') {
      await new Promise(resolve => setTimeout(resolve, 150));
    } else if (event.type === 'webauthn') {
      status.textContent = 'Follow the browser prompt and touch your YubiKey.';
      let reply;
      try {
        reply = {request_id: event.request_id, credential: await assertion(event)};
      } catch (error) {
        reply = {request_id: event.request_id, error: error.name};
      }
      await jsonRequest(path + '/respond', reply);
      status.textContent = 'MySQL is verifying your key…';
    } else if (event.type === 'success') {
      window.location.assign('/main');
      return;
    } else {
      throw new Error(event.message || 'Login failed');
    }
  }
  throw new Error('Login expired. Try again.');
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button');
  if (button.disabled) return;
  button.disabled = true;
  const body = Object.fromEntries(new FormData(form));
  form.querySelector('[name=password]').value = '';
  status.textContent = 'Connecting to MySQL…';
  try {
    if (!window.isSecureContext || !window.PublicKeyCredential) throw new Error('Open the configured trusted HTTPS origin with a WebAuthn browser.');
    const {flow_id} = await jsonRequest('/api/login', body);
    body.password = '';
    await completeLogin(flow_id);
  } catch (error) {
    status.textContent = error.message;
  } finally {
    body.password = '';
    button.disabled = false;
  }
});
