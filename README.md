# TruthLens — Single-file Flask deploy (simple)

## Quick run locally
1. python -m venv venv
2. source venv/bin/activate   (Windows: venv\\Scripts\\activate)
3. pip install -r requirements.txt
4. python app.py
5. Open http://localhost:5000

## Deploy to Render
- Create a new Web Service (Python).
- Connect your repo.
- Set Build Command: `pip install -r requirements.txt`
- Start Command: `python app.py`
- Add any env vars (FACTCHECK_API_KEY) if you want Google Fact Check integration.