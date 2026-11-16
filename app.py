
from datetime import datetime, date, timedelta
from functools import wraps
import os
from dotenv import load_dotenv
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DB_PATH = os.path.join(BASE_DIR, "melties.db")
app = Flask(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is missing. Create a .env file and add a secure SECRET_KEY."
    )

app.secret_key = SECRET_KEY
app.config["JSON_SORT_KEYS"] = False

STATUSES = ["New", "Preparing", "Ready", "Completed", "Cancelled"]
PAYMENT_STATUSES = ["Pending", "Paid"]


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        price REAL NOT NULL CHECK(price >= 0),
        image TEXT DEFAULT '',
        stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK(stock_quantity >= 0),
        is_available INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        address TEXT DEFAULT '',
        order_type TEXT NOT NULL CHECK(order_type IN ('Pickup','Delivery')),
        notes TEXT DEFAULT '',
        total_amount REAL NOT NULL,
        order_status TEXT NOT NULL DEFAULT 'New',
        payment_status TEXT NOT NULL DEFAULT 'Pending',
        stock_deducted INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        product_name TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        unit_price REAL NOT NULL,
        line_total REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS admin_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    );
    """)

    # Create or refresh administrator credentials from .env
    admin_username = os.getenv("ADMIN_USERNAME", "admin").strip()
    admin_password = os.getenv("ADMIN_PASSWORD")

    if not admin_username or not admin_password:
        conn.close()
        raise RuntimeError(
            "ADMIN_USERNAME and ADMIN_PASSWORD must be set in your .env file."
        )

    admin = conn.execute(
        "SELECT id FROM admin_users WHERE username = ?",
        (admin_username,)
    ).fetchone()

    password_hash = generate_password_hash(admin_password)

    if admin:
        conn.execute(
            "UPDATE admin_users SET password_hash = ? WHERE id = ?",
            (password_hash, admin["id"])
        )
    else:
        conn.execute(
            "INSERT INTO admin_users(username, password_hash) VALUES (?, ?)",
            (admin_username, password_hash)
        )

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM products"
    ).fetchone()["n"]

    if count == 0:
        samples = [
            (
                "Classic Chocolate Chip",
                "Soft cookie filled with chocolate chips.",
                1.200,
                "https://images.unsplash.com/photo-1499636136210-6f4ee915583e?w=800",
                30
            ),
            (
                "Double Chocolate",
                "Rich chocolate cookie with chocolate chunks.",
                1.400,
                "https://images.unsplash.com/photo-1606313564200-e75d5e30476c?w=800",
                24
            ),
            (
                "Red Velvet",
                "A soft red velvet cookie with a sweet finish.",
                1.500,
                "https://images.unsplash.com/photo-1558961363-fa8fdf82db35?w=800",
                18
            ),
            (
                "Lotus Cookie",
                "Caramelised biscuit flavour with a smooth centre.",
                1.500,
                "https://images.unsplash.com/photo-1558961363-fa8fdf82db35?w=800",
                15
            ),
        ]

        now = datetime.now().isoformat(timespec="seconds")

        conn.executemany("""
            INSERT INTO products(
                name, description, price, image,
                stock_quantity, created_at
            )
            VALUES(?,?,?,?,?,?)
        """, [(*p, now) for p in samples])

    conn.commit()
    conn.close()


def money(value):
    return f"OMR {float(value or 0):.3f}"


@app.template_filter("omr")
def omr(value):
    return money(value)


@app.template_filter("datetime")
def format_datetime(value):
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return value


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    conn = db()
    products = conn.execute(
        "SELECT * FROM products WHERE is_available=1 ORDER BY id"
    ).fetchall()
    conn.close()

    return render_template("home.html", products=products)


@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.get_json(silent=True) or request.form

    name = (data.get("customer_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    address = (data.get("address") or "").strip()
    order_type = data.get("order_type") or "Pickup"
    notes = (data.get("notes") or "").strip()
    items = data.get("items", [])

    if isinstance(items, str):
        import json
        try:
            items = json.loads(items)
        except Exception:
            items = []

    if not name or not phone:
        return jsonify(
            success=False,
            message="Please enter your name and phone number."
        ), 400

    if order_type not in ("Pickup", "Delivery"):
        return jsonify(
            success=False,
            message="Please choose pickup or delivery."
        ), 400

    if order_type == "Delivery" and not address:
        return jsonify(
            success=False,
            message="Please enter your delivery address."
        ), 400

    if not isinstance(items, list) or not items:
        return jsonify(
            success=False,
            message="Your cart is empty."
        ), 400

    conn = db()

    try:
        conn.execute("BEGIN IMMEDIATE")
        normalized = {}

        for item in items:
            pid = int(item.get("product_id", 0))
            qty = int(item.get("quantity", 0))

            if qty <= 0:
                raise ValueError("Product quantities must be positive.")

            normalized[pid] = normalized.get(pid, 0) + qty

        order_lines = []
        total = 0.0

        for pid, qty in normalized.items():
            product = conn.execute(
                "SELECT * FROM products WHERE id=? AND is_available=1",
                (pid,)
            ).fetchone()

            if not product:
                raise ValueError(
                    "One of the selected products is unavailable."
                )

            if product["stock_quantity"] < qty:
                raise ValueError(
                    f"Only {product['stock_quantity']} left for {product['name']}."
                )

            line_total = round(product["price"] * qty, 3)
            total += line_total
            order_lines.append((product, qty, line_total))

        total = round(total, 3)

        cur = conn.execute("""
            INSERT INTO orders(
                customer_name, phone, address, order_type, notes,
                total_amount, order_status, payment_status,
                stock_deducted, created_at
            )
            VALUES(?,?,?,?,?,?, 'New','Pending',1,?)
        """, (
            name,
            phone,
            address,
            order_type,
            notes,
            total,
            datetime.now().isoformat(timespec="seconds")
        ))

        order_id = cur.lastrowid

        for product, qty, line_total in order_lines:
            conn.execute("""
                INSERT INTO order_items(
                    order_id, product_id, product_name,
                    quantity, unit_price, line_total
                )
                VALUES(?,?,?,?,?,?)
            """, (
                order_id,
                product["id"],
                product["name"],
                qty,
                product["price"],
                line_total
            ))

            conn.execute(
                "UPDATE products SET stock_quantity=stock_quantity-? WHERE id=?",
                (qty, product["id"])
            )

        conn.commit()

        return jsonify(
            success=True,
            order_id=order_id,
            total=money(total)
        )

    except (ValueError, TypeError) as exc:
        conn.rollback()
        return jsonify(success=False, message=str(exc)), 400

    except Exception:
        conn.rollback()
        return jsonify(
            success=False,
            message="We could not place your order. Please try again."
        ), 500

    finally:
        conn.close()


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = db()

        user = conn.execute(
            "SELECT * FROM admin_users WHERE username=?",
            (username,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["admin_id"] = user["id"]
            session["admin_username"] = user["username"]

            return redirect(
                request.args.get("next") or url_for("dashboard")
            )

        flash("Incorrect username or password.", "error")

    return render_template("login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/admin")
@admin_required
def dashboard():
    conn = db()

    total_sales = conn.execute("""
        SELECT COALESCE(SUM(total_amount),0) v
        FROM orders
        WHERE order_status='Completed' AND payment_status='Paid'
    """).fetchone()["v"]

    total_orders = conn.execute(
        "SELECT COUNT(*) v FROM orders"
    ).fetchone()["v"]

    pending = conn.execute("""
        SELECT COUNT(*) v FROM orders
        WHERE order_status IN ('New','Preparing','Ready')
    """).fetchone()["v"]

    low_stock = conn.execute("""
        SELECT COUNT(*) v FROM products
        WHERE stock_quantity<=5 AND is_available=1
    """).fetchone()["v"]

    recent = conn.execute(
        "SELECT * FROM orders ORDER BY id DESC LIMIT 8"
    ).fetchall()

    daily = conn.execute("""
        SELECT date(created_at) day, COALESCE(SUM(total_amount),0) total
        FROM orders
        WHERE order_status='Completed' AND payment_status='Paid'
        AND date(created_at)>=date('now','-6 day')
        GROUP BY date(created_at)
        ORDER BY day
    """).fetchall()

    conn.close()

    chart = {
        r["day"]: round(r["total"], 3)
        for r in daily
    }

    labels = []
    values = []

    for i in range(6, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        labels.append(datetime.fromisoformat(d).strftime("%a"))
        values.append(chart.get(d, 0))

    return render_template(
        "dashboard.html",
        total_sales=total_sales,
        total_orders=total_orders,
        pending=pending,
        low_stock=low_stock,
        recent=recent,
        chart_labels=labels,
        chart_values=values
    )


@app.route("/admin/orders")
@admin_required
def orders():
    status = request.args.get("status", "")
    q = request.args.get("q", "").strip()

    conn = db()

    sql = "SELECT * FROM orders WHERE 1=1"
    args = []

    if status in STATUSES:
        sql += " AND order_status=?"
        args.append(status)

    if q:
        sql += " AND (CAST(id AS TEXT) LIKE ? OR customer_name LIKE ?)"
        args.extend([f"%{q}%", f"%{q}%"])

    sql += " ORDER BY id DESC"

    rows = conn.execute(sql, args).fetchall()
    conn.close()

    return render_template(
        "orders.html",
        orders=rows,
        statuses=STATUSES,
        selected=status,
        q=q
    )


@app.route("/admin/orders/<int:order_id>")
@admin_required
def order_detail(order_id):
    conn = db()

    order = conn.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()

    if not order:
        conn.close()
        abort(404)

    items = conn.execute(
        "SELECT * FROM order_items WHERE order_id=?",
        (order_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "order_detail.html",
        order=order,
        items=items,
        statuses=STATUSES,
        payment_statuses=PAYMENT_STATUSES
    )


@app.route("/admin/orders/<int:order_id>/update", methods=["POST"])
@admin_required
def update_order(order_id):
    status = request.form.get("order_status")
    payment = request.form.get("payment_status")

    if status not in STATUSES or payment not in PAYMENT_STATUSES:
        flash("Invalid order update.", "error")
        return redirect(url_for("order_detail", order_id=order_id))

    conn = db()

    try:
        conn.execute("BEGIN IMMEDIATE")

        order = conn.execute(
            "SELECT * FROM orders WHERE id=?",
            (order_id,)
        ).fetchone()

        if not order:
            abort(404)

        # Restore stock once if an order is cancelled.
        # Deduct again if the order is reopened.
        if (
            status == "Cancelled"
            and order["order_status"] != "Cancelled"
            and order["stock_deducted"]
        ):
            items = conn.execute("""
                SELECT product_id, quantity
                FROM order_items
                WHERE order_id=?
            """, (order_id,)).fetchall()

            for item in items:
                if item["product_id"]:
                    conn.execute("""
                        UPDATE products
                        SET stock_quantity=stock_quantity+?
                        WHERE id=?
                    """, (item["quantity"], item["product_id"]))

            conn.execute(
                "UPDATE orders SET stock_deducted=0 WHERE id=?",
                (order_id,)
            )

        elif (
            status != "Cancelled"
            and order["order_status"] == "Cancelled"
            and not order["stock_deducted"]
        ):
            items = conn.execute("""
                SELECT product_id, quantity
                FROM order_items
                WHERE order_id=?
            """, (order_id,)).fetchall()

            for item in items:
                if item["product_id"]:
                    p = conn.execute("""
                        SELECT stock_quantity, name
                        FROM products
                        WHERE id=?
                    """, (item["product_id"],)).fetchone()

                    if not p or p["stock_quantity"] < item["quantity"]:
                        raise ValueError(
                            "Not enough stock to reopen this order."
                        )

            for item in items:
                if item["product_id"]:
                    conn.execute("""
                        UPDATE products
                        SET stock_quantity=stock_quantity-?
                        WHERE id=?
                    """, (item["quantity"], item["product_id"]))

            conn.execute(
                "UPDATE orders SET stock_deducted=1 WHERE id=?",
                (order_id,)
            )

        conn.execute("""
            UPDATE orders
            SET order_status=?, payment_status=?
            WHERE id=?
        """, (status, payment, order_id))

        conn.commit()
        flash("Order updated successfully.", "success")

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")

    finally:
        conn.close()

    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/admin/products")
@admin_required
def products():
    conn = db()

    rows = conn.execute(
        "SELECT * FROM products ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return render_template("products.html", products=rows)


@app.route("/admin/products/save", methods=["POST"])
@admin_required
def save_product():
    try:
        pid = request.form.get("id")
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price = round(float(request.form.get("price", 0)), 3)
        stock = int(request.form.get("stock_quantity", 0))
        image = request.form.get("image", "").strip()
        available = (
            1 if request.form.get("is_available") == "on" else 0
        )

        if not name or price < 0 or stock < 0:
            raise ValueError()

        conn = db()

        if pid:
            conn.execute("""
                UPDATE products
                SET name=?, description=?, price=?, image=?,
                    stock_quantity=?, is_available=?
                WHERE id=?
            """, (
                name,
                description,
                price,
                image,
                stock,
                available,
                int(pid)
            ))

        else:
            conn.execute("""
                INSERT INTO products(
                    name, description, price, image,
                    stock_quantity, is_available, created_at
                )
                VALUES(?,?,?,?,?,?,?)
            """, (
                name,
                description,
                price,
                image,
                stock,
                available,
                datetime.now().isoformat(timespec="seconds")
            ))

        conn.commit()
        conn.close()

        flash("Product saved.", "success")

    except Exception:
        flash(
            "Please check the product details. Price and stock must be valid.",
            "error"
        )

    return redirect(url_for("products"))


@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def delete_product(product_id):
    conn = db()

    conn.execute(
        "DELETE FROM products WHERE id=?",
        (product_id,)
    )

    conn.commit()
    conn.close()

    flash("Product deleted.", "success")

    return redirect(url_for("products"))


@app.route("/admin/reports")
@admin_required
def reports():
    start = request.args.get("start") or (
        date.today() - timedelta(days=29)
    ).isoformat()

    end = request.args.get("end") or date.today().isoformat()

    conn = db()

    paid = conn.execute("""
        SELECT COALESCE(SUM(total_amount),0) v, COUNT(*) n
        FROM orders
        WHERE order_status='Completed'
        AND payment_status='Paid'
        AND date(created_at) BETWEEN date(?) AND date(?)
    """, (start, end)).fetchone()

    best = conn.execute("""
        SELECT oi.product_name, SUM(oi.quantity) qty
        FROM order_items oi
        JOIN orders o ON o.id=oi.order_id
        WHERE o.order_status='Completed'
        AND o.payment_status='Paid'
        AND date(o.created_at) BETWEEN date(?) AND date(?)
        GROUP BY oi.product_name
        ORDER BY qty DESC
        LIMIT 1
    """, (start, end)).fetchone()

    pending_total = conn.execute("""
        SELECT COALESCE(SUM(total_amount),0) v
        FROM orders
        WHERE payment_status='Pending'
        AND order_status!='Cancelled'
        AND date(created_at) BETWEEN date(?) AND date(?)
    """, (start, end)).fetchone()["v"]

    rows = conn.execute("""
        SELECT date(created_at) day, SUM(total_amount) total
        FROM orders
        WHERE order_status='Completed'
        AND payment_status='Paid'
        AND date(created_at) BETWEEN date(?) AND date(?)
        GROUP BY date(created_at)
        ORDER BY day
    """, (start, end)).fetchall()

    conn.close()

    return render_template(
        "reports.html",
        start=start,
        end=end,
        paid=paid,
        best=best,
        pending_total=pending_total,
        labels=[r["day"] for r in rows],
        values=[round(r["total"], 3) for r in rows]
    )


@app.route("/health")
def health():
    return jsonify(
        status="ok",
        app="MELTIES Sales System"
    )


if __name__ == "__main__":
    init_db()

    debug_mode = (
        os.getenv("FLASK_DEBUG", "false").strip().lower() == "true"
    )

    app.run(debug=debug_mode)
