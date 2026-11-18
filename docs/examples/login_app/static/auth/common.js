'use strict';
async function jsonRequest(url, body) {
  const options = {credentials: 'same-origin'};
  if (body !== undefined) {
    options.method = 'POST';
    options.headers = {'Content-Type': 'application/json',
      'X-CSRF-Token': document.querySelector('meta[name=csrf-token]').content};
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const data = await response.json();
  if (response.status === 401) window.location.assign('/login');
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
