/* Framework-free browser transport; no CDN and no PIN handling in application JS. */
'use strict';
const csrf = document.querySelector('meta[name=csrf-token]').content;
const operationMessage = document.querySelector('#operation-message');
const operationCommands = document.querySelector('#operation-commands');
let activeOperation = false;
function notify(message, state = '') {
  operationMessage.textContent = message;
  operationMessage.className = state;
}
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
function decode(value) {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(normalized + '='.repeat((4 - normalized.length % 4) % 4)), c => c.charCodeAt(0));
}
function encode(value) {
  return btoa(Array.from(new Uint8Array(value), n => String.fromCharCode(n)).join(''))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function creationOptions(json) {
  const options = structuredClone(json);
  options.challenge = decode(options.challenge);
  options.user.id = decode(options.user.id);
  if (options.excludeCredentials) options.excludeCredentials.forEach(c => c.id = decode(c.id));
  return options;
}
function requestOptions(json) {
  const options = structuredClone(json);
  options.challenge = decode(options.challenge);
  if (options.allowCredentials) options.allowCredentials.forEach(c => c.id = decode(c.id));
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
  const options = body === undefined ? {} : {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(body)};
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}
for (const form of document.querySelectorAll('form')) {
  form.addEventListener('invalid', event => {
    notify(`Complete the required field: ${event.target.labels?.[0]?.textContent.trim() || event.target.name}. No command was sent.`, 'error');
  }, true);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (activeOperation) {
      notify('An operation is already running. Wait for it to finish.', 'error');
      return;
    }
    activeOperation = true;
    const panel = form.closest('section');
    const status = panel.querySelector('.status');
    const proof = panel.querySelector('.proof');
    const button = form.querySelector('button');
    const payload = Object.fromEntries(new FormData(form));
    payload.action = form.dataset.action;
    payload.reset = form.elements.reset ? form.elements.reset.checked : false;
    if (proof) proof.textContent = '';
    status.className = 'status';
    status.textContent = 'Starting MySQL operation…';
    operationCommands.textContent = '';
    notify(`${form.querySelector('button').textContent.trim()}: connecting to MySQL…`);
    operationMessage.closest('.operation-notifications').scrollIntoView({behavior: 'smooth', block: 'start'});
    button.disabled = true;
    form.querySelectorAll('input[type=password]:not([name=admin_token])').forEach(input => input.value = '');
    try {
      if (['register', 'login'].includes(payload.action) && (!window.isSecureContext || !window.PublicKeyCredential)) {
        throw new Error('Open this page over trusted HTTPS in a browser supporting WebAuthn.');
      }
      const {flow_id} = await jsonRequest('/api/flows', payload);
      // Clear ordinary JS references after the request; secrets are never saved to browser storage.
      payload.password = payload.root_password = payload.admin_token = '';
      const deadline = Date.now() + 150000;
      let finished = false;
      while (Date.now() < deadline) {
        const message = await jsonRequest('/api/flows/' + flow_id);
        if (message.type === 'waiting') { await wait(150); continue; }
        if (message.type === 'command') {
          operationCommands.textContent += message.sql + ';\n';
          notify('Submitting command to MySQL…');
          continue;
        }
        if (message.type === 'webauthn') {
          status.textContent = 'Follow your browser’s security-key prompt. Insert and touch your YubiKey; enter its PIN there if asked.';
          notify(status.textContent);
          let reply;
          try {
            const credential = message.operation === 'create'
              ? await navigator.credentials.create({publicKey: creationOptions(message.publicKey)})
              : await navigator.credentials.get({publicKey: requestOptions(message.publicKey)});
            if (!credential) throw new Error('No credential returned');
            reply = {request_id: message.request_id, credential: serialize(credential)};
          } catch (error) {
            reply = {request_id: message.request_id, error: error.name + ': ' + error.message};
          }
          await jsonRequest('/api/flows/' + flow_id + '/respond', reply);
          status.textContent = 'Waiting for MySQL to verify the response…';
        } else if (message.type === 'success') {
          finished = true;
          status.className = 'status success';
          status.textContent = message.result.message || 'MySQL accepted the operation.';
          notify(status.textContent, 'success');
          if (proof) proof.textContent = JSON.stringify(message.result, null, 2);
          break;
        } else if (message.type === 'error') { throw new Error(message.message); }
      }
      if (!finished) throw new Error('Ceremony expired. Start again.');
    } catch (error) {
      status.className = 'status error';
      status.textContent = error.message;
      notify(error.message, 'error');
    } finally {
      payload.password = payload.root_password = payload.admin_token = '';
      activeOperation = false;
      button.disabled = false;
    }
  });
}
