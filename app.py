import os
import sqlite3
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash
)
from flask_login import (
    LoginManager, UserMixin, login_user,
    login_required, logout_user, current_user
)
from flask_dance.contrib.google import make_google_blueprint, google
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from google import genai
from google.genai.types import GenerateContentConfig
from flask_talisman import Talisman

# ------------------- CONFIGURATION -------------------

load_dotenv()

app = Flask(__name__)
Talisman(app, content_security_policy=None)

app.secret_key = os.getenv("SECRET_KEY", "default_secret")

DATABASE = "truthlens.db"
UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

login_manager = LoginManager(app)
login_manager.login_view = "login"

# ------------------- GOOGLE OAUTH -------------------

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

google_bp = make_google_blueprint(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    scope=["profile", "email"],
    redirect_to="google_login"
)
app.register_blueprint(google_bp, url_prefix="/login")

# ------------------- GEMINI API SETUP -------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai_client = genai.Client(api_key=GEMINI_API_KEY)

# ------------------- DATABASE -------------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                email TEXT UNIQUE,
                password TEXT,
                theme TEXT DEFAULT 'light',
                language TEXT DEFAULT 'en'
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                input_text TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.commit()

init_db()

# ------------------- USER MODEL -------------------

class User(UserMixin):
    def __init__(self, id_, username, email, password):
        self.id = id_
        self.username = username
        self.email = email
        self.password = password

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user:
        return User(user["id"], user["username"], user["email"], user["password"])
    return None

# ------------------- ROUTES -------------------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])
        try:
            with get_db() as db:
                db.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)", (username, email, password))
                db.commit()
                flash("Signup successful! Please log in.", "success")
                return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.", "error")
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password"], password):
            login_user(User(user["id"], user["username"], user["email"], user["password"]))
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials.", "error")
    return render_template("login.html")

@app.route("/login/google")
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))
    resp = google.get("/oauth2/v2/userinfo")
    info = resp.json()
    email = info["email"]
    username = info.get("name", email.split("@")[0])

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        db.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)", (username, email, ""))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    login_user(User(user["id"], user["username"], user["email"], user["password"]))
    return redirect(url_for("dashboard"))

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully!", "info")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    results = db.execute("SELECT * FROM analyses WHERE user_id = ? ORDER BY created_at DESC", (current_user.id,)).fetchall()
    return render_template("dashboard.html", analyses=results, username=current_user.username)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", user=current_user)

# ------------------- ANALYSIS (GEMINI) -------------------

def gemini_analyze_text(text):
    """Analyze text using Gemini API"""
    try:
        response = genai_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=text,
            config=GenerateContentConfig(
                max_output_tokens=500,
                temperature=0.4
            )
        )
        return response.text or "No analysis found."
    except Exception as e:
        return f"Error: {e}"

@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    text = request.form.get("text")
    if not text:
        return jsonify({"error": "No text provided."}), 400

    result = gemini_analyze_text(text)
    with get_db() as db:
        db.execute("INSERT INTO analyses (user_id, input_text, result) VALUES (?, ?, ?)",
                   (current_user.id, text, result))
        db.commit()

    return jsonify({"result": result})

# ------------------- SETTINGS & APIs -------------------

@app.route("/api/theme", methods=["POST"])
@login_required
def update_theme():
    theme = request.json.get("theme", "light")
    with get_db() as db:
        db.execute("UPDATE users SET theme = ? WHERE id = ?", (theme, current_user.id))
        db.commit()
    return jsonify({"success": True, "theme": theme})

@app.route("/api/language", methods=["POST"])
@login_required
def update_language():
    language = request.json.get("language", "en")
    with get_db() as db:
        db.execute("UPDATE users SET language = ? WHERE id = ?", (language, current_user.id))
        db.commit()
    return jsonify({"success": True, "language": language})

@app.route("/api/history")
@login_required
def history():
    db = get_db()
    data = db.execute("SELECT * FROM analyses WHERE user_id = ? ORDER BY created_at DESC", (current_user.id,)).fetchall()
    return jsonify([dict(row) for row in data])

@app.route("/api/ping")
def ping():
    return jsonify({"status": "ok"})

# ------------------- OPTIONAL UTILS -------------------

@app.route("/init_db")
def manual_init():
    init_db()
    return "Database initialized successfully!"

@app.route("/debug_env")
def debug_env():
    return jsonify({
        "GEMINI_API_KEY": bool(GEMINI_API_KEY),
        "GOOGLE_CLIENT_ID": bool(GOOGLE_CLIENT_ID),
        "GOOGLE_CLIENT_SECRET": bool(GOOGLE_CLIENT_SECRET)
    })

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def internal_error(e):
    return render_template("500.html"), 500

# ------------------- MAIN -------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)