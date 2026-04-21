/**
 * app.js — Anova Typist SPA Frontend Logic
 * ==========================================
 * Phases:
 *   0 — Upload & configure
 *   1 — Bilingual editor (post-transcription)
 *   2 — Download & apply translation
 */

'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────
const State = {
  phase:         0,
  uploadedFile:  null,   // File object
  uploadedURL:   null,   // Object URL for the source viewer
  result:        null,   // transcription result from API
  segments:      [],     // current (possibly edited) segments
  currentPage:   1,
  totalPages:    1,
  docxBlob:      null,   // cached DOCX bytes
  xliffBlob:     null,   // cached XLIFF bytes
  xliffFile:     null,   // File chosen for apply-xliff
  authRequired:  false,  // filled on health check
};

// ─────────────────────────────────────────────────────────────────────────────
// DOM helpers
// ─────────────────────────────────────────────────────────────────────────────
const $  = (id) => document.getElementById(id);
const show  = (id) => $(id) && $(id).classList.remove('hidden');
const hide  = (id) => $(id) && $(id).classList.add('hidden');
const isHidden = (id) => $(id)?.classList.contains('hidden');

// ─────────────────────────────────────────────────────────────────────────────
// Auth helpers
// ─────────────────────────────────────────────────────────────────────────────
function getAccessKey() {
  return $('access-key-input').value.trim();
}

function authHeaders() {
  const k = getAccessKey();
  const h = {};
  if (k) h['X-Access-Key'] = k;
  return h;
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase management
// ─────────────────────────────────────────────────────────────────────────────
function setPhase(n) {
  State.phase = n;

  // Phase dots
  const dots = ['ph0', 'ph1', 'ph2'];
  dots.forEach((id, i) => {
    const el = $(id);
    el.className = 'phase-dot';
    if (i < n)       el.classList.add('done');
    else if (i === n) el.classList.add('active');
  });

  // Sidebar controls
  const locked = n > 0;
  $('model-select').disabled      = locked;
  $('img-placeholders').disabled  = locked;
  $('xliff-enable').disabled      = locked;
  $('xliff-target-lang').disabled = locked;
  $('xliff-source-lang').disabled = locked;
  $('access-key-input').disabled  = locked;
  $('file-input').disabled        = locked;

  // Section visibility
  if (n === 0) {
    show('phase-upload');
    hide('phase-processing');
    hide('phase-editor');
    hide('phase-downloads');
  } else if (n === 1) {
    // keep upload visible but locked
    hide('phase-processing');
    show('phase-editor');
    hide('phase-downloads');
  } else if (n === 2) {
    hide('phase-editor');
    show('phase-downloads');
  }

  // Transcribe button
  updateTranscribeBtn();
}

function updateTranscribeBtn() {
  const btn = $('btn-transcribe');
  btn.disabled = !State.uploadedFile || State.phase > 0;
}

// ─────────────────────────────────────────────────────────────────────────────
// Health check — detect if auth is required
// ─────────────────────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const res = await fetch('/api/health');
    const data = await res.json();
    State.authRequired = !!data.auth_required;
    updateKeyStatus(false); // not validated yet, just init
    if (!State.authRequired) {
      hide('sidebar-auth');
    }
  } catch (_) { /* ignore */ }
}

function updateKeyStatus(validated, ok) {
  const badge = $('key-status');
  if (!State.authRequired) {
    badge.textContent = '✓ No key required';
    badge.className   = 'key-badge ok';
    return;
  }
  if (!validated) {
    badge.textContent = '⚠ Key required';
    badge.className   = 'key-badge warn';
  } else if (ok) {
    badge.textContent = '✓ Key valid';
    badge.className   = 'key-badge ok';
  } else {
    badge.textContent = '✗ Key invalid';
    badge.className   = 'key-badge warn';
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// File upload
// ─────────────────────────────────────────────────────────────────────────────
function onFileSelected(file) {
  if (!file) return;
  State.uploadedFile = file;
  if (State.uploadedURL) URL.revokeObjectURL(State.uploadedURL);
  State.uploadedURL = URL.createObjectURL(file);

  const nameEl = $('upload-filename');
  nameEl.textContent = `📄 ${file.name}  (${(file.size / 1024).toFixed(0)} KB)`;
  nameEl.classList.remove('hidden');

  updateTranscribeBtn();
}

// ─────────────────────────────────────────────────────────────────────────────
// Transcription
// ─────────────────────────────────────────────────────────────────────────────
async function startTranscription() {
  if (!State.uploadedFile) return;

  showError(null);
  setPhase(0); // will be locked during processing
  $('btn-transcribe').disabled = true;
  show('phase-processing');
  hide('phase-upload');

  const form = new FormData();
  form.append('file',  State.uploadedFile);
  form.append('model', $('model-select').value);
  form.append('include_image_placeholders', $('img-placeholders').checked ? 'true' : 'false');

  try {
    $('progress-label').textContent = 'Transcribing document…';
    const res = await fetch('/api/transcribe', {
      method:  'POST',
      headers: authHeaders(),
      body:    form,
    });

    if (res.status === 401) {
      updateKeyStatus(true, false);
      throw new Error('Invalid access key. Please enter a valid key and try again.');
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Transcription failed.');
    }

    updateKeyStatus(true, true);
    State.result   = await res.json();
    State.segments = State.result.segments || [];

    // Total pages from segments
    const pages = State.segments.map(s => s.page || 1);
    State.totalPages  = pages.length ? Math.max(...pages) : 1;
    State.currentPage = 1;

    // Reset blobs
    State.docxBlob  = null;
    State.xliffBlob = null;

    show('phase-upload');
    hide('phase-processing');
    renderEditor();
    setPhase(1);

  } catch (err) {
    show('phase-upload');
    hide('phase-processing');
    showError(err.message);
    setPhase(0);
    $('btn-transcribe').disabled = false;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Bilingual editor
// ─────────────────────────────────────────────────────────────────────────────
function renderEditor() {
  renderSourceViewer();
  renderSegmentTable();
  updatePageNav();
  $('editor-page-info').textContent =
    `${State.segments.length} segments · ${State.totalPages} page(s)`;
}

function renderSourceViewer() {
  const viewer = $('source-viewer');
  viewer.innerHTML = '';

  const ext = (State.uploadedFile?.name || '').split('.').pop().toLowerCase();
  const isPDF = ext === 'pdf';

  if (isPDF) {
    const iframe = document.createElement('iframe');
    iframe.src = `${State.uploadedURL}#page=${State.currentPage}`;
    iframe.title = 'Source document';
    viewer.appendChild(iframe);
  } else {
    const img = document.createElement('img');
    img.src = State.uploadedURL;
    img.alt = 'Source document';
    viewer.appendChild(img);
  }
}

function renderSegmentTable() {
  const tbody = $('seg-tbody');
  tbody.innerHTML = '';

  const pageSegs = State.segments.filter(s => (s.page || 1) === State.currentPage);

  if (pageSegs.length === 0) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="3" style="text-align:center;color:var(--text-muted);padding:20px">
      No segments on this page.</td>`;
    tbody.appendChild(tr);
    return;
  }

  pageSegs.forEach((seg, visIdx) => {
    const globalIdx = State.segments.indexOf(seg);
    const tr = document.createElement('tr');

    const disabled = State.phase === 2 ? 'disabled' : '';

    tr.innerHTML = `
      <td class="seg-idx">${globalIdx + 1}</td>
      <td class="seg-page">p.${seg.page || 1}</td>
      <td>
        <textarea
          class="seg-input"
          data-idx="${globalIdx}"
          rows="3"
          ${disabled}
        >${escHtml(seg.text || '')}</textarea>
      </td>`;
    tbody.appendChild(tr);
  });

  // Attach change listeners
  tbody.querySelectorAll('.seg-input').forEach(ta => {
    ta.addEventListener('input', e => {
      const idx = parseInt(e.target.dataset.idx, 10);
      State.segments[idx].text = e.target.value;
    });
    // Auto-resize
    ta.addEventListener('input', autoResize);
    autoResize.call(ta);
  });
}

function autoResize() {
  this.style.height = 'auto';
  this.style.height = this.scrollHeight + 'px';
}

function updatePageNav() {
  $('page-counter').textContent = `Page ${State.currentPage} / ${State.totalPages}`;
  $('btn-prev-page').disabled = State.currentPage <= 1;
  $('btn-next-page').disabled = State.currentPage >= State.totalPages;
}

function goToPage(delta) {
  const next = State.currentPage + delta;
  if (next < 1 || next > State.totalPages) return;
  State.currentPage = next;
  renderSourceViewer();
  renderSegmentTable();
  updatePageNav();
  // Scroll segments back to top
  $('segments-scroll').scrollTop = 0;
}

// ─────────────────────────────────────────────────────────────────────────────
// Save & Export
// ─────────────────────────────────────────────────────────────────────────────
async function saveAndExport() {
  $('btn-save-export').disabled = true;
  $('progress-label').textContent = 'Generating files…';
  show('phase-processing');
  hide('phase-editor');
  hide('phase-upload');
  showError(null);

  const body = buildExportBody();

  try {
    // Always generate DOCX
    $('progress-label').textContent = 'Generating Word document…';
    const docxRes = await fetch('/api/export-docx', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body:    JSON.stringify(body),
    });
    if (!docxRes.ok) {
      const e = await docxRes.json().catch(() => ({}));
      throw new Error(e.detail || 'DOCX generation failed.');
    }
    State.docxBlob = await docxRes.blob();

    // Optionally generate XLIFF
    const xliffEnabled = $('xliff-enable').checked;
    if (xliffEnabled) {
      $('progress-label').textContent = 'Generating XLIFF…';
      const xliffBody = {
        ...body,
        target_language: $('xliff-target-lang').value.trim() || 'EN',
        source_language: $('xliff-source-lang').value.trim() || '',
        include_bilingual_docx: true,
      };
      const xliffRes = await fetch('/api/export-xliff', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body:    JSON.stringify(xliffBody),
      });
      if (!xliffRes.ok) {
        const e = await xliffRes.json().catch(() => ({}));
        throw new Error(e.detail || 'XLIFF generation failed.');
      }
      State.xliffBlob = await xliffRes.blob();
    }

    hide('phase-processing');
    show('phase-upload');
    renderDownloads();
    setPhase(2);

    // Re-render editor in read-only mode too (re-disable textareas)
    renderSegmentTable();

  } catch (err) {
    hide('phase-processing');
    show('phase-upload');
    show('phase-editor');
    showError(err.message);
    $('btn-save-export').disabled = false;
  }
}

function buildExportBody() {
  const r = State.result || {};
  return {
    content:                  reconstructContent(),
    segments:                 State.segments,
    metadata:                 r.metadata                 || '',
    formatting_notes:         r.formatting_notes         || '',
    quality_notes:            r.quality_notes            || '',
    filename:                 r.filename                 || State.uploadedFile?.name || 'document',
    model:                    r.model                    || $('model-select').value,
    include_image_placeholders: r.include_image_placeholders ?? true,
    flagged_items:            r.flagged_items             || [],
  };
}

function reconstructContent() {
  // Rebuild content string from segments (page-ordered)
  const segs = [...State.segments].sort(
    (a, b) => (a.page - b.page) || (a.block_idx - b.block_idx) || (a.sent_idx - b.sent_idx)
  );
  const blocks = {};
  segs.forEach(s => {
    const key = `${s.page}|${s.block_idx ?? 0}`;
    if (!blocks[key]) blocks[key] = { page: s.page, bi: s.block_idx ?? 0, texts: [] };
    blocks[key].texts.push(s.text || '');
  });
  const sorted = Object.values(blocks).sort((a, b) => a.page - b.page || a.bi - b.bi);
  const lines = [];
  let lastPage = 0;
  sorted.forEach(b => {
    if (b.page > lastPage && lastPage > 0) lines.push('\n---PAGE BREAK---\n');
    lastPage = b.page;
    lines.push(b.texts.join(' '));
  });
  return lines.join('\n\n');
}

// ─────────────────────────────────────────────────────────────────────────────
// Downloads
// ─────────────────────────────────────────────────────────────────────────────
function renderDownloads() {
  const xliffWrap = $('dl-xliff-wrap');
  if (State.xliffBlob) {
    xliffWrap.style.display = '';
  } else {
    xliffWrap.style.display = 'none';
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement('a');
  a.href     = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function getOutputBasename() {
  const fn = State.result?.filename || State.uploadedFile?.name || 'document';
  return fn.replace(/\.[^.]+$/, '');
}

// ─────────────────────────────────────────────────────────────────────────────
// Apply translated XLIFF
// ─────────────────────────────────────────────────────────────────────────────
async function applyXliff() {
  if (!State.xliffFile) return;
  $('btn-apply-xliff').disabled = true;
  $('btn-apply-xliff').textContent = '⚙ Generating…';
  showError(null);

  const form = new FormData();
  form.append('file', State.xliffFile);

  try {
    const res = await fetch('/api/apply-xliff', {
      method:  'POST',
      headers: authHeaders(),
      body:    form,
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.detail || 'Apply XLIFF failed.');
    }
    const blob = await res.blob();
    const base = getOutputBasename();
    downloadBlob(blob, `${base}_translated.docx`);
  } catch (err) {
    showError(err.message);
  } finally {
    $('btn-apply-xliff').disabled = false;
    $('btn-apply-xliff').textContent = '⚙ Generate Translated Word';
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Error display
// ─────────────────────────────────────────────────────────────────────────────
function showError(msg) {
  if (!msg) {
    hide('error-banner');
    return;
  }
  $('error-msg').textContent = msg;
  show('error-banner');
}

// ─────────────────────────────────────────────────────────────────────────────
// Reset
// ─────────────────────────────────────────────────────────────────────────────
function resetWorkflow() {
  State.phase        = 0;
  State.uploadedFile = null;
  if (State.uploadedURL) { URL.revokeObjectURL(State.uploadedURL); State.uploadedURL = null; }
  State.result       = null;
  State.segments     = [];
  State.currentPage  = 1;
  State.totalPages   = 1;
  State.docxBlob     = null;
  State.xliffBlob    = null;
  State.xliffFile    = null;

  $('file-input').value            = '';
  $('upload-filename').textContent = '';
  hide('upload-filename');
  $('seg-tbody').innerHTML         = '';
  $('source-viewer').innerHTML     = '';
  $('xliff-upload-name').textContent = '';
  hide('xliff-upload-name');
  $('btn-apply-xliff').disabled    = true;

  showError(null);
  setPhase(0);
}

// ─────────────────────────────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ─────────────────────────────────────────────────────────────────────────────
// XLIFF option toggle
// ─────────────────────────────────────────────────────────────────────────────
function toggleXliffOptions() {
  const opts = $('xliff-options');
  if ($('xliff-enable').checked) {
    opts.classList.remove('hidden');
    opts.style.display = 'flex';
  } else {
    opts.classList.add('hidden');
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Event Wiring
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  checkHealth();

  // File input
  $('file-input').addEventListener('change', e => {
    onFileSelected(e.target.files[0] || null);
  });

  // Drag & drop
  const zone = $('upload-zone');
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const f = e.dataTransfer.files[0];
    if (f) {
      $('file-input').files = e.dataTransfer.files;
      onFileSelected(f);
    }
  });

  // Transcribe
  $('btn-transcribe').addEventListener('click', startTranscription);

  // Page navigation
  $('btn-prev-page').addEventListener('click', () => goToPage(-1));
  $('btn-next-page').addEventListener('click', () => goToPage(+1));

  // Save & Export
  $('btn-save-export').addEventListener('click', saveAndExport);

  // Reset buttons
  $('btn-reset').addEventListener('click', resetWorkflow);
  $('btn-new-doc').addEventListener('click', resetWorkflow);

  // Download buttons
  $('btn-dl-docx').addEventListener('click', () => {
    if (State.docxBlob)
      downloadBlob(State.docxBlob, `${getOutputBasename()}_transcription.docx`);
  });
  $('btn-dl-xliff').addEventListener('click', () => {
    if (State.xliffBlob)
      downloadBlob(State.xliffBlob, `${getOutputBasename()}.xlf`);
  });

  // Apply XLIFF file picker
  $('xliff-upload-input').addEventListener('change', e => {
    const f = e.target.files[0];
    if (!f) return;
    State.xliffFile = f;
    $('xliff-upload-name').textContent = f.name;
    show('xliff-upload-name');
    $('btn-apply-xliff').disabled = false;
  });

  // Apply XLIFF
  $('btn-apply-xliff').addEventListener('click', applyXliff);

  // XLIFF toggle
  $('xliff-enable').addEventListener('change', toggleXliffOptions);

  // Initial phase
  setPhase(0);
});
