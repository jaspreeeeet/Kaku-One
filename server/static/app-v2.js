const API_BASE = 'https://kaku-one-gamma.vercel.app';

const ROUTES = {
  mimiclaw: {
    expressions: `${API_BASE}/mimiclaw/expressions`,
    expression: `${API_BASE}/mimiclaw/expression`,
    animation: `${API_BASE}/mimiclaw/api/animation`,
    status: `${API_BASE}/mimiclaw/api/status`,
    stream: `${API_BASE}/mimiclaw/stream`,
    upload: `${API_BASE}/api/assets/upload`,
  },
  music: {
    health: `${API_BASE}/music/health`,
    list: `${API_BASE}/music/list`,
    upload: `${API_BASE}/music/upload`,
    stream: `${API_BASE}/music/stream`,
    file: `${API_BASE}/music`,
  },
};

const EXPRESSION_LABELS = {
  idle: 'Idle',
  happy: 'Happy',
  sad: 'Sad',
  angry: 'Angry',
  surprised: 'Surprised',
  thinking: 'Thinking',
  talking: 'Talking',
  sleeping: 'Sleeping',
  confused: 'Confused',
  excited: 'Excited',
  smug: 'Smug',
  embarrassed: 'Embarrassed',
};

let currentExpression = null;

function renderLayout() {
  document.getElementById('app-root').innerHTML = `
    <nav class="system-switcher" aria-label="System switcher">
      <button class="system-tab active" data-system="mimiclaw" type="button">MimiClaw</button>
      <button class="system-tab" data-system="esp32winamp" type="button">ESP32 Winamp</button>
    </nav>

    <section id="mimiclaw-panel" class="system-panel active">
      <div class="panel-grid">
        <section class="preview-section">
          <div class="amoled-frame">
            <img id="stream-img" alt="Live expression stream" />
          </div>
          <div class="current-expr-label">
            Current: <strong id="current-expr-name">--</strong>
          </div>
        </section>

        <section class="controls-section">
          <h2>Expressions</h2>
          <div id="expr-grid" class="expr-grid"></div>
        </section>

        <section class="upload-section">
          <h2>Upload Sprite</h2>
          <form id="upload-form">
            <select id="upload-subfolder" required>
              <option value="">Select layer</option>
              <option value="base">base (face)</option>
              <option value="eyes">eyes</option>
              <option value="mouths">mouths</option>
              <option value="extras">extras</option>
            </select>
            <label class="file-label">
              <input type="file" id="upload-file" accept=".png" required />
              <span id="file-name-label">Choose PNG...</span>
            </label>
            <button type="submit" class="btn primary">Upload</button>
            <span id="upload-status"></span>
          </form>
        </section>

        <section class="animation-section">
          <h2>Animation Tuning</h2>
          <form id="animation-form">
            <label>
              Stream FPS
              <input id="anim-stream-fps" type="number" min="1" max="60" step="1" required />
            </label>
            <label>
              Transition frames
              <input id="anim-transition" type="number" min="0" max="60" step="1" required />
            </label>
            <div class="animation-actions">
              <button id="anim-save" type="submit" class="btn primary">Apply</button>
              <span id="anim-status"></span>
            </div>
          </form>
        </section>

        <section class="info-section">
          <h2>MimiClaw Server Info</h2>
          <table id="info-table">
            <tr><th>Stream URL</th><td><a id="stream-url" target="_blank"></a></td></tr>
            <tr><th>Expression API</th><td><code>POST /mimiclaw/expression</code></td></tr>
            <tr><th>Animation API</th><td><code>GET/POST /mimiclaw/api/animation</code></td></tr>
            <tr><th>Connected clients</th><td id="info-clients">--</td></tr>
          </table>
          <h3>ESP32 CLI command</h3>
          <pre id="cli-hint"></pre>
        </section>
      </div>
    </section>

    <section id="esp32winamp-panel" class="system-panel">
      <div class="panel-grid panel-grid-single">
        <section class="integration-section">
          <h2>ESP32 Winamp Local Music</h2>
          <p class="section-copy">Upload MP3 files locally or stream them directly from a URL. No upstream proxy required.</p>
          <div class="meta-grid">
            <div>
              <span class="meta-label">Proxy status</span>
              <strong id="esp32-status">Checking...</strong>
            </div>
            <div>
              <span class="meta-label">Proxy route</span>
              <code>/music/*</code>
            </div>
            <div>
              <span class="meta-label">Catalog size</span>
              <strong id="esp32-count">--</strong>
            </div>
          </div>
          <div class="integration-actions">
            <button id="esp32-refresh" type="button" class="btn primary">Refresh Catalog</button>
          </div>
        </section>

        <section class="tracks-section">
          <h2>Track Catalog</h2>
          <div id="esp32-empty" class="empty-state">No tracks loaded yet.</div>
          <ul id="esp32-track-list" class="track-list"></ul>
          <audio id="esp32-player" controls preload="none" class="player"></audio>
        </section>

        <section class="tracks-section">
          <h2>Upload MP3</h2>
          <form id="music-upload-form">
            <label class="file-label">
              <input type="file" id="music-upload-file" accept=".mp3" required />
              <span id="music-upload-label">Choose MP3...</span>
            </label>
            <button type="submit" class="btn primary">Upload</button>
            <span id="music-upload-status"></span>
          </form>
        </section>

        <section class="tracks-section">
          <h2>Play From URL</h2>
          <form id="music-url-form">
            <label>
              MP3 URL
              <input id="music-url-input" type="url" placeholder="https://example.com/song.mp3" required />
            </label>
            <button type="submit" class="btn primary">Stream</button>
            <span id="music-url-status"></span>
          </form>
        </section>
      </div>
    </section>
  `;
}

function setupTabs() {
  document.querySelectorAll('.system-tab').forEach((button) => {
    button.addEventListener('click', () => {
      const system = button.dataset.system;
      document.querySelectorAll('.system-tab').forEach((item) => {
        item.classList.toggle('active', item.dataset.system === system);
      });
      document.querySelectorAll('.system-panel').forEach((panel) => {
        panel.classList.toggle('active', panel.id === `${system}-panel`);
      });
    });
  });
}

function setBadge(state) {
  const badge = document.getElementById('status-badge');
  badge.className = `badge ${state}`;
  badge.textContent = state === 'online' ? 'Online' : 'Offline';
}

function setStreamUrl() {
  const url = ROUTES.mimiclaw.stream;
  const streamLink = document.getElementById('stream-url');
  streamLink.textContent = url;
  streamLink.href = url;
  document.getElementById('stream-img').src = url;
  document.getElementById('stream-img').addEventListener('load', () => setBadge('online'));
  document.getElementById('stream-img').addEventListener('error', () => {
    setTimeout(() => {
      document.getElementById('stream-img').src = `${url}?t=${Date.now()}`;
    }, 3000);
  });
  document.getElementById('cli-hint').textContent =
    `set_display_server ${API_BASE || location.origin}`;
}

async function loadExpressions() {
  const res = await fetch(ROUTES.mimiclaw.expressions);
  const data = await res.json();
  const grid = document.getElementById('expr-grid');
  grid.innerHTML = '';

  (data.expressions || []).forEach((name) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'expr-btn';
    button.dataset.expr = name;
    button.innerHTML = `<span class="expr-btn-label">${EXPRESSION_LABELS[name] || name}</span><small>${name}</small>`;
    button.addEventListener('click', () => setExpression(name));
    grid.appendChild(button);
  });
}

async function setExpression(name) {
  const res = await fetch(ROUTES.mimiclaw.expression, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expression: name }),
  });

  if (!res.ok) {
    console.error(await res.text());
    return;
  }

  document.querySelectorAll('.expr-btn').forEach((button) => {
    button.classList.toggle('active', button.dataset.expr === name);
  });
  document.getElementById('current-expr-name').textContent = name;
  currentExpression = name;
}

async function loadAnimationConfig() {
  const res = await fetch(ROUTES.mimiclaw.animation);
  const config = await res.json();
  document.getElementById('anim-stream-fps').value = config.stream_fps ?? 12;
  document.getElementById('anim-transition').value = config.transition_frames ?? 5;
}

function setupAnimationForm() {
  document.getElementById('animation-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = document.getElementById('anim-status');
    status.className = '';
    status.textContent = 'Applying...';

    const payload = {
      stream_fps: Number(document.getElementById('anim-stream-fps').value),
      transition_frames: Number(document.getElementById('anim-transition').value),
    };

    const res = await fetch(ROUTES.mimiclaw.animation, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!res.ok) {
      status.className = 'error';
      status.textContent = data.detail || `Request failed (${res.status})`;
      return;
    }

    status.textContent = 'Applied';
    document.getElementById('anim-stream-fps').value = data.stream_fps;
    document.getElementById('anim-transition').value = data.transition_frames;
  });
}

function setupUploadForm() {
  const fileInput = document.getElementById('upload-file');
  const fileLabel = document.getElementById('file-name-label');

  fileInput.addEventListener('change', () => {
    fileLabel.textContent = fileInput.files[0]?.name || 'Choose PNG...';
  });

  document.getElementById('upload-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = document.getElementById('upload-status');
    status.className = '';
    status.textContent = 'Uploading...';

    const form = new FormData();
    form.append('subfolder', document.getElementById('upload-subfolder').value);
    form.append('file', fileInput.files[0]);

    const res = await fetch(ROUTES.mimiclaw.upload, { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) {
      status.className = 'error';
      status.textContent = data.detail || `Request failed (${res.status})`;
      return;
    }

    status.textContent = `Uploaded ${data.path}`;
    fileInput.value = '';
    fileLabel.textContent = 'Choose PNG...';
  });
}

async function pollStatus() {
  try {
    const res = await fetch(ROUTES.mimiclaw.status);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || String(res.status));
    }
    setBadge('online');
    document.getElementById('info-clients').textContent = data.connected_clients ?? '--';
    if (data.current_expression && data.current_expression !== currentExpression) {
      currentExpression = data.current_expression;
      document.getElementById('current-expr-name').textContent = currentExpression;
      document.querySelectorAll('.expr-btn').forEach((button) => {
        button.classList.toggle('active', button.dataset.expr === currentExpression);
      });
    }
  } catch {
    setBadge('offline');
  }
}

async function refreshMusicCatalog() {
  const healthRes = await fetch(ROUTES.music.health);
  const health = await healthRes.json();
  document.getElementById('esp32-status').textContent = healthRes.ok ? 'Online' : `Offline (${health.detail || healthRes.status})`;
  document.getElementById('esp32-count').textContent = health.tracks ?? '--';

  const listRes = await fetch(ROUTES.music.list);
  const listData = await listRes.json();
  const list = document.getElementById('esp32-track-list');
  const empty = document.getElementById('esp32-empty');
  const player = document.getElementById('esp32-player');

  list.innerHTML = '';
  const tracks = listRes.ok ? (listData.tracks || []) : [];
  if (!tracks.length) {
    empty.textContent = listRes.ok ? 'No tracks available yet.' : `Catalog unavailable: ${listData.detail || listRes.status}`;
    empty.style.display = 'block';
    return;
  }

  empty.style.display = 'none';
  tracks.forEach((track) => {
    const item = document.createElement('li');
    item.className = 'track-item';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'track-button';
    button.textContent = track;
    button.addEventListener('click', () => {
      player.src = `${ROUTES.music.file}/${encodeURIComponent(track)}`;
      player.play().catch(() => {});
    });

    item.appendChild(button);
    list.appendChild(item);
  });
}

function setupMusicUpload() {
  const input = document.getElementById('music-upload-file');
  const label = document.getElementById('music-upload-label');
  const status = document.getElementById('music-upload-status');

  input.addEventListener('change', () => {
    label.textContent = input.files[0]?.name || 'Choose MP3...';
  });

  document.getElementById('music-upload-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!input.files[0]) {
      return;
    }
    status.textContent = 'Uploading...';
    status.className = '';

    const form = new FormData();
    form.append('file', input.files[0]);
    const response = await fetch(ROUTES.music.upload, { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok) {
      status.textContent = data.detail || 'Upload failed';
      status.className = 'error';
      return;
    }

    status.textContent = `Uploaded ${data.filename}`;
    input.value = '';
    label.textContent = 'Choose MP3...';
    await refreshMusicCatalog();
  });
}

function setupMusicUrlStream() {
  const input = document.getElementById('music-url-input');
  const status = document.getElementById('music-url-status');
  const player = document.getElementById('esp32-player');

  document.getElementById('music-url-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    status.textContent = '';
    const url = input.value.trim();
    if (!url) {
      return;
    }
    status.textContent = 'Streaming...';
    const streamUrl = `${ROUTES.music.stream}?url=${encodeURIComponent(url)}`;
    player.src = streamUrl;
    player.play().catch(() => {});
  });
}

async function init() {
  renderLayout();
  setupTabs();
  setStreamUrl();
  setupAnimationForm();
  setupUploadForm();
  document.getElementById('esp32-refresh').addEventListener('click', refreshMusicCatalog);
  setupMusicUpload();
  setupMusicUrlStream();

  await Promise.all([
    loadExpressions(),
    loadAnimationConfig(),
    pollStatus(),
    refreshMusicCatalog(),
  ]);

  setInterval(pollStatus, 2000);
}

document.addEventListener('DOMContentLoaded', init);
