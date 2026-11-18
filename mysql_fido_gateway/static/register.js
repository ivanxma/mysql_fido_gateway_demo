'use strict';
const form = document.querySelector('#register');
const status = document.querySelector('#status');
let registered = false;
async function completeRegistration(flowId) {
  const path = new URL(form.action).pathname + '/' + encodeURIComponent(flowId);
  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    const event = await jsonRequest(path);
    if (event.type === 'waiting') {
      await new Promise(resolve => setTimeout(resolve, 150));
    } else if (event.type === 'webauthn') {
      status.textContent = 'Follow your browser’s security-key prompt. Enter the key PIN there, then touch your key.';
      let reply;
      try {
        reply = {request_id: event.request_id, credential: await GatewayWebAuthn.credential(event, 'create')};
      } catch (error) {
        reply = {request_id: event.request_id, error: error.name};
      }
      await jsonRequest(path + '/respond', reply);
      status.textContent = 'Verifying your new passkey…';
    } else if (event.type === 'success' && event.result?.registered === true) {
      registered = true;
      status.className = 'activity success';
      status.textContent = event.result.message;
      form.hidden = true;
      document.querySelector('#registration-complete').hidden = false;
      document.querySelector('#registration-complete a').focus();
      return;
    } else {
      throw new Error(event.message || 'Registration could not be completed.');
    }
  }
  throw new Error('Registration expired. Please try again.');
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button');
  if (button.disabled || registered) return;
  button.disabled = true;
  const body = Object.fromEntries(new FormData(form));
  form.querySelector('[name=password]').value = '';
  status.className = 'activity';
  status.textContent = 'Connecting to your account…';
  try {
    if (!window.isSecureContext || !window.PublicKeyCredential) throw new Error('Open this application over trusted HTTPS in a browser supporting WebAuthn.');
    const {flow_id} = await jsonRequest(form.action, body);
    body.password = '';
    await completeRegistration(flow_id);
  } catch (error) {
    status.className = 'activity error';
    status.textContent = error.message;
  } finally {
    body.password = '';
    button.disabled = false;
  }
});
