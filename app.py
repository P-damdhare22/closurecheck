"""ClosureCheck - mobile-only citizen app (PWA) with login, roles and live-photo protection."""
import functools
import hashlib
import hmac
import math
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "closurecheck.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")  # set SECRET_KEY on the real server
app.config["UPLOAD_FOLDER"] = os.path.join(BASE, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024       # 8 MB per upload
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",   # set COOKIE_SECURE=1 on the https server
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

CATEGORIES = ["Pothole", "Streetlight", "Garbage", "Water supply"]
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}
DISTANCE_LIMIT_M = 30     # after-photo must be within 30 m of the original spot

# ---- accounts ----
# Officers must type this access code when they sign up. SET YOUR OWN on the real server.
OFFICER_CODE = os.environ.get("OFFICER_CODE", "demo-officer")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
MAX_FAILED, FAIL_WINDOW = 5, 600          # 5 wrong passwords per username per 10 minutes
failed_logins = {}
DUMMY_HASH = generate_password_hash("not-a-real-password")

# ---- anti-misuse settings ----
LIVE_ONLY = True          # True  = photos must come from the live camera (no gallery / downloaded images)
                          # False = demo mode: normal file upload + typed coordinates (for testing)
TOKEN_MAX_AGE = 600       # a camera session is valid for 10 minutes

# ---- mobile-only settings ----
MOBILE_ONLY_ALL = False                                   # True = block laptops from EVERY page
ALLOW_DESKTOP = os.environ.get("ALLOW_DESKTOP") == "1"    # developer switch for testing on a laptop
CITIZEN_ENDPOINTS = {"new_complaint", "after"}            # pages that take photos
MOBILE_UA = re.compile(r"Android|iPhone|iPad|iPod|Mobile", re.I)

serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])

# Complaint life-cycle:
#   open -> resolved_claimed -> after_submitted | unclear   (Day 3/4 will add verified / not_fixed)
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('citizen', 'officer')),
    created_at    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS complaints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT    NOT NULL,
    description         TEXT    NOT NULL,
    lat                 REAL    NOT NULL,
    lon                 REAL    NOT NULL,
    before_photo        TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'open',
    created_at          TEXT    NOT NULL,
    resolved_at         TEXT,
    after_photo         TEXT,
    after_lat           REAL,
    after_lon           REAL,
    verification_result TEXT,
    verification_note   TEXT,
    before_hash         TEXT,
    after_hash          TEXT,
    before_mode         TEXT,
    after_mode          TEXT,
    user_id             INTEGER
);
"""
NEW_COLUMNS = [("before_hash", "TEXT"), ("after_hash", "TEXT"),
               ("before_mode", "TEXT"), ("after_mode", "TEXT"), ("user_id", "INTEGER")]


# ---------- database helpers ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(SCHEMA)
        # upgrade an older database without losing its data
        existing = {r[1] for r in con.execute("PRAGMA table_info(complaints)")}
        for col, typ in NEW_COLUMNS:
            if col not in existing:
                con.execute(f"ALTER TABLE complaints ADD COLUMN {col} {typ}")


# ---------- request hooks: user, CSRF, mobile gate ----------
@app.before_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if g.user is None:
            session.clear()


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.context_processor
def inject_user():
    return {"user": g.get("user")}


@app.before_request
def csrf_protect():
    """Every form must carry the secret token of the current session."""
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
            abort(400, description="Your session expired. Please go back, reload the page and try again.")


def is_mobile():
    """True if the request comes from a phone/tablet browser."""
    if request.headers.get("Sec-CH-UA-Mobile") == "?1":
        return True
    return bool(MOBILE_UA.search(request.headers.get("User-Agent", "")))


@app.before_request
def mobile_gate():
    """Photo pages only open on a phone. A laptop gets a 'use your phone' page."""
    if not LIVE_ONLY or ALLOW_DESKTOP or is_mobile():
        return None
    if request.endpoint in CITIZEN_ENDPOINTS:
        return render_template("mobile_only.html"), 403
    if MOBILE_ONLY_ALL and request.endpoint not in ("static", "manifest", "service_worker"):
        return render_template("mobile_only.html"), 403
    return None


def login_required(role=None):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user is None:
                flash("Please log in first.")
                return redirect(url_for("login", next=request.path))
            if role and g.user["role"] != role:
                who = "department officers" if role == "officer" else "citizens"
                flash(f"That page is only for {who}.")
                return redirect(url_for("index"))
            return fn(*args, **kwargs)
        return wrapper
    return deco


def safe_next(target):
    """Only allow redirects to pages on this same site."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("index")


def too_many_attempts(key):
    now = time.time()
    recent = [t for t in failed_logins.get(key, []) if now - t < FAIL_WINDOW]
    failed_logins[key] = recent
    return len(recent) >= MAX_FAILED


# ---------- photo + live-capture helpers ----------
def read_photo(file_storage):
    """Return (bytes, extension) for a valid image upload, else None."""
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    data = file_storage.read()
    if ext not in ALLOWED_EXT or not data:
        return None
    return data, ext


def store_photo(data, ext):
    name = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(app.config["UPLOAD_FOLDER"], name), "wb") as f:
        f.write(data)
    return name


def make_token(purpose):
    return serializer.dumps(purpose)


def capture_error(purpose):
    """Return an error message if the live-capture rules are broken, else None."""
    if not LIVE_ONLY:
        return None
    if request.form.get("capture_mode") != "camera":
        return "Please take a live photo with the camera. Gallery or downloaded images are not accepted."
    try:
        value = serializer.loads(request.form.get("capture_token", ""), max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        return "This page was open too long. Please reload it and take a fresh photo."
    except BadSignature:
        return "Invalid camera session. Please reload the page and try again."
    if value != purpose:
        return "Invalid camera session. Please reload the page and try again."
    return None


def duplicate_of(db, digest):
    """Id of a complaint that already used this exact image file, else None."""
    row = db.execute(
        "SELECT id FROM complaints WHERE before_hash = ? OR after_hash = ?", (digest, digest)
    ).fetchone()
    return row["id"] if row else None


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle (haversine) distance between two GPS points, in metres."""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def mode_label():
    return "camera" if LIVE_ONLY else "upload"


# ---------- installable-app (PWA) files ----------
@app.route("/manifest.webmanifest")
def manifest():
    data = {
        "name": "ClosureCheck",
        "short_name": "ClosureCheck",
        "description": "Verify that government complaints are really fixed.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#0f1115",
        "theme_color": "#12141a",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    resp = jsonify(data)
    resp.mimetype = "application/manifest+json"
    return resp


@app.route("/sw.js")
def service_worker():
    return send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")


# ---------- accounts ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    nxt = request.values.get("next", "")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        key = username.lower()
        if too_many_attempts(key):
            flash("Too many wrong attempts. Please wait a few minutes and try again.")
            return render_template("login.html", next=nxt), 429
        row = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        ok = check_password_hash(row["password_hash"] if row else DUMMY_HASH, password)
        if row and ok:
            failed_logins.pop(key, None)
            session.clear()
            session["uid"] = row["id"]
            session.permanent = True
            flash(f"Welcome back, {row['display_name']}.")
            return redirect(safe_next(nxt))
        failed_logins.setdefault(key, []).append(time.time())
        flash("Wrong username or password.")
        return render_template("login.html", next=nxt), 401
    return render_template("login.html", next=nxt)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        role = request.form.get("role", "citizen")
        name = request.form.get("display_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        errors = []
        if role not in ("citizen", "officer"):
            errors.append("Please choose an account type.")
        elif role == "officer" and not hmac.compare_digest(request.form.get("officer_code", ""), OFFICER_CODE):
            errors.append("That officer access code is not correct.")
        if not 2 <= len(name) <= 40:
            errors.append("Please enter your name (2 to 40 letters).")
        if not USERNAME_RE.match(username):
            errors.append("Username must be 3 to 30 characters: letters, numbers, dot, dash or underscore.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if not errors:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (username, display_name, password_hash, role, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (username, name, generate_password_hash(password), role,
                     datetime.now().isoformat(timespec="seconds")),
                )
                db.commit()
            except sqlite3.IntegrityError:
                errors.append("That username is already taken.")
            else:
                session.clear()
                session["uid"] = cur.lastrowid
                session.permanent = True
                flash(f"Account created. Welcome, {name}!")
                return redirect(url_for("index"))
        for e in errors:
            flash(e)
        return render_template("signup.html", form=request.form), 400
    return render_template("signup.html", form={})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("index"))


@app.route("/account")
@login_required()
def account():
    return render_template("account.html")


# ---------- complaints ----------
@app.route("/")
def index():
    if g.user is None:
        return render_template("landing.html")
    db = get_db()
    sql = ("SELECT c.*, u.display_name AS filer FROM complaints c"
           " LEFT JOIN users u ON u.id = c.user_id")
    if g.user["role"] == "officer":
        rows = db.execute(sql + " ORDER BY c.id DESC").fetchall()
    else:
        rows = db.execute(sql + " WHERE c.user_id = ? ORDER BY c.id DESC", (g.user["id"],)).fetchall()
    stats = {
        "total": len(rows),
        "claimed": sum(1 for r in rows if r["status"] != "open"),
        "verified": sum(1 for r in rows if r["status"] == "verified"),
        "flagged": sum(1 for r in rows if r["status"] in ("not_fixed", "unclear")),
    }
    return render_template("index.html", complaints=rows, stats=stats)


@app.route("/new", methods=["GET", "POST"])
@login_required("citizen")
def new_complaint():
    def page(code=200):
        return render_template("new.html", categories=CATEGORIES, live_only=LIVE_ONLY,
                               token=make_token("before"), photo_field="before_photo"), code

    if request.method == "POST":
        err = capture_error("before")
        category = request.form.get("category", "")
        description = request.form.get("description", "").strip()
        lat = lon = None
        try:
            lat = float(request.form["lat"])
            lon = float(request.form["lon"])
        except (KeyError, ValueError):
            err = err or "Please allow location access (or give a valid latitude and longitude)."
        photo = read_photo(request.files.get("before_photo"))
        if not err and (category not in CATEGORIES or not description or not photo):
            err = "Category, description and a photo are required."

        db = get_db()
        if not err and LIVE_ONLY:
            digest = hashlib.sha256(photo[0]).hexdigest()
            dup = duplicate_of(db, digest)
            if dup:
                err = f"This exact photo was already used in complaint #{dup}. Please take a new photo."
        if err:
            flash(err)
            return page(400)

        name = store_photo(*photo)
        db.execute(
            "INSERT INTO complaints (category, description, lat, lon, before_photo, created_at,"
            " before_hash, before_mode, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (category, description, lat, lon, name, datetime.now().isoformat(timespec="seconds"),
             hashlib.sha256(photo[0]).hexdigest(), mode_label(), g.user["id"]),
        )
        db.commit()
        flash("Complaint submitted.")
        return redirect(url_for("index"))
    return page()


@app.route("/admin")
@login_required("officer")
def admin():
    """Department view: complaints still open, with a 'Mark resolved' button."""
    db = get_db()
    rows = db.execute("SELECT * FROM complaints WHERE status = 'open' ORDER BY id").fetchall()
    return render_template("admin.html", complaints=rows)


@app.route("/resolve/<int:complaint_id>", methods=["POST"])
@login_required("officer")
def resolve(complaint_id):
    db = get_db()
    db.execute(
        "UPDATE complaints SET status = 'resolved_claimed', resolved_at = ?"
        " WHERE id = ? AND status = 'open'",
        (datetime.now().isoformat(timespec="seconds"), complaint_id),
    )
    db.commit()
    flash(f"Complaint #{complaint_id} marked resolved by the department.")
    return redirect(url_for("admin"))


@app.route("/after/<int:complaint_id>", methods=["GET", "POST"])
@login_required("citizen")
def after(complaint_id):
    """The citizen who filed the complaint uploads an after-photo once the department says 'resolved'."""
    db = get_db()
    c = db.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
    if c is None or c["user_id"] != g.user["id"]:
        flash("You can only add an after-photo to your own complaints.")
        return redirect(url_for("index"))
    if c["status"] != "resolved_claimed":
        flash("That complaint is not waiting for an after-photo.")
        return redirect(url_for("index"))
    purpose = f"after-{complaint_id}"

    def page(code=200):
        return render_template("after.html", c=c, live_only=LIVE_ONLY,
                               token=make_token(purpose), photo_field="after_photo"), code

    if request.method == "POST":
        err = capture_error(purpose)
        lat = lon = None
        try:
            lat = float(request.form["lat"])
            lon = float(request.form["lon"])
        except (KeyError, ValueError):
            err = err or "Please allow location access (or give a valid latitude and longitude)."
        photo = read_photo(request.files.get("after_photo"))
        if not err and not photo:
            err = "Please take or attach an after-photo."
        if not err and LIVE_ONLY:
            digest = hashlib.sha256(photo[0]).hexdigest()
            dup = duplicate_of(db, digest)
            if dup:
                err = f"This exact photo was already used in complaint #{dup}. Please take a new photo."
        if err:
            flash(err)
            return page(400)

        name = store_photo(*photo)
        d = distance_m(c["lat"], c["lon"], lat, lon)
        if d > DISTANCE_LIMIT_M:
            status = "unclear"
            note = f"After-photo was taken {d:.0f} m away from the original spot (limit {DISTANCE_LIMIT_M} m)."
        else:
            status = "after_submitted"
            note = f"Location matches ({d:.0f} m). Visual check comes next."

        db.execute(
            "UPDATE complaints SET after_photo=?, after_lat=?, after_lon=?, status=?,"
            " verification_result=?, verification_note=?, after_hash=?, after_mode=? WHERE id=?",
            (name, lat, lon, status, status, note,
             hashlib.sha256(photo[0]).hexdigest(), mode_label(), complaint_id),
        )
        db.commit()
        flash(note)
        return redirect(url_for("index"))
    return page()


init_db()

if __name__ == "__main__":
    app.run(debug=True)
