"""
TruthLens - Flask App
----------------------------------
Features:
 - /api/factcheck/text  -> text & URL verification
 - /api/factcheck/media -> image/video prototype analysis
 - /api/translate       -> optional translation API
 - Serves index.html and /static/*
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
from dotenv import load_dotenv
from PIL import Image, ImageOps

# Load environment variables
load_dotenv()

# Flask setup
app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app)

PORT = int(os.getenv('PORT', 5000))
FACTCHECK_KEY = os.getenv('FACTCHECK_API_KEY')  # Google Fact Check API
TINEYE_KEY = os.getenv('TINEYE_API_KEY')  # optional
GOOGLE_VISION_KEY = os.getenv('GOOGLE_VISION_KEY')  # optional
TRANSLATE_ENDPOINT = os.getenv('TRANSLATE_ENDPOINT')  # optional
TRANSLATE_KEY = os.getenv('TRANSLATE_KEY')  # optional

# -------------------------------
# Heuristic patterns
# -------------------------------
SENSATIONAL_RE = re.compile(
    r'\b(viral|shocking|unbelievable|breaking|must-see|exclusive|miracle|shocker)\b', re.I)
LOW_REPUTATION_DOMAINS_RE = re.compile(
    r'\.(xyz|club|cf|ga|gq|icu|top|tk)$', re.I)


# -------------------------------
# Utility functions
# -------------------------------
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


def compute_blended_score(external_matches, heuristics):
    """Return score 0–100 by blending heuristics + external sources."""
    score = 50
    if external_matches:
        has_debunk = any(
            re.search(r'(false|hoax|mislead|incorrect|debunk)', (m.get('verdict') or ''), re.I)
            for m in external_matches
        )
        score = 20 if has_debunk else 85
    score -= len(heuristics) * 8
    return max(0, min(100, score))


def verdict_from_score(score):
    if score >= 70:
        return "Likely real"
    if score <= 40:
        return "Likely false"
    return "Unclear"


# -------------------------------
# External integrations (mocked)
# -------------------------------
def query_google_factcheck(query):
    """Query Google Fact Check Tools API if key is set."""
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
                claim_reviews = c.get('claimReview', [])
                if claim_reviews:
                    cr = claim_reviews[0]
                    publisher = cr.get('publisher', {}).get('name')
                    verdict = cr.get('textualRating') or cr.get('title') or ''
                    results.append({
                        'source': publisher or 'factcheck',
                        'verdict': verdict,
                        'url': cr.get('url')
                    })
            return results
    except Exception as e:
        app.logger.warning("FactCheck API failed: %s", e)
    return []


def query_tineye_by_image_bytes(_):
    """Placeholder for TinEye or reverse-image APIs."""
    return []


def detect_ai_text_heuristic(text):
    """Lightweight heuristic for AI-generated text detection."""
    if not text or len(text) < 50:
        return {'ai_prob': 0.1, 'reason': 'Too short for detection'}

    words = text.split()
    avg_word_len = sum(len(w) for w in words) / max(1, len(words))
    unique_words_ratio = len(set(words)) / max(1, len(words))
    punctuation_variety = len(set(ch for ch in text if ch in '.,;:!?'))

    score = 0.1
    if avg_word_len > 6.5:
        score += 0.25
    if unique_words_ratio < 0.45:
        score += 0.35
    if punctuation_variety < 2:
        score += 0.2

    ai_prob = min(0.99, score)
    return {'ai_prob': ai_prob,
            'reason': f'avg_word_len={avg_word_len:.2f}, uniq_ratio={unique_words_ratio:.2f}, punct_var={punctuation_variety}'}


# -------------------------------
# API Endpoints
# -------------------------------
@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.utcnow().isoformat() + 'Z'})


@app.route('/api/factcheck/text', methods=['POST'])
def factcheck_text():
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get('text') or '').strip()
    url = (body.get('url') or '').strip()

    if not text and not url:
        return jsonify({'error': 'Provide text or URL'}), 400

    query = text or url
    external_matches = query_google_factcheck(query)
    heuristics = []

    if text and SENSATIONAL_RE.search(text):
        heuristics.append('sensational-language')
    if url and LOW_REPUTATION_DOMAINS_RE.search(domain_from_url(url)):
        heuristics.append('low-reputation-domain')
    if text and len(text) > 800:
        heuristics.append('very-long-claim')
    if text and sum(1 for ch in text if ch.isupper()) > len(text) * 0.45:
        heuristics.append('excessive-caps')

    ai_check = detect_ai_text_heuristic(text)
    score = compute_blended_score(external_matches, heuristics)
    if ai_check.get('ai_prob', 0) > 0.65:
        score = max(0, score - 6)

    verdict = verdict_from_score(score)
    return jsonify({
        'score': score,
        'verdict': verdict,
        'heuristics': heuristics,
        'sources': external_matches,
        'ai_check': ai_check,
        'explanation': 'Automated verification combining heuristic checks and external databases.',
        'checked_at': datetime.utcnow().isoformat() + 'Z'
    })


@app.route('/api/factcheck/media', methods=['POST'])
def factcheck_media():
    try:
        if 'file' in request.files:
            content = request.files['file'].read()
        else:
            body = request.get_json(force=True, silent=True) or {}
            if 'b64' not in body:
                return jsonify({'error': 'No file or b64 provided'}), 400
            content = base64.b64decode(body['b64'])
    except Exception as e:
        return jsonify({'error': 'Invalid file data', 'details': str(e)}), 400

    findings = []
    score = 50
    verdict = verdict_from_score(score)

    try:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(content)
        tmp.close()
        img = Image.open(tmp.name)
        img.verify()
        img = Image.open(tmp.name)
        w, h = img.size
        findings.append({'type': 'image', 'note': f'Validated image ({w}x{h})'})

        img_small = ImageOps.grayscale(img).resize((8, 8), Image.LANCZOS)
        pixels = list(img_small.getdata())
        avg = sum(pixels) / len(pixels)
        bits = ''.join('1' if p > avg else '0' for p in pixels)
        phash = f'{int(bits, 2):016x}'[:16]
        findings.append({'type': 'phash', 'value': phash})

    except Exception as e:
        findings.append({'type': 'file', 'note': f'Not an image: {str(e)}'})
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    return jsonify({
        'score': score,
        'verdict': verdict,
        'findings': findings,
        'explanation': 'Prototype image analysis; add Vision/TinEye API for deeper checks.',
        'checked_at': datetime.utcnow().isoformat() + 'Z'
    })


@app.route('/api/translate', methods=['POST'])
def translate():
    body = request.get_json(force=True, silent=True) or {}
    text = body.get('text', '')
    target = body.get('target', 'en')

    if not TRANSLATE_ENDPOINT:
        return jsonify({
            'translated': text,
            'provider': 'none',
            'note': 'Translate endpoint not configured.'
        })

    try:
        r = requests.post(TRANSLATE_ENDPOINT,
                          json={'q': text, 'target': target, 'key': TRANSLATE_KEY},
                          timeout=8)
        return jsonify(safe_json(r))
    except Exception as e:
        return jsonify({'error': 'Translation failed', 'details': str(e)}), 500


# -------------------------------
# Frontend Routes
# -------------------------------
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def static_proxy(path):
    if os.path.exists(path):
        return send_from_directory('.', path)
    static_path = os.path.join(app.static_folder, path)
    if os.path.exists(static_path):
        return send_from_directory(app.static_folder, path)
    return abort(404)


# -------------------------------
# Main
# -------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)