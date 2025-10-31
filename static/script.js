// static/script.js - UI logic for TruthLens SPA

const inputText = document.getElementById('inputText');
const checkBtn = document.getElementById('checkBtn');
const clearBtn = document.getElementById('clearBtn');
const resultBox = document.getElementById('resultBox');
const lastChecked = document.getElementById('lastChecked');
const langSelect = document.getElementById('lang');
const fileInput = document.getElementById('fileInput');
const analyzeBtn = document.getElementById('analyzeBtn');
const preview = document.getElementById('preview');
const resetMediaBtn = document.getElementById('resetMediaBtn');
const historyList = document.getElementById('historyList');
const clearHistory = document.getElementById('clearHistory');
const exportHistory = document.getElementById('exportHistory');
const themeToggle = document.getElementById('themeToggle');
const yearEl = document.getElementById('year');

yearEl.textContent = new Date().getFullYear();

const STORAGE_KEY = 'truthlens_v2_history';
let history = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
let selectedFile = null;

function setLastChecked(ts){
  lastChecked.textContent = ts ? new Date(ts).toLocaleString() : '—';
}

function renderHistory(){
  historyList.innerHTML = '';
  if (!history.length){ historyList.innerHTML = '<div class="muted small">No history yet</div>'; return; }
  history.forEach(h => {
    const d = document.createElement('div');
    d.className = 'history-item';
    d.innerHTML = `<div style="font-weight:600">${escapeHtml(h.input)}</div><div class="muted small">${new Date(h.ts).toLocaleString()}</div>`;
    d.onclick = () => {
      // load in input and show cached result
      inputText.value = h.input;
      renderResult(h.result);
    };
    historyList.appendChild(d);
  });
}

function saveHistory(input, result){
  const item = { id: Date.now(), ts: new Date().toISOString(), input, result };
  history.unshift(item);
  history = history.slice(0,30);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
  renderHistory();
  setLastChecked(item.ts);
}

function exportHistoryFn(){
  const blob = new Blob([JSON.stringify(history, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'truthlens-history.json'; a.click();
  URL.revokeObjectURL(url);
}

function clearHistoryFn(){
  if (!confirm('Clear all saved history?')) return;
  history = []; localStorage.removeItem(STORAGE_KEY); renderHistory(); setLastChecked(null);
}

clearHistory.addEventListener('click', clearHistoryFn);
exportHistory.addEventListener('click', exportHistoryFn);

function escapeHtml(s){ return String(s).replace(/[&<>"']/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[m]); }

function renderResult(data){
  if (!data){ resultBox.innerHTML = ''; return; }
  if (data.error){
    resultBox.innerHTML = `<div class="card"><div class="muted">Error: ${escapeHtml(data.error)}</div></div>`; return;
  }
  const score = data.score ?? 0;
  const verdict = data.verdict ?? 'Unclear';
  const explanation = data.explanation || '';
  const heuristics = (data.heuristics || []).join(', ');
  const aiCheck = data.ai_check || null;
  const sources = data.sources || [];

  let colorClass = 'score-mid';
  if (score >= 70) colorClass = 'score-good';
  if (score <= 40) colorClass = 'score-bad';

  let html = `<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div><strong style="font-size:18px">${escapeHtml(verdict)}</strong><div class="muted small">${escapeHtml(explanation)}</div></div>
      <div style="text-align:right">
        <div style="font-size:18px;font-weight:700">${escapeHtml(String(score))}</div>
        <div class="scorebar" style="width:160px;margin-top:8px"><div class="scorebar-inner ${colorClass}" style="width:${Math.max(6,score)}%"></div></div>
      </div>
    </div>`;

  if (heuristics) html += `<div class="mt small"><strong>Signals:</strong> ${escapeHtml(heuristics)}</div>`;
  if (aiCheck) html += `<div class="mt small"><strong>AI-detect:</strong> ${(aiCheck.ai_prob*100).toFixed(0)}% — ${escapeHtml(aiCheck.reason)}</div>`;
  if (sources.length){
    html += `<div class="mt"><strong>Sources</strong><ul>`;
    for (const s of sources){
      const title = escapeHtml((s.source||'source') + ' — ' + (s.verdict||''));
      const url = s.url ? `<a href="${escapeAttr(s.url)}" target="_blank" rel="noreferrer">link</a>` : '';
      html += `<li class="small">${title} ${url}</li>`;
    }
    html += `</ul></div>`;
  }

  html += `<div class="mt"><button id="shareBtn" class="btn ghost">Share</button> <button id="copyResultBtn" class="btn ghost">Copy JSON</button></div>`;
  html += `</div>`;
  resultBox.innerHTML = html;

  document.getElementById('shareBtn').onclick = () => {
    if (navigator.share){
      navigator.share({ title: 'TruthLens result', text: JSON.stringify(data, null, 2) }).catch(()=>alert('Share failed'));
    } else {
      alert('Share not supported on this device');
    }
  };
  document.getElementById('copyResultBtn').onclick = () => {
    navigator.clipboard?.writeText(JSON.stringify(data, null, 2)).then(()=> alert('Result copied'));
  };
}

function escapeAttr(s){ return String(s).replace(/"/g, '&quot;'); }

async function checkNow(){
  const text = inputText.value.trim();
  if (!text){ alert('Paste text or a URL to check'); return; }
  checkBtn.disabled = true; checkBtn.textContent = 'Checking...';
  renderResult(null);
  try {
    const payload = { text, lang: langSelect.value || 'en' };
    const res = await fetch('/api/factcheck/text', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    const data = await res.json();
    renderResult(data);
    saveHistory(text, data);
  } catch (e) {
    console.error(e);
    renderResult({ error: 'Network or server error' });
  } finally {
    checkBtn.disabled = false; checkBtn.textContent = 'Check now';
  }
}

checkBtn.addEventListener('click', checkNow);
clearBtn.addEventListener('click', ()=>{ inputText.value=''; renderResult(null); });

fileInput.addEventListener('change', (ev)=>{
  const f = ev.target.files && ev.target.files[0];
  selectedFile = f || null; preview.innerHTML = '';
  if (!f) return;
  if (f.type.startsWith('image/')){
    const img = document.createElement('img'); img.src = URL.createObjectURL(f); preview.appendChild(img);
  } else {
    const v = document.createElement('video'); v.src = URL.createObjectURL(f); v.controls=true; preview.appendChild(v);
  }
});

resetMediaBtn.addEventListener('click', ()=>{
  fileInput.value=''; selectedFile=null; preview.innerHTML='';
});

async function analyzeMedia(){
  if (!selectedFile){ alert('Choose a file first'); return; }
  analyzeBtn.disabled = true; analyzeBtn.textContent = 'Analyzing...';
  renderResult(null);
  try {
    const b64 = await fileToBase64(selectedFile);
    const payload = { b64: b64.split(',')[1] };
    const res = await fetch('/api/factcheck/media', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    const data = await res.json();
    renderResult(data);
    saveHistory('[media upload]', data);
  } catch (e) {
    console.error(e);
    renderResult({ error: 'Media analysis failed' });
  } finally {
    analyzeBtn.disabled = false; analyzeBtn.textContent = 'Analyze media';
  }
}

analyzeBtn.addEventListener('click', analyzeMedia);

function fileToBase64(file){
  return new Promise((res, rej) => {
    const reader = new FileReader();
    reader.onload = ()=> res(reader.result);
    reader.onerror = ()=> rej('read error');
    reader.readAsDataURL(file);
  });
}

// Theme toggle
themeToggle.addEventListener('click', ()=>{
  const isDark = document.body.classList.toggle('dark');
  themeToggle.textContent = isDark ? 'Light' : 'Dark';
});

// Init
renderHistory();
setLastChecked(null);

// Preload optional sample for convenience
inputText.value = 'Breaking: New government order claims everyone will get free money — viral message circulated on WhatsApp.';