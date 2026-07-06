"""
Climax Lounge Makindye — Secure Flask API
==========================================
Database : PostgreSQL (Railway) — orders persist forever
Security : API key auth, rate limiting, input validation, CORS
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
from functools import wraps
from collections import defaultdict
import json, uuid, os, time, re

# PostgreSQL driver
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────

API_KEY      = os.environ.get("API_SECRET_KEY", "climax-secret-2025")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# CORS — open to all origins, security via API key
CORS(app, resources={r"/api/*": {
    "origins": "*",
    "allow_headers": ["Content-Type", "X-API-Key"],
    "methods": ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
}})

# ─────────────────────────────────────────
# DATABASE — PostgreSQL
# ─────────────────────────────────────────

def get_db():
    """Open a PostgreSQL connection."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    """Create the orders, venues, and tables tables if they don't exist."""
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id          TEXT PRIMARY KEY,
            table_name  TEXT,
            table_num   INTEGER,
            customer    TEXT,
            note        TEXT DEFAULT '',
            items       TEXT,
            total       INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT
        )
    """)

    # Single-row table holding venue-wide settings (name, theme, geofence).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS venues (
            id                 TEXT PRIMARY KEY DEFAULT 'default',
            name               TEXT DEFAULT 'Climax Lounge Makindye',
            theme_color        TEXT DEFAULT '#d4a017',
            logo_url           TEXT DEFAULT '',
            lat                DOUBLE PRECISION,
            lng                DOUBLE PRECISION,
            geofence_radius_m  INTEGER DEFAULT 150,
            updated_at         TEXT
        )
    """)
    # Seed the single venue row if it doesn't exist yet.
    cur.execute("""
        INSERT INTO venues (id, updated_at) VALUES ('default', %s)
        ON CONFLICT (id) DO NOTHING
    """, (datetime.now().isoformat(),))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tables (
            id          TEXT PRIMARY KEY,
            name        TEXT,
            table_num   INTEGER,
            active      BOOLEAN DEFAULT TRUE,
            created_at  TEXT
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("  Database ready (PostgreSQL)")

def row_to_dict(row):
    """Convert a DB row to a plain dict, parsing items JSON."""
    d = dict(row)
    try:
        d["items"] = json.loads(d.get("items") or "[]")
    except Exception:
        d["items"] = []
    return d

# ─────────────────────────────────────────
# SECURITY — API KEY
# ─────────────────────────────────────────

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("apikey")
        if not key or key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────
# SECURITY — RATE LIMITING
# ─────────────────────────────────────────

request_counts = defaultdict(list)

def rate_limit(max_per_minute=60):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            ip  = request.remote_addr or "unknown"
            now = time.time()
            request_counts[ip] = [t for t in request_counts[ip] if now - t < 60]
            if len(request_counts[ip]) >= max_per_minute:
                return jsonify({"error": "Too many requests. Slow down."}), 429
            request_counts[ip].append(now)
            return f(*args, **kwargs)
        return decorated
    return decorator

# ─────────────────────────────────────────
# SECURITY — INPUT VALIDATION
# ─────────────────────────────────────────

def sanitise(text, max_len=200):
    if not isinstance(text, str):
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[^\w\s\.,\-\'\"!?#@+:/()]', '', text)
    return text.strip()[:max_len]

def validate_order(data):
    if not isinstance(data, dict):
        return False, "Invalid request body"
    table_num = data.get("table_num")
    if not isinstance(table_num, int) or not (1 <= table_num <= 500):
        return False, "table_num must be between 1 and 500"
    customer = data.get("customer", "").strip()
    if not customer:
        return False, "customer name is required"
    items = data.get("items", [])
    if not isinstance(items, list) or len(items) == 0:
        return False, "items cannot be empty"
    if len(items) > 30:
        return False, "too many items in one order"
    for item in items:
        if not isinstance(item, dict):
            return False, "invalid item format"
        if not item.get("name"):
            return False, "each item must have a name"
        price = item.get("price", 0)
        qty   = item.get("qty", 0)
        if not isinstance(price, (int, float)) or price < 0:
            return False, "invalid item price"
        if not isinstance(qty, int) or qty < 1 or qty > 50:
            return False, "invalid item quantity"
    return True, None


def validate_venue(data):
    if not isinstance(data, dict):
        return False, "Invalid request body"
    if "theme_color" in data and data["theme_color"] is not None:
        tc = data["theme_color"]
        if not isinstance(tc, str) or not re.match(r'^#[0-9A-Fa-f]{6}$', tc):
            return False, "theme_color must be a hex color like #d4a017"
    if "lat" in data and data["lat"] is not None:
        lat = data["lat"]
        if not isinstance(lat, (int, float)) or not (-90 <= lat <= 90):
            return False, "lat must be between -90 and 90"
    if "lng" in data and data["lng"] is not None:
        lng = data["lng"]
        if not isinstance(lng, (int, float)) or not (-180 <= lng <= 180):
            return False, "lng must be between -180 and 180"
    if "geofence_radius_m" in data and data["geofence_radius_m"] is not None:
        r = data["geofence_radius_m"]
        if not isinstance(r, int) or not (10 <= r <= 5000):
            return False, "geofence_radius_m must be between 10 and 5000"
    return True, None


def validate_table(data):
    if not isinstance(data, dict):
        return False, "Invalid request body"
    name = data.get("name", "")
    if not isinstance(name, str) or not name.strip():
        return False, "table name is required"
    if "table_num" in data and data["table_num"] is not None:
        tn = data["table_num"]
        if not isinstance(tn, int) or not (1 <= tn <= 500):
            return False, "table_num must be between 1 and 500"
    return True, None

# ─────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────

@app.route("/api/ping")
def ping():
    return jsonify({"status": "ok", "service": "Climax Lounge API", "db": "postgresql"})


@app.route("/api/orders", methods=["GET"])
@require_api_key
@rate_limit(60)
def get_orders():
    status = request.args.get("status")
    conn = get_db()
    cur  = conn.cursor()
    if status:
        cur.execute("SELECT * FROM orders WHERE status=%s ORDER BY created_at DESC", (status,))
    else:
        cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/orders", methods=["POST"])
@require_api_key
@rate_limit(30)
def place_order():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    ok, err = validate_order(data)
    if not ok:
        return jsonify({"error": err}), 400

    customer   = sanitise(data.get("customer", "Guest"), 60)
    note       = sanitise(data.get("note", ""), 200)
    table_name = sanitise(data.get("table_name", ""), 30)
    table_num  = int(data["table_num"])

    clean_items = []
    total = 0
    for i in data["items"]:
        qty   = int(i.get("qty", 1))
        price = int(i.get("price", 0))
        clean_items.append({
            "id":    sanitise(str(i.get("id","")),   20),
            "name":  sanitise(str(i.get("name","")), 60),
            "emoji": sanitise(str(i.get("emoji","")), 5),
            "price": price,
            "qty":   qty
        })
        total += price * qty

    order_id = uuid.uuid4().hex[:8].upper()
    now      = datetime.now().isoformat()

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        """INSERT INTO orders
           (id,table_name,table_num,customer,note,items,total,status,created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (order_id, table_name, table_num, customer, note,
         json.dumps(clean_items), total, "pending", now)
    )
    conn.commit()
    cur.close()
    conn.close()

    print(f"  New order #{order_id} — {table_name} — {customer} — UGX {total:,}")
    return jsonify({"success": True, "id": order_id}), 201


@app.route("/api/orders/<oid>", methods=["PATCH"])
@require_api_key
@rate_limit(60)
def update_order(oid):
    data   = request.get_json(force=True, silent=True)
    status = (data or {}).get("status")
    if status not in ["pending", "preparing", "ready", "delivered"]:
        return jsonify({"error": "invalid status"}), 400
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE orders SET status=%s WHERE id=%s", (status, oid))
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if updated == 0:
        return jsonify({"error": "order not found"}), 404
    return jsonify({"success": True})


@app.route("/api/orders/<oid>", methods=["DELETE"])
@require_api_key
@rate_limit(60)
def delete_order(oid):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM orders WHERE id=%s", (oid,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/orders/delivered", methods=["DELETE"])
@require_api_key
@rate_limit(10)
def clear_delivered():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM orders WHERE status='delivered'")
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/stats")
@require_api_key
@rate_limit(60)
def get_stats():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT status, total FROM orders")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    p=pr=rd=d=rev=0
    for r in rows:
        if   r["status"] == "pending":   p  += 1
        elif r["status"] == "preparing": pr += 1
        elif r["status"] == "ready":     rd += 1
        elif r["status"] == "delivered": d  += 1; rev += r["total"] or 0
    return jsonify({
        "total": len(rows), "pending": p, "preparing": pr,
        "ready": rd, "delivered": d, "revenue": rev
    })

@app.route("/api/venue", methods=["GET"])
@require_api_key
@rate_limit(60)
def get_venue():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM venues WHERE id='default'")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(dict(row) if row else {})


@app.route("/api/venue", methods=["PATCH"])
@require_api_key
@rate_limit(20)
def update_venue():
    data = request.get_json(force=True, silent=True) or {}
    ok, err = validate_venue(data)
    if not ok:
        return jsonify({"error": err}), 400

    fields = {}
    if "name" in data:
        fields["name"] = sanitise(data.get("name", ""), 80)
    if "theme_color" in data:
        fields["theme_color"] = data.get("theme_color")
    if "logo_url" in data:
        fields["logo_url"] = sanitise(data.get("logo_url", ""), 300)
    if "lat" in data:
        fields["lat"] = data.get("lat")
    if "lng" in data:
        fields["lng"] = data.get("lng")
    if "geofence_radius_m" in data:
        fields["geofence_radius_m"] = data.get("geofence_radius_m")

    if not fields:
        return jsonify({"error": "no updatable fields provided"}), 400

    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k}=%s" for k in fields)
    values = list(fields.values())

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(f"UPDATE venues SET {set_clause} WHERE id='default'", values)
    conn.commit()
    cur.execute("SELECT * FROM venues WHERE id='default'")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify({"success": True, "venue": dict(row) if row else {}})


@app.route("/api/tables", methods=["GET"])
@require_api_key
@rate_limit(60)
def get_tables():
    # Customer-facing table picker only wants active tables; pass ?all=1
    # from the admin dashboard to include inactive ones for management.
    include_all = request.args.get("all") == "1"
    conn = get_db()
    cur  = conn.cursor()
    if include_all:
        cur.execute("SELECT * FROM tables ORDER BY table_num ASC NULLS LAST, created_at ASC")
    else:
        cur.execute("SELECT * FROM tables WHERE active=TRUE ORDER BY table_num ASC NULLS LAST, created_at ASC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tables", methods=["POST"])
@require_api_key
@rate_limit(30)
def create_table():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    ok, err = validate_table(data)
    if not ok:
        return jsonify({"error": err}), 400

    name      = sanitise(data.get("name", ""), 40)
    table_num = data.get("table_num")
    table_id  = uuid.uuid4().hex[:8].upper()
    now       = datetime.now().isoformat()

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        """INSERT INTO tables (id, name, table_num, active, created_at)
           VALUES (%s, %s, %s, TRUE, %s)""",
        (table_id, name, table_num, now)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True, "id": table_id}), 201


@app.route("/api/tables/<tid>", methods=["PATCH"])
@require_api_key
@rate_limit(60)
def update_table(tid):
    data = request.get_json(force=True, silent=True) or {}

    fields = {}
    if "name" in data:
        name = data.get("name", "")
        if not isinstance(name, str) or not name.strip():
            return jsonify({"error": "table name cannot be empty"}), 400
        fields["name"] = sanitise(name, 40)
    if "table_num" in data:
        tn = data.get("table_num")
        if tn is not None and (not isinstance(tn, int) or not (1 <= tn <= 500)):
            return jsonify({"error": "table_num must be between 1 and 500"}), 400
        fields["table_num"] = tn
    if "active" in data:
        if not isinstance(data["active"], bool):
            return jsonify({"error": "active must be true or false"}), 400
        fields["active"] = data["active"]

    if not fields:
        return jsonify({"error": "no updatable fields provided"}), 400

    set_clause = ", ".join(f"{k}=%s" for k in fields)
    values = list(fields.values()) + [tid]

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(f"UPDATE tables SET {set_clause} WHERE id=%s", values)
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if updated == 0:
        return jsonify({"error": "table not found"}), 404
    return jsonify({"success": True})


@app.route("/api/tables/<tid>", methods=["DELETE"])
@require_api_key
@rate_limit(30)
def delete_table(tid):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM tables WHERE id=%s", (tid,))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if deleted == 0:
        return jsonify({"error": "table not found"}), 404
    return jsonify({"success": True})


# ─────────────────────────────────────────
# STARTUP — init DB on every start
# ─────────────────────────────────────────
init_db()

# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────
if __name__ == "__main__":
    print()
    print("  Climax Lounge API — Running")
    print("  http://localhost:5000/api/ping")
    print()
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
