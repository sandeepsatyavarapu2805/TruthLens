# app.py
import os
import re
import base64
import json
import tempfile
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, request, jsonify, send_from_directory, render_template_string
from flask_cors import CORS
import requests
from dotenv import load_dotenv
from PIL import Image

# Load .env if present
load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app)

# Config (set in environment in Render)
GOOGLE_FACTCHECK_KEY = os.getenv('FACTCHECK_API_KEY')  # optional
PORT = int(os.getenv('PORT', 5000))

SENSATIONAL_RE = re.compile(r'\b(viral|shocking|unbelievable|breaking|must-see|exclusive|miracle)\b', re.I)
LOW_REPUTATION_DOMAINS = re.compile(r'\.(xyz|club|cf|ga|gq|icu|top)$', re.I)

# ---------- Utilities ----------
def query_external_factcheck(text=None, url=None):
    """
    Prototype: If you have a Google Fact Check Tools API key, implement it here.
    For now this returns an empty list unless FACTCHECK_API_KEY provided and a successful call occurs.
    """
    results = []
    key = GOOGLE_FACTCHECK_KEY
    if not key:
        return results

    # Google Fact Check Tools v1alpha1: claims:search
    q = text or url or ''
    try:
        resp = requests.get(
            'https://factchecktools.googleapis.com/v1alpha1/claims:search',
            params={'query': q, 'key': key},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            claims = data.get('claims', [])
            for c in claims:
                # quick mapping - production should parse more carefully
                results.append({
                    'source': c.get('claimReview', [{}])[0].get('publisher', {}).get('name', 'fact-check'),
                    'verdict': c.get('claimReview', [{}])[0].get('textualRating') or c.get('text'),
                    'url': c.get('claimReview', [{}])[0].get('url'),
                    'date': c.get('claimDate')
                })
    except Exception as e:
        app.logger.warning('Factcheck query failed: %s', e)
    return results

def domain_from_url(u):
    try:
        host = urlparse(u).hostname or ''
        return host.lower()
    except Exception:
        return ''

def compute_blended_score(db_matches, heuristics_count):
    score = 50
    if db_matches:
        # if any match looks like a debunk (text contains false/misleading) => lower
        has_debunk = any(re.search(r'(false|mislead|fabricat|hoax|incorrect)', (m.get('verdict') or '') , re.I) for m in db_matches)
        score = 20 if has_debunk else 85
    # heuristics penalty
    score -= heuristics_count * 8
    score = max(0, min(100, score))
    return score

def verdict_from_score(score):
    if score >= 70:
        return "Likely real"
    if score <= 40:
        return "Likely false"
    return "Unclear"

# ---------- API endpoints ----------
@app.route('/api/factcheck/text', methods=['POST'])
def factcheck_text():
    """
    Request JSON: { text: "...", url: "...", lang: "en" }
    Response: score, verdict, heuristics[], sources[], explanation
    """
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get('text') or '').strip()
    url = (body.get('url') or '').strip()
    lang = body.get('lang') or 'en'

    if not text and not url:
        return jsonify({'error': 'Provide text or url'}), 400

    # 1) query external fact-check DBs (prototype)
    db_matches = query_external_factcheck(text=text, url=url)

    # 2) heuristics
    heuristics = []
    if text and SENSATIONAL_RE.search(text):
        heuristics.append('sensational-language')
    if url:
        dom = domain_from_url(url)
        if LOW_REPUTATION_DOMAINS.search(dom):
            heuristics.append('low-reputation-domain')
    # length and caps heuristics
    if text and len(text) > 500:
        heuristics.append('long-claim')
    if text and sum(1 for ch in text if ch.isupper()) > len(text) * 0.5:
        heuristics.append('excessive-caps')

    # compute score
    score = compute_blended_score(db_matches, len(heuristics))
    verdict = verdict_from_score(score)

    explanation = "Automated blend of external fact-check matches (if any) and heuristic signals. Always verify with sources below."

    return jsonify({
        'score': score,
        'verdict': verdict,
        'heuristics': heuristics,
        'sources': db_matches,
        'explanation': explanation,
        'checked_at': datetime.utcnow().isoformat() + 'Z'
    })

@app.route('/api/factcheck/media', methods=['POST'])
def factcheck_media():
    """
    Accepts either multipart form-data with 'file' or JSON { b64: "..." } (base64 string w/o data: prefix)
    Returns a prototype analysis.
    """
    # Try files first
    file = None
    if 'file' in request.files:
        file = request.files['file']
    else:
        # Try JSON body with b64
        body = request.get_json(force=True, silent=True) or {}
        b64 = body.get('b64')
        if b64:
            try:
                raw = base64.b64decode(b64)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.bin')
                tmp.write(raw)
                tmp.flush()
                tmp.close()
                file = open(tmp.name, 'rb')
            except Exception as e:
                return jsonify({'error': 'Invalid base64'}), 400

    if not file:
        return jsonify({'error': 'No file or base64 provided'}), 400

    # Minimal validation: image vs video
    mimetype = None
    try:
        mimetype = getattr(file, 'mimetype', None) or ''
    except Exception:
        mimetype = ''
    findings = []

    # If it's an image, try to open with PIL to ensure it's valid
    try:
        # PIL can open many formats; for videos we skip
        if not mimetype.startswith('video'):
            # If it's a werkzeug FileStorage, pass directly; else open path
            img = Image.open(file)
            w, h = img.size
            findings.append({'type': 'image', 'note': f'image validated ({w}x{h})'})
            # optionally compute simple perceptual-ish hash (average brightness) - cheap
            try:
                gray = img.convert('L').resize((8,8))
                avg = sum(list(gray.getdata())) / 64
                bits = ''.join(['1' if p > avg else '0' for p in gray.getdata()])
                phash = f'{int(bits,2):016x}'[:16]
                findings.append({'type': 'phash', 'value': phash})
            except Exception:
                pass
        else:
            findings.append({'type': 'video', 'note': 'video file received; consider frame extraction for production'})
    except Exception as e:
        # Not an image
        findings.append({'type': 'file', 'note': 'file received (not recognized as image)'})

    # In production: send frames to reverse-image search services (TinEye / Google Vision)
    # For now return an "Unclear" verdict
    score = 50
    verdict = verdict_from_score(score)
    explanation = 'Media analysis is a prototype. Integrate reverse-image search and frame-matching for production.'

    # close file if we opened a temp file
    try:
        if hasattr(file, 'close'):
            file.close()
    except:
        pass

    return jsonify({
        'score': score,
        'verdict': verdict,
        'findings': findings,
        'explanation': explanation,
        'checked_at': datetime.utcnow().isoformat() + 'Z'
    })

# ---------- Serve SPA ----------
@app.route('/', methods=['GET'])
def index():
    return send_from_directory('.', 'index.html')

# allow static files
@app.route('/<path:path>')
def static_proxy(path):
    # serve static files (static/* or root assets)
    if os.path.exists(path):
        return send_from_directory('.', path)
    # otherwise 404
    return jsonify({'error': 'Not found'}), 404

if __name__ == '__main__':
    # For production on Render, use the command: python app.py
    app.run(host='0.0.0.0', port=PORT, debug=False)