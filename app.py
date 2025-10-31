"""
TruthLens - Flask single-service backend (Gemini + heuristics)
Endpoints:
 - GET  /api/health
 - POST /api/factcheck/text   { text, url, lang }
 - POST /api/factcheck/media  form-data file OR JSON { b64 }
 - POST /api/translate        { text, target }  (optional)
Serves static files (index.html + /static/*)
Environment variables:
 - GEMINI_API_KEY (required)
 - FACTCHECK_API_KEY (optional — Google Fact Check Tools)
 - TRANSLATE_ENDPOINT (optional — e.g. LibreTranslate)
"""
import os
import re
import base64
import tempfile
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from PIL import Image, ImageOps

# Optional Google generative ai (Gemini)
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except Exception:
    genai = None
    GEMINI_AVAILABLE = False

load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app)

PORT = int(os.getenv('PORT', 5000))
GEMINI_KEY = os.getenv('GEMINI_API_KEY')
FACTCHECK_KEY = os.getenv('FACTCHECK_API_KEY')
TRANSLATE_ENDPOINT = os.getenv('TRANSLATE_ENDPOINT')
TRANSLATE_KEY = os.getenv('TRANSLATE_KEY')

if GEMINI_KEY and GEMINI_AVAILABLE:
    genai.configure(api_key=GEMINI_KEY)
    GEN_MODEL = genai.GenerativeModel("gemini-1.5-flash")
else:
    GEN_MODEL = None

# Heuristics
SENSATIONAL_RE = re.compile(
    r'\b(viral|shocking|unbelievable|breaking|must-see|exclusive|miracle|shocker)\b', re.I)
LOW_REP_DOMAIN_RE = re.compile(r'\.(xyz|club|cf|ga|gq|icu|top|tk)$', re.I)


# ---------- utilities ----------
def domain_from_url(u):
    try:
        host = urlparse(u).hostname or ''
        return host.lower()
    except Exception:
        return ''


def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {}


def compute_score(db_matches, heuristics_count, ai_prob=0.0):
    # base score
    score = 55
    if db_matches:
        # If any db match contains debunk keywords -> low
        debunk = any(re.search(r'(false|hoax|mislead|fabricat|incorrect|debunk)', (m.get('verdict') or ''), re.I)
                     for m in db_matches)
        score = 20 if debunk else 85
    score -= heuristics_count * 8
    # small penalty for likely-AI content
    score = max(0, min(100, int(score - ai_prob * 10)))
    return score


def verdict_from_score(score):
    if score >= 70:
        return "Likely real"
    if score <= 40:
        return "Likely false"
    return "Unclear"


# ---------- external integrations (optional) ----------
def query_google_factcheck(query):
    """Query Google Fact Check Tools if FACTCHECK_KEY is set (optional)."""
    if not FACTCHECK_KEY:
        return []
    url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
    try:
        r = requests.get(url, params={'query': query, 'key': FACTCHECK_KEY}, timeout=8)
        if r.status_code == 200:
            data = safe_json(r)
            claims = data.get('claims', [])
            results = []
            for c in claims:
                crs = c.get('claimReview', [])
                if crs:
                    cr = crs[0]
                    results.append({
                        'source': cr.get('publisher', {}).get('name', 'fact-check'),
                        'verdict': cr.get('textualRating') or cr.get('title') or '',
                        'url': cr.get('url')
                    })
            return results
    except Exception:
        pass
    return []


def gemini_text_analysis(text):
    """Ask Gemini to summarize / fact-check the text. Returns text answer and ai_prob estimate."""
    if not GEN_MODEL:
        return None, 0.0
    try:
        prompt = (
            "You are TruthLens, an impartial fact-checking assistant. "
            "For the claim below, give a concise JSON with keys: Verdict, Explanation, Confidence (0-100).\n\n"
            f"Claim: \"{text}\"\n\n"
            "Respond ONLY in JSON."
        )
        resp = GEN_MODEL.generate_content(prompt)
        # The API returns a text block — try to parse numbers for ai_prob heuristically
        answer = resp.text.strip()
        # very rough ai_prob = 0 for text analysis; we use separate heuristic
        return answer, 0.0
    except Exception:
        return None, 0.0


# ---------- endpoints ----------
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'time': datetime.utcnow().isoformat() + 'Z'})


@app.route('/api/factcheck/text', methods=['POST'])
def factcheck_text():
    """
    Request: JSON { text: "...", url: "...", lang: "en" }
    Response: { score, verdict, heuristics[], sources[], explanation, ai_check, checked_at }
    """
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get('text') or '').strip()
    url = (body.get('url') or '').strip()
    lang = body.get('lang') or 'en'

    if not text and not url:
        return jsonify({'error': 'Provide text or URL'}), 400

    query = text or url
    heuristics = []
    if text and SENSATIONAL_RE.search(text):
        heuristics.append('sensational-language')
    if text and len(text) > 800:
        heuristics.append('very-long-claim')
    if text and sum(1 for ch in text if ch.isupper()) > len(text) * 0.45:
        heuristics.append('excessive-caps')
    if url and LOW_REP_DOMAIN_RE.search(domain_from_url(url)):
        heuristics.append('low-reputation-domain')

    # external matches (Google FactCheck optional)
    db_matches = query_google_factcheck(query) if FACTCHECK_KEY else []

    # AI text analysis via Gemini (optional)
    gemini_ans, ai_prob = gemini_text_analysis(query)

    score = compute_score(db_matches, len(heuristics), ai_prob)
    verdict = verdict_from_score(score)
    explanation = "Automated blend of external matches (if any) and heuristic signals. Use sources below to verify."

    resp = {
        'score': score,
        'verdict': verdict,
        'heuristics': heuristics,
        'sources': db_matches,
        'ai_check': {'gemini_output': gemini_ans, 'ai_prob': ai_prob},
        'explanation': explanation,
        'checked_at': datetime.utcnow().isoformat() + 'Z'
    }
    return jsonify(resp)


@app.route('/api/factcheck/media', methods=['POST'])
def factcheck_media():
    """
    Accepts multipart form-data 'file' or JSON { b64: "<base64>" }
    Returns {score, verdict, findings[], explanation}
    """
    try:
        if 'file' in request.files:
            f = request.files['file']
            content = f.read()
            filename = getattr(f, 'filename', 'upload')
        else:
            body = request.get_json(force=True, silent=True) or {}
            b64 = body.get('b64')
            if not b64:
                return jsonify({'error': 'No file or b64 provided'}), 400
            content = base64.b64decode(b64)
            filename = 'upload'
    except Exception as e:
        return jsonify({'error': 'Invalid file data', 'details': str(e)}), 400

    findings = []
    score = 50
    verdict = verdict_from_score(score)

    tmp = None
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1] or '.img')
        tmp.write(content)
        tmp.flush()
        tmp.close()
        # attempt to open as image
        img = Image.open(tmp.name)
        img.verify()
        img = Image.open(tmp.name)
        w, h = img.size
        findings.append({'type': 'image', 'note': f'validated image ({w}x{h})'})
        # a small perceptual hash
        try:
            small = ImageOps.grayscale(img).resize((8, 8), Image.LANCZOS)
            pixels = list(small.getdata())
            avg = sum(pixels) / len(pixels)
            bits = ''.join('1' if p > avg else '0' for p in pixels)
            phash = f'{int(bits, 2):016x}'[:16]
            findings.append({'type': 'phash', 'value': phash})
        except Exception:
            pass

        # Optionally ask Gemini to analyze image (if configured)
        if GEN_MODEL:
            try:
                prompt = "Analyze this image. State if it appears AI-generated, edited, or reused and give short reasoning."
                # Gemini image API: provide prompt and image bytes in a parts list — best-effort approach
                response = GEN_MODEL.generate_content([prompt, content])
                findings.append({'type': 'gemini_analysis', 'value': response.text.strip()})
            except Exception:
                pass
    except Exception as e:
        # Not an image -> treat as video or unsupported file
        findings.append({'type': 'file', 'note': f'Could not parse as image ({str(e)})'})
    finally:
        if tmp:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    # final verdict (prototype)
    score = compute_score([], len([f for f in findings if 'note' in f and 'validated' not in f]))
    verdict = verdict_from_score(score)
    explanation = 'Prototype media analysis. Integrate reverse-image search (TinEye) or Google Vision for production.'

    return jsonify({
        'score': score,
        'verdict': verdict,
        'findings': findings,
        'explanation': explanation,
        'checked_at': datetime.utcnow().isoformat() + 'Z'
    })


@app.route('/api/translate', methods=['POST'])
def translate():
    """
    Uses TRANSLATE_ENDPOINT if provided (expected LibreTranslate-style { q, target }).
    Fallback: echoes original text with note.
    """
    body = request.get_json(force=True, silent=True) or {}
    text = body.get('text', '')
    target = body.get('target', 'en')
    if not TRANSLATE_ENDPOINT:
        return jsonify({'translated': text, 'provider': 'none', 'note': 'Translate endpoint not configured.'})
    try:
        r = requests.post(TRANSLATE_ENDPOINT, json={'q': text, 'target': target}, timeout=8)
        return jsonify(safe_json(r))
    except Exception as e:
        return jsonify({'error': 'translation failed', 'details': str(e)}), 500


# Serve SPA root and static files
@app.route('/', methods=['GET'])
def index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def static_proxy(path):
    # serve file from root or static folder
    if os.path.exists(path):
        return send_from_directory('.', path)
    static_path = os.path.join(app.static_folder, path)
    if os.path.exists(static_path):
        return send_from_directory(app.static_folder, path)
    return abort(404)


if __name__ == '__main__':
    # For Render use gunicorn start command; this is for local debug.
    app.run(host='0.0.0.0', port=PORT, debug=False)