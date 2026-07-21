// API base: same-origin '/api/music' in production (the static site and Functions
// live under one App Platform domain, path-routed). For local dev against
// functions/local_dev_server.py on a different port, set it before this script
// runs, e.g. in the browser console: localStorage.setItem('api_base', 'http://localhost:8787/api/music')
const API_BASE = localStorage.getItem('api_base') || '/api/music';

async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(`${API_BASE}/${path}`, {
    method,
    credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty body, e.g. 204 */ }
  if (!res.ok) {
    throw new Error((data && data.error) || `${path} failed (${res.status})`);
  }
  return data;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

// Shows a spinner + label inside a button and disables it while busy, restoring
// its original label and enabled state afterward - used for every action that
// makes a Function call, so it's always visible that something is in flight.
function setBusy(btn, busy, busyLabel) {
  if (!btn) return;
  if (busy) {
    if (btn.dataset.idleLabel === undefined) btn.dataset.idleLabel = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-icon"></span>${escapeHtml(busyLabel || btn.dataset.idleLabel)}`;
  } else {
    btn.disabled = false;
    btn.textContent = btn.dataset.idleLabel !== undefined ? btn.dataset.idleLabel : btn.textContent;
  }
}

const els = {
  loginGate: document.getElementById('login-gate'),
  app: document.getElementById('app'),
  whoami: document.getElementById('whoami'),
  signinBtn: document.getElementById('signin-btn'),
  signoutBtn: document.getElementById('signout-btn'),
  authStatus: document.getElementById('auth-status'),
  form: document.getElementById('generate-form'),
  result: document.getElementById('result'),
  count: document.getElementById('count'),
  countVal: document.getElementById('count-val'),
};

// --- Auth -------------------------------------------------------------

async function checkAuth() {
  const data = await api('whoami');
  els.loginGate.hidden = !!data.authenticated;
  els.app.hidden = !data.authenticated;
  if (data.authenticated) {
    els.whoami.textContent = `Signed in as ${data.title || data.username}`;
    if (!autocompleteData) loadAutocompleteData();
  }
  return data.authenticated;
}

let pollTimer = null;

els.signinBtn.addEventListener('click', async () => {
  setBusy(els.signinBtn, true, 'Starting sign-in...');
  els.authStatus.textContent = '';
  try {
    const { pin_id, auth_url } = await api('plex-auth-start', { method: 'POST' });
    window.open(auth_url, '_blank', 'noopener');
    setBusy(els.signinBtn, true, 'Waiting for Plex...');
    els.authStatus.textContent = 'Finish signing in with Plex in the new tab, then come back here.';

    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const res = await api('plex-auth-poll', { method: 'POST', body: { pin_id } });
        if (res.status === 'ok') {
          clearInterval(pollTimer);
          setBusy(els.signinBtn, false);
          els.authStatus.textContent = '';
          await checkAuth();
        } else if (res.status === 'denied') {
          clearInterval(pollTimer);
          setBusy(els.signinBtn, false);
          els.authStatus.textContent = res.message || 'Access denied.';
        }
      } catch (err) {
        clearInterval(pollTimer);
        setBusy(els.signinBtn, false);
        els.authStatus.textContent = `Sign-in failed: ${err.message}`;
      }
    }, 2000);
  } catch (err) {
    setBusy(els.signinBtn, false);
    els.authStatus.textContent = `Sign-in failed: ${err.message}`;
  }
});

els.signoutBtn.addEventListener('click', async () => {
  setBusy(els.signoutBtn, true, 'Signing out...');
  try {
    await api('logout', { method: 'POST' });
    await checkAuth();
  } finally {
    setBusy(els.signoutBtn, false);
  }
});

// --- Autocomplete -------------------------------------------------------
//
// Seed-song/genre/style/mood suggestions used to call a Function per keystroke
// (seed-search/label-search), which builds the full ParquetDataSource including
// the ~50MB embeddings matrix on a cold container - a several-second delay on
// every few keystrokes. Instead, autocomplete-data is fetched once (right after
// sign-in) and all filtering happens in the browser against that cached copy, so
// typing feels instant regardless of container warmth.

// Raw response is flat delimited strings (see get_cached_autocomplete_data's
// docstring for why) - "Artist - Title" per song, "source|label|track_count" per
// label - parsed apart here into the shapes the rest of this file wants.
let autocompleteData = null; // { songs: ["Artist - Title", ...], labels: [{source, label, track_count}] }

// Whether OPENROUTER_API_KEY is configured and DISABLE_AI_FEATURES isn't set
// server-side (see functions/packages/music/autocomplete-data). Defaults true
// so older cached responses without the field don't hide anything.
let aiEnabled = true;

async function loadAutocompleteData() {
  try {
    const raw = await api('autocomplete-data');
    autocompleteData = {
      songs: raw.songs,
      labels: raw.labels.map((s) => {
        const [source, label, track_count] = s.split('|');
        return { source, label, track_count: Number(track_count) };
      }),
    };
    aiEnabled = raw.ai_enabled !== false;
  } catch (err) {
    console.warn('Failed to load autocomplete data:', err);
    autocompleteData = { songs: [], labels: [] };
  }
  if (!aiEnabled) {
    const vibeField = document.getElementById('vibe-field');
    if (vibeField) vibeField.hidden = true;
  }
}

function wireAutocomplete(inputId, listId, getItems, onPick) {
  const input = document.getElementById(inputId);
  const list = document.getElementById(listId);
  if (!input || !list) return;

  input.addEventListener('input', () => {
    const q = input.value.trim();
    if (!q) { list.innerHTML = ''; return; }
    const items = getItems(q.toLowerCase());
    list.innerHTML = items.map((item, i) => `<li class="suggestion-item" data-idx="${i}">${escapeHtml(item.label)}</li>`).join('');
    list.querySelectorAll('.suggestion-item').forEach((el, i) => {
      el.addEventListener('click', () => {
        onPick(items[i].value, input);
        list.innerHTML = '';
      });
    });
  });
}

wireAutocomplete('seed_song', 'seed_song-matches', (needle) => {
  if (!autocompleteData) return [];
  return autocompleteData.songs
    .filter((s) => s.toLowerCase().includes(needle))
    .slice(0, 8)
    .map((s) => ({ label: s, value: s }));
}, (value, input) => { input.value = value; });

const LABEL_SOURCE_BY_FIELD = { genre: 'discogs genre', style: 'allmusic style', mood: 'allmusic mood' };

for (const field of ['genre', 'style', 'mood']) {
  const source = LABEL_SOURCE_BY_FIELD[field];
  wireAutocomplete(field, `${field}-matches`, (needle) => {
    if (!autocompleteData) return [];
    return autocompleteData.labels
      .filter((l) => l.source === source && l.label.toLowerCase().includes(needle))
      .slice(0, 10)
      .map((l) => ({ label: `${l.label} (${l.track_count})`, value: l.label }));
  }, (value, input) => { input.value = value; });
}

els.count.addEventListener('input', () => { els.countVal.textContent = els.count.value; });

// --- Generate -> preview -> (generate title -> generate cover) -> push ----

let currentTracks = null;
let currentMeta = null;
let currentCoverUrl = null;
let currentCoverKey = null;
let currentCoverPrompt = null;
let currentParams = null;

function formToParams() {
  const f = els.form;
  const num = (id) => f.elements[id].value ? Number(f.elements[id].value) : undefined;
  return {
    prompt: f.elements['prompt'].value || undefined,
    seed_song: f.elements['seed_song'].value || undefined,
    mood: f.elements['mood'].value || undefined,
    style: f.elements['style'].value || undefined,
    genre: f.elements['genre'].value || undefined,
    count: num('count'),
    min_artists: num('min_artists'),
    artist_window: num('artist_window'),
    album_window: num('album_window'),
    ignore_play_history: f.elements['ignore_play_history'].checked,
    recent_days: num('recent_days'),
    novelty: f.elements['novelty'].value,
  };
}

function defaultTitle(params) {
  const seed = params.prompt || params.seed_song || params.mood || params.style || params.genre
    || (params.recent_days ? `Recent Mix (${params.novelty})` : 'Mix');
  return `Discovery - ${seed.replace(/\b\w/g, (c) => c.toUpperCase())}`;
}

function renderTrackTable(tracks) {
  const rows = tracks.map((t, i) => `
    <tr>
      <td>${i + 1}</td>
      <td>${escapeHtml(t.artist)}</td>
      <td>${escapeHtml(t.title)}</td>
      <td>${escapeHtml(t.album)}</td>
      <td>${t.sim_score != null ? t.sim_score.toFixed(3) : ''}</td>
    </tr>`).join('');
  return `
    <table class="track-table">
      <thead><tr><th>#</th><th>Artist</th><th>Title</th><th>Album</th><th>Sim</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderPreview(title, coverDataUri) {
  const coverHtml = coverDataUri ? `<img class="cover-preview" src="${coverDataUri}" alt="Generated playlist cover art">` : '';
  const creativeActionsHtml = aiEnabled ? `
      <div class="creative-actions">
        <button id="generate-title-btn" type="button">Generate Title (AI)</button>
        <span id="title-status" class="muted"></span>
      </div>
      <div class="creative-actions" id="cover-action-slot"></div>
      <div id="cover-slot">${coverHtml}</div>` : '';
  els.result.innerHTML = `
    <div class="preview">
      <h2 id="preview-title">${escapeHtml(title)}</h2>
      <p class="meta muted">${escapeHtml(currentMeta.description)} &middot; ${currentMeta.generated_count}/${currentMeta.target_count} tracks &middot;
        ${currentMeta.unique_artists} unique artists &middot; ${currentMeta.unique_albums} unique albums</p>
      ${renderTrackTable(currentTracks)}
      <div class="field">
        <label for="push-title">Plex playlist title</label>
        <input type="text" id="push-title" value="${escapeHtml(title)}">
      </div>
      ${creativeActionsHtml}
      <div class="field checkbox-field">
        <label><input type="checkbox" id="keep-existing"> Keep existing Plex playlist with the same title instead of overwriting it</label>
      </div>
      <button id="push-btn" type="button">Push to Plex</button>
      <button id="regenerate-btn" type="button">Regenerate</button>
    </div>`;

  document.getElementById('push-btn').addEventListener('click', doPush);
  document.getElementById('regenerate-btn').addEventListener('click', () => els.form.requestSubmit());
  if (aiEnabled) {
    document.getElementById('generate-title-btn').addEventListener('click', doGenerateTitle);
    if (coverDataUri) showGenerateCoverButton();
  }
}

async function doGenerateTitle() {
  const btn = document.getElementById('generate-title-btn');
  const status = document.getElementById('title-status');
  status.textContent = '';
  setBusy(btn, true, 'Generating title...');
  try {
    const creative = await api('creative', { method: 'POST', body: { description: currentMeta.description, tracks: currentTracks } });
    currentCoverPrompt = creative.cover_prompt;
    if (creative.title) {
      document.getElementById('preview-title').textContent = creative.title;
      document.getElementById('push-title').value = creative.title;
    }
    showGenerateCoverButton();
  } catch (err) {
    status.textContent = `Title generation failed: ${err.message}`;
  } finally {
    setBusy(btn, false);
  }
}

function showGenerateCoverButton() {
  const slot = document.getElementById('cover-action-slot');
  if (document.getElementById('generate-cover-btn')) return;
  slot.innerHTML = `<button id="generate-cover-btn" type="button">Generate Cover Art (AI)</button> <span id="cover-status" class="muted"></span>`;
  document.getElementById('generate-cover-btn').addEventListener('click', doGenerateCover);
}

async function doGenerateCover() {
  const btn = document.getElementById('generate-cover-btn');
  const status = document.getElementById('cover-status');
  status.textContent = '';
  setBusy(btn, true, 'Generating cover art...');
  try {
    const cover = await api('cover', {
      method: 'POST',
      body: { description: currentMeta.description, tracks: currentTracks, prompt: currentCoverPrompt },
    });
    if (cover.cover_url) {
      currentCoverUrl = cover.cover_url;
      currentCoverKey = cover.cover_key;
      document.getElementById('cover-slot').innerHTML =
        `<img class="cover-preview" src="${cover.cover_url}" alt="Generated playlist cover art">`;
    } else {
      status.textContent = 'No image came back (the prompt may have been moderated) - try again.';
    }
  } catch (err) {
    status.textContent = `Cover generation failed: ${err.message}`;
  } finally {
    setBusy(btn, false);
  }
}

els.form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const genBtn = document.getElementById('generate-btn');
  setBusy(genBtn, true, 'Generating playlist...');
  els.result.innerHTML = '';
  currentCoverUrl = null;
  currentCoverKey = null;
  currentCoverPrompt = null;

  const params = formToParams();
  const cover_url = els.form.elements['cover_url'].value.trim();
  const titleOverride = els.form.elements['title'].value.trim();

  try {
    const gen = await api('generate', { method: 'POST', body: params });
    currentTracks = gen.tracks;
    currentMeta = gen.meta;
    currentParams = params;

    const title = titleOverride || defaultTitle(params);
    renderPreview(title, cover_url || null);
  } catch (err) {
    els.result.innerHTML = `<div class="error-box">${escapeHtml(err.message)}</div>`;
  } finally {
    setBusy(genBtn, false);
  }
});

async function doPush() {
  const pushBtn = document.getElementById('push-btn');
  const title = document.getElementById('push-title').value.trim();
  const overwrite = !document.getElementById('keep-existing').checked;
  const manualCoverUrl = els.form.elements['cover_url'].value.trim();

  setBusy(pushBtn, true, 'Pushing...');
  try {
    const res = await api('push', {
      method: 'POST',
      body: {
        tracks: currentTracks,
        title,
        overwrite,
        cover_url: currentCoverUrl || manualCoverUrl || undefined,
        cover_key: currentCoverUrl ? currentCoverKey : undefined,
        params: currentParams,
        description: currentMeta ? currentMeta.description : undefined,
      },
    });
    els.result.insertAdjacentHTML('beforeend', `<div class="success-box">${escapeHtml(res.message)}</div>`);
    loadHistory();
  } catch (err) {
    els.result.insertAdjacentHTML('beforeend', `<div class="error-box">${escapeHtml(err.message)}</div>`);
  } finally {
    setBusy(pushBtn, false);
  }
}

// --- History --------------------------------------------------------------

const els2 = { historyList: document.getElementById('history-list') };

function renderHistory(entries) {
  if (!entries.length) {
    els2.historyList.innerHTML = '<p class="muted">No playlists pushed yet.</p>';
    return;
  }
  const rows = entries.map((e) => `
    <tr>
      <td>${escapeHtml(e.title)}</td>
      <td class="muted">${escapeHtml(e.description || '')}</td>
      <td>${e.track_count}</td>
      <td class="muted">${escapeHtml((e.updated_at || '').slice(0, 10))}</td>
      <td class="history-actions">
        <button type="button" data-action="refresh" data-title="${escapeHtml(e.title)}">Refresh</button>
        <button type="button" class="danger" data-action="delete" data-title="${escapeHtml(e.title)}">Delete</button>
      </td>
    </tr>`).join('');

  els2.historyList.innerHTML = `
    <table class="track-table history-table">
      <thead><tr><th>Title</th><th>Seed</th><th>Tracks</th><th>Updated</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;

  els2.historyList.querySelectorAll('button[data-action]').forEach((btn) => {
    btn.addEventListener('click', () => onHistoryAction(btn.dataset.action, btn.dataset.title, btn));
  });
}

async function loadHistory() {
  try {
    const data = await api('history-list');
    renderHistory(data.history || []);
  } catch (err) {
    els2.historyList.innerHTML = `<p class="muted">Could not load history: ${escapeHtml(err.message)}</p>`;
  }
}

async function onHistoryAction(action, title, btn) {
  setBusy(btn, true, action === 'refresh' ? 'Refreshing...' : 'Deleting...');
  try {
    if (action === 'refresh') {
      const res = await api('history-refresh', { method: 'POST', body: { title } });
      els.result.innerHTML = `<div class="success-box">${escapeHtml(res.message)}</div>`;
    } else if (action === 'delete') {
      await api('history-delete', { method: 'POST', body: { title } });
    }
  } catch (err) {
    els.result.innerHTML = `<div class="error-box">${escapeHtml(err.message)}</div>`;
  }
  loadHistory();
}

checkAuth().then((authenticated) => { if (authenticated) loadHistory(); });

// Footer build badge - lets an owner see which SynthDigger version is live. The
// endpoint is public and optional; a failure here must never affect the app.
api('version')
  .then((v) => {
    const el = document.getElementById('app-version');
    if (el && v && v.app_version) el.textContent = `SynthDigger v${v.app_version}`;
  })
  .catch(() => { /* version endpoint unavailable - leave the footer blank */ });
