'use strict';
const status = document.querySelector('#status');
const hello = document.querySelector('#hello');
hello.addEventListener('click', async () => {
  hello.disabled = true;
  status.textContent = 'Querying MySQL…';
  try {
    const result = await jsonRequest('/api/hello', {});
    document.querySelector('#result').textContent = JSON.stringify(result, null, 2);
    status.textContent = result.message;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    hello.disabled = false;
  }
});
document.querySelector('#logout').addEventListener('click', async event => {
  event.target.disabled = true;
  try {
    await jsonRequest('/api/logout', {});
    window.location.assign('/login');
  } catch (error) {
    status.textContent = error.message;
    event.target.disabled = false;
  }
});
