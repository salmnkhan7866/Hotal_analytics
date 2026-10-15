"""DATABASE LAYER - the only file that writes SQL for the app."""
import os
import sqlite3
from flask import g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hotel.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'staff'
);
CREATE TABLE IF NOT EXISTS rooms (
    room_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    room_no   TEXT UNIQUE NOT NULL,
    room_type TEXT NOT NULL,
    price     REAL NOT NULL,
    status    TEXT NOT NULL DEFAULT 'Available'
);
CREATE TABLE IF NOT EXISTS customers (
    customer_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    country       TEXT NOT NULL,
    customer_type TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
    booking_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    room_id        INTEGER NOT NULL REFERENCES rooms(room_id),
    check_in       TEXT NOT NULL,
    check_out      TEXT NOT NULL,
    booking_date   TEXT NOT NULL,
    booking_status TEXT NOT NULL DEFAULT 'Confirmed',
    total_amount   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id               INTEGER NOT NULL REFERENCES bookings(booking_id),
    cancellation_probability REAL NOT NULL,
    risk_level               TEXT NOT NULL,
    model_name               TEXT,
    created_at               TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# ---------- connection helpers ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)


def init_db():
    get_db().executescript(SCHEMA)
    get_db().commit()


def query(sql, args=(), one=False):
    rows = get_db().execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    conn = get_db()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.lastrowid


# ---------- users ----------
def get_user(username):
    return query("SELECT * FROM users WHERE username = ?", (username,), one=True)


def add_user(username, password_hash, role="staff"):
    return execute("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                   (username, password_hash, role))


# ---------- rooms ----------
def list_rooms():
    return query("SELECT * FROM rooms ORDER BY room_no")


def count_rooms():
    return query("SELECT COUNT(*) AS n FROM rooms", one=True)["n"]


def get_room(room_id):
    return query("SELECT * FROM rooms WHERE room_id = ?", (room_id,), one=True)


def find_room_by_no(room_no):
    return query("SELECT * FROM rooms WHERE room_no = ?", (room_no,), one=True)


def add_room(room_no, room_type, price, status="Available"):
    return execute("INSERT INTO rooms (room_no, room_type, price, status) VALUES (?,?,?,?)",
                   (room_no, room_type, price, status))


def update_room(room_id, price, status):
    execute("UPDATE rooms SET price = ?, status = ? WHERE room_id = ?", (price, status, room_id))


def delete_room(room_id):
    execute("DELETE FROM rooms WHERE room_id = ?", (room_id,))


# ---------- customers ----------
def list_customers():
    return query("SELECT * FROM customers ORDER BY customer_id DESC LIMIT 300")


def add_customer(name, country, customer_type):
    return execute("INSERT INTO customers (name, country, customer_type) VALUES (?,?,?)",
                   (name, country, customer_type))


def find_or_create_customer(name, country, customer_type):
    row = query("SELECT customer_id FROM customers WHERE name=? AND country=?",
                (name, country), one=True)
    return row["customer_id"] if row else add_customer(name, country, customer_type)


# ---------- bookings ----------
def list_bookings(status=None):
    sql = """SELECT b.*, c.name AS customer_name, r.room_no, r.room_type,
               (SELECT risk_level FROM predictions p WHERE p.booking_id = b.booking_id
                ORDER BY p.prediction_id DESC LIMIT 1) AS risk_level
             FROM bookings b
             JOIN customers c ON c.customer_id = b.customer_id
             JOIN rooms r ON r.room_id = b.room_id"""
    args = ()
    if status:
        sql += " WHERE b.booking_status = ?"
        args = (status,)
    sql += " ORDER BY b.check_in DESC LIMIT 200"
    return query(sql, args)


def room_is_booked(room_id, check_in, check_out):
    row = query("""SELECT 1 FROM bookings WHERE room_id = ? AND booking_status != 'Cancelled'
                   AND check_in < ? AND check_out > ? LIMIT 1""",
                (room_id, check_out, check_in), one=True)
    return row is not None


def add_booking(customer_id, room_id, check_in, check_out, booking_date, status, total):
    return execute("""INSERT INTO bookings (customer_id, room_id, check_in, check_out,
                      booking_date, booking_status, total_amount) VALUES (?,?,?,?,?,?,?)""",
                   (customer_id, room_id, check_in, check_out, booking_date, status, total))


def set_booking_status(booking_id, status):
    execute("UPDATE bookings SET booking_status = ? WHERE booking_id = ?", (status, booking_id))


def upcoming_confirmed_ids(today):
    rows = query("SELECT booking_id FROM bookings WHERE booking_status='Confirmed' AND check_in >= ?",
                 (today,))
    return [r["booking_id"] for r in rows]


# ---------- predictions ----------
def save_prediction(booking_id, probability, risk, model_name):
    execute("""INSERT INTO predictions (booking_id, cancellation_probability, risk_level, model_name, created_at)
               VALUES (?,?,?,?, datetime('now'))""", (booking_id, probability, risk, model_name))


def list_predictions(risk=None):
    sql = """SELECT p.*, b.check_in, b.check_out, b.booking_status, c.name AS customer_name, r.room_no
             FROM predictions p
             JOIN bookings b ON b.booking_id = p.booking_id
             JOIN customers c ON c.customer_id = b.customer_id
             JOIN rooms r ON r.room_id = b.room_id"""
    args = ()
    if risk:
        sql += " WHERE p.risk_level = ?"
        args = (risk,)
    sql += " ORDER BY p.prediction_id DESC LIMIT 300"
    return query(sql, args)


def risky_bookings(limit=10):
    """Latest prediction of every still-Confirmed booking, highest risk first."""
    return query("""SELECT p.*, b.check_in, b.total_amount, c.name AS customer_name, r.room_no
                    FROM predictions p
                    JOIN bookings b ON b.booking_id = p.booking_id
                    JOIN customers c ON c.customer_id = b.customer_id
                    JOIN rooms r ON r.room_id = b.room_id
                    WHERE p.prediction_id IN (SELECT MAX(prediction_id) FROM predictions GROUP BY booking_id)
                      AND b.booking_status = 'Confirmed'
                    ORDER BY p.cancellation_probability DESC LIMIT ?""", (limit,))
