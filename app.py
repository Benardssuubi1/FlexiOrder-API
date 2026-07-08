import os
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
from functools import wraps
from collections import defaultdict
import json, uuid, time, re
import psycopg2
from psycopg2.extras import RealDictCursor

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
# Pulled directly from the environment (or .env file)
API_KEY = os.environ.get("API_SECRET_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

if not API_KEY:
    raise ValueError("CRITICAL ERROR: API_SECRET_KEY not set in environment.")
if not DATABASE_URL:
    raise ValueError("CRITICAL ERROR: DATABASE_URL not set in environment.")

# CORS — single source of truth (previously registered twice, which is
# unnecessary and confusing; keep only this one).
CORS(app, resources={r"/api/*": {
    "origins": "https://flexi-order-rouge.vercel.app",
    "allow_headers": ["Content-Type", "X-API-Key"],
    "methods": ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
}})

# ─────────────────────────────────────────
# DATABASE — PostgreSQL
# ─────────────────────────────────────────
def get_db():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL is not set!")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            table_name TEXT,
            table_num INTEGER,
            customer TEXT,
            note TEXT DEFAULT '',
            items TEXT,
            total INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS venues (
            id TEXT PRIMARY KEY DEFAULT 'default',
            name TEXT DEFAULT 'FlexiOrder',
            theme_color TEXT DEFAULT '#d4a017',
            logo_url TEXT DEFAULT '',
            lat DOUBLE PRECISION,
            lng DOUBLE PRECISION,
            geofence_radius_m INTEGER DEFAULT 150,
            updated_at TEXT
        )
    """)
    cur.execute("""
        INSERT INTO venues (id, updated_at) VALUES ('default', %s)
        ON CONFLICT (id) DO NOTHING
    """, (datetime.now().isoformat(),))
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tables (
            id TEXT PRIMARY KEY,
            name TEXT,
            table_num INTEGER,
            active BOOLEAN DEFAULT TRUE,
            created_at TEXT
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("Database ready (PostgreSQL)")

def row_to_dict(row):
    d = dict(row)
    try:
        d["items"] = json.loads(d.get("items") or "[]")
    except:
        d["items"] = []
    return d

# ─────────────────────────────────────────
# SECURITY & HELPERS
# ─────────────────────────────────────────
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("apikey")
        if not key or key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

request_counts = defaultdict(list)
def rate_limit(max_per_minute=60):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            ip = request.remote_addr or "unknown"
            now = time.time()
            request_counts[ip] = [t for t in request_counts[ip] if now - t < 60]
            if len(request_counts[ip]) >= max_per_minute:
                return jsonify({"error": "Too many requests"}), 429
            request_counts[ip].append(now)
            return f(*args, **kwargs)
        return decorated
    return decorator

def sanitise(text, max_len=200):
    text = re.sub(r'<[^>]+>', '', str(text))
    text = re.sub(r'[^\w\s\.,\-\'\"!?#@+:/()]', '', text)
    return text.strip()[:max_len]

# ─────────────────────────────────────────
# API ROUTES (Simplified for brevity, same logic as before)
# ─────────────────────────────────────────
@app.route("/")
def index():
    return {
        "status": "online",
        "service": "FlexiOrder API",
        "version": "1.0.0",
        "documentation": "https://flexiorder-api.onrender.com/api/docs"
    }

@app.route("/api/ping")
def ping(): return jsonify({"status": "ok", "service": "FlexiOrder API"})

@app.route("/api/orders", methods=["GET"])
@require_api_key
def get_orders():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/venue", methods=["GET"])
@require_api_key
def get_venue():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM venues WHERE id='default'")
    row = cur.fetchone()
    cur.close(); conn.close()
    return jsonify(dict(row) if row else {})

@app.route("/api/tables", methods=["GET"])
@require_api_key
def get_tables():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tables WHERE active=TRUE ORDER BY table_num ASC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])
@app.route('/settings', methods=['POST'])
def update_settings():
    data = request.json
    # Logic to save settings to your database
    return {"status": "Settings Updated"}, 200

# (All your other POST/PATCH/DELETE routes go here as before...)

# ─────────────────────────────────────────
# DATABASE INITIALIZATION
# ─────────────────────────────────────────
# IMPORTANT: this must run at IMPORT time, not just under `python app.py`.
# In production, gunicorn imports this module directly (`gunicorn app:app`),
# so `__name__` is never "__main__" and anything inside that guard is
# skipped. init_db() has to run unconditionally here so the tables exist
# whether the app is started locally or via gunicorn on Render/Railway.
init_db()

if __name__ == "__main__":
    # Local development only — gunicorn (production) never hits this block.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
