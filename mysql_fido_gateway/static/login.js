'use strict';
const form = document.querySelector('#login');
const status = document.querySelector('#status');

async function completeLogin(flowId) {
  const path = new URL(form.action).pathname + '/' + encodeURIComponent(flowId);
  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    const event = await jsonRequest(path);
    if (event.type === 'waiting') {
      await new Promise(resolve => setTimeout(resolve, 150));
    } else if (event.type === 'webauthn') {
      status.textContent = 'Follow the browser prompt and touch your YubiKey.';
      let reply;
      try {
        reply = {request_id: event.request_id, credential: await GatewayWebAuthn.credential(event, 'get')};
      } catch (error) {
        reply = {request_id: event.request_id, error: error.name};
      }
      await jsonRequest(path + '/respond', reply);
      status.textContent = 'MySQL is verifying your key…';
    } else if (event.type === 'success') {
      window.location.assign(event.redirect || '/main');
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
  status.className = 'activity';
  status.textContent = 'Connecting to MySQL…';
  try {
    if (!window.isSecureContext || !window.PublicKeyCredential) throw new Error('Open the configured trusted HTTPS origin with a WebAuthn browser.');
    const {flow_id} = await jsonRequest(form.action, body);
    body.password = '';
    await completeLogin(flow_id);
  } catch (error) {
    status.className = 'activity error';
    status.textContent = error.message;
  } finally {
    body.password = '';
    button.disabled = false;
  }
});
