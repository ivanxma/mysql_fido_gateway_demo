'use strict';
globalThis.GatewayWebAuthn = (() => {
  function decode(value) {
    const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
    return Uint8Array.from(atob(normalized + '='.repeat((4 - normalized.length % 4) % 4)), c => c.charCodeAt(0));
  }
  function encode(value) {
    return btoa(Array.from(new Uint8Array(value), n => String.fromCharCode(n)).join(''))
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  async function credential(event, expectedOperation) {
    if (event.operation !== expectedOperation) throw new Error('Unexpected security-key operation');
    const publicKey = structuredClone(event.publicKey);
    publicKey.challenge = decode(publicKey.challenge);
    if (publicKey.user) publicKey.user.id = decode(publicKey.user.id);
    for (const name of ['allowCredentials', 'excludeCredentials']) {
      if (publicKey[name]) publicKey[name].forEach(c => c.id = decode(c.id));
    }
    const key = event.operation === 'create'
      ? await navigator.credentials.create({publicKey})
      : await navigator.credentials.get({publicKey});
    if (!key) throw new Error('No credential returned');
    const r = key.response;
    const response = {clientDataJSON: encode(r.clientDataJSON)};
    if (event.operation === 'create') {
      response.attestationObject = encode(r.attestationObject);
      response.transports = r.getTransports ? r.getTransports() : [];
    } else {
      response.authenticatorData = encode(r.authenticatorData);
      response.signature = encode(r.signature);
      response.userHandle = r.userHandle ? encode(r.userHandle) : null;
    }
    return {id: key.id, rawId: encode(key.rawId), type: key.type, response,
      clientExtensionResults: key.getClientExtensionResults()};
  }
  return Object.freeze({credential});
})();
