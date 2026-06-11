/* ── RAG Chatbot — app.js ── */

const API = '/api';
let conversationId = null;
let pollTimer = null;

// ── Token helpers ──────────────────────────────────────────────
function getToken()  { return localStorage.getItem('access_token'); }
function setTokens(access, refresh) {
  localStorage.setItem('access_token', access);
  localStorage.setItem('refresh_token', refresh);
}
function clearTokens() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
}

// ── Authenticated fetch (auto-refresh on 401) ─────────────────
async function apiRequest(url, options = {}) {
  const headers = { ...options.headers };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  // Only set Content-Type for JSON (not for FormData uploads)
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  let resp = await fetch(url, { ...options, headers });

  if (resp.status === 401) {
    const refreshed = await tryRefreshToken();
    if (!refreshed) { logout(); return null; }
    headers['Authorization'] = `Bearer ${getToken()}`;
    resp = await fetch(url, { ...options, headers });
  }

  return resp;
}

async function tryRefreshToken() {
  const refresh = localStorage.getItem('refresh_token');
  if (!refresh) return false;
  try {
    const resp = await fetch(`${API}/auth/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    });
    if (!resp.ok) return false;
    const data = await resp.json();
    localStorage.setItem('access_token', data.data.access);
    return true;
  } catch {
    return false;
  }
}

function logout() {
  clearTokens();
  window.location.href = '/login/';
}

// ── Notifications ─────────────────────────────────────────────
function notify(message, type = 'info') {
  const el = document.getElementById('notification');
  el.textContent = message;
  el.className = `notification notification-${type} show`;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove('show'), 4000);
}

// ── Utilities ─────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// Auto-grow textarea
function autoGrow(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

// ── Documents ─────────────────────────────────────────────────
async function loadDocuments() {
  const resp = await apiRequest(`${API}/documents/`);
  if (!resp) return;
  const { data } = await resp.json();
  renderDocuments(data);
  schedulePolling(data);
}

function renderDocuments(docs) {
  const list = document.getElementById('doc-list');
  if (!docs.length) {
    list.innerHTML = '<p class="empty-state">No documents yet. Upload a PDF to start.</p>';
    return;
  }
  list.innerHTML = docs.map(doc => `
    <div class="doc-item">
      <span class="doc-name" title="${escHtml(doc.title)}">${escHtml(doc.title)}</span>
      <span class="doc-status status-${doc.status}">
        <span class="status-indicator"></span>${doc.status}
      </span>
      ${doc.chunk_count ? `<span class="doc-meta">${doc.chunk_count} chunks · ${doc.page_count || '?'} pages</span>` : ''}
    </div>
  `).join('');
}

function schedulePolling(docs) {
  const pending = docs.some(d => d.status === 'pending' || d.status === 'processing');
  if (pending && !pollTimer) {
    pollTimer = setInterval(async () => {
      const resp = await apiRequest(`${API}/documents/`);
      if (!resp) return;
      const { data } = await resp.json();
      renderDocuments(data);
      const stillPending = data.some(d => d.status === 'pending' || d.status === 'processing');
      if (!stillPending) { clearInterval(pollTimer); pollTimer = null; }
    }, 3000);
  }
}

async function handleUpload(file) {
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    notify('Only PDF files are supported.', 'error');
    return;
  }

  const btn = document.getElementById('upload-btn');
  btn.disabled = true;
  btn.textContent = 'Uploading…';

  const formData = new FormData();
  formData.append('file', file);

  const resp = await apiRequest(`${API}/documents/upload/`, {
    method: 'POST',
    body: formData,
  });

  btn.disabled = false;
  btn.textContent = '+ Upload PDF';

  if (!resp) return;
  const data = await resp.json();

  if (!resp.ok) {
    notify(data.message || 'Upload failed.', 'error');
    return;
  }

  notify('Document uploaded! Processing started.', 'success');
  await loadDocuments();
}

// ── Chat ──────────────────────────────────────────────────────
async function sendMessage() {
  const input = document.getElementById('chat-input');
  const question = input.value.trim();
  if (!question) return;

  const sendBtn = document.getElementById('send-btn');
  input.value = '';
  input.style.height = 'auto';
  input.disabled = true;
  sendBtn.disabled = true;
  sendBtn.textContent = '…';

  // Remove welcome message on first send
  document.querySelector('.welcome-msg')?.remove();

  appendMessage('user', question, []);
  appendThinking();

  const body = { question };
  if (conversationId) body.conversation_id = conversationId;

  const resp = await apiRequest(`${API}/chat/`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

  removeThinking();
  input.disabled = false;
  sendBtn.disabled = false;
  sendBtn.textContent = 'Send';
  input.focus();

  if (!resp) return;

  if (resp.status === 429) {
    notify('Rate limit reached. Please wait a moment.', 'error');
    return;
  }

  const data = await resp.json();

  if (!resp.ok) {
    notify(data.message || 'Something went wrong.', 'error');
    return;
  }

  conversationId = data.data.conversation_id;
  appendMessage('assistant', data.data.answer, data.data.sources);
}

function appendMessage(role, content, sources) {
  const messages = document.getElementById('messages');
  const wrapper = document.createElement('div');
  wrapper.className = `message message-${role}`;

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = content;
  wrapper.appendChild(bubble);

  if (role === 'assistant' && sources.length > 0) {
    const sourcesEl = document.createElement('div');
    sourcesEl.className = 'sources';
    sourcesEl.innerHTML = 'Sources: ' + sources.map(s =>
      `<span class="source-chip">Doc #${s.document_id}, p.${s.page_number}</span>`
    ).join('');
    wrapper.appendChild(sourcesEl);
  }

  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
}

function appendThinking() {
  const messages = document.getElementById('messages');
  const div = document.createElement('div');
  div.id = 'thinking';
  div.className = 'message message-assistant';
  div.innerHTML = '<div class="bubble thinking"><span></span><span></span><span></span></div>';
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

function removeThinking() {
  document.getElementById('thinking')?.remove();
}

// ── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  if (!getToken()) { window.location.href = '/login/'; return; }

  // Bind controls
  document.getElementById('logout-btn').addEventListener('click', logout);

  document.getElementById('upload-btn').addEventListener('click', () => {
    document.getElementById('file-input').click();
  });

  document.getElementById('file-input').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) { handleUpload(file); e.target.value = ''; }
  });

  document.getElementById('send-btn').addEventListener('click', sendMessage);

  const input = document.getElementById('chat-input');
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  input.addEventListener('input', () => autoGrow(input));

  document.getElementById('new-chat-btn').addEventListener('click', () => {
    conversationId = null;
    const messages = document.getElementById('messages');
    messages.innerHTML = '<div class="welcome-msg"><p>Upload a PDF document and ask questions about its content.</p></div>';
    notify('New conversation started.', 'info');
  });

  // Drag and drop upload
  const sidebar = document.querySelector('.sidebar');
  sidebar.addEventListener('dragover', (e) => { e.preventDefault(); sidebar.classList.add('drag-over'); });
  sidebar.addEventListener('dragleave', ()  => sidebar.classList.remove('drag-over'));
  sidebar.addEventListener('drop', (e) => {
    e.preventDefault();
    sidebar.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
  });

  loadDocuments();
});
