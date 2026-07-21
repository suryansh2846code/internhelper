// ── State ─────────────────────────────────────────────────────────────────────
let currentJobId = null;
let pollTimer    = null;
let activeFilter = 'all';   // role filter for results
let authPollTimer = null;

// ── Internshala login ─────────────────────────────────────────────────────────
async function relogin() {
  const btn = document.getElementById('relogin-btn');
  const el  = document.getElementById('auth-status');
  btn.disabled = true;
  el.textContent = 'Opening browser…';
  el.style.color = 'var(--muted)';
  try {
    await fetch('/api/relogin', { method: 'POST' });
  } catch {
    el.textContent = '✗ Could not start login';
    el.style.color = 'var(--red)';
    btn.disabled = false;
    return;
  }
  el.textContent = 'Solve the CAPTCHA in the browser window…';
  if (authPollTimer) clearInterval(authPollTimer);
  authPollTimer = setInterval(pollAuth, 2000);
}

async function pollAuth() {
  let s;
  try { s = await (await fetch('/api/auth/status')).json(); }
  catch { return; }
  const btn = document.getElementById('relogin-btn');
  const el  = document.getElementById('auth-status');

  if (s.status === 'logging_in') return;
  clearInterval(authPollTimer);
  btn.disabled = false;

  if (s.status === 'ready') {
    el.textContent = '✓ Logged in';
    el.style.color = 'var(--green)';
  } else if (s.status === 'error') {
    el.textContent = '✗ Login failed (timed out?) — try again';
    el.style.color = 'var(--red)';
  }
}

// ── Browser window control ──────────────────────────────────────────────────
async function closeBrowser() {
  const btn = document.getElementById('stop-browser-btn');
  btn.disabled = true;
  btn.textContent = 'Closing…';
  try { await fetch('/api/browser/close', { method: 'POST' }); } catch {}
  // The window closes once any in-flight task finishes; poll reflects it.
  setTimeout(pollBrowser, 500);
}

async function pollBrowser() {
  let running = false;
  try { running = (await (await fetch('/api/browser/status')).json()).running; }
  catch { return; }
  const btn  = document.getElementById('stop-browser-btn');
  const dot  = document.getElementById('statusbar-dot');
  const info = document.getElementById('statusbar-info');
  if (btn) { btn.style.display = running ? '' : 'none'; btn.disabled = false; btn.textContent = '✕ Close browser window'; }
  if (dot) dot.classList.toggle('live', running);
  if (info) info.textContent = running ? 'Automation browser active' : 'Ready';
}
setInterval(pollBrowser, 3000);
pollBrowser();

// ── Sidebar nav active state ────────────────────────────────────────────────
document.querySelectorAll('.nav-item[data-nav]').forEach(a => {
  a.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    a.classList.add('active');
  });
});

// ── Applications manager ──────────────────────────────────────────────────────
let demoMode = false;
const APP_STATUSES = ['applied', 'under review', 'interview', 'offer', 'rejected'];
const DEMO_APPLIED = [
  { url: "#a", title: "Full Stack Development Internship", company: "Codemax Digital", role: "fullstack", stipend: "₹15,000 - ₹25,000/month", platform: "unstop", status: "interview", applied_at: "2026-07-18T10:00:00+00:00" },
  { url: "#b", title: "Backend Development Internship", company: "NayePankh Foundation", role: "backend", stipend: "Unpaid", platform: "internshala", status: "applied", applied_at: "2026-07-19T09:00:00+00:00" },
  { url: "#c", title: "MERN Stack Developer Internship", company: "SwiftBL", role: "fullstack", stipend: "₹5,000 - ₹15,000/month", platform: "unstop", status: "under review", applied_at: "2026-07-20T14:00:00+00:00" },
  { url: "#d", title: "Web Development Internship", company: "Nexora", role: "frontend", stipend: "₹10,000/month", platform: "unstop", status: "offer", applied_at: "2026-07-15T11:00:00+00:00" },
  { url: "#e", title: "Data Analyst Internship", company: "Acme Corp", role: "data", stipend: "₹12,000/month", platform: "internshala", status: "rejected", applied_at: "2026-07-14T08:00:00+00:00" },
];
const _slug = s => (s || '').replace(/\s+/g, '-');

async function fetchApplied() {
  if (demoMode) return DEMO_APPLIED;
  try { return await (await fetch('/api/applied')).json(); } catch { return []; }
}

async function refreshAppliedCount() {
  const items = await fetchApplied();
  document.getElementById('applied-btn').textContent = `Applications (${items.length})`;
  return items;
}

async function toggleApplied() {
  const panel = document.getElementById('applied-panel');
  if (!panel.classList.contains('hidden')) { panel.classList.add('hidden'); return; }
  renderApplied(await refreshAppliedCount());
  panel.classList.remove('hidden');
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderApplied(items) {
  const list = document.getElementById('applied-list');
  if (!items.length) {
    list.innerHTML = `<p class="step-hint">No applications yet — every listing you auto-apply to lands here to track.</p>`;
    return;
  }
  const counts = {};
  items.forEach(it => { const s = it.status || 'applied'; counts[s] = (counts[s] || 0) + 1; });
  const summary = `<div class="app-summary">
    <span class="app-stat"><b>${items.length}</b> total</span>
    ${APP_STATUSES.filter(s => counts[s]).map(s => `<span class="app-stat st-${_slug(s)}">${counts[s]} ${s}</span>`).join('')}
  </div>`;

  const rows = items.map(it => {
    const st = it.status || 'applied';
    const esc = it.url.replace(/'/g, "\\'");
    const plat = it.platform ? `<span class="platform-tag platform-${it.platform}">${platformLabel(it)}</span>` : '';
    const role = it.role ? `<span class="role-tag">${it.role}</span>` : '';
    const opts = APP_STATUSES.map(s => `<option value="${s}" ${s === st ? 'selected' : ''}>${s}</option>`).join('');
    return `
      <div class="applied-row">
        <div class="applied-meta">
          <span class="applied-title">${plat}${role}<a href="${it.url}" target="_blank" rel="noopener">${it.title || 'Listing'} ↗</a></span>
          <span class="listing-sub">${it.company || ''}${it.stipend ? ` · ${it.stipend}` : ''} · applied ${(it.applied_at || '').slice(0, 10)}</span>
        </div>
        <div class="applied-actions">
          <select class="status-select st-${_slug(st)}" onchange="setAppliedStatus('${esc}', this.value)">${opts}</select>
          <button class="btn-sm btn-skip" onclick="removeApplied('${esc}')">Remove</button>
        </div>
      </div>`;
  }).join('');
  list.innerHTML = summary + rows;
}

async function setAppliedStatus(url, status) {
  if (demoMode) {
    const it = DEMO_APPLIED.find(x => x.url === url);
    if (it) it.status = status;
    renderApplied(DEMO_APPLIED);
    return;
  }
  await fetch('/api/applied/status', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, status }),
  });
  renderApplied(await refreshAppliedCount());
}

async function removeApplied(url) {
  if (demoMode) {
    const i = DEMO_APPLIED.findIndex(x => x.url === url);
    if (i >= 0) DEMO_APPLIED.splice(i, 1);
    renderApplied(await refreshAppliedCount());
    return;
  }
  await fetch('/api/applied/remove', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  renderApplied(await refreshAppliedCount());
}

async function clearApplied() {
  if (!confirm('Clear the entire applications list? Listings will become applyable again.')) return;
  if (demoMode) { DEMO_APPLIED.length = 0; renderApplied(await refreshAppliedCount()); return; }
  await fetch('/api/applied', { method: 'DELETE' });
  renderApplied(await refreshAppliedCount());
}

async function syncApplications() {
  const btn = document.getElementById('sync-btn');
  if (demoMode) { alert('Sync pulls live statuses from the platforms — try it outside demo mode.'); return; }
  btn.disabled = true;
  btn.textContent = '⏳ Syncing… (a browser window opens)';
  try { await fetch('/api/applied/sync', { method: 'POST' }); } catch {}
  const t = setInterval(async () => {
    let s;
    try { s = await (await fetch('/api/applied/sync-status')).json(); } catch { return; }
    if (s.running) return;
    clearInterval(t);
    btn.disabled = false;
    btn.textContent = '🔄 Sync status';
    if (s.error) { btn.textContent = '⚠ Sync failed — re-login?'; }
    renderApplied(await refreshAppliedCount());
  }, 1500);
}

refreshAppliedCount();

// Reflect whether a session file already exists on page load
(async () => {
  try {
    const s = await (await fetch('/api/auth/status')).json();
    const el = document.getElementById('auth-status');
    if (s.status === 'logging_in') {
      el.textContent = 'Solve the CAPTCHA in the browser window…';
      document.getElementById('relogin-btn').disabled = true;
      authPollTimer = setInterval(pollAuth, 2000);
    } else if (s.has_session) {
      el.textContent = 'Session saved';
      el.style.color = 'var(--muted)';
    } else {
      el.textContent = 'Not logged in';
      el.style.color = 'var(--yellow)';
    }
  } catch {}
})();

// ── Resume upload ─────────────────────────────────────────────────────────────
document.getElementById('resume-file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const role = document.getElementById('role-input').value.trim().toLowerCase();
  if (!role) {
    setUploadStatus('Enter a role label first', 'error');
    e.target.value = '';
    return;
  }

  setUploadStatus('Uploading…', 'info');

  const fd = new FormData();
  fd.append('role', role);
  fd.append('file', file);
  const res  = await fetch('/api/resumes', { method: 'POST', body: fd });
  const data = await res.json();

  if (data.ok) {
    setUploadStatus(`✓ ${file.name} uploaded — extracting keywords…`, 'ok');
    document.getElementById('role-input').value = '';
    e.target.value = '';
    pollResumes();
  } else {
    setUploadStatus('✗ Upload failed', 'error');
  }
});

function setUploadStatus(msg, type) {
  const el = document.getElementById('upload-status');
  el.textContent = msg;
  el.style.color = type === 'error' ? 'var(--red)' : type === 'ok' ? 'var(--green)' : 'var(--muted)';
}

// Poll resumes until all keyword extractions are done
let resumePollTimer = null;
function pollResumes() {
  if (resumePollTimer) return;
  resumePollTimer = setInterval(async () => {
    const res  = await fetch('/api/resumes');
    const data = await res.json();
    renderResumeCards(data);
    const allDone = Object.values(data).every(r => r.keyword_status !== 'extracting');
    if (allDone) { clearInterval(resumePollTimer); resumePollTimer = null; }
  }, 1500);
}

function renderResumeCards(resumes) {
  const container = document.getElementById('resume-cards');
  container.innerHTML = '';
  for (const [role, data] of Object.entries(resumes)) {
    container.appendChild(buildResumeCard(role, data));
  }
}

function buildResumeCard(role, data) {
  const card = document.createElement('div');
  card.className = 'resume-card';
  card.id = `rcard-${role}`;

  let kwHtml = '';
  if (data.keyword_status === 'extracting') {
    kwHtml = `<span class="kw-extracting"><span class="spinner"></span>Extracting keywords…</span>`;
  } else if (data.keyword_status === 'error') {
    const errMsg = _friendlyError(data.error || '');
    kwHtml = `
      <div style="margin-bottom:8px">
        <span style="color:var(--red);font-size:12px">✗ ${errMsg}</span>
        <button class="btn-sm btn-generate" style="margin-left:8px;font-size:11px;padding:3px 10px"
          onclick="retryExtract('${role}')">Retry</button>
      </div>
      <p style="color:var(--muted);font-size:12px;margin-bottom:6px">
        Will search using <strong style="color:var(--text)">"${role}"</strong> as keyword — or add your own:
      </p>
      <div class="keyword-area" id="kw-${role}">
        <input class="chip-input" placeholder="+ add keyword" id="kwinput-${role}"
          onkeydown="addKeyword(event,'${role}')" />
      </div>`;
  } else {
    const chips = (data.keywords || []).map((kw, i) =>
      `<span class="chip">${kw}<button class="chip-remove" onclick="removeKeyword('${role}',${i})">×</button></span>`
    ).join('');
    kwHtml = `
      <div class="keyword-area" id="kw-${role}">
        ${chips}
        <input class="chip-input" placeholder="+ add" id="kwinput-${role}"
          onkeydown="addKeyword(event,'${role}')" />
      </div>`;
  }

  card.innerHTML = `
    <div class="resume-card-header">
      <div>
        <span class="resume-role">${role}</span>
        <span class="resume-filename"> · ${data.filename || ''}</span>
      </div>
      <button class="btn-delete" onclick="deleteResume('${role}')" title="Remove">✕</button>
    </div>
    ${kwHtml}
  `;
  return card;
}

async function removeKeyword(role, index) {
  const res  = await fetch('/api/resumes');
  const data = await res.json();
  const kws  = [...(data[role]?.keywords || [])];
  kws.splice(index, 1);
  await fetch(`/api/resumes/${role}/keywords`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keywords: kws }),
  });
  renderResumeCards({ ...data, [role]: { ...data[role], keywords: kws } });
}

async function addKeyword(e, role) {
  if (e.key !== 'Enter') return;
  const input = document.getElementById(`kwinput-${role}`);
  const kw    = input.value.trim().toLowerCase();
  if (!kw) return;
  const res  = await fetch('/api/resumes');
  const data = await res.json();
  const kws  = [...(data[role]?.keywords || []), kw];
  await fetch(`/api/resumes/${role}/keywords`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keywords: kws }),
  });
  renderResumeCards({ ...data, [role]: { ...data[role], keywords: kws } });
}

async function deleteResume(role) {
  await fetch(`/api/resumes/${role}`, { method: 'DELETE' });
  const res  = await fetch('/api/resumes');
  renderResumeCards(await res.json());
}

// Load existing resumes + platforms on page load
window.addEventListener('load', async () => {
  const res  = await fetch('/api/resumes');
  const data = await res.json();
  renderResumeCards(data);
  const anyExtracting = Object.values(data).some(r => r.keyword_status === 'extracting');
  if (anyExtracting) pollResumes();
  loadPlatforms();
});

async function loadPlatforms() {
  try {
    const platforms = await (await fetch('/api/platforms')).json();
    // Platform toggles — search several at once; all on by default.
    const toggles = document.getElementById('platform-toggles');
    if (toggles) toggles.innerHTML = platforms.map(p => `
      <label class="platform-toggle">
        <input type="checkbox" value="${p.name}" checked>
        ${p.label}${p.supports_auto_apply ? '' : ' (search only)'}
      </label>`).join('');
    // A "Log into X" button for each platform with a manual login (not Internshala)
    const box = document.getElementById('platform-logins');
    if (box) box.innerHTML = platforms
      .filter(p => p.login_url && p.name !== 'internshala')
      .map(p => `<button class="btn-relogin" onclick="loginPlatform('${p.name}','${p.label}')">Log into ${p.label}</button>`)
      .join('');
  } catch {}
}

function selectedPlatforms() {
  return [...document.querySelectorAll('#platform-toggles input:checked')].map(c => c.value);
}

async function loginPlatform(name, label) {
  const el = document.getElementById('auth-status');
  el.textContent = `Opening ${label} login…`;
  el.style.color = 'var(--muted)';
  try { await fetch(`/api/login/${name}`, { method: 'POST' }); } catch {}
  el.textContent = `Log into ${label} in the browser window…`;
  if (authPollTimer) clearInterval(authPollTimer);
  authPollTimer = setInterval(pollAuth, 2000);
}

// ── Search ────────────────────────────────────────────────────────────────────
async function startSearch() {
  const btn      = document.getElementById('search-btn');
  const statusEl = document.getElementById('search-status');
  btn.disabled   = true;
  statusEl.innerHTML = '<span class="spinner"></span>Logging in & searching all roles…';
  stopPolling();

  const platforms = selectedPlatforms();
  if (!platforms.length) { statusEl.textContent = 'Select at least one platform.'; btn.disabled = false; return; }
  const body = {
    location:     document.getElementById('location').value.trim(),
    stipend_min:  parseInt(document.getElementById('stipend').value) || 0,
    max_per_role: parseInt(document.getElementById('max').value) || 10,
    platforms,
  };

  const res  = await fetch('/api/search/multi', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (data.error) { statusEl.textContent = `Error: ${data.error}`; btn.disabled = false; return; }
  currentJobId = data.job_id;
  pollTimer    = setInterval(() => pollJob(statusEl, btn), 2000);
}

async function pollJob(statusEl, btn) {
  if (!currentJobId) return;
  const res = await fetch(`/api/job/${currentJobId}`);
  const job = await res.json();

  if (job.status === 'searching') {
    statusEl.innerHTML = '<span class="spinner"></span>Scraping Internshala across all roles…';
    return;
  }
  if (job.status === 'error') {
    stopPolling();
    statusEl.textContent = `Error: ${job.error}`;
    btn.disabled = false;
    return;
  }
  if (job.status === 'ready') {
    stopPolling();
    statusEl.textContent = '';
    btn.disabled = false;
    renderListings(job.listings);
  }
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

// ── Bright colour palette (every card/button gets its own bold colour) ────────
const BRIGHT = ['#ffd23f', '#ff8a3d', '#ff6b9d', '#34d399', '#7c5cff',
                '#3b9dff', '#a3e635', '#22d3ee', '#ff5c5c', '#c084fc'];
function brightColor(i) { return BRIGHT[((i % BRIGHT.length) + BRIGHT.length) % BRIGHT.length]; }

// ── Demo cards (visual testing without running a search) ─────────────────────
const DEMO_LISTINGS = [
  { title: "Full Stack Development Internship", company: "Codemax Digital", url: "#", stipend: "₹15,000 - ₹25,000/month", platform: "unstop", matched_role: "fullstack", status: "auto", logo: "" },
  { title: "Backend Development Internship", company: "NayePankh Foundation", url: "#", stipend: "Unpaid", platform: "internshala", matched_role: "backend", status: "auto", logo: "" },
  { title: "Frontend Developer (React) Internship", company: "Nexora", url: "#", stipend: "₹10,000/month", platform: "unstop", matched_role: "frontend", status: "link", reason: "2 custom question(s) — apply manually", logo: "" },
  { title: "Web Development Internship", company: "Intern Crowd", url: "#", stipend: "Not disclosed", platform: "unstop", matched_role: "fullstack", status: "submitted", logo: "" },
  { title: "Product Management Internship", company: "BrightLabs", url: "#", stipend: "₹20,000/month", platform: "internshala", matched_role: "product", status: "link", reason: "Complete your Internshala profile to apply", logo: "" },
  { title: "MERN Stack Developer Internship", company: "SwiftBL", url: "#", stipend: "₹5,000 - ₹15,000/month", platform: "unstop", matched_role: "fullstack", status: "auto", logo: "" },
  { title: "Data Analyst Internship", company: "Acme Corp", url: "#", stipend: "₹12,000/month", platform: "internshala", matched_role: "data", status: "error", error: "Auto-apply failed", logo: "" },
  { title: "UI/UX Design Internship", company: "Pixel Studio", url: "#", stipend: "₹8,000/month", platform: "unstop", matched_role: "design", status: "auto", logo: "" },
];
const DEMO_RESUMES = {
  fullstack: { filename: "Suryansh_Fullstack.docx", keyword_status: "ready",
    keywords: ["full stack development", "react", "node.js", "python", "web development", "backend development"] },
  frontend: { filename: "Suryansh_Frontend.docx", keyword_status: "ready",
    keywords: ["react", "javascript", "typescript", "next.js", "ux design"] },
  backend: { filename: "Suryansh_Backend.docx", keyword_status: "ready",
    keywords: ["python", "node.js", "fastapi", "postgresql", "docker"] },
  "product management": { filename: "Suryansh_PM.docx", keyword_status: "ready",
    keywords: ["product management", "roadmapping", "user research", "analytics", "agile"] },
  "data science": { filename: "Suryansh_Data.docx", keyword_status: "ready",
    keywords: ["python", "pandas", "machine learning", "sql", "data visualization"] },
  design: { filename: "Suryansh_Design.docx", keyword_status: "ready",
    keywords: ["figma", "ui design", "ux design", "prototyping", "design systems"] },
};
function loadDemo() {
  demoMode = true;
  currentJobId = 'demo';
  activeFilter = 'all';
  renderResumeCards(DEMO_RESUMES);
  renderListings(DEMO_LISTINGS);
  refreshAppliedCount();
  document.getElementById('results-panel').scrollIntoView({ behavior: 'smooth' });
}

// ── Render listings ───────────────────────────────────────────────────────────
function renderListings(listings) {
  const panel = document.getElementById('results-panel');
  const grid  = document.getElementById('listings-grid');
  panel.classList.remove('hidden');

  // Build role filter pills
  const roles = ['all', ...new Set(listings.map(l => l.matched_role).filter(Boolean))];
  document.getElementById('role-filters').innerHTML = roles.map(r =>
    `<button class="role-pill ${r === activeFilter ? 'active' : ''}"
       onclick="setFilter('${r}', ${JSON.stringify(listings).replace(/"/g, '&quot;')})">${r}</button>`
  ).join('');

  const filtered = activeFilter === 'all' ? listings : listings.filter(l => l.matched_role === activeFilter);
  document.getElementById('results-title').textContent =
    `${filtered.length} listing${filtered.length !== 1 ? 's' : ''}${activeFilter !== 'all' ? ` · ${activeFilter}` : ''}`;

  grid.innerHTML = '';
  filtered.forEach((l, i) => {
    const realIndex = listings.indexOf(l);
    const card = document.createElement('div');
    card.className = 'listing-card';
    card.id = `listing-${realIndex}`;
    card.style.backgroundColor = brightColor(realIndex);
    card.innerHTML = listingHTML(l, realIndex);
    grid.appendChild(card);
  });

  // Bulk-apply bar for no-question ('auto') listings in the current view
  const autoIndices = filtered.filter(l => l.status === 'auto').map(l => listings.indexOf(l));
  renderBulkBar(autoIndices);
}

// ── Bulk apply ────────────────────────────────────────────────────────────────
let selected = new Set();

function renderBulkBar(autoIndices) {
  const bar = document.getElementById('bulk-bar');
  // Drop selections that are no longer auto-eligible (e.g. already applied)
  selected = new Set([...selected].filter(i => autoIndices.includes(i)));
  if (!autoIndices.length) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = '';
  const cAll = brightColor(2), cSel = brightColor(7);
  bar.innerHTML = `
    <button class="btn-sm pop-btn" style="--pop:${cAll}" onclick='applyBatch(${JSON.stringify(autoIndices)})'>
      ⚡ Apply to all ${autoIndices.length} no-question listing${autoIndices.length !== 1 ? 's' : ''}
    </button>
    <button id="apply-selected-btn" class="btn-sm pop-btn" style="--pop:${cSel}" onclick="applyBatch([...selected])" ${selected.size ? '' : 'disabled'}>
      Apply to selected (${selected.size})
    </button>
    <span id="bulk-progress" class="bulk-progress"></span>`;
}

function toggleSelect(index, checked) {
  if (checked) selected.add(index); else selected.delete(index);
  const btn = document.getElementById('apply-selected-btn');
  if (btn) {
    btn.textContent = `Apply to selected (${selected.size})`;
    btn.disabled = selected.size === 0;
  }
}

async function applyBatch(indices) {
  if (!indices.length) return;
  if (!confirm(`Auto-apply to ${indices.length} internship${indices.length !== 1 ? 's' : ''}? Each is submitted one at a time (with a short pause between) to avoid getting your account flagged.`)) return;
  document.querySelectorAll('#bulk-bar button').forEach(b => b.disabled = true);
  indices.forEach(i => patchListingStatus(i, 'submitting'));
  await fetch('/api/submit-batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: currentJobId, listing_indices: indices }),
  });
  const t = setInterval(async () => {
    const j = await (await fetch(`/api/job/${currentJobId}`)).json();
    const prog = document.getElementById('bulk-progress');
    if (prog && j.batch) {
      const b = j.batch;
      prog.textContent = b.running
        ? `Applying ${b.done}/${b.total} · ✓${b.applied}${b.failed ? ` ✗${b.failed}` : ''}`
        : `Done · ✓${b.applied} applied${b.failed ? ` · ✗${b.failed} failed` : ''}`;
    }
    let pending = false;
    indices.forEach(i => {
      refreshListing(i, j.listings[i], j.listings);
      if (j.listings[i].status === 'submitting') pending = true;
    });
    if (!pending && !(j.batch && j.batch.running)) {
      clearInterval(t);
      selected.clear();
      refreshAppliedCount();
      setTimeout(() => renderListings(j.listings), 2500);  // let the summary linger
    }
  }, 1500);
}

function setFilter(role, listings) {
  activeFilter = role;
  renderListings(listings);
}

function platformLabel(l) {
  const n = l.platform || 'internshala';
  return n.charAt(0).toUpperCase() + n.slice(1);
}

function listingHTML(l, i) {
  const roleTag = l.matched_role ? `<span class="role-tag">${l.matched_role}</span>` : '';
  const platTag = l.platform ? `<span class="platform-tag">${platformLabel(l)}</span>` : '';
  const logo = l.logo
    ? `<img class="tile-logo" src="${l.logo}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'tile-logo tile-logo-fallback',textContent:'${(l.company || '?').charAt(0)}'}))">`
    : `<span class="tile-logo tile-logo-fallback">${(l.company || '?').charAt(0)}</span>`;
  const link = `<a href="${l.url}" target="_blank" rel="noopener"
      class="btn-sm tile-btn" style="text-decoration:none">Apply on ${platformLabel(l)} ↗</a>`;

  let actions, note = '';
  switch (l.status) {
    case 'auto':
      actions = `
        <label class="tile-check"><input type="checkbox" onchange="toggleSelect(${i}, this.checked)" ${selected.has(i) ? 'checked' : ''}> Select</label>
        <button class="btn-sm tile-btn" onclick="directApply(${i})">⚡ Auto-apply</button>`;
      break;
    case 'submitting': actions = `<span class="tile-status"><span class="spinner"></span> Applying…</span>`; break;
    case 'submitted':  actions = `<span class="tile-status">✓ Applied</span>`; break;
    case 'skipped':    actions = `<span class="tile-status">Skipped</span>`; break;
    case 'error':      actions = link; note = `✗ ${l.error || 'Auto-apply failed'} — apply manually`; break;
    default:           actions = link; note = l.reason || 'Apply manually';
  }

  const character = `/assets/illustration/${(i % 5) + 1}.png`;

  return `
    <div class="tile-main">
      <div class="tile-top">
        ${logo}
        <div class="tile-tags">${platTag}${roleTag}</div>
      </div>
      <div class="tile-body">
        <span class="tile-title">${l.title}</span>
        <span class="tile-sub">${l.company}</span>
        <span class="tile-stipend">${l.stipend}</span>
        ${note ? `<span class="tile-note">${note}</span>` : ''}
      </div>
      <div class="tile-actions">${actions}</div>
    </div>
    <div class="tile-hero"><img src="${character}" alt="" loading="lazy"></div>`;
}

function badgeLabel(s) {
  return ({ pending:'Pending', generating:'Generating…', ready:'Ready',
            submitting:'Submitting…', submitted:'Submitted', skipped:'Skipped', error:'Error' })[s] ?? s;
}

// ── Direct apply (0-question listings) ───────────────────────────────────────
async function directApply(index) {
  if (!confirm('Auto-apply now? This uploads your résumé and submits the application on Internshala.')) return;
  patchListingStatus(index, 'submitting');
  await fetch('/api/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: currentJobId, listing_index: index, answers: {}, action: 'approve' }),
  });
  const t = setInterval(async () => {
    const j = await (await fetch(`/api/job/${currentJobId}`)).json();
    if (j.listings[index].status !== 'submitting') {
      clearInterval(t);
      refreshListing(index, j.listings[index], j.listings);
      refreshAppliedCount();
    }
  }, 1500);
}

// ── Generate answers ──────────────────────────────────────────────────────────
async function generateAnswers(index) {
  patchListingStatus(index, 'generating');
  await fetch(`/api/generate/${currentJobId}/${index}`, { method: 'POST' });
  const t = setInterval(async () => {
    const job = await (await fetch(`/api/job/${currentJobId}`)).json();
    if (job.listings[index].status !== 'generating') {
      clearInterval(t);
      refreshListing(index, job.listings[index], job.listings);
    }
  }, 1500);
}

// ── Review modal ──────────────────────────────────────────────────────────────
let reviewIndex = null;

async function openReview(index) {
  const job     = await (await fetch(`/api/job/${currentJobId}`)).json();
  const listing = job.listings[index];
  reviewIndex   = index;

  document.getElementById('modal-content').innerHTML = `
    <h3>${listing.title}</h3>
    <p class="modal-sub">
      ${listing.matched_role ? `<span class="role-tag">${listing.matched_role}</span> · ` : ''}
      ${listing.company} · ${listing.stipend} ·
      <a href="${listing.url}" target="_blank" style="color:var(--accent)">View listing ↗</a>
    </p>
    <div id="qa-list">
      ${listing.questions.map((q, qi) => `
        <div class="qa-block">
          <p class="qa-question">${q}</p>
          <textarea class="answer-box" id="answer-${qi}" rows="4">${listing.answers[q] ?? ''}</textarea>
        </div>`).join('')}
    </div>
    <div class="modal-actions">
      <button class="btn-sm btn-skip"   onclick="submitDecision('skip')">Skip</button>
      <button class="btn-sm btn-approve" onclick="submitDecision('approve')">Submit Application</button>
    </div>`;

  document.getElementById('modal-overlay').classList.remove('hidden');
}

async function submitDecision(action) {
  const job     = await (await fetch(`/api/job/${currentJobId}`)).json();
  const listing = job.listings[reviewIndex];

  const finalAnswers = {};
  listing.questions.forEach((q, qi) => {
    const el = document.getElementById(`answer-${qi}`);
    finalAnswers[q] = el ? el.value.trim() : (listing.answers[q] ?? '');
  });

  closeModalDirect();
  patchListingStatus(reviewIndex, action === 'approve' ? 'submitting' : 'skipped');

  await fetch('/api/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: currentJobId, listing_index: reviewIndex, answers: finalAnswers, action }),
  });

  if (action === 'approve') {
    const t = setInterval(async () => {
      const j = await (await fetch(`/api/job/${currentJobId}`)).json();
      if (j.listings[reviewIndex].status !== 'submitting') {
        clearInterval(t);
        refreshListing(reviewIndex, j.listings[reviewIndex], j.listings);
      }
    }, 1500);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function patchListingStatus(index, status) {
  fetch(`/api/job/${currentJobId}`).then(r => r.json()).then(job => {
    refreshListing(index, { ...job.listings[index], status }, job.listings);
  });
}

function refreshListing(index, listing, allListings) {
  const card = document.getElementById(`listing-${index}`);
  if (card) card.innerHTML = listingHTML(listing, index);
}

// ── Keyword extraction helpers ────────────────────────────────────────────────
function _friendlyError(raw) {
  if (raw.includes('credit balance is too low') || raw.includes('insufficient'))
    return 'API credits empty — add credits at console.anthropic.com/billing';
  if (raw.includes('invalid') && raw.includes('key') || raw.includes('authentication'))
    return 'Invalid API key — update ANTHROPIC_API_KEY in .env';
  if (raw.includes('rate'))
    return 'Rate limited — try again in a moment';
  return 'Keyword extraction failed — add manually or retry';
}

async function retryExtract(role) {
  const res = await fetch(`/api/resumes/${role}/retry-extract`, { method: 'POST' });
  if ((await res.json()).ok) pollResumes();
}

function closeModal(e) {
  if (e.target === document.getElementById('modal-overlay')) closeModalDirect();
}
function closeModalDirect() {
  document.getElementById('modal-overlay').classList.add('hidden');
}
