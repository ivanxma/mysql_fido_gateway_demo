'use strict';
const csrf = document.querySelector('meta[name=csrf-token]').content;
const status = document.querySelector('#status');
const commands = document.querySelector('#commands');
const result = document.querySelector('#result');
const forms = [...document.querySelectorAll('form[data-action]')];
let busy = false;

function decode(value) {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(normalized + '='.repeat((4 - normalized.length % 4) % 4)), c => c.charCodeAt(0));
}

function encode(value) {
  return btoa(Array.from(new Uint8Array(value), n => String.fromCharCode(n)).join(''))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function optionsFor(operation, json) {
  const options = structuredClone(json);
  options.challenge = decode(options.challenge);
  if (operation === 'create') {
    options.user.id = decode(options.user.id);
    if (options.excludeCredentials) options.excludeCredentials.forEach(c => c.id = decode(c.id));
  } else if (options.allowCredentials) {
    options.allowCredentials.forEach(c => c.id = decode(c.id));
  }
  return options;
}

function serialize(credential) {
  const r = credential.response;
  const response = {clientDataJSON: encode(r.clientDataJSON)};
  if (r.attestationObject) {
    response.attestationObject = encode(r.attestationObject);
    response.transports = r.getTransports ? r.getTransports() : [];
  } else {
    response.authenticatorData = encode(r.authenticatorData);
    response.signature = encode(r.signature);
    response.userHandle = r.userHandle ? encode(r.userHandle) : null;
  }
  return {id: credential.id, rawId: encode(credential.rawId), type: credential.type,
    response, clientExtensionResults: credential.getClientExtensionResults()};
}

async function jsonRequest(url, body) {
  const options = {credentials: 'same-origin'};
  if (body !== undefined) {
    options.method = 'POST';
    options.headers = {'Content-Type': 'application/json', 'X-CSRF-Token': csrf};
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const data = await response.json().catch(() => { throw new Error(`HTTP ${response.status}: reload the configured HTTPS page`); });
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function completeFlow(flowId) {
  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    const event = await jsonRequest(`/api/flows/${flowId}`);
    if (event.type === 'waiting') {
      await new Promise(resolve => setTimeout(resolve, 150));
    } else if (event.type === 'command') {
      commands.textContent += event.sql + ';\n';
    } else if (event.type === 'webauthn') {
      status.textContent = 'Follow the browser prompt. Touch your key and enter its PIN there if requested.';
      let reply;
      try {
        const options = {publicKey: optionsFor(event.operation, event.publicKey)};
        const credential = event.operation === 'create'
          ? await navigator.credentials.create(options) : await navigator.credentials.get(options);
        if (!credential) throw new Error('No credential returned');
        reply = {request_id: event.request_id, credential: serialize(credential)};
      } catch (error) {
        reply = {request_id: event.request_id, error: error.name + ': ' + error.message};
      }
      await jsonRequest(`/api/flows/${flowId}/respond`, reply);
      status.textContent = 'Waiting for MySQL to verify the response…';
    } else if (event.type === 'success') {
      status.textContent = event.result.message || 'MySQL accepted the operation.';
      result.textContent = JSON.stringify(event.result, null, 2);
      return;
    } else if (event.type === 'error') {
      throw new Error(event.message);
    } else {
      throw new Error('Unexpected operation event');
    }
  }
  throw new Error('Operation expired. Start a new action.');
}

for (const form of forms) {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    forms.forEach(f => { f.querySelector('button').disabled = true; });
    const payload = Object.fromEntries(new FormData(form));
    payload.action = form.dataset.action;
    form.querySelector('input[type=password]').value = '';
    status.className = '';
    status.textContent = 'Connecting to MySQL…';
    commands.textContent = result.textContent = '';
    try {
      if (!window.isSecureContext || !window.PublicKeyCredential) {
        throw new Error('Open the configured trusted HTTPS origin in a browser supporting WebAuthn.');
      }
      const {flow_id} = await jsonRequest('/api/flows', payload);
      payload.password = '';
      await completeFlow(flow_id);
    } catch (error) {
      status.className = 'error';
      status.textContent = error.message;
    } finally {
      payload.password = '';
      busy = false;
      forms.forEach(f => { f.querySelector('button').disabled = false; });
    }
  });
}
