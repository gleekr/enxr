/* enxr web UI — app.js */

'use strict';

// ── State ────────────────────────────────────────────────────────────────────

const state = {
  files: [],
  selected: new Set(),
  enhanceTarget: null,
  passes: 1,
  progressES: null,
  pendingUrl: null,
  history: [],
  theme: localStorage.getItem('enxr-theme') || 'dark',
};

// ── DOM helpers ──────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const qs = sel => document.querySelector(sel);

function showModal(id) { $(id).classList.remove('hidden'); }
function hideModal(id) { $(id).classList.add('hidden'); }

// ── Theme toggle ─────────────────────────────────────────────────────────────

function initTheme() {
  document.documentElement.dataset.theme = state.theme;
  $('btn-theme-toggle').textContent = state.theme === 'dark' ? '◑' : '◐';
}

$('btn-theme-toggle').addEventListener('click', () => {
  state.theme = state.theme === 'dark' ? 'light' : 'dark';
  localStorage.setItem('enxr-theme', state.theme);
  document.documentElement.dataset.theme = state.theme;
  $('btn-theme-toggle').textContent = state.theme === 'dark' ? '◑' : '◐';
});

// ── Navigation ───────────────────────────────────────────────────────────────

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const view = btn.dataset.view;
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    btn.classList.add('active');
    $(`view-${view}`).classList.add('active');
  });
});

document.querySelectorAll('.modal-close').forEach(btn => {
  btn.addEventListener('click', () => hideModal(btn.dataset.modal));
});

// ── History Management ───────────────────────────────────────────────────────

function addToHistory(entry) {
  state.history.unshift(entry);
  if (state.history.length > 100) state.history.pop();
  localStorage.setItem('enxr-history', JSON.stringify(state.history));
}

function loadHistory() {
  try {
    state.history = JSON.parse(localStorage.getItem('enxr-history') || '[]');
  } catch (e) {
    state.history = [];
  }
}

function renderHistory() {
  const list = $('history-list');
  if (!state.history.length) {
    list.innerHTML = '<div class="empty">no processing history</div>';
    return;
  }
  list.innerHTML = state.history.map((h, i) => `
    <div class="history-item">
      <div class="history-name">${h.file.split(/[\\/]/).pop()}</div>
      <div class="history-meta">${h.preset || 'level ' + (h.level || 'auto')} • ${h.passes}p • ${h.target_res}p</div>
      <div class="history-time">${new Date(h.timestamp).toLocaleString()}</div>
      <div class="history-duration">${h.duration_display}</div>
    </div>
  `).join('');
}

$('btn-history').addEventListener('click', () => {
  renderHistory();
  showModal('modal-history');
});

$('btn-clear-history').addEventListener('click', () => {
  if (confirm('Clear all processing history?')) {
    state.history = [];
    localStorage.removeItem('enxr-history');
    renderHistory();
  }
});

// ── Hardware Detection ───────────────────────────────────────────────────────

async function loadHardwareInfo() {
  try {
    const res = await fetch('/hardware');
    const info = await res.json();
    const el = $('hardware-info');
    el.innerHTML = `
      <div style="font-size:12px; line-height:1.8;">
        <p><strong>Device:</strong> ${info.device || 'unknown'}</p>
        <p><strong>Encode Encoders:</strong> ${(info.encoders || []).join(', ') || 'none detected'}</p>
        <p><strong>Calibration Speed:</strong> ${info.speed ? info.speed.toFixed(2) + ' fps at 1080p' : 'not calibrated yet'}</p>
        <p style="color:var(--dim); font-size:11px; margin-top:12px;">Speed will improve as you process videos.</p>
      </div>
    `;
  } catch (e) {
    $('hardware-info').innerHTML = `<div class="empty">failed to load hardware info</div>`;
  }
}

$('btn-hardware').addEventListener('click', () => {
  loadHardwareInfo();
  showModal('modal-hardware');
});

// ── Mobile Guide Modal ───────────────────────────────────────────────────────

$('btn-mobile-guide').addEventListener('click', () => {
  showModal('modal-mobile-guide');
});

// ── File browser ─────────────────────────────────────────────────────────────

async function loadFiles() {
  $('files-list').innerHTML = '<div class="loading">loading...</div>';
  state.selected.clear();
  updateBatchButtons();

  try {
    const res = await fetch('/files');
    state.files = await res.json();
  } catch (e) {
    $('files-list').innerHTML = `<div class="empty">failed to load: ${e.message}</div>`;
    return;
  }

  if (!state.files.length) {
    $('files-list').innerHTML = '<div class="empty">no video files found in ~/Documents</div>';
    $('files-count').textContent = '';
    return;
  }

  const originals = state.files.filter(f => !f.is_enhanced).length;
  $('files-count').textContent = `${state.files.length} files  (${originals} originals)`;

  $('files-list').innerHTML = '';
  state.files.forEach(f => {
    const row = document.createElement('div');
    row.className = 'file-row' + (f.is_enhanced ? ' enhanced' : '');
    row.dataset.path = f.path;
    row.draggable = !f.is_enhanced;

    const nameEl = document.createElement('span');
    nameEl.className = 'file-name' + (f.is_enhanced ? ' is-enhanced' : '');
    nameEl.textContent = f.name;

    const metaEl = document.createElement('span');
    metaEl.className = 'file-meta';
    metaEl.textContent = f.subfolder || '~/Documents';

    const infoEl = document.createElement('div');
    infoEl.className = 'file-info';
    infoEl.appendChild(nameEl);
    infoEl.appendChild(metaEl);

    const check = document.createElement('input');
    check.type = 'checkbox';
    check.className = 'file-check';
    check.addEventListener('change', () => {
      if (check.checked) { state.selected.add(f.path); row.classList.add('selected'); }
      else               { state.selected.delete(f.path); row.classList.remove('selected'); }
      updateBatchButtons();
    });

    const sizeEl = document.createElement('span');
    sizeEl.className = 'file-size';
    sizeEl.textContent = `${f.size_mb} MB`;

    const actions = document.createElement('div');
    actions.className = 'file-actions';

    if (!f.is_enhanced) {
      const btnEnhance = document.createElement('button');
      btnEnhance.className = 'small primary';
      btnEnhance.textContent = 'ENHANCE';
      btnEnhance.addEventListener('click', () => openEnhanceModal(f.path));
      actions.appendChild(btnEnhance);

      const exName = 'ex' + f.name;
      const pair = state.files.find(x => x.name === exName && x.subfolder === f.subfolder);
      if (pair) {
        const btnCmp = document.createElement('button');
        btnCmp.className = 'small';
        btnCmp.textContent = 'COMPARE';
        btnCmp.addEventListener('click', () => openCompare(f.path, pair.path));
        actions.appendChild(btnCmp);
      }
    }

    const btnDel = document.createElement('button');
    btnDel.className = 'small danger';
    btnDel.textContent = 'DEL';
    btnDel.addEventListener('click', () => deleteFile(f.path, row));
    actions.appendChild(btnDel);

    row.append(check, infoEl, sizeEl, actions);
    $('files-list').appendChild(row);
  });
}

function updateBatchButtons() {
  const n = state.selected.size;
  $('btn-enhance-batch').classList.toggle('hidden', n === 0);
  $('btn-delete-batch').classList.toggle('hidden', n === 0);
}

async function deleteFile(path, rowEl) {
  if (!confirm(`Delete ${path.split(/[\\/]/).pop()}?`)) return;
  const res = await fetch(`/file?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
  if (res.ok) { rowEl.remove(); }
  else { alert('delete failed'); }
}

$('btn-refresh').addEventListener('click', loadFiles);

$('btn-delete-batch').addEventListener('click', async () => {
  const paths = [...state.selected];
  if (!confirm(`Delete ${paths.length} files?`)) return;
  for (const p of paths) {
    await fetch(`/file?path=${encodeURIComponent(p)}`, { method: 'DELETE' });
  }
  loadFiles();
});

$('btn-enhance-batch').addEventListener('click', () => {
  const paths = [...state.selected];
  if (!paths.length) return;
  openEnhanceModal(paths[0]);
});

// ── Drag and drop upload ─────────────────────────────────────────────────────

let dropZoneActive = false;

document.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropZoneActive = true;
  $('files-list').classList.add('drop-active');
});

document.addEventListener('dragleave', () => {
  dropZoneActive = false;
  $('files-list').classList.remove('drop-active');
});

document.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZoneActive = false;
  $('files-list').classList.remove('drop-active');
});

// ── Download ──────────────────────────────────────────────────────────────────

$('btn-download').addEventListener('click', () => {
  const url = $('url-input').value.trim();
  if (!url) return;

  const isYT = url.includes('watch?v=') || url.includes('youtu.be/');
  const hasList = url.includes('list=');

  if (isYT && hasList) {
    state.pendingUrl = url;
    $('playlist-prompt').classList.remove('hidden');
    return;
  }
  submitDownload(url);
});

$('btn-single').addEventListener('click', () => {
  $('playlist-prompt').classList.add('hidden');
  submitDownload(state.pendingUrl);
  state.pendingUrl = null;
});

$('btn-playlist').addEventListener('click', () => {
  $('playlist-prompt').classList.add('hidden');
  submitDownload(state.pendingUrl);
  state.pendingUrl = null;
});

async function submitDownload(url) {
  const log = $('download-log');
  log.textContent = '';
  log.classList.remove('hidden');
  showProgress('indeterminate', 'DOWNLOADING...');

  const res = await fetch('/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });

  if (!res.ok) {
    const err = await res.json();
    setProgressError(err.error || 'download failed');
    return;
  }

  connectProgress(line => { log.textContent += line + '\n'; log.scrollTop = log.scrollHeight; },
                  out => { loadFiles(); $('url-input').value = ''; });
}

// ── Enhance modal ─────────────────────────────────────────────────────────────

async function openEnhanceModal(path) {
  const fname = path.split(/[\\/]/).pop();
  $('enhance-filename').textContent = fname;
  $('enhance-dims').textContent = 'probing...';
  $('enhance-codec').textContent = '';
  $('res-group').innerHTML = '';
  $('enhance-estimate').classList.add('hidden');
  resetPasses(1);
  showPresetRow(false);
  showModal('modal-enhance');

  let info;
  try {
    const res = await fetch(`/dims?file=${encodeURIComponent(path)}`);
    info = await res.json();
  } catch (e) {
    $('enhance-dims').textContent = 'probe failed';
    return;
  }

  const orient = info.is_portrait ? 'portrait' : 'landscape';
  $('enhance-dims').textContent = `${info.w}×${info.h} ${orient} / ${info.short_side}p`;
  $('enhance-codec').textContent = info.codec;

  const resGroup = $('res-group');
  if (info.is_high_res) {
    const btn = document.createElement('button');
    btn.className = 'opt-btn active';
    btn.dataset.value = info.short_side;
    btn.textContent = 'SOURCE (enhance only)';
    resGroup.appendChild(btn);
  } else {
    const recommended = info.options.length ? info.options[info.options.length - 1] : info.short_side;
    (info.options.length ? info.options : [info.short_side]).forEach(t => {
      const btn = document.createElement('button');
      btn.className = 'opt-btn' + (t === recommended ? ' active recommended' : '');
      btn.dataset.value = t;
      btn.textContent = `${t}p`;
      btn.addEventListener('click', () => {
        resGroup.querySelectorAll('.opt-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        fetchEstimate(path, t);
      });
      resGroup.appendChild(btn);
    });
    fetchEstimate(path, recommended);
  }

  state.enhanceTarget = { path, is_high_res: info.is_high_res,
                          short_side: info.short_side, options: info.options,
                          duration: info.duration };
}

async function fetchEstimate(path, targetRes) {
  const passes = state.passes;
  try {
    const r = await fetch(`/estimate?file=${encodeURIComponent(path)}&target_res=${targetRes}&passes=${passes}`);
    const d = await r.json();
    const el = $('enhance-estimate');
    if (d.estimate) {
      el.textContent = `est. ${d.estimate}  (${passes} pass${passes > 1 ? 'es' : ''} @ ${targetRes}p)`;
      el.classList.remove('hidden');
    } else {
      el.classList.add('hidden');
    }
  } catch (_) { /* silent */ }
}

document.querySelectorAll('#level-group .opt-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#level-group .opt-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});

document.querySelectorAll('#preset-group .opt-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#preset-group .opt-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});

$('passes-dec').addEventListener('click', () => {
  if (state.passes > 1) resetPasses(state.passes - 1);
});
$('passes-inc').addEventListener('click', () => {
  if (state.passes < 4) resetPasses(state.passes + 1);
});

function resetPasses(n) {
  state.passes = n;
  $('passes-val').textContent = n;
  showPresetRow(n > 1);
  if (state.enhanceTarget) {
    const active = qs('#res-group .opt-btn.active');
    if (active) fetchEstimate(state.enhanceTarget.path, parseInt(active.dataset.value));
  }
}

function showPresetRow(show) {
  $('preset-row').style.display = show ? '' : 'none';
}

$('btn-enhance-submit').addEventListener('click', async () => {
  if (!state.enhanceTarget) return;

  const { path, is_high_res, short_side } = state.enhanceTarget;
  const levelBtn = qs('#level-group .opt-btn.active');
  const resBtn   = qs('#res-group .opt-btn.active');
  const presetBtn = qs('#preset-group .opt-btn.active');

  const level      = levelBtn?.dataset.value ? parseInt(levelBtn.dataset.value) : null;
  const target_res = resBtn   ? parseInt(resBtn.dataset.value)   : null;
  const preset     = (state.passes > 1 && presetBtn) ? presetBtn.dataset.value : null;
  const ceiling    = is_high_res ? 0 : null;

  hideModal('modal-enhance');
  showProgress('indeterminate', 'STARTING ENCODE...');

  const t0 = Date.now();
  const fname = path.split(/[\\/]/).pop();

  const res = await fetch('/enhance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file: path, level, passes: state.passes, target_res, preset, ceiling }),
  });

  if (!res.ok) {
    const err = await res.json();
    setProgressError(err.error || 'enhance failed');
    return;
  }

  connectProgress(
    null,
    out => {
      const duration = ((Date.now() - t0) / 1000).toFixed(1);
      addToHistory({
        file: fname,
        preset,
        level,
        passes: state.passes,
        target_res,
        timestamp: new Date().toISOString(),
        duration_display: duration + 's',
      });
      dismissProgress();
      loadFiles();
      if (out) openCompare(path, out);
    }
  );
});

// ── SSE progress ─────────────────────────────────────────────────────────────

function connectProgress(onLine, onDone) {
  if (state.progressES) { state.progressES.close(); }
  $('job-indicator').classList.remove('hidden');

  state.progressES = new EventSource('/progress');

  state.progressES.onmessage = e => {
    const d = JSON.parse(e.data);

    if (d.stage === 'done' || d.stage === 'error') {
      state.progressES.close();
      state.progressES = null;
      $('job-indicator').classList.add('hidden');
      if (d.stage === 'error') {
        setProgressError(d.error || 'encode failed');
      } else {
        setProgressDone();
        if (onDone) onDone(d.output);
      }
      return;
    }

    if (d.stage === 'heartbeat') return;

    if (d.stage && d.stage.startsWith('cleanup')) {
      setProgressLabel(`PASS A — ${d.stage.replace('cleanup:', '').toUpperCase()}`);
      setProgressPct(5);
    } else if (d.stage && d.stage.startsWith('pass:')) {
      const label = d.stage.replace('pass:', '').toUpperCase();
      setProgressLabel(`PASS B — ${label}`);
      setProgressPct(20);
    } else if (d.stage === 'downloading') {
      setProgressLabel('DOWNLOADING...');
    } else if (d.stage === 'encoding' && d.line) {
      const pct = parseFFmpegTime(d.line);
      if (pct !== null) setProgressPct(pct);
      setProgressLabel(d.line.length > 80 ? d.line.slice(0, 80) + '…' : d.line);
      if (onLine) onLine(d.line);
    }
  };

  state.progressES.onerror = () => {
    state.progressES.close();
    state.progressES = null;
    $('job-indicator').classList.add('hidden');
  };
}

function parseFFmpegTime(line) {
  const m = line.match(/time=(\d+):(\d+):([\d.]+)/);
  if (!m || !state.enhanceTarget?.duration) return null;
  const secs = parseInt(m[1]) * 3600 + parseInt(m[2]) * 60 + parseFloat(m[3]);
  const dur  = state.enhanceTarget.duration;
  return dur > 0 ? Math.min(95, Math.round((secs / dur) * 90 + 10)) : null;
}

function showProgress(mode, label) {
  $('progress-wrap').classList.remove('hidden');
  $('progress-dismiss').classList.add('hidden');
  const bar = $('progress-bar');
  bar.classList.toggle('indeterminate', mode === 'indeterminate');
  bar.style.setProperty('--pct', '0%');
  $('progress-label').textContent = label || '';
}

function setProgressPct(pct) {
  const bar = $('progress-bar');
  bar.classList.remove('indeterminate');
  bar.style.setProperty('--pct', pct + '%');
}

function setProgressLabel(text) { $('progress-label').textContent = text; }

function setProgressDone() {
  setProgressPct(100);
  setProgressLabel('DONE');
  $('progress-dismiss').classList.remove('hidden');
}

function setProgressError(msg) {
  $('progress-bar').classList.remove('indeterminate');
  $('progress-bar').style.setProperty('--pct', '0%');
  setProgressLabel('ERROR: ' + msg);
  $('progress-dismiss').classList.remove('hidden');
  $('job-indicator').classList.add('hidden');
}

function dismissProgress() {
  $('progress-wrap').classList.add('hidden');
  $('progress-bar').style.setProperty('--pct', '0%');
}

$('progress-dismiss').addEventListener('click', dismissProgress);

// ── Before / After compare ────────────────────────────────────────────────────

function openCompare(beforePath, afterPath) {
  const toSrc = p => `/file-stream?path=${encodeURIComponent(p)}`;
  $('vid-before').src = toSrc(beforePath);
  $('vid-after').src  = toSrc(afterPath);
  showModal('modal-compare');

  const vb = $('vid-before');
  const va = $('vid-after');

  vb.addEventListener('play',   () => va.play(),   { once: false });
  vb.addEventListener('pause',  () => va.pause(),  { once: false });
  vb.addEventListener('seeked', () => { va.currentTime = vb.currentTime; });

  va.addEventListener('play',   () => vb.play(),   { once: false });
  va.addEventListener('pause',  () => vb.pause(),  { once: false });
  va.addEventListener('seeked', () => { vb.currentTime = va.currentTime; });
}

$('modal-compare').querySelector('.modal-close').addEventListener('click', () => {
  $('vid-before').pause(); $('vid-before').src = '';
  $('vid-after').pause();  $('vid-after').src  = '';
});

// ── Init ──────────────────────────────────────────────────────────────────────

initTheme();
loadHistory();
loadFiles();
