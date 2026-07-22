// Auth gate — runs before the app. Stores the JWT, gates the dashboard,
// and exposes apiFetch() (adds the token, handles 401) for app.js to use.
let authMode = 'login';

const _tok = {
  get: () => localStorage.getItem('token'),
  set: (t) => localStorage.setItem('token', t),
  clear: () => localStorage.removeItem('token'),
};

window.apiFetch = (path, opts = {}) => {
  const headers = { ...(opts.headers || {}), Authorization: `Bearer ${_tok.get()}` };
  return fetch(path, { ...opts, headers }).then(r => {
    if (r.status === 401) { _tok.clear(); showAuth(); throw new Error('unauthorized'); }
    return r;
  });
};
window.logout = () => { _tok.clear(); location.reload(); };

function showAuth() {
  document.getElementById('auth-screen').classList.remove('hidden');
  document.querySelector('.app').classList.add('hidden');
}

let _appLoaded = false;
function showApp() {
  document.getElementById('auth-screen').classList.add('hidden');
  document.querySelector('.app').classList.remove('hidden');
  if (!_appLoaded) {
    _appLoaded = true;
    const s = document.createElement('script');
    s.src = '/static/app.js?v=44';
    document.body.appendChild(s);
  }
}

function toggleAuthMode() {
  authMode = authMode === 'login' ? 'register' : 'login';
  document.getElementById('auth-title').textContent = authMode === 'login' ? 'Log in' : 'Create account';
  document.getElementById('auth-submit').textContent = authMode === 'login' ? 'Log in' : 'Sign up';
  document.getElementById('auth-switch').innerHTML = authMode === 'login'
    ? `New here? <a href="#" onclick="toggleAuthMode();return false">Create an account</a>`
    : `Have an account? <a href="#" onclick="toggleAuthMode();return false">Log in</a>`;
}

async function submitAuth() {
  const email = document.getElementById('auth-email').value.trim();
  const pw = document.getElementById('auth-pw').value;
  const err = document.getElementById('auth-err');
  err.textContent = '';
  if (!email || !pw) { err.textContent = 'Email and password required'; return; }
  try {
    let token;
    if (authMode === 'register') {
      const r = await fetch('/api/auth/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: pw }),
      });
      if (!r.ok) { err.textContent = (await r.json()).detail || 'Could not register'; return; }
      token = (await r.json()).access_token;
    } else {
      const r = await fetch('/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username: email, password: pw }),
      });
      if (!r.ok) { err.textContent = 'Wrong email or password'; return; }
      token = (await r.json()).access_token;
    }
    _tok.set(token);
    showApp();
  } catch { err.textContent = 'Network error'; }
}

// boot
if (_tok.get()) showApp(); else showAuth();
