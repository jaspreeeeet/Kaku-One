/* MimiClaw Expression Dashboard — app.js */

const EXPRESSION_ICONS = {
  idle:        '😐',
  happy:       '😄',
  sad:         '😢',
  angry:       '😠',
  surprised:   '😲',
  thinking:    '🤔',
  talking:     '💬',
  sleeping:    '😴',
  confused:    '😕',
  excited:     '🤩',
  smug:        '😏',
  embarrassed: '😳',
};

let currentExpression = null;
let pollingInterval   = null;

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  await loadExpressions();
  await loadAnimationConfig();
  await pollStatus();
  pollingInterval = setInterval(pollStatus, 2000);
  setupUpload();
  setupAnimationControls();
  setStreamUrl();
}

function setStreamUrl() {
  const url = `${location.origin}/stream`;
  const el = document.getElementById('stream-url');
  el.textContent = url;
  el.href = url;
  document.getElementById('cli-hint').textContent =
    `set_display_server ${location.origin}`;
}

// ── Expression buttons ────────────────────────────────────────────────────────

async function loadExpressions() {
  try {
    const res = await fetch('/expressions');
    const { expressions } = await res.json();
    renderButtons(expressions);
  } catch (e) {
    console.error('Failed to load expressions', e);
  }
}

function renderButtons(expressions) {
  const grid = document.getElementById('expr-grid');
  grid.innerHTML = '';
  expressions.forEach(name => {
    const btn = document.createElement('button');
    btn.className = 'expr-btn';
    btn.dataset.expr = name;
    btn.innerHTML = `<span>${EXPRESSION_ICONS[name] || '🎭'}</span>${name}`;
    btn.addEventListener('click', () => setExpression(name));
    grid.appendChild(btn);
  });
}

async function setExpression(name) {
  try {
    const res = await fetch('/expression', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expression: name }),
    });
    if (!res.ok) throw new Error(await res.text());
    updateActiveButton(name);
  } catch (e) {
    console.error('Set expression failed:', e);
  }
}

function updateActiveButton(name) {
  document.querySelectorAll('.expr-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.expr === name);
  });
  const label = document.getElementById('current-expr-name');
  label.textContent = name;
  currentExpression = name;
}

// ── Status polling ────────────────────────────────────────────────────────────

async function pollStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();

    setBadge('online');
    document.getElementById('info-clients').textContent = data.connected_clients;

    if (data.current_expression !== currentExpression) {
      updateActiveButton(data.current_expression);
    }
  } catch {
    setBadge('offline');
  }
}

function setBadge(state) {
  const b = document.getElementById('status-badge');
  b.className = `badge ${state}`;
  b.textContent = state === 'online' ? 'Online' : 'Offline';
}

// ── Animation controls ─────────────────────────────────────────────────────

async function loadAnimationConfig() {
  try {
    const res = await fetch('/api/animation');
    if (!res.ok) throw new Error(res.status);
    const cfg = await res.json();
    fillAnimationForm(cfg);
  } catch (e) {
    console.error('Failed to load animation config', e);
  }
}

function fillAnimationForm(cfg) {
  document.getElementById('anim-stream-fps').value = cfg.stream_fps;
  document.getElementById('anim-blink-min').value = cfg.blink_min_interval_s;
  document.getElementById('anim-blink-max').value = cfg.blink_max_interval_s;
  document.getElementById('anim-blink-duration').value = cfg.blink_duration_frames;
  document.getElementById('anim-talking-cycle').value = cfg.talking_cycle_frames;
  document.getElementById('anim-transition').value = cfg.transition_frames;
}

function setupAnimationControls() {
  const form = document.getElementById('animation-form');
  const saveBtn = document.getElementById('anim-save');
  const statusEl = document.getElementById('anim-status');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const payload = {
      stream_fps: Number(document.getElementById('anim-stream-fps').value),
      blink_min_interval_s: Number(document.getElementById('anim-blink-min').value),
      blink_max_interval_s: Number(document.getElementById('anim-blink-max').value),
      blink_duration_frames: Number(document.getElementById('anim-blink-duration').value),
      talking_cycle_frames: Number(document.getElementById('anim-talking-cycle').value),
      transition_frames: Number(document.getElementById('anim-transition').value),
    };

    saveBtn.disabled = true;
    statusEl.textContent = 'Applying...';
    statusEl.className = '';

    try {
      const res = await fetch('/api/animation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || res.status);
      }

      fillAnimationForm(data);
      statusEl.textContent = 'Applied';
    } catch (err) {
      statusEl.textContent = `Error: ${err.message}`;
      statusEl.className = 'error';
    } finally {
      saveBtn.disabled = false;
    }
  });
}

// ── Stream error handling ────────────────────────────────────────────────────

function onStreamError() {
  // Try to reload the stream after a short delay
  const img = document.getElementById('stream-img');
  setTimeout(() => {
    img.src = `/stream?t=${Date.now()}`;
  }, 3000);
}

function onStreamLoad() {
  // Stream connected — ensure status reflects this
  setBadge('online');
}

// ── File upload ───────────────────────────────────────────────────────────────

function setupUpload() {
  const fileInput = document.getElementById('upload-file');
  const fileLabel = document.getElementById('file-name-label');

  fileInput.addEventListener('change', () => {
    fileLabel.textContent = fileInput.files[0]?.name || 'Choose PNG…';
  });

  document.getElementById('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const statusEl = document.getElementById('upload-status');
    const btn = e.target.querySelector('button[type=submit]');

    const subfolder = document.getElementById('upload-subfolder').value;
    const file = fileInput.files[0];

    if (!subfolder || !file) return;

    const form = new FormData();
    form.append('subfolder', subfolder);
    form.append('file', file);

    btn.disabled = true;
    statusEl.textContent = 'Uploading…';
    statusEl.className = '';

    try {
      const res = await fetch('/api/assets/upload', { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.status);
      statusEl.textContent = `✓ Uploaded ${data.path}`;
      statusEl.className = '';
      fileInput.value = '';
      fileLabel.textContent = 'Choose PNG…';
    } catch (err) {
      statusEl.textContent = `✗ ${err.message}`;
      statusEl.className = 'error';
    } finally {
      btn.disabled = false;
    }
  });
}

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
