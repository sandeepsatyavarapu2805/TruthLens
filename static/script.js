// static/script.js
// Handles theme, language, translations, analyze stubs, toasts, animations

let translations = {};
let currentLang = localStorage.getItem('tl_lang') || 'en';
let currentTheme = localStorage.getItem('tl_theme') || 'ocean';

// load translations from /translations endpoint
async function loadTranslations(){
  try{
    const r = await fetch('/translations');
    if(r.ok){ translations = await r.json(); }
    else { throw new Error('no translations'); }
  }catch(e){
    translations = {
      en:{appName:'TruthLens',tagline:'See the Truth Beyond the Noise.',verifyNow:'Verify Now',login:'Login',signup:'Sign Up'},
      hi:{appName:'ट्रुथलेंस',tagline:'शोर के परे सत्य देखें।',verifyNow:'अभी सत्यापित करें',login:'लॉगइन',signup:'साइन अप'},
      te:{appName:'ట్రూథ్‌లెన్సు',tagline:'ఇప్పుడు నిర్ధారించండి',verifyNow:'ఇప్పుడు నిర్ధారించండి',login:'లాగిన్',signup:'సైన్ అప్'}
    };
  }
  initLangAndThemeUI();
  applyLanguage(currentLang);
  applyTheme(currentTheme);
}

// populate language & theme selectors
function initLangAndThemeUI(){
  const langSelects = document.querySelectorAll('#langSelect');
  langSelects.forEach(s=>{
    s.innerHTML = '';
    Object.keys(translations).forEach(k=>{
      const opt = document.createElement('option'); opt.value=k; opt.textContent=k.toUpperCase(); s.appendChild(opt);
    });
    s.value = currentLang;
    s.onchange = (e)=>changeLanguage(e.target.value);
  });
  const themes = ['ocean','emerald','crimson','midnight','classic','royal'];
  const themeSelects = document.querySelectorAll('#themeSelect');
  themeSelects.forEach(s=>{
    s.innerHTML=''; themes.forEach(t=>{ const opt=document.createElement('option'); opt.value=t; opt.textContent=t.charAt(0).toUpperCase()+t.slice(1); s.appendChild(opt);});
    s.value=currentTheme; s.onchange=(e)=>changeTheme(e.target.value);
  });
}

// apply language strings to elements with data-i18n
function applyLanguage(lang){
  currentLang = lang; localStorage.setItem('tl_lang', lang);
  const dict = translations[lang] || translations['en'];
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const key = el.getAttribute('data-i18n');
    if(dict[key]) el.textContent = dict[key];
  });
  // placeholders update
  if(document.getElementById('email')) document.getElementById('email').placeholder = dict.email || 'Email';
  if(document.getElementById('password')) document.getElementById('password').placeholder = dict.password || 'Password';
  // push language to server (best-effort)
  fetch('/api/language', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({language:lang})}).catch(()=>{});
}

function changeLanguage(l){ applyLanguage(l); showToast('Language changed','info'); }

function applyTheme(theme){ document.documentElement.setAttribute('data-theme', theme); currentTheme = theme; localStorage.setItem('tl_theme', theme); }
function changeTheme(t){ applyTheme(t); fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({theme:t})}).catch(()=>{}); showToast('Theme saved', 'success'); }

// analyze helpers
async function doAnalyze(formData){
  showToast('Analyzing...', 'info');
  try{
    const res = await fetch('/analyze', {method:'POST', body: formData});
    const data = await res.json();
    if(data.status === 'ok') { displayResults(data.result); showToast('Analysis complete', 'success'); }
    else { showToast('Error: ' + (data.message||'unknown'), 'error'); }
  }catch(e){ showToast('Network/API error', 'error'); }
}

function displayResults(result){
  const area = document.getElementById('resultsArea');
  if(!area) return;
  area.innerHTML = '';
  const score = result.credibility_score || 0;
  const category = result.category || 'unverifiable';
  const summary = result.summary || result.explanation || '';
  const sources = (result.source_links && result.source_links.length) ? result.source_links : [];
  const html = `
    <div class="row" style="gap:18px;align-items:flex-start;">
      <div style="flex:0 0 220px;">
        <div style="font-weight:700">Score</div>
        <div class="scoreBar"><div class="scoreFill" style="width:0%"></div></div>
        <div style="margin-top:8px">${score} / 100 • <strong>${category}</strong></div>
      </div>
      <div style="flex:1;">
        <div style="font-weight:700">Summary</div>
        <div>${escapeHTML(summary).replace(/\n/g,'<br/>')}</div>
        <div style="margin-top:8px;font-weight:700">Sources</div>
        <ul>${sources.map(s=>`<li><a href="${s}" target="_blank">${s}</a></li>`).join('')}</ul>
      </div>
    </div>
  `;
  area.innerHTML = html;
  // animate fill
  requestAnimationFrame(()=> {
    document.querySelectorAll('.scoreFill').forEach(el => el.style.width = (score)+'%');
  });
}

function escapeHTML(s){ return String(s||'').replace(/[&<>"']/g, (m)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

// toasts
function showToast(msg, type='info'){
  const t = document.createElement('div'); t.className = 'toast toast-'+type; t.textContent = msg; document.body.appendChild(t);
  setTimeout(()=> t.classList.add('visible'), 50);
  setTimeout(()=> { t.classList.remove('visible'); setTimeout(()=>t.remove(),300); }, 3500);
}

// hook analyze buttons
function initAnalyzeButtons(){
  const textBtn = document.getElementById('analyzeTextBtn');
  if(textBtn) textBtn.onclick = ()=>{ const text=document.getElementById('inputText').value||''; const fd=new FormData(); fd.append('type','text'); fd.append('content', text); doAnalyze(fd); };
  const linkBtn = document.getElementById('analyzeLinkBtn');
  if(linkBtn) linkBtn.onclick = ()=>{ const link=document.getElementById('linkInput').value||''; const fd=new FormData(); fd.append('type','link'); fd.append('content', link); doAnalyze(fd); };
  const fileBtn = document.getElementById('analyzeFileBtn');
  if(fileBtn) fileBtn.onclick = ()=>{ const file=document.getElementById('fileInput').files[0]; if(!file){ showToast('Choose a file first','warning'); return;} const fd=new FormData(); fd.append('type','image'); fd.append('file', file); doAnalyze(fd); };
  const transcriptBtn = document.getElementById('analyzeTranscriptBtn');
  if(transcriptBtn) transcriptBtn.onclick = ()=>{ const text=document.getElementById('transcriptInput').value||''; const fd=new FormData(); fd.append('type','video'); fd.append('content', text); doAnalyze(fd); };
}

// init
window.addEventListener('DOMContentLoaded', async ()=>{
  await loadTranslations();
  initAnalyzeButtons();
  const fab = document.getElementById('fabVerify'); if(fab) fab.onclick = ()=>{ const el=document.getElementById('inputText'); if(el) el.focus(); showToast('Ready for quick verify','info'); };
});