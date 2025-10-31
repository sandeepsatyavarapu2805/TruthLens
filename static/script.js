/* TruthLens script.js
   Handles:
   - Tabbing and tool actions
   - Theme switching (localStorage + calls server API)
   - Language switching (translations object)
   - Calls to /analyze
   - Speech recognition & voice output
   - Toasts and simple animations
   - PDF export via jsPDF (frontend)
*/

const TRANSLATIONS = {
  en: {
    verifyNow: "Verify Now",
    login: "Login",
    signup: "Sign Up",
    analyze: "Analyze",
    summary: "Summary",
    explanation: "Explanation",
    sources: "Verified Sources",
    credibility: "Credibility"
  },
  hi: {
    verifyNow: "अब सत्यापित करें",
    login: "लॉगिन",
    signup: "साइन अप",
    analyze: "विश्लेषण करें",
    summary: "सारांश",
    explanation: "व्याख्या",
    sources: "सत्यापित स्रोत",
    credibility: "विश्वसनीयता"
  },
  te: {
    verifyNow: "ఇప్పుడు చిత్రానికి సాక్ష్యం తీసుకోండి",
    login: "లాగిన్",
    signup: "సైన్ అప్",
    analyze: "విశ్లేషణ",
    summary: "సారాంశం",
    explanation: "వివరణ",
    sources: "సమర్థించబడిన మూలాలు",
    credibility: "నమ్మకదారుడు"
  }
};

document.addEventListener("DOMContentLoaded", () => {
  // Tabs
  document.querySelectorAll(".tab-link").forEach(link => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      document.querySelectorAll(".tab-link").forEach(x => x.classList.remove("active"));
      e.target.classList.add("active");
      const href = e.target.getAttribute("href").substring(1);
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      document.getElementById(href).classList.add("active");
    });
  });

  // Theme init
  const savedTheme = localStorage.getItem("truthlens_theme") || document.body.getAttribute("data-theme") || "ocean";
  applyTheme(savedTheme);
  const themeSelect = document.getElementById("theme-select") || document.getElementById("top-theme-switch");
  if (themeSelect) themeSelect.value = savedTheme;
  if (themeSelect) themeSelect.addEventListener("change", (e) => {
    const t = e.target.value;
    applyTheme(t);
    localStorage.setItem("truthlens_theme", t);
    // Persist to server if logged in
    fetch("/api/theme", {method:"POST", credentials:"include", headers:{"Content-Type":"application/json"}, body:JSON.stringify({theme:t})});
  });

  // Language init
  const savedLang = localStorage.getItem("truthlens_lang") || "en";
  const langSelect = document.getElementById("lang-select") || document.getElementById("top-lang-switch");
  if (langSelect) langSelect.value = savedLang;
  setLanguage(savedLang);
  if (langSelect) langSelect.addEventListener("change", (e) => {
    const l = e.target.value;
    setLanguage(l);
    localStorage.setItem("truthlens_lang", l);
    fetch("/api/language", {method:"POST", credentials:"include", headers:{"Content-Type":"application/json"}, body:JSON.stringify({language:l})});
  });

  // Tool actions
  const analyzeTextBtn = document.getElementById("analyze-text");
  if (analyzeTextBtn) analyzeTextBtn.addEventListener("click", () => submitAnalysis("text", document.getElementById("text-input").value));

  const analyzeLinkBtn = document.getElementById("analyze-link");
  if (analyzeLinkBtn) analyzeLinkBtn.addEventListener("click", () => submitAnalysis("link", document.getElementById("link-input").value));

  const analyzeImageBtn = document.getElementById("analyze-image");
  if (analyzeImageBtn) analyzeImageBtn.addEventListener("click", () => {
    const file = document.getElementById("image-file").files[0];
    if (!file) { toast("Choose a file first", "warning"); return; }
    uploadAndAnalyzeFile(file);
  });

  const analyzeVideoBtn = document.getElementById("analyze-video");
  if (analyzeVideoBtn) analyzeVideoBtn.addEventListener("click", () => {
    const url = document.getElementById("video-url").value;
    const transcript = document.getElementById("video-transcript").value;
    submitAnalysis("video", url || transcript, {transcript: transcript});
  });

  // FAB quick verify
  const fab = document.getElementById("fab-verify");
  if (fab) fab.addEventListener("click", () => {
    document.getElementById("text-input").focus();
    toast("Quick verify ready", "info");
  });

  // Export PDF
  const pdfBtn = document.getElementById("download-pdf");
  if (pdfBtn) pdfBtn.addEventListener("click", exportResultPDF);

  // Share buttons
  const wBtn = document.getElementById("share-whatsapp");
  if (wBtn) wBtn.addEventListener("click", shareWhatsApp);
  const tBtn = document.getElementById("share-twitter");
  if (tBtn) tBtn.addEventListener("click", shareTwitter);

  // Contact form
  const contact = document.getElementById("contact-form");
  if (contact) {
    contact.addEventListener("submit", (e) => {
      e.preventDefault();
      document.getElementById("contact-result").innerText = "Thanks — we'll reply to your email.";
      contact.reset();
    });
  }

  // Speech recognition example: press analyze-text will also read aloud summary after result
});

// ----------------------
// Theme & language
// ----------------------
function applyTheme(theme) {
  document.body.setAttribute("data-theme", theme || "ocean");
  // apply class to body for CSS variables reading
  document.documentElement.setAttribute("data-theme", theme);
}

function setLanguage(lang) {
  const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
  document.getElementById("hero-title")?.innerText && (document.getElementById("hero-title").innerText = TRANSLATIONS[lang]?.verifyNow || "See the Truth Beyond the Noise");
  // update other tokens
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    el.innerText = t[key] || el.innerText;
  });
}

// ----------------------
// Toasts & helpers
// ----------------------
function toast(message, type="info", duration=3500) {
  const root = document.getElementById("toast");
  root.className = `toast toast-${type}`;
  root.innerText = message;
  root.style.opacity = 1;
  setTimeout(() => { root.style.opacity = 0; }, duration);
}

// ----------------------
// Analysis
// ----------------------
async function submitAnalysis(type, content, extras = {}) {
  try {
    showLoader(true);
    const form = new FormData();
    form.append("type", type);
    form.append("content", content || "");
    if (extras.transcript) form.append("transcript", extras.transcript);
    const res = await fetch("/analyze", {method: "POST", body: form, credentials: "include"});
    const data = await res.json();
    showLoader(false);
    if (data.status === "ok") {
      displayResult(data.result);
      toast("Analysis complete", "success");
    } else {
      toast("Analysis failed: " + (data.message || "Unknown"), "error");
    }
  } catch (err) {
    console.error(err);
    showLoader(false);
    toast("Error during analysis", "error");
  }
}

async function uploadAndAnalyzeFile(file) {
  const form = new FormData();
  form.append("type", file.type.startsWith("image") ? "image" : "video");
  form.append("file", file);
  showLoader(true);
  try {
    const res = await fetch("/analyze", {method:"POST", body:form, credentials:"include"});
    const data = await res.json();
    showLoader(false);
    if (data.status === "ok") {
      displayResult(data.result);
      toast("File analyzed", "success");
    } else {
      toast("File analysis failed", "error");
    }
  } catch (e) {
    showLoader(false);
    toast("Upload error", "error");
  }
}

// ----------------------
// Display result & UI
// ----------------------
function displayResult(result) {
  document.getElementById("result-title").innerText = `Result • ${result.category?.toUpperCase() || ''}`;
  document.getElementById("result-summary").innerText = result.summary || "No summary provided.";
  document.getElementById("result-explanation").innerText = result.explanation || "";
  const sourcesList = document.getElementById("result-sources");
  sourcesList.innerHTML = "";
  (result.source_links || []).forEach(s => {
    const li = document.createElement("li");
    li.innerHTML = `<a href="${s}" target="_blank">${s}</a>`;
    sourcesList.appendChild(li);
  });
  const score = Math.max(0, Math.min(100, parseInt(result.credibility_score || 0)));
  const bar = document.getElementById("credibility-bar");
  bar.style.width = `${score}%`;
  bar.setAttribute("aria-valuenow", score);
  const badge = document.getElementById("trust-badge");
  badge.className = "badge";
  if (score >= 80) { badge.classList.add("good"); badge.innerText = "True"; }
  else if (score >= 50) { badge.classList.add("warn"); badge.innerText = "Partially True"; }
  else { badge.classList.add("bad"); badge.innerText = "Fake / Unreliable"; }

  // Chart breakdown
  try {
    const ctx = document.getElementById("score-breakdown").getContext("2d");
    if (window._scoreChart) window._scoreChart.destroy();
    window._scoreChart = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: ["Credibility", "Uncertainty"],
        datasets: [{data: [score, 100-score]}]
      },
      options: {responsive:true, maintainAspectRatio:false}
    });
  } catch (e) { console.warn(e); }

  // Voice output (optional)
  try {
    const utter = new SpeechSynthesisUtterance(result.summary || "No summary");
    speechSynthesis.speak(utter);
  } catch(e) { /* ignore */ }

  // animate fade-in
  const card = document.getElementById("result-card");
  card.classList.add("reveal");
  setTimeout(() => card.classList.remove("reveal"), 1200);
}

// ----------------------
// PDF export & share
// ----------------------
function exportResultPDF() {
  const title = document.getElementById("result-title").innerText;
  const summary = document.getElementById("result-summary").innerText;
  const explanation = document.getElementById("result-explanation").innerText;
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF();
  doc.setFontSize(18);
  doc.text("TruthLens Report", 14, 20);
  doc.setFontSize(12);
  doc.text(title, 14, 30);
  doc.text("Summary:", 14, 44);
  doc.text(doc.splitTextToSize(summary, 180), 14, 50);
  doc.text("Explanation:", 14, 100);
  doc.text(doc.splitTextToSize(explanation, 180), 14, 106);
  doc.save("truthlens-report.pdf");
  toast("PDF exported", "success");
}

function shareWhatsApp() {
  const title = encodeURIComponent(document.getElementById("result-title").innerText);
  const summary = encodeURIComponent(document.getElementById("result-summary").innerText);
  const url = `https://api.whatsapp.com/send?text=${title}%0A${summary}`;
  window.open(url, "_blank");
}
function shareTwitter() {
  const text = encodeURIComponent(document.getElementById("result-title").innerText + " - " + document.getElementById("result-summary").innerText);
  const url = `https://twitter.com/intent/tweet?text=${text}`;
  window.open(url, "_blank");
}

// ----------------------
// Loader
// ----------------------
function showLoader(on=true) {
  if (on) document.body.classList.add("loading");
  else document.body.classList.remove("loading");
}