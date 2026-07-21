// InternHelper dashboard (multi-tenant, job-based). All calls use apiFetch()
// from auth.js (adds the JWT). Search/apply are queued as jobs the local agent
// runs; the dashboard polls the job for the result.

let activeFilter = 'all';
let selected = new Set();
let demoMode = false;
let currentListings = [];   // latest search results (held client-side)

// ── Job polling ──────────────────────────────────────────────────────────────
function pollJob(jobId, onTick) {
  return new Promise((resolve) => {
    const t = setInterval(async () => {
      let job;
      try { job = await (await apiFetch(`/api/jobs/${jobId}`)).json(); } catch { return; }
      if (onTick) onTick(job);
      if (job.status === 'done' || job.status === 'failed') { clearInterval(t); resolve(job); }
    }, 2000);
  });
}

// ── Sidebar nav active state ─────────────────────────────────────────────────
document.querySelectorAll('.nav-item[data-nav]').forEach(a => {
  a.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    a.classList.add('active');
  });
});

// ── Platforms ────────────────────────────────────────────────────────────────
async function loadPlatforms() {
  try {
    const platforms = await (await apiFetch('/api/platforms')).json();
    const toggles = document.getElementById('platform-toggles');
    if (toggles) toggles.innerHTML = platforms.map(p => `
      <label class="platform-toggle">
        <input type="checkbox" value="${p.name}" checked>
        ${p.label}${p.supports_auto_apply ? '' : ' (search only)'}
      </label>`).join('');
  } catch {}
}
function selectedPlatforms() {
  return [...document.querySelectorAll('#platform-toggles input:checked')].map(c => c.value);
}

// ── Résumés ──────────────────────────────────────────────────────────────────
document.getElementById('resume-file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const role = document.getElementById('role-input').value.trim().toLowerCase();
  if (!role) { setUploadStatus('Enter a role label first', 'error'); e.target.value = ''; return; }
  setUploadStatus('Uploading…', 'info');
  const fd = new FormData();
  fd.append('role', role); fd.append('file', file);
  try {
    await apiFetch('/api/resumes', { method: 'POST', body: fd });
    setUploadStatus(`✓ ${file.name} uploaded — extracting keywords…`, 'ok');
    document.getElementById('role-input').value = ''; e.target.value = '';
    loadResumes();
  } catch { setUploadStatus('✗ Upload failed', 'error'); }
});

function setUploadStatus(msg, type) {
  const el = document.getElementById('upload-status');
  el.textContent = msg;
  el.style.color = type === 'error' ? 'var(--red)' : type === 'ok' ? 'var(--green)' : 'var(--muted)';
}

let resumePollTimer = null;
async function loadResumes() {
  let list;
  try { list = await (await apiFetch('/api/resumes')).json(); } catch { return; }
  renderResumeCards(list);
  if (list.some(r => r.keyword_status === 'extracting') && !resumePollTimer) {
    resumePollTimer = setInterval(async () => {
      const l = await (await apiFetch('/api/resumes')).json();
      renderResumeCards(l);
      if (!l.some(r => r.keyword_status === 'extracting')) { clearInterval(resumePollTimer); resumePollTimer = null; }
    }, 1500);
  }
}

function renderResumeCards(list) {
  const c = document.getElementById('resume-cards');
  c.innerHTML = '';
  list.forEach(r => c.appendChild(buildResumeCard(r)));
}

function buildResumeCard(r) {
  const card = document.createElement('div');
  card.className = 'resume-card';
  card.id = `rcard-${r.id}`;
  let kwHtml;
  if (r.keyword_status === 'extracting') {
    kwHtml = `<span class="kw-extracting"><span class="spinner"></span>Extracting keywords…</span>`;
  } else {
    const chips = (r.keywords || []).map((kw, i) =>
      `<span class="chip">${kw}<button class="chip-remove" onclick="removeKeyword(${r.id},${i})">×</button></span>`).join('');
    kwHtml = `<div class="keyword-area">${chips}
      <input class="chip-input" placeholder="+ add" onkeydown="addKeyword(event,${r.id})" /></div>`;
  }
  card.innerHTML = `
    <button class="btn-delete" onclick="deleteResume(${r.id})" title="Remove">✕</button>
    <div class="resume-card-header">
      <div><span class="resume-role">${r.role}</span><span class="resume-filename"> · ${r.filename || ''}</span></div>
    </div>
    ${kwHtml}`;
  return card;
}

async function _patchKeywords(id, kws) {
  await apiFetch(`/api/resumes/${id}/keywords`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keywords: kws }),
  });
  loadResumes();
}
async function removeKeyword(id, index) {
  const r = (await (await apiFetch('/api/resumes')).json()).find(x => x.id === id);
  if (!r) return;
  const kws = [...r.keywords]; kws.splice(index, 1);
  _patchKeywords(id, kws);
}
async function addKeyword(e, id) {
  if (e.key !== 'Enter') return;
  const kw = e.target.value.trim().toLowerCase();
  if (!kw) return;
  const r = (await (await apiFetch('/api/resumes')).json()).find(x => x.id === id);
  _patchKeywords(id, [...((r && r.keywords) || []), kw]);
}
async function deleteResume(id) {
  await apiFetch(`/api/resumes/${id}`, { method: 'DELETE' });
  loadResumes();
}

// ── Search (enqueue job → poll → render) ─────────────────────────────────────
async function startSearch() {
  const btn = document.getElementById('search-btn');
  const statusEl = document.getElementById('search-status');
  const platforms = selectedPlatforms();
  if (!platforms.length) { statusEl.textContent = 'Select at least one platform.'; return; }
  btn.disabled = true;
  statusEl.innerHTML = '<span class="spinner"></span>Queuing search…';
  demoMode = false;

  const body = {
    platforms,
    location: document.getElementById('location').value.trim(),
    stipend_min: parseInt(document.getElementById('stipend').value) || 0,
    max_per_role: parseInt(document.getElementById('max').value) || 10,
  };
  let job;
  try { job = await (await apiFetch('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json(); }
  catch { statusEl.textContent = 'Error queuing search.'; btn.disabled = false; return; }

  const done = await pollJob(job.id, j => {
    statusEl.innerHTML = j.status === 'queued'
      ? '<span class="spinner"></span>Waiting for your local agent…'
      : '<span class="spinner"></span>Agent is searching…';
  });
  btn.disabled = false;
  if (done.status === 'failed') { statusEl.textContent = `Search failed: ${done.error}`; return; }
  statusEl.textContent = '';
  currentListings = done.result.listings || [];
  renderListings(currentListings);
}

// ── Render listings ──────────────────────────────────────────────────────────
function renderListings(listings) {
  currentListings = listings;
  const panel = document.getElementById('results-panel');
  const grid = document.getElementById('listings-grid');
  panel.classList.remove('hidden');
  const roles = ['all', ...new Set(listings.map(l => l.matched_role).filter(Boolean))];
  document.getElementById('role-filters').innerHTML = roles.map(r =>
    `<button class="role-pill ${r === activeFilter ? 'active' : ''}" onclick="setFilter('${r}')">${r}</button>`).join('');
  const filtered = activeFilter === 'all' ? listings : listings.filter(l => l.matched_role === activeFilter);
  document.getElementById('results-title').textContent =
    `${filtered.length} listing${filtered.length !== 1 ? 's' : ''}${activeFilter !== 'all' ? ` · ${activeFilter}` : ''}`;
  grid.innerHTML = '';
  filtered.forEach(l => {
    const realIndex = listings.indexOf(l);
    const card = document.createElement('div');
    card.className = 'listing-card';
    card.id = `listing-${realIndex}`;
    card.style.backgroundColor = brightColor(realIndex);
    card.innerHTML = listingHTML(l, realIndex);
    grid.appendChild(card);
  });
  renderBulkBar(filtered.filter(l => l.status === 'auto').map(l => listings.indexOf(l)));
}
function setFilter(role) { activeFilter = role; renderListings(currentListings); }

const BRIGHT = ['#ffd23f', '#ff8a3d', '#ff6b9d', '#34d399', '#7c5cff', '#3b9dff', '#a3e635', '#22d3ee', '#ff5c5c', '#c084fc'];
function brightColor(i) { return BRIGHT[((i % BRIGHT.length) + BRIGHT.length) % BRIGHT.length]; }
function platformLabel(l) { const n = l.platform || 'internshala'; return n.charAt(0).toUpperCase() + n.slice(1); }

function listingHTML(l, i) {
  const roleTag = l.matched_role ? `<span class="role-tag">${l.matched_role}</span>` : '';
  const platTag = l.platform ? `<span class="platform-tag">${platformLabel(l)}</span>` : '';
  const logo = l.logo
    ? `<img class="tile-logo" src="${l.logo}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'tile-logo tile-logo-fallback',textContent:'${(l.company || '?').charAt(0)}'}))">`
    : `<span class="tile-logo tile-logo-fallback">${(l.company || '?').charAt(0)}</span>`;
  const link = `<a href="${l.url}" target="_blank" rel="noopener" class="btn-sm tile-btn" style="text-decoration:none">Apply on ${platformLabel(l)} ↗</a>`;
  let actions, note = '';
  switch (l.status) {
    case 'auto':
      actions = `<label class="tile-check"><input type="checkbox" onchange="toggleSelect(${i}, this.checked)" ${selected.has(i) ? 'checked' : ''}> Select</label>
        <button class="btn-sm tile-btn" onclick="directApply(${i})">⚡ Auto-apply</button>`;
      break;
    case 'submitting': actions = `<span class="tile-status"><span class="spinner"></span> Applying…</span>`; break;
    case 'submitted':  actions = `<span class="tile-status">✓ Applied</span>`; break;
    case 'error':      actions = link; note = `✗ ${l.error || 'Auto-apply failed'} — apply manually`; break;
    default:           actions = link; note = l.reason || 'Apply manually';
  }
  const character = `/assets/illustration/${(i % 5) + 1}.png`;
  return `
    <div class="tile-main">
      <div class="tile-top">${logo}<div class="tile-tags">${platTag}${roleTag}</div></div>
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

function patchListingStatus(index, status) { currentListings[index].status = status; refreshListing(index); }
function refreshListing(index) {
  const card = document.getElementById(`listing-${index}`);
  if (card) card.innerHTML = listingHTML(currentListings[index], index);
}

// ── Apply (enqueue apply job → poll) ─────────────────────────────────────────
async function _runApply(index) {
  const l = currentListings[index];
  patchListingStatus(index, 'submitting');
  if (demoMode) { await new Promise(r => setTimeout(r, 700)); patchListingStatus(index, 'submitted'); return true; }
  let job;
  try { job = await (await apiFetch('/api/apply', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ listing: l, resume_id: l.resume_id }) })).json(); }
  catch { l.status = 'error'; l.error = 'Could not queue'; refreshListing(index); return false; }
  const done = await pollJob(job.id);
  const ok = done.status === 'done' && done.result && done.result.ok;
  l.status = ok ? 'submitted' : 'error';
  if (!ok) l.error = (done.result && done.result.message) || done.error || 'failed';
  refreshListing(index);
  return ok;
}

async function directApply(index) {
  if (!confirm('Auto-apply now? Your local agent submits this on the platform using your session.')) return;
  await _runApply(index);
  refreshAppliedCount();
}

async function applyBatch(indices) {
  if (!indices.length) return;
  if (!confirm(`Auto-apply to ${indices.length} internship${indices.length !== 1 ? 's' : ''}? Each runs on your agent, one at a time.`)) return;
  document.querySelectorAll('#bulk-bar button').forEach(b => b.disabled = true);
  const prog = document.getElementById('bulk-progress');
  let applied = 0, failed = 0;
  for (let n = 0; n < indices.length; n++) {
    if (prog) prog.textContent = `Applying ${n + 1}/${indices.length} · ✓${applied}${failed ? ` ✗${failed}` : ''}`;
    (await _runApply(indices[n])) ? applied++ : failed++;
  }
  if (prog) prog.textContent = `Done · ✓${applied} applied${failed ? ` · ✗${failed} failed` : ''}`;
  selected.clear();
  refreshAppliedCount();
  setTimeout(() => renderListings(currentListings), 2500);
}

let bulkSelected = () => [...selected];
function renderBulkBar(autoIndices) {
  const bar = document.getElementById('bulk-bar');
  selected = new Set([...selected].filter(i => autoIndices.includes(i)));
  if (!autoIndices.length) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = '';
  const cAll = brightColor(2), cSel = brightColor(7);
  bar.innerHTML = `
    <button class="btn-sm pop-btn" style="--pop:${cAll}" onclick='applyBatch(${JSON.stringify(autoIndices)})'>
      ⚡ Apply to all ${autoIndices.length} no-question listing${autoIndices.length !== 1 ? 's' : ''}</button>
    <button id="apply-selected-btn" class="btn-sm pop-btn" style="--pop:${cSel}" onclick="applyBatch([...selected])" ${selected.size ? '' : 'disabled'}>
      Apply to selected (${selected.size})</button>
    <span id="bulk-progress" class="bulk-progress"></span>`;
}
function toggleSelect(index, checked) {
  if (checked) selected.add(index); else selected.delete(index);
  const btn = document.getElementById('apply-selected-btn');
  if (btn) { btn.textContent = `Apply to selected (${selected.size})`; btn.disabled = selected.size === 0; }
}

// ── Applications manager ─────────────────────────────────────────────────────
const APP_STATUSES = ['applied', 'under review', 'interview', 'offer', 'rejected'];
const _slug = s => (s || '').replace(/\s+/g, '-');

const DEMO_APPLIED = [
  { id: 1, url: "#a", title: "Full Stack Development Internship", company: "Codemax Digital", role: "fullstack", stipend: "₹15,000 - ₹25,000/month", platform: "unstop", status: "interview", applied_at: "2026-07-18" },
  { id: 2, url: "#b", title: "Backend Development Internship", company: "NayePankh Foundation", role: "backend", stipend: "Unpaid", platform: "internshala", status: "applied", applied_at: "2026-07-19" },
  { id: 3, url: "#c", title: "MERN Stack Developer Internship", company: "SwiftBL", role: "fullstack", stipend: "₹5,000 - ₹15,000/month", platform: "unstop", status: "under review", applied_at: "2026-07-20" },
  { id: 4, url: "#d", title: "Web Development Internship", company: "Nexora", role: "frontend", stipend: "₹10,000/month", platform: "unstop", status: "offer", applied_at: "2026-07-15" },
  { id: 5, url: "#e", title: "Data Analyst Internship", company: "Acme Corp", role: "data", stipend: "₹12,000/month", platform: "internshala", status: "rejected", applied_at: "2026-07-14" },
];

async function fetchApplied() {
  if (demoMode) return DEMO_APPLIED;
  try { return await (await apiFetch('/api/applications')).json(); } catch { return []; }
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
  if (!items.length) { list.innerHTML = `<p class="step-hint">No applications yet — auto-applied listings and platform syncs land here.</p>`; return; }
  const counts = {};
  items.forEach(it => { const s = it.status || 'applied'; counts[s] = (counts[s] || 0) + 1; });
  const summary = `<div class="app-summary"><span class="app-stat"><b>${items.length}</b> total</span>
    ${APP_STATUSES.filter(s => counts[s]).map(s => `<span class="app-stat st-${_slug(s)}">${counts[s]} ${s}</span>`).join('')}</div>`;
  const rows = items.map(it => {
    const st = it.status || 'applied';
    const plat = it.platform ? `<span class="platform-tag platform-${it.platform}">${platformLabel(it)}</span>` : '';
    const role = it.role ? `<span class="role-tag">${it.role}</span>` : '';
    const opts = APP_STATUSES.map(s => `<option value="${s}" ${s === st ? 'selected' : ''}>${s}</option>`).join('');
    return `<div class="applied-row">
        <div class="applied-meta">
          <span class="applied-title">${plat}${role}<a href="${it.url}" target="_blank" rel="noopener">${it.title || 'Listing'} ↗</a></span>
          <span class="listing-sub">${it.company || ''}${it.stipend ? ` · ${it.stipend}` : ''} · applied ${(it.applied_at || '').slice(0, 10)}</span>
        </div>
        <div class="applied-actions">
          <select class="status-select st-${_slug(st)}" onchange="setAppliedStatus(${it.id}, this.value)">${opts}</select>
          <button class="btn-sm btn-skip" onclick="removeApplied(${it.id})">Remove</button>
        </div></div>`;
  }).join('');
  list.innerHTML = summary + rows;
}
async function setAppliedStatus(id, status) {
  if (demoMode) { const it = DEMO_APPLIED.find(x => x.id === id); if (it) it.status = status; renderApplied(DEMO_APPLIED); return; }
  await apiFetch(`/api/applications/${id}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
  renderApplied(await refreshAppliedCount());
}
async function removeApplied(id) {
  if (demoMode) { const i = DEMO_APPLIED.findIndex(x => x.id === id); if (i >= 0) DEMO_APPLIED.splice(i, 1); renderApplied(await refreshAppliedCount()); return; }
  await apiFetch(`/api/applications/${id}`, { method: 'DELETE' });
  renderApplied(await refreshAppliedCount());
}
async function clearApplied() {
  if (!confirm('Clear the entire applications list?')) return;
  if (demoMode) { DEMO_APPLIED.length = 0; renderApplied(await refreshAppliedCount()); return; }
  await apiFetch('/api/applications', { method: 'DELETE' });
  renderApplied(await refreshAppliedCount());
}
async function syncApplications() {
  const btn = document.getElementById('sync-btn');
  if (demoMode) { alert('Sync pulls live statuses from the platforms — try it outside demo mode.'); return; }
  btn.disabled = true; btn.textContent = '⏳ Syncing…';
  let job;
  try { job = await (await apiFetch('/api/sync', { method: 'POST' })).json(); } catch { btn.disabled = false; btn.textContent = '🔄 Sync status'; return; }
  const done = await pollJob(job.id);
  btn.disabled = false; btn.textContent = done.status === 'failed' ? '⚠ Sync failed' : '🔄 Sync status';
  renderApplied(await refreshAppliedCount());
}

// ── Demo (no server / agent needed) ──────────────────────────────────────────
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
const DEMO_RESUMES = [
  { id: 101, role: "fullstack", filename: "Suryansh_Fullstack.docx", keyword_status: "ready", keywords: ["full stack development", "react", "node.js", "python", "web development", "backend development"] },
  { id: 102, role: "frontend", filename: "Suryansh_Frontend.docx", keyword_status: "ready", keywords: ["react", "javascript", "typescript", "next.js", "ux design"] },
  { id: 103, role: "backend", filename: "Suryansh_Backend.docx", keyword_status: "ready", keywords: ["python", "node.js", "fastapi", "postgresql", "docker"] },
  { id: 104, role: "product management", filename: "Suryansh_PM.docx", keyword_status: "ready", keywords: ["product management", "roadmapping", "user research", "analytics", "agile"] },
  { id: 105, role: "data science", filename: "Suryansh_Data.docx", keyword_status: "ready", keywords: ["python", "pandas", "machine learning", "sql", "data visualization"] },
  { id: 106, role: "design", filename: "Suryansh_Design.docx", keyword_status: "ready", keywords: ["figma", "ui design", "ux design", "prototyping", "design systems"] },
];
function loadDemo() {
  demoMode = true; activeFilter = 'all';
  renderResumeCards(DEMO_RESUMES);
  renderListings(DEMO_LISTINGS.map(l => ({ ...l })));
  refreshAppliedCount();
  document.getElementById('results-panel').scrollIntoView({ behavior: 'smooth' });
}

// ── Boot ─────────────────────────────────────────────────────────────────────
loadPlatforms();
loadResumes();
refreshAppliedCount();

function closeModal(e) { if (e.target === document.getElementById('modal-overlay')) closeModalDirect(); }
function closeModalDirect() { document.getElementById('modal-overlay').classList.add('hidden'); }
