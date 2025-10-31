import os
import json
import sqlite3
import traceback
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
load_dotenv()

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, jsonify, send_file, abort
)
from flask_cors import CORS
from flask_login import (
    LoginManager, login_required, login_user, logout_user, current_user,
    UserMixin
)
from flask_dance.contrib.google import make_google_blueprint, google
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Gemini SDK (google-generativeai)
import google.generativeai as genai
# Configure from env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# App config
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
CORS(app)

# OAuth blueprint for Google (Flask-Dance)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
google_bp = make_google_blueprint(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    scope=["profile", "email"],
    redirect_url="/google_login"
)
app.register_blueprint(google_bp, url_prefix="/login_google")

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

DB_PATH = "truthlens.db"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "mp4", "mov", "webm"}

# --------------------------
# Database utilities
# --------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        password TEXT,
        name TEXT,
        avatar TEXT,
        bio TEXT,
        theme TEXT DEFAULT 'ocean',
        language TEXT DEFAULT 'en',
        google_id TEXT,
        created_at TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        input_type TEXT,
        input_content TEXT,
        result_json TEXT,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()

init_db()

# --------------------------
# User model for Flask-Login
# --------------------------
class User(UserMixin):
    def __init__(self, id_, email, name=None):
        self.id = str(id_)
        self.email = email
        self.name = name

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return User(row["id"], row["email"], row["name"])
    return None

# --------------------------
# Helpers
# --------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def save_analysis(user_id, input_type, input_content, result):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO analyses (user_id, input_type, input_content, result_json, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, input_type, input_content, json.dumps(result), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def gemini_analyze_text(prompt, max_tokens=700):
    # Minimal example of calling Gemini via google-generativeai
    # The exact API call may differ depending on SDK version; update as necessary.
    if not GEMINI_API_KEY:
        # Fallback dummy response for local dev if no key provided
        return {
            "credibility_score": 50,
            "summary": "Gemini API not configured. This is a placeholder summary.",
            "source_links": [],
            "category": "unverifiable",
            "explanation": "No Gemini key - placeholder result."
        }
    try:
        # Using chat completion as an example
        response = genai.chat.completions.create(
            model="gpt-4o-mini",  # example model; update as needed
            messages=[
                {"role": "system", "content": "You are an assistant that assesses news credibility."},
                {"role": "user", "content": f"Analyze the following content for credibility and provide: credibility_score (0-100), summary, source_links (list), category (fake/partially true/true/unverifiable), explanation. Content: {prompt}"}
            ],
            temperature=0.0,
            max_output_tokens=max_tokens
        )
        content = response.choices[0].message.get("content", "")
        # Expecting a JSON-ish output; try to parse best-effort
        # We'll attempt to parse JSON from the model output; otherwise fallback.
        try:
            parsed = json.loads(content)
            return parsed
        except Exception:
            # If Gemini returned natural text, craft a structured output
            return {
                "credibility_score": 75,  # heuristic placeholder
                "summary": content[:1000],
                "source_links": [],
                "category": "partially true",
                "explanation": content
            }
    except Exception as e:
        # Log and return safe fallback
        traceback.print_exc()
        return {
            "credibility_score": 0,
            "summary": "",
            "source_links": [],
            "category": "unverifiable",
            "explanation": f"Error calling Gemini: {str(e)}"
        }

# --------------------------
# Auth routes (email/password)
# --------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        data = request.form
        email = data.get("email")
        name = data.get("name")
        password = data.get("password")
        if not email or not password:
            flash("Please provide email and password.", "warning")
            return redirect(url_for("signup"))
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (email, password, name, created_at) VALUES (?, ?, ?, ?)",
                (email, generate_password_hash(password), name, datetime.utcnow().isoformat())
            )
            conn.commit()
            flash("Signup successful. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already exists.", "danger")
            return redirect(url_for("signup"))
        finally:
            conn.close()
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = request.form
        email = data.get("email")
        password = data.get("password")
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        conn.close()
        if row and check_password_hash(row["password"], password):
            user = User(row["id"], row["email"], row["name"])
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html")

@app.route("/google_login")
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Failed to fetch user info from Google.", "danger")
        return redirect(url_for("login"))
    info = resp.json()
    email = info.get("email")
    name = info.get("name")
    google_id = info.get("id")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE google_id = ? OR email = ?", (google_id, email))
    row = cur.fetchone()
    if row:
        user = User(row["id"], row["email"], row["name"])
    else:
        cur.execute("""
            INSERT INTO users (email, name, google_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (email, name, google_id, datetime.utcnow().isoformat()))
        conn.commit()
        user_id = cur.lastrowid
        user = User(user_id, email, name)
    conn.close()
    login_user(user)
    flash("Logged in with Google.", "success")
    return redirect(url_for("dashboard"))

@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))

# --------------------------
# Main routes / pages
# --------------------------
from datetime import datetime

@app.route("/")
def index():
    return render_template("index.html", datetime=datetime)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user)

@app.route("/profile")
@login_required
def profile():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (current_user.id,))
    user_row = cur.fetchone()
    cur.execute("SELECT * FROM analyses WHERE user_id = ? ORDER BY created_at DESC LIMIT 50", (current_user.id,))
    analyses = cur.fetchall()
    conn.close()
    return render_template("profile.html", user_row=user_row, analyses=analyses)

# --------------------------
# API endpoints
# --------------------------
@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    try:
        data = request.form.to_dict()
        # Accept JSON body as well
        if request.is_json:
            data = request.get_json()
        input_type = data.get("type", "text")  # text/link/image/video
        content = data.get("content", "")
        # For file uploads, handle separately
        if input_type == "image" and "file" in request.files:
            f = request.files["file"]
            if f and allowed_file(f.filename):
                filename = secure_filename(f.filename)
                save_path = os.path.join("static", "uploads", filename)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                f.save(save_path)
                content = save_path  # store path as content
        # If analyzing a link, optionally fetch content server-side (simple)
        if input_type == "link":
            # Very simple fetch (could be improved with requests + BeautifulSoup)
            import requests
            try:
                r = requests.get(content, timeout=8)
                page_text = r.text[:50000]
                prompt = f"Source link: {content}\nPage excerpt:\n{page_text}\n\nAssess credibility and provide JSON with credibility_score, summary, source_links, category, explanation."
            except Exception:
                prompt = f"Please analyze this link for credibility: {content}"
        elif input_type == "video":
            # For video, user supplies transcript or we try to fetch captions (placeholder)
            transcript = data.get("transcript", "")
            prompt = f"Analyze this video transcript for false claims and credibility:\n{transcript or content}"
        else:
            prompt = content

        result = gemini_analyze_text(prompt)
        # Add UI-friendly derived fields if missing
        if "credibility_score" not in result:
            result["credibility_score"] = int(result.get("score", 50))
        if "category" not in result:
            # heuristics
            score = result["credibility_score"]
            if score >= 80:
                result["category"] = "true"
            elif score >= 50:
                result["category"] = "partially true"
            elif score >= 20:
                result["category"] = "unverifiable"
            else:
                result["category"] = "fake"

        # Save analysis history
        save_analysis(current_user.id, input_type, content, result)
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/history", methods=["GET"])
@login_required
def api_history():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM analyses WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (current_user.id,))
    rows = cur.fetchall()
    conn.close()
    history = []
    for r in rows:
        history.append({
            "id": r["id"],
            "input_type": r["input_type"],
            "input_content": r["input_content"],
            "result": json.loads(r["result_json"]),
            "created_at": r["created_at"]
        })
    return jsonify({"status": "ok", "history": history})

@app.route("/api/theme", methods=["POST"])
@login_required
def api_theme():
    data = request.get_json() or {}
    theme = data.get("theme", "ocean")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET theme = ? WHERE id = ?", (theme, current_user.id))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "theme": theme})

@app.route("/api/language", methods=["POST"])
@login_required
def api_language():
    data = request.get_json() or {}
    language = data.get("language", "en")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET language = ? WHERE id = ?", (language, current_user.id))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "language": language})

# --------------------------
# Static API examples
# --------------------------
@app.route("/api/ping")
def ping():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})

# --------------------------
# Error handlers
# --------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html", error=e), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("500.html", error=e), 500

# --------------------------
# Run
# --------------------------
if __name__ == "__main__":
    # For dev
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)