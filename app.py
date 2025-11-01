# app.py - TruthLens Free-Pro Edition
import os
import json
import sqlite3
import traceback
import csv
from datetime import datetime
from functools import wraps
from io import StringIO

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
try:
    import google.generativeai as genai
except Exception:
    genai = None

# ---------------------------
# Config
# ---------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY and genai:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception:
        pass

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24)
CORS(app)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
google_bp = make_google_blueprint(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    scope=["profile", "email"],
    redirect_url="/google_login"
)
app.register_blueprint(google_bp, url_prefix="/login_google")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

DB_PATH = os.getenv("DB_PATH", "truthlens.db")
UPLOAD_FOLDER = os.path.join("static", "uploads")
AVATAR_FOLDER = os.path.join("static", "avatars")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AVATAR_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "mp4", "mov", "webm", "csv"}

# --------------------------
# Database utilities & migrations
# --------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    # core tables
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
        is_admin INTEGER DEFAULT 0,
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
    cur.execute("""
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()

# Safe migration for older DBs (attempt to add columns if missing)
def migrate_db():
    conn = get_db()
    cur = conn.cursor()
    # Add columns if they don't exist (SQLite simple approach)
    try:
        cur.execute("PRAGMA table_info(users)")
        cols = [r["name"] for r in cur.fetchall()]
        if "avatar" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT ''")
        if "bio" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")
        if "is_admin" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    except Exception:
        pass
    conn.commit()
    conn.close()

init_db()
migrate_db()

# --------------------------
# User model for Flask-Login
# --------------------------
class User(UserMixin):
    def __init__(self, id_, email, name=None, is_admin=0):
        self.id = str(id_)
        self.email = email
        self.name = name
        self.is_admin = bool(is_admin)

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return User(row["id"], row["email"], row["name"], row["is_admin"])
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
    """Calls Gemini via google.generativeai if available. Returns standardized dict."""
    if not GEMINI_API_KEY or genai is None:
        return {
            "credibility_score": 50,
            "summary": "Gemini not configured — placeholder analysis. Add GEMINI_API_KEY to environment for real results.",
            "source_links": [],
            "category": "unverifiable",
            "explanation": "No Gemini API available in environment or SDK not installed."
        }
    try:
        response = genai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an assistant that assesses news credibility and returns JSON."},
                {"role": "user", "content": f"Analyze for credibility and output JSON with keys: credibility_score (0-100), summary, source_links (list), category (fake/partially true/true/unverifiable), explanation. Content: {prompt}"}
            ],
            temperature=0.0,
            max_output_tokens=max_tokens
        )
        try:
            content = response.choices[0].message.get("content", "")
        except Exception:
            content = str(response)
        try:
            parsed = json.loads(content)
            return parsed
        except Exception:
            return {
                "credibility_score": 70,
                "summary": content[:1200],
                "source_links": [],
                "category": "partially true",
                "explanation": content
            }
    except Exception as e:
        traceback.print_exc()
        return {
            "credibility_score": 0,
            "summary": "",
            "source_links": [],
            "category": "unverifiable",
            "explanation": f"Error calling Gemini: {str(e)}"
        }

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        # Load fresh user record
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT is_admin FROM users WHERE id = ?", (current_user.id,))
        r = cur.fetchone()
        conn.close()
        if not r or r["is_admin"] != 1:
            flash("Admin access required.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated

# --------------------------
# Auth routes (signup/login/logout + Google)
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
    return render_template("signup.html", datetime=datetime, user=current_user)

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
        if row and row["password"] and check_password_hash(row["password"], password):
            user = User(row["id"], row["email"], row["name"], row["is_admin"])
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("analyze_page"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html", datetime=datetime, user=current_user)

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
        user = User(row["id"], row["email"], row["name"], row["is_admin"])
    else:
        cur.execute("""
            INSERT INTO users (email, name, google_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (email, name, google_id, datetime.utcnow().isoformat()))
        conn.commit()
        user_id = cur.lastrowid
        user = User(user_id, email, name, 0)
    conn.close()
    login_user(user)
    flash("Logged in with Google.", "success")
    return redirect(url_for("analyze_page"))

@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))

# --------------------------
# Main pages (home, analyze, profile, etc.)
# --------------------------
@app.route("/")
def index():
    return render_template("index.html", datetime=datetime, user=current_user)

@app.route("/analyze")
@login_required
def analyze_page():
    return render_template("analyze.html", datetime=datetime, user=current_user)

@app.route("/insights")
@login_required
def insights():
    return render_template("insights.html", datetime=datetime, user=current_user)

@app.route("/resources")
def resources():
    return render_template("resources.html", datetime=datetime, user=current_user)

@app.route("/profile")
@login_required
def profile():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (current_user.id,))
    user_row = cur.fetchone()
    cur.execute("SELECT * FROM analyses WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (current_user.id,))
    analyses = cur.fetchall()
    conn.close()
    return render_template("profile.html", user_row=user_row, analyses=analyses, datetime=datetime, user=current_user)

@app.route("/about")
def about():
    return render_template("about.html", datetime=datetime, user=current_user)

@app.route("/contact", methods=["GET","POST"])
def contact():
    if request.method == "POST":
        flash("Thanks — your message was received.", "success")
        return redirect(url_for("contact"))
    return render_template("contact.html", datetime=datetime, user=current_user)

# --------------------------
# New pages: dashboard, settings, feedback, leaderboard, privacy, terms, faq
# --------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    # user analytics: total analyses, avg score, distribution
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as total FROM analyses WHERE user_id = ?", (current_user.id,))
    total = cur.fetchone()["total"]
    cur.execute("SELECT AVG(JSON_EXTRACT(result_json, '$.credibility_score')) as avg_score FROM analyses WHERE user_id = ?", (current_user.id,))
    avg_row = cur.fetchone()
    avg_score = avg_row["avg_score"] if avg_row else None
    # categories distribution
    cur.execute("SELECT result_json FROM analyses WHERE user_id = ?", (current_user.id,))
    cats = {"true":0,"partially true":0,"unverifiable":0,"fake":0,"other":0}
    for r in cur.fetchall():
        try:
            res = json.loads(r["result_json"])
            cat = res.get("category","other")
            cats[cat] = cats.get(cat,0)+1
        except Exception:
            cats["other"] += 1
    conn.close()
    return render_template("dashboard.html", total=total, avg_score=avg_score or 0, cats=cats, datetime=datetime, user=current_user)

@app.route("/settings", methods=["GET","POST"])
@login_required
def settings():
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        # profile updates: name, bio, language, theme, avatar, password change
        name = request.form.get("name")
        bio = request.form.get("bio")
        language = request.form.get("language", "en")
        theme = request.form.get("theme", "ocean")
        if "avatar" in request.files:
            f = request.files["avatar"]
            if f and allowed_file(f.filename):
                filename = secure_filename(f.filename)
                avatar_path = os.path.join(AVATAR_FOLDER, filename)
                f.save(avatar_path)
                cur.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar_path, current_user.id))
        if name is not None:
            cur.execute("UPDATE users SET name = ? WHERE id = ?", (name, current_user.id))
        if bio is not None:
            cur.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, current_user.id))
        cur.execute("UPDATE users SET language = ?, theme = ? WHERE id = ?", (language, theme, current_user.id))
        # change password (optional)
        old = request.form.get("old_password")
        new = request.form.get("new_password")
        if old and new:
            cur.execute("SELECT password FROM users WHERE id = ?", (current_user.id,))
            row = cur.fetchone()
            if row and row["password"] and check_password_hash(row["password"], old):
                cur.execute("UPDATE users SET password = ? WHERE id = ?", (generate_password_hash(new), current_user.id))
                flash("Password updated.", "success")
            else:
                flash("Old password incorrect.", "danger")
        conn.commit()
    cur.execute("SELECT * FROM users WHERE id = ?", (current_user.id,))
    user_row = cur.fetchone()
    conn.close()
    return render_template("settings.html", user_row=user_row, datetime=datetime, user=current_user)

@app.route("/feedback", methods=["GET","POST"])
@login_required
def feedback():
    if request.method == "POST":
        msg = request.form.get("message","").strip()
        if msg:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("INSERT INTO feedback (user_id, message, created_at) VALUES (?, ?, ?)", (current_user.id, msg, datetime.utcnow().isoformat()))
            conn.commit()
            conn.close()
            flash("Thanks — feedback saved.", "success")
            return redirect(url_for("feedback"))
    # show user's feedback (recent)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM feedback WHERE user_id = ? ORDER BY created_at DESC LIMIT 50", (current_user.id,))
    fb = cur.fetchall()
    conn.close()
    return render_template("feedback.html", feedbacks=fb, datetime=datetime, user=current_user)

@app.route("/leaderboard")
def leaderboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.id, u.name, u.email, COUNT(a.id) as analyses_count
        FROM users u
        LEFT JOIN analyses a ON a.user_id = u.id
        GROUP BY u.id
        ORDER BY analyses_count DESC
        LIMIT 10
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template("leaderboard.html", rows=rows, datetime=datetime, user=current_user)

@app.route("/privacy")
def privacy():
    return render_template("privacy.html", datetime=datetime, user=current_user)

@app.route("/terms")
def terms():
    return render_template("terms.html", datetime=datetime, user=current_user)

@app.route("/faq")
def faq():
    return render_template("faq.html", datetime=datetime, user=current_user)

# --------------------------
# API: analyze + batch, reanalyze, history, stats, theme, language
# --------------------------
@app.route("/api/analyze", methods=["POST"])
@login_required
def api_analyze():
    try:
        data = request.form.to_dict()
        if request.is_json:
            data = request.get_json()
        input_type = data.get("type", "text")
        content = data.get("content", "")

        # File handling (image/video)
        if input_type in ("image", "video") and "file" in request.files:
            f = request.files["file"]
            if f and allowed_file(f.filename):
                filename = secure_filename(f.filename)
                save_path = os.path.join(UPLOAD_FOLDER, filename)
                f.save(save_path)
                content = save_path

        # Link scraping
        if input_type == "link":
            import requests
            try:
                r = requests.get(content, timeout=8, headers={"User-Agent":"TruthLens/1.0"})
                page_text = r.text[:50000]
                prompt = f"Source link: {content}\nPage excerpt:\n{page_text}\n\nAssess credibility and return JSON with credibility_score, summary, source_links, category, explanation."
            except Exception:
                prompt = f"Please analyze this link for credibility: {content}"
        elif input_type == "video":
            transcript = data.get("transcript","")
            prompt = f"Analyze this video transcript for false claims and credibility:\n{transcript or content}"
        else:
            prompt = content or ""

        result = gemini_analyze_text(prompt)
        # Normalize simple fields
        if "credibility_score" not in result:
            try:
                result["credibility_score"] = int(result.get("score", 50) or 50)
            except Exception:
                result["credibility_score"] = 50
        if "category" not in result:
            score = result["credibility_score"]
            if score >= 80:
                result["category"] = "true"
            elif score >= 50:
                result["category"] = "partially true"
            elif score >= 20:
                result["category"] = "unverifiable"
            else:
                result["category"] = "fake"

        # save
        save_analysis(current_user.id, input_type, content, result)
        return jsonify({"status":"ok","result":result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status":"error","message":str(e)}), 500

@app.route("/api/batch_analyze", methods=["POST"])
@login_required
def api_batch_analyze():
    """
    Accepts a CSV upload with a column 'text' or plain text file with one item per line.
    Returns list of results and also stores them in DB.
    """
    try:
        if "file" not in request.files:
            return jsonify({"status":"error","message":"No file provided"}), 400
        f = request.files["file"]
        if not f or not allowed_file(f.filename):
            return jsonify({"status":"error","message":"Invalid file"}), 400
        filename = secure_filename(f.filename)
        data = f.read().decode("utf-8")
        results = []
        # detect CSV vs newline list
        if filename.lower().endswith(".csv"):
            reader = csv.DictReader(StringIO(data))
            # prefer column 'text' or first column
            for row in reader:
                text = row.get("text") or next(iter(row.values()), "")
                prompt = text
                res = gemini_analyze_text(prompt)
                # normalize
                if "credibility_score" not in res:
                    res["credibility_score"] = int(res.get("score",50) or 50)
                results.append({"input": text, "result": res})
                save_analysis(current_user.id, "text", text, res)
        else:
            # plain text lines
            for line in data.splitlines():
                text = line.strip()
                if not text:
                    continue
                res = gemini_analyze_text(text)
                if "credibility_score" not in res:
                    res["credibility_score"] = int(res.get("score",50) or 50)
                results.append({"input": text, "result": res})
                save_analysis(current_user.id, "text", text, res)
        return jsonify({"status":"ok","count":len(results), "results":results})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status":"error","message":str(e)}), 500

@app.route("/api/reanalyze/<int:analysis_id>", methods=["POST"])
@login_required
def api_reanalyze(analysis_id):
    """
    Re-run analysis using current model & save new analysis linked to user.
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM analyses WHERE id = ? AND user_id = ?", (analysis_id, current_user.id))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"status":"error","message":"Analysis not found"}), 404
        old = json.loads(row["result_json"])
        input_type = row["input_type"]
        content = row["input_content"]
        # Rebuild prompt according to input_type
        if input_type == "link":
            prompt = f"Please analyze this link for credibility: {content}"
        elif input_type == "video":
            prompt = content
        else:
            prompt = content
        new_result = gemini_analyze_text(prompt)
        if "credibility_score" not in new_result:
            new_result["credibility_score"] = int(new_result.get("score",50) or 50)
        save_analysis(current_user.id, input_type, content, new_result)
        conn.close()
        return jsonify({"status":"ok","result":new_result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status":"error","message":str(e)}), 500

@app.route("/api/history")
@login_required
def api_history():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, input_type, input_content, result_json, created_at FROM analyses WHERE user_id = ? ORDER BY created_at DESC LIMIT 200", (current_user.id,))
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
    return jsonify({"status":"ok","history":history})

@app.route("/api/stats")
@login_required
def api_stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as total, AVG(JSON_EXTRACT(result_json, '$.credibility_score')) as avg_score FROM analyses WHERE user_id = ?", (current_user.id,))
    r = cur.fetchone()
    conn.close()
    return jsonify({"status":"ok", "total": r["total"], "avg_score": r["avg_score"] or 0})

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
    return jsonify({"status":"ok","theme":theme})

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
    return jsonify({"status":"ok","language":language})

# --------------------------
# Admin routes
# --------------------------
@app.route("/admin")
@admin_required
def admin_index():
    conn = get_db()
    cur = conn.cursor()
    # quick stats
    cur.execute("SELECT COUNT(*) as users FROM users")
    users_count = cur.fetchone()["users"]
    cur.execute("SELECT COUNT(*) as analyses FROM analyses")
    analyses_count = cur.fetchone()["analyses"]
    conn.close()
    return render_template("admin/index.html", users_count=users_count, analyses_count=analyses_count, user=current_user)

@app.route("/admin/users")
@admin_required
def admin_users():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, email, name, is_admin, created_at FROM users ORDER BY created_at DESC LIMIT 500")
    rows = cur.fetchall()
    conn.close()
    return render_template("admin/users.html", rows=rows, user=current_user)

@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    cur.execute("DELETE FROM analyses WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash("User deleted.", "info")
    return redirect(url_for("admin_users"))

# --------------------------
# Simple static translations endpoint (no change)
# --------------------------
@app.route("/translations")
def translations():
    translations = {
        "en": {
            "appName":"TruthLens","tagline":"See the Truth Beyond the Noise.","verifyNow":"Verify Now",
            "login":"Login","signup":"Sign Up","email":"Email","password":"Password","or":"or",
            "googleSignIn":"Sign in with Google","analyze":"Analyze","uploadImage":"Upload Image","analyzeLink":"Analyze Link",
            "videoTranscript":"Video Transcript","profile":"Profile","dashboard":"Dashboard","about":"About","logout":"Logout",
            "language":"Language","theme":"Theme","score":"Credibility Score","summary":"Summary","sources":"Verified Sources",
            "category":"Category","exportPDF":"Export PDF","feedback":"Feedback","contact":"Contact Us","history":"History",
            "insights":"Insights","resources":"Resources","how":"How it works","searchPlaceholder":"Paste text or URL..."
        },
        "hi": {
            "appName":"ट्रुथलेंस","tagline":"शोर के परे सत्य देखें।","verifyNow":"अभी सत्यापित करें",
            "login":"लॉगइन","signup":"साइन अप","email":"ईमेल","password":"पासवर्ड","or":"या",
            "googleSignIn":"Google से साइन इन करें","analyze":"विश्लेषण करें","uploadImage":"छवि अपलोड करें","analyzeLink":"लिंक विश्लेषण",
            "videoTranscript":"वीडियो प्रतिलिपि","profile":"प्रोफ़ाइल","dashboard":"डैशबोर्ड","about":"बारे में","logout":"लॉगआउट",
            "language":"भाषा","theme":"थीम","score":"विश्वसनीयता स्कोर","summary":"सारांश","sources":"सत्यापित स्रोत",
            "category":"वर्ग","exportPDF":"PDF एक्सपोर्ट करें","feedback":"प्रतिक्रिया","contact":"संपर्क करें","history":"इतिहास",
            "insights":"इनसाइट्स","resources":"संसाधन","how":"यह कैसे काम करता है","searchPlaceholder":"पाठ या URL चिपकाएँ..."
        },
        "te": {
            "appName":"ట్రూథ్‌లెన్సు","tagline":"శబ్దం అందరి నుండి నిజాన్ని చూడండి.","verifyNow":"ఇప్పుడు నిర్ధారించండి",
            "login":"లాగిన్","signup":"సైన్ అప్","email":"ఇమెయిల్","password":"పాస్‌వర్డ్","or":"లేదా",
            "googleSignIn":"Googleతో సైన్ ఇన్ చేయండి","analyze":"విశ్లేషించండి","uploadImage":"చిత్రాన్ని అప్లోడ్ చేయండి","analyzeLink":"లింక్ విశ్లేషణ",
            "videoTranscript":"వీడియో లిప్యంతరం","profile":"ప్రొఫైల్","dashboard":"డాష్బోర్డ్","about":"గురించి","logout":"లాగ్ అవుట్",
            "language":"భాష","theme":"థీమ్","score":"నమ్మక స్థాయి","summary":"సారాంశం","sources":"నిజమైన మూలాలు",
            "category":"వర్ణన","exportPDF":"PDF ఎగుమతి చేయండి","feedback":"ప్రతిస్పందన","contact":"మమ్మల్ని సంప్రదించండి","history":"చరిత్ర",
            "insights":"ఇన్సైట్","resources":"వనరులు","how":"ఇది ఎలా పనిచేస్తుంది","searchPlaceholder":"పాఠ్యం లేదా URL నిలిపివేయండి..."
        }
    }
    return jsonify(translations)

# --------------------------
# Errors
# --------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html", error=e, datetime=datetime, user=current_user), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("500.html", error=e, datetime=datetime, user=current_user), 500

# --------------------------
# Run
# --------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=os.getenv("FLASK_ENV","development")=="development")