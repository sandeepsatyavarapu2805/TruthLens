# TruthLens — Single-file Flask (Production-ready SPA)

## Quick Local Run
1. python -m venv venv
2. source venv/bin/activate   (Windows: venv\Scripts\activate)
3. pip install -r requirements.txt
4. python app.py
5. Open http://127.0.0.1:5000

## Deploy to Render (recommended)
- Create a new Web Service (Python).
- Connect your repo.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 3`
- Add env vars if you want to enable integrations:
  - FACTCHECK_API_KEY (Google Fact Check Tools)
  - GOOGLE_VISION_KEY
  - TIN EYE_API_KEY
  - TRANSLATE_ENDPOINT / TRANSLATE_KEY

## Notes & Next Steps
- Replace placeholder integrations (TinEye/Google) with licensed APIs and parse responses.
- Add caching & rate-limiting for external API calls.
- Add an admin dashboard and a manual review workflow for community reports.
- For heavy traffic use a proper WSGI server and configure HTTPS & logging.