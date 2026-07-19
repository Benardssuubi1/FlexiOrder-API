import os, json, uuid, time, re, hashlib, hmac, math
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timezone
from functools import wraps
from collections import defaultdict
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

app = Flask(__name__)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
API_KEY      = os.environ.get("API_SECRET_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")
DEBUG        = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

if not API_KEY:
    raise ValueError("CRITICAL: API_SECRET_KEY not set.")
if not DATABASE_URL:
    raise ValueError("CRITICAL: DATABASE_URL not set.")

CORS(app, resources={r"/api/*": {
    "origins": "*",
    "allow_headers": ["Content-Type", "X-API-Key"],
    "methods": ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
}})

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def utcnow():
    return datetime.now(timezone.utc).isoformat()

def safe_float(val):
    """Convert to float, rejecting NaN/Inf."""
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            raise ValueError("NaN or Inf not allowed")
        return f
    except (TypeError, ValueError):
        raise ValueError(f"Invalid float value: {val}")

def _hash_pw(pw):
    return hmac.new(API_KEY.encode(), pw.encode(), hashlib.sha256).hexdigest()

# ─────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────
def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, table_name TEXT, table_num INTEGER,
            customer TEXT, note TEXT DEFAULT '', items TEXT,
            total INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
            payment_method TEXT DEFAULT '', payment_contact TEXT DEFAULT '',
            temp_preference TEXT DEFAULT '', created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS venues (
            id TEXT PRIMARY KEY DEFAULT 'default',
            name TEXT DEFAULT 'FlexiOrder',
            theme_color TEXT DEFAULT '#d4a017',
            logo_url TEXT DEFAULT '',
            lat DOUBLE PRECISION, lng DOUBLE PRECISION,
            geofence_radius_m INTEGER DEFAULT 150,
            updated_at TEXT
        )
    """)
    cur.execute("""
        INSERT INTO venues (id, updated_at) VALUES ('default', %s)
        ON CONFLICT (id) DO NOTHING
    """, (utcnow(),))
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tables (
            id TEXT PRIMARY KEY, name TEXT, table_num INTEGER,
            active BOOLEAN DEFAULT TRUE, created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS menu_items (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
            price INTEGER NOT NULL, category TEXT DEFAULT 'Other',
            emoji TEXT DEFAULT '🍹', available BOOLEAN DEFAULT TRUE,
            sort_order INTEGER DEFAULT 0, created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_passwords (
            role TEXT PRIMARY KEY,
            pw_hash TEXT NOT NULL,
            updated_at TEXT
        )
    """)
    for role, default_pw in [('manager', 'flexi2025'), ('attendant', 'flexiattendant')]:
        cur.execute("SELECT role FROM app_passwords WHERE role=%s", (role,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO app_passwords (role, pw_hash, updated_at) VALUES (%s, %s, %s)",
                (role, _hash_pw(default_pw), utcnow())
            )
    
    # Add default tables if none exist
    cur.execute("SELECT COUNT(*) FROM tables")
    table_count = cur.fetchone()['count']
    if table_count == 0:
        print("Adding default tables...")
        default_tables = [
            ('t1', 'Table 1', 1),
            ('t2', 'Table 2', 2),
            ('t3', 'Table 3', 3),
            ('t4', 'Table 4', 4),
            ('t5', 'Table 5', 5),
            ('t6', 'Table 6', 6),
            ('t7', 'Table 7', 7),
            ('t8', 'Table 8', 8),
            ('t9', 'Table 9', 9),
            ('t10', 'Table 10', 10),
            ('t11', 'Table 11', 11),
            ('t12', 'Table 12', 12),
            ('t13', 'VIP 1', 13),
            ('t14', 'VIP 2', 14),
            ('t15', 'VIP 3', 15),
        ]
        for table_id, name, num in default_tables:
            cur.execute(
                "INSERT INTO tables (id, name, table_num, active, created_at) VALUES (%s, %s, %s, TRUE, %s)",
                (table_id, name, num, utcnow())
            )
        print(f"Added {len(default_tables)} default tables")
    
    # Add default menu items if none exist
    cur.execute("SELECT COUNT(*) FROM menu_items")
    menu_count = cur.fetchone()['count']
    if menu_count == 0:
        print("Adding default menu items...")
        default_menu = [
            ('m1', 'Nile Special', 'Popular Ugandan lager', 5000, 'Beers & Ciders', '🍺', 1),
            ('m2', 'Bell Lager', 'Classic beer', 4000, 'Beers & Ciders', '🍺', 2),
            ('m3', 'Club Pilsner', 'Light pilsner', 3500, 'Beers & Ciders', '🍺', 3),
            ('m4', 'Coca Cola', 'Soft drink', 2000, 'Soft Drinks', '🥤', 4),
            ('m5', 'Sprite', 'Lemon soft drink', 2000, 'Soft Drinks', '🥤', 5),
            ('m6', 'Stoney', 'Ginger soft drink', 2000, 'Soft Drinks', '🥤', 6),
            ('m7', 'Water', 'Mineral water', 1000, 'Water', '💧', 7),
            ('m8', 'Soda', 'Sparkling water', 1500, 'Soft Drinks', '🥤', 8),
            ('m9', 'Juice', 'Fresh fruit juice', 3000, 'Juices', '🧃', 9),
            ('m10', 'Tonic Water', 'Mixing tonic', 2000, 'Soft Drinks', '🥤', 10),
        ]
        for item_id, name, desc, price, category, emoji, sort_order in default_menu:
            cur.execute(
                "INSERT INTO menu_items (id, name, description, price, category, emoji, available, sort_order, created_at) VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s)",
                (item_id, name, desc, price, category, emoji, sort_order, utcnow())
            )
        print(f"Added {len(default_menu)} default menu items")
    
    conn.commit(); cur.close(); conn.close()
    print("Database ready (PostgreSQL)")

def row_to_dict(row):
    d = dict(row)
    try: d["items"] = json.loads(d.get("items") or "[]")
    except: d["items"] = []
    return d

# ─────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("apikey")
        if not key or key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

_req_counts = defaultdict(list)
def rate_limit(max_per_minute=60):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            ip = request.remote_addr or "unknown"
            now = time.time()
            _req_counts[ip] = [t for t in _req_counts[ip] if now - t < 60]
            if len(_req_counts[ip]) >= max_per_minute:
                return jsonify({"error": "Too many requests"}), 429
            _req_counts[ip].append(now)
            return f(*args, **kwargs)
        return decorated
    return decorator

_login_fails = defaultdict(list)
def check_login_rate(ip):
    now = time.time()
    _login_fails[ip] = [t for t in _login_fails[ip] if now - t < 300]
    return len(_login_fails[ip]) >= 10

def sanitise(text, max_len=200):
    text = re.sub(r'<[^>]+>', '', str(text))
    text = re.sub(r'[^\w\s\.,\-\'\"!?#@+:/()]', '', text)
    return text.strip()[:max_len]

# ─────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────
@app.route("/api/auth/login", methods=["POST"])
@rate_limit(20)
def login():
    ip = request.remote_addr or "unknown"
    if check_login_rate(ip):
        return jsonify({"error": "Too many failed attempts. Try again in 5 minutes."}), 429
    data = request.get_json(silent=True) or {}
    role = data.get("role", "").strip().lower()
    pw   = data.get("password", "").strip()
    if role not in ("manager", "attendant"):
        return jsonify({"error": "Invalid role"}), 400
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT pw_hash FROM app_passwords WHERE role=%s", (role,))
    row = cur.fetchone(); cur.close(); conn.close()
    if not row or row["pw_hash"] != _hash_pw(pw):
        _login_fails[ip].append(time.time())
        return jsonify({"error": "Incorrect password"}), 401
    ts    = str(int(time.time()))
    token = hmac.new(API_KEY.encode(), f"{role}:{ts}".encode(), hashlib.sha256).hexdigest()
    return jsonify({"success": True, "role": role, "token": token, "ts": ts})

@app.route("/api/auth/change-password", methods=["POST"])
@require_api_key
def change_password():
    data   = request.get_json(silent=True) or {}
    role   = data.get("role", "").strip().lower()
    old_pw = data.get("old_password", "").strip()
    new_pw = data.get("new_password", "").strip()
    if role not in ("manager", "attendant"):
        return jsonify({"error": "Invalid role"}), 400
    if len(new_pw) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT pw_hash FROM app_passwords WHERE role=%s", (role,))
    row = cur.fetchone()
    if not row or row["pw_hash"] != _hash_pw(old_pw):
        cur.close(); conn.close()
        return jsonify({"error": "Current password incorrect"}), 401
    cur.execute(
        "UPDATE app_passwords SET pw_hash=%s, updated_at=%s WHERE role=%s",
        (_hash_pw(new_pw), utcnow(), role)
    )
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})

# ─────────────────────────────────────────
# ORDERS
# ─────────────────────────────────────────
@app.route("/api/orders", methods=["GET"])
@require_api_key
def get_orders():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
    rows = cur.fetchall(); cur.close(); conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/orders", methods=["POST"])
@rate_limit(30)
def post_order():
    data  = request.get_json(silent=True) or {}
    items = data.get("items", [])
    if not isinstance(items, list) or not items:
        return jsonify({"error": "items required"}), 400
    table_name = sanitise(data.get("table_name", ""), 30)
    if not table_name:
        return jsonify({"error": "table_name required"}), 400
    clean_items = []
    total = 0
    for it in items:
        if not isinstance(it, dict): continue
        qty   = max(1, min(20, int(it.get("qty", 1))))
        price = max(0, int(it.get("price", 0)))
        clean_items.append({
            "name":     sanitise(it.get("name", ""), 80),
            "emoji":    sanitise(it.get("emoji", ""), 8),
            "qty":      qty,
            "price":    price,
            "category": sanitise(it.get("category", ""), 40)
        })
        total += qty * price
    oid = str(uuid.uuid4())[:8].upper()
    conn = get_db(); cur = conn.cursor()
    table_num_raw = data.get("table_num", "")
    table_num = int(table_num_raw) if str(table_num_raw).isdigit() else None
    cur.execute("""
        INSERT INTO orders (id, table_name, table_num, customer, note, items, total,
            status, payment_method, payment_contact, temp_preference, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s)
    """, (
        oid, table_name, table_num,
        sanitise(data.get("customer", "Guest"), 60),
        sanitise(data.get("note", ""), 300),
        json.dumps(clean_items), total,
        sanitise(data.get("payment_method", "Cash"), 40),
        sanitise(data.get("payment_contact", ""), 60),
        sanitise(data.get("temp_preference", ""), 20),
        utcnow()
    ))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True, "id": oid, "total": total}), 201

@app.route("/api/orders/<oid>", methods=["PATCH"])
@require_api_key
def patch_order(oid):
    data   = request.get_json(silent=True) or {}
    status = data.get("status", "")
    if status not in ("pending", "preparing", "ready", "delivered"):
        return jsonify({"error": "Invalid status"}), 400
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE orders SET status=%s WHERE id=%s", (status, oid))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})

@app.route("/api/orders/<oid>", methods=["DELETE"])
@require_api_key
def delete_order(oid):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM orders WHERE id=%s", (oid,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})

@app.route("/api/orders/delivered", methods=["DELETE"])
@require_api_key
def clear_delivered():
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM orders WHERE status='delivered'")
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})

# ─────────────────────────────────────────
# MENU
# ─────────────────────────────────────────
@app.route("/api/menu", methods=["GET"])
def get_menu():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM menu_items WHERE available=TRUE ORDER BY category, sort_order, name")
    rows = cur.fetchall(); cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/menu/all", methods=["GET"])
@require_api_key
def get_menu_all():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM menu_items ORDER BY category, sort_order, name")
    rows = cur.fetchall(); cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/menu", methods=["POST"])
@require_api_key
def add_menu_item():
    data = request.get_json(silent=True) or {}
    name = sanitise(data.get("name", ""), 80).strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    price = int(data.get("price", 0))
    if price < 0:
        return jsonify({"error": "price must be >= 0"}), 400
    mid = str(uuid.uuid4())
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO menu_items (id, name, description, price, category, emoji, available, sort_order, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        mid, name,
        sanitise(data.get("description", ""), 200),
        price,
        sanitise(data.get("category", "Other"), 40),
        sanitise(data.get("emoji", "🍹"), 8),
        bool(data.get("available", True)),
        int(data.get("sort_order", 0)),
        utcnow()
    ))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True, "id": mid}), 201

@app.route("/api/menu/<mid>", methods=["PATCH"])
@require_api_key
def update_menu_item(mid):
    data = request.get_json(silent=True) or {}
    fields, vals = [], []
    for col, maxlen in [("name",80),("description",200),("category",40),("emoji",8)]:
        if col in data:
            fields.append(f"{col}=%s"); vals.append(sanitise(data[col], maxlen))
    if "price" in data:
        fields.append("price=%s"); vals.append(max(0, int(data["price"])))
    if "available" in data:
        fields.append("available=%s"); vals.append(bool(data["available"]))
    if "sort_order" in data:
        fields.append("sort_order=%s"); vals.append(int(data["sort_order"]))
    if not fields:
        return jsonify({"error": "Nothing to update"}), 400
    vals.append(mid)
    conn = get_db(); cur = conn.cursor()
    cur.execute(f"UPDATE menu_items SET {','.join(fields)} WHERE id=%s", vals)
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})

@app.route("/api/menu/<mid>", methods=["DELETE"])
@require_api_key
def delete_menu_item(mid):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM menu_items WHERE id=%s", (mid,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})

# ─────────────────────────────────────────
# VENUE
# ─────────────────────────────────────────
@app.route("/api/venue", methods=["GET"])
@require_api_key
def get_venue():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM venues WHERE id='default'")
    row = cur.fetchone(); cur.close(); conn.close()
    return jsonify(dict(row) if row else {})

@app.route("/api/venue", methods=["PATCH"])
@require_api_key
def patch_venue():
    data = request.get_json(silent=True) or {}
    fields, vals = [], []
    if "name"              in data: fields.append("name=%s");              vals.append(sanitise(data["name"], 100))
    if "theme_color"       in data: fields.append("theme_color=%s");       vals.append(sanitise(data["theme_color"], 20))
    if "logo_url"          in data: fields.append("logo_url=%s");          vals.append(sanitise(data["logo_url"], 300))
    if "geofence_radius_m" in data: fields.append("geofence_radius_m=%s"); vals.append(int(data["geofence_radius_m"]))
    if "lat" in data:
        try:    fields.append("lat=%s"); vals.append(safe_float(data["lat"]))
        except: return jsonify({"error": "Invalid lat value"}), 400
    if "lng" in data:
        try:    fields.append("lng=%s"); vals.append(safe_float(data["lng"]))
        except: return jsonify({"error": "Invalid lng value"}), 400
    if not fields:
        return jsonify({"error": "Nothing to update"}), 400
    fields.append("updated_at=%s"); vals.append(utcnow())
    conn = get_db(); cur = conn.cursor()
    cur.execute(f"UPDATE venues SET {','.join(fields)} WHERE id='default'", vals)
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})

# ─────────────────────────────────────────
# TABLES
# ─────────────────────────────────────────
@app.route("/api/tables", methods=["GET"])
def get_tables():
    """Public endpoint — customers need to see active tables to place orders."""
    show_all = request.args.get("all") == "1"
    # show_all=1 requires API key (admin use)
    if show_all:
        key = request.headers.get("X-API-Key") or request.args.get("apikey")
        if not key or key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
    conn = get_db(); cur = conn.cursor()
    if show_all:
        cur.execute("SELECT * FROM tables ORDER BY table_num ASC, name ASC")
    else:
        cur.execute("SELECT * FROM tables WHERE active=TRUE ORDER BY table_num ASC, name ASC")
    rows = cur.fetchall(); cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/tables", methods=["POST"])
@require_api_key
def add_table():
    data = request.get_json(silent=True) or {}
    name = sanitise(data.get("name", ""), 30).strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    tid = str(uuid.uuid4())
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO tables (id, name, table_num, active, created_at) VALUES (%s,%s,%s,TRUE,%s)",
        (tid, name, data.get("table_num"), utcnow())
    )
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True, "id": tid}), 201

@app.route("/api/tables/<tid>", methods=["PATCH"])
@require_api_key
def patch_table(tid):
    data = request.get_json(silent=True) or {}
    fields, vals = [], []
    if "name"      in data: fields.append("name=%s");      vals.append(sanitise(data["name"], 30))
    if "table_num" in data: fields.append("table_num=%s"); vals.append(data["table_num"])
    if "active"    in data: fields.append("active=%s");    vals.append(bool(data["active"]))
    if not fields:
        return jsonify({"error": "Nothing to update"}), 400
    vals.append(tid)
    conn = get_db(); cur = conn.cursor()
    cur.execute(f"UPDATE tables SET {','.join(fields)} WHERE id=%s", vals)
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})

@app.route("/api/tables/<tid>", methods=["DELETE"])
@require_api_key
def delete_table(tid):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM tables WHERE id=%s", (tid,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})

# ─────────────────────────────────────────
# MISC
# ─────────────────────────────────────────
@app.route("/")
def index():
    return jsonify({"status": "online", "service": "FlexiOrder API", "version": "2.1.0"})

@app.route("/api/ping")
def ping():
    return jsonify({"status": "ok"})

# ─────────────────────────────────────────
# INIT
# ─────────────────────────────────────────
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=DEBUG)
