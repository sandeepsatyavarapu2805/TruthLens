/* static/script.js - UI logic connecting to backend endpoints */

const textInput = document.getElementById('textInput');
const checkBtn = document.getElementById('checkBtn');
const clearBtn = document.getElementById('clearBtn');
const copyBtn = document.getElementById('copyBtn');
const resultBox = document.getElementById('result');

const fileInput = document.getElementById('fileInput');
const scanBtn = document.getElementById('scanBtn');
const resetBtn = document.getElementById('resetBtn');
const preview = document.getElementById('preview');

const historyKey = 'truthlens_history_v1';
let history = JSON.parse(localStorage.getItem(historyKey) || '[]');

document.getElementById('year').textContent = new Date().getFullYear();

function renderHistory(){
  const list = document.getElementById('historyList');
  list.innerHTML = '';
  if (!history.length){
    list.innerHTML = '<div class="small">No history yet.</div>';
    return;
  }
  history.forEach(item=>{
    const el = document.createElement('div');
    el.className = 'history-item';
    el.textContent = `${item.type} • ${new Date(item.ts).toLocaleString()} • ${item.summary || (item.text || '').slice(0,60)}`;
    el.onclick = ()=> {
      if (item.type === 'text') {
        textInput.value = item.text;
      }
      resultBox.innerText = JSON.stringify(item.result, null, 2);
    };
    list.appendChild(el);
  });
}

function saveHistory(entry){
  history.unshift(entry);
  history = history.slice(0, 40);
  localStorage.setItem(historyKey, JSON.stringify(history));
  renderHistory();
}

// text check
checkBtn.onclick = async ()=>{
  const text = textInput.value.trim();
  if (!text) return alert('Paste a message, headline or URL to check.');
  checkBtn.disabled = true; checkBtn.textContent = 'Checking...';
  resultBox.innerText = 'Analyzing...';
  try {
    const res = await fetch('/api/factcheck/text', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ text, lang: document.getElementById('langSelect').value })
    });
    const data = await res.json();
    resultBox.innerText = JSON.stringify(data, null, 2);
    saveHistory({ type: 'text', ts: new Date().toISOString(), text, summary: data.verdict, result: data });
  } catch (e){
    resultBox.innerText = 'Request failed. ' + e;
  } finally {
    checkBtn.disabled = false; checkBtn.textContent = 'Check now';
  }
};

clearBtn.onclick = ()=>{ textInput.value=''; resultBox.innerText=''; };

copyBtn.onclick = ()=> {
  navigator.clipboard.writeText(textInput.value || '').then(()=> alert('Copied to clipboard'));
};

// media handlers
fileInput.onchange = ()=>{
  const f = fileInput.files[0];
  preview.innerHTML = '';
  if (!f) return;
  if (f.type.startsWith('image/')){
    const img = document.createElement('img'); img.src = URL.createObjectURL(f); preview.appendChild(img);
  } else {
    const v = document.createElement('video'); v.src = URL.createObjectURL(f); v.controls = true; preview.appendChild(v);
  }
};

resetBtn.onclick = ()=> { fileInput.value=''; preview.innerHTML=''; resultBox.innerText=''; };

scanBtn.onclick = async ()=>{
  const file = fileInput.files[0];
  if (!file) return alert('Choose an image or video first.');
  scanBtn.disabled = true; scanBtn.textContent = 'Analyzing...';
  resultBox.innerText = 'Analyzing media...';
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch('/api/factcheck/media', { method: 'POST', body: fd });
    const data = await res.json();
    resultBox.innerText = JSON.stringify(data, null, 2);
    saveHistory({ type: 'media', ts: new Date().toISOString(), summary: data.verdict, result: data });
  } catch (e) {
    resultBox.innerText = 'Media analysis failed. ' + e;
  } finally {
    scanBtn.disabled = false; scanBtn.textContent = 'Analyze media';
  }
};

// history controls
document.getElementById('exportBtn').onclick = ()=>{
  const blob = new Blob([JSON.stringify(history, null, 2)], {type:'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'truthlens-history.json'; a.click();
};

document.getElementById('clearHistoryBtn').onclick = ()=>{
  if (!confirm('Clear history?')) return;
  history = []; localStorage.removeItem(historyKey); renderHistory();
};

// theme toggle
document.getElementById('themeToggle').onclick = ()=>{
  document.body.classList.toggle('light');
  document.getElementById('themeToggle').textContent = document.body.classList.contains('light') ? 'Light' : 'Dark';
};

renderHistory();