const API = '/api';

function saveTokens(access, refresh) {
  localStorage.setItem('access_token', access);
  localStorage.setItem('refresh_token', refresh);
}

function showError(msg) {
  const el = document.getElementById('error-msg');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideError() {
  document.getElementById('error-msg').classList.add('hidden');
}

function setLoading(btn, loading) {
  btn.disabled = loading;
  btn.textContent = loading ? 'Please wait...' : btn.dataset.label;
}

if (localStorage.getItem('access_token')) {
  window.location.href = '/chat/';
}

document.getElementById('login-btn').dataset.label = 'Sign in';
document.getElementById('register-btn').dataset.label = 'Create account';

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideError();
  const btn = document.getElementById('login-btn');
  setLoading(btn, true);

  const resp = await fetch(`${API}/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: document.getElementById('email').value,
      password: document.getElementById('password').value,
    }),
  });

  setLoading(btn, false);
  const data = await resp.json();

  if (!resp.ok) {
    showError(data.message || 'Invalid credentials.');
    return;
  }

  saveTokens(data.data.tokens.access, data.data.tokens.refresh);
  window.location.href = '/chat/';
});

document.getElementById('show-register').addEventListener('click', (e) => {
  e.preventDefault();
  hideError();
  document.getElementById('login-form').classList.add('hidden');
  document.querySelector('.register-link').classList.add('hidden');
  document.getElementById('register-form').classList.remove('hidden');
});

document.getElementById('back-to-login').addEventListener('click', () => {
  hideError();
  document.getElementById('register-form').classList.add('hidden');
  document.querySelector('.register-link').classList.remove('hidden');
  document.getElementById('login-form').classList.remove('hidden');
});

document.getElementById('register-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideError();
  const password = document.getElementById('reg-password').value;
  const confirm = document.getElementById('reg-confirm').value;

  if (password !== confirm) {
    showError('Passwords do not match.');
    return;
  }

  const btn = document.getElementById('register-btn');
  setLoading(btn, true);

  const resp = await fetch(`${API}/auth/register/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: document.getElementById('reg-email').value,
      password,
      password_confirm: confirm,
    }),
  });

  setLoading(btn, false);
  const data = await resp.json();

  if (!resp.ok) {
    const errors = data.data || {};
    const msg = Object.values(errors).flat().join(' ') || data.message || 'Registration failed.';
    showError(msg);
    return;
  }

  saveTokens(data.data.tokens.access, data.data.tokens.refresh);
  window.location.href = '/chat/';
});
