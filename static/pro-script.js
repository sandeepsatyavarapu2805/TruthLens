/* pro-script.js - Handles theme, language, analyze interactions, toasts, animations */

/* State */
let translations = {};
let currentLang = localStorage.getItem('tl_lang') || 'en';
let currentTheme = localStorage.getItem('tl_theme') || 'midnight';
document.documentElement.setAttribute('data-theme', currentTheme);

async function fetchTranslations(){
  try{
    const r = await fetch('/translations');
    if(r.ok) translations = await r.json();
    else throw new Error('no translations');
  }catch(e){
    translations = { en: { appName:'TruthLens', tagline:'See the Truth Beyond the Noise.' } };
  }
  initUI();
}

/* Populate selects & apply language/theme */
function initUI(){
  // Language select(s)
  document.querySelectorAll('#langSelect').forEach(s=>{
    s.innerHTML = '';
    Object.keys(translations).forEach(code=>{
      const opt = document.createElement('option'); opt.value=code; opt.textContent = code.toUpperCase(); s.appendChild(opt);
    });
    s.value = currentLang;
    s.onchange = (e)=>changeLanguage(e.target.value);
  });
  // Theme select(s)
  const themes = ['ocean','emerald','crimson','midnight','classic','royal'];
  document.querySelectorAll('#themeSelect').forEach(s=>{
    s.innerHTML = '';
    themes.forEach(t=>{
      const opt = document.createElement('option'); opt.value = t; opt.textContent = t.charAt(0).toUpperCase()+t.slice(1); s.appendChild(opt);
    });
    s.value = currentTheme;
    s.onchange = (e)=>changeTheme(e.target.value);
  });
  applyLanguage(currentLang);
  applyTheme(currentTheme);
  attachAnalyzeHandlers();
  loadHistory();
}

/* Language application */
function applyLanguage(lang){
  currentLang = lang; localStorage.setItem('tl_lang', lang);
  const dict = translations[lang] || translations['en'];
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const key = el.getAttribute('data-i18n');
    if(dict[key]) el.textContent = dict[key];
  });
  // placeholders
  document.querySelectorAll('textarea, input').forEach(inp=>{
    if(inp.id === 'inputContent' && dict.searchPlaceholder) inp.placeholder = dict.searchPlaceholder;
  });
  // notify server (best-effort)
  fetch('/api/language', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({language:lang})}).catch(()=>{});
}

/* Theme */
function applyTheme(theme){
  currentTheme = theme; localStorage.setItem('tl_theme', theme);
  document.documentElement.setAttribute('data-theme', theme);
}
function changeTheme(t){ applyTheme(t); fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({theme:t})}).catch(()=>{}); showToast('Theme saved', 'success'); }

/* Toasts */
function showToast(msg, type='info'){
  const el = document.createElement('div'); el.className = `toast ${type}`; el.textContent = msg; document.body.appendChild(el);
  setTimeout(()=>el.classList.add('visible'), 40);
  setTimeout(()=>{ el.classList.remove('visible'); setTimeout(()=>el.remove(),300); }, 3000);
}

/* Analyze */
function attachAnalyzeHandlers(){
  const btnText = document.getElementById('btnAnalyzeText');
  if(btnText) btnText.onclick = async ()=>{
    const content = document.getElementById('inputContent').value.trim();
    if(!content){ showToast('Enter text or URL', 'warning'); return; }
    await analyze({type:'text', content});
  };
  const btnFile = document.getElementById('btnAnalyzeFile');
  if(btnFile) btnFile.onclick = async ()=>{
    const f = document.getElementById('fileInput').files[0];
    if(!f){ showToast('Choose a file', 'warning'); return; }
    const fd = new FormData(); fd.append('type','image'); fd.append('file', f);
    await doAnalyzeForm(fd);
  };
  const btnTranscript = document.getElementById('btnAnalyzeTranscript');
  if(btnTranscript) btnTranscript.onclick = async ()=>{
    const content = document.getElementById('transcriptInput').value.trim();
    if(!content){ showToast('Paste transcript', 'warning'); return; }
    await analyze({type:'video', content});
  };

  // copy / clear
  const btnCopy = document.getElementById('btnCopy');
  if(btnCopy) btnCopy.onclick = ()=>{ navigator.clipboard.writeText(document.getElementById('inputContent').value||''); showToast('Copied', 'success'); };
  const btnClear = document.getElementById('btnClear');
  if(btnClear) btnClear.onclick = ()=>{ document.getElementById('inputContent').value=''; showToast('Cleared', 'info'); };
}

/* analyze helpers */
async function analyze(payload){
  try{
    showToast('Analyzing…','info');
    const res = await fetch('/api/analyze', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const data = await res.json();
    if(data.status === 'ok'){ renderResult(data.result); showToast('Done','success'); loadHistory(); }
    else showToast('Error: '+(data.message||'unknown'), 'error');
  }catch(e){
    showToast('Network/API error', 'error');
  }
}
async function doAnalyzeForm(fd){
  try{
    showToast('Analyzing file…','info');
    const res = await fetch('/api/analyze', {method:'POST', body: fd});
    const data = await res.json();
    if(data.status === 'ok'){ renderResult(data.result); showToast('Done','success'); loadHistory(); }
    else showToast('Error: '+(data.message||'unknown'), 'error');
  }catch(e){ showToast('Network/API error', 'error'); }
}

/* Render results */
function renderResult(result){
  const area = document.getElementById('resultsArea');
  if(!area) return;
  area.innerHTML = '';
  const score = result.credibility_score || 0;
  const cat = result.category || 'unverifiable';
  const summary = result.summary || result.explanation || '';
  const sources = (result.source_links && result.source_links.length) ? result.source_links : [];
  const wrapper = document.createElement('div');
  wrapper.innerHTML = `
    <div class="row" style="align-items:flex-start;gap:16px;">
      <div style="width:220px;">
        <div style="font-weight:700">Score</div>
        <div class="scoreBar"><div class="scoreFill" style="width:0%"></div></div>
        <div style="margin-top:8px">${score} / 100 • <strong>${cat}</strong></div>
      </div>
      <div style="flex:1;">
        <div style="font-weight:700">Summary</div>
        <div>${escapeHTML(summary).replace(/\n/g,'<br/>')}</div>
        <div style="margin-top:8px;font-weight:700">Sources</div>
        <ul>${sources.map(s=>`<li><a href="${s}" target="_blank" rel="noopener">${s}</a></li>`).join('')}</ul>
      </div>
    </div>
  `;
  area.appendChild(wrapper);
  // animate score
  requestAnimationFrame(()=>{ document.querySelectorAll('.scoreFill').forEach(el=> el.style.width = score + '%'); });
}

/* escape helper */
function escapeHTML(s){ return String(s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

/* History load */
async function loadHistory(){
  try{
    const res = await fetch('/api/history'); if(!res.ok) return;
    const data = await res.json();
    if(data.status !== 'ok') return;
    const list = document.getElementById('historyList');
    if(!list) return;
    list.innerHTML = '';
    data.history.slice(0,12).forEach(h=>{
      const li = document.createElement('div'); li.className = 'history-item';
      li.innerHTML = `<div><strong>${h.input_type}</strong> • ${new Date(h.created_at).toLocaleString()}</div><div class="muted small">${(h.result && h.result.summary) ? h.result.summary.slice(0,140) : ''}</div>`;
      li.onclick = ()=>{ renderResult(h.result); window.scrollTo({top:0,behavior:'smooth'}); };
      list.appendChild(li);
    });
  }catch(e){}
}

/* Init */
window.addEventListener('DOMContentLoaded', async ()=>{
  await fetchTranslations();
});