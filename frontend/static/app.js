// ── State ─────────────────────────────────────────────────────────────────────
let currentJobId = null;
let pollTimer    = null;
let activeFilter = 'all';   // role filter for results

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

// Load existing resumes on page load
window.addEventListener('load', async () => {
  const res  = await fetch('/api/resumes');
  const data = await res.json();
  renderResumeCards(data);
  const anyExtracting = Object.values(data).some(r => r.keyword_status === 'extracting');
  if (anyExtracting) pollResumes();
});

// ── Search ────────────────────────────────────────────────────────────────────
async function startSearch() {
  const btn      = document.getElementById('search-btn');
  const statusEl = document.getElementById('search-status');
  btn.disabled   = true;
  statusEl.innerHTML = '<span class="spinner"></span>Logging in & searching all roles…';
  stopPolling();

  const body = {
    location:     document.getElementById('location').value.trim(),
    stipend_min:  parseInt(document.getElementById('stipend').value) || 0,
    max_per_role: parseInt(document.getElementById('max').value) || 10,
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
    card.innerHTML = listingHTML(l, realIndex);
    grid.appendChild(card);
  });
}

function setFilter(role, listings) {
  activeFilter = role;
  renderListings(listings);
}

function listingHTML(l, i) {
  const roleTag = l.matched_role ? `<span class="role-tag">${l.matched_role}</span>` : '';

  const actions = `<a href="${l.url}" target="_blank" rel="noopener"
      class="btn-sm btn-approve" style="text-decoration:none">Apply on Internshala ↗</a>`;

  return `
    <div class="listing-meta">
      <span class="listing-title">${roleTag}${l.title}</span>
      <span class="listing-sub">${l.company} · ${l.stipend}</span>
    </div>
    <div class="listing-actions">${actions}</div>`;
}

function badgeLabel(s) {
  return ({ pending:'Pending', generating:'Generating…', ready:'Ready',
            submitting:'Submitting…', submitted:'Submitted', skipped:'Skipped', error:'Error' })[s] ?? s;
}

// ── Direct apply (0-question listings) ───────────────────────────────────────
async function directApply(index) {
  if (!confirm('Submit this application directly (no questions)?')) return;
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
