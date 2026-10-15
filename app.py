"""PRESENTATION LAYER - Flask routes only. SQL lives in db.py, logic lives in services.py."""
import os
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import (Flask, Response, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import db
import seed
import services

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-in-production")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024          # 2 MB upload limit
UPLOAD_DIR = os.path.join(db.BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
db.init_app(app)


# ---------- login helpers ----------
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Only admins can do that.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapper


# ---------- auth ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = db.get_user(request.form["username"].strip())
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            session.clear()
            session.update(user_id=user["user_id"], username=user["username"], role=user["role"])
            return redirect(url_for("dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username, password = request.form["username"].strip(), request.form["password"]
        if len(username) < 3 or len(password) < 6:
            flash("Username needs 3+ characters and password 6+ characters.", "error")
        elif db.get_user(username):
            flash("That username is taken.", "error")
        else:
            db.add_user(username, generate_password_hash(password), "staff")
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- dashboard ----------
@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", risky=db.risky_bookings(5))


# ---------- rooms ----------
@app.route("/rooms", methods=["GET", "POST"])
@login_required
def rooms():
    if request.method == "POST":
        if session.get("role") != "admin":
            flash("Only admins can add rooms.", "error")
        else:
            try:
                db.add_room(request.form["room_no"].strip(), request.form["room_type"],
                            float(request.form["price"]))
                flash("Room added.", "success")
            except (ValueError, sqlite3.IntegrityError):
                flash("Could not add room (room number must be unique, price must be a number).", "error")
        return redirect(url_for("rooms"))
    return render_template("rooms.html", rooms=db.list_rooms(), room_types=services.ROOM_TYPES)


@app.route("/rooms/<int:room_id>/update", methods=["POST"])
@login_required
@admin_required
def room_update(room_id):
    try:
        db.update_room(room_id, float(request.form["price"]), request.form["status"])
        flash("Room updated.", "success")
    except ValueError:
        flash("Price must be a number.", "error")
    return redirect(url_for("rooms"))


@app.route("/rooms/<int:room_id>/delete", methods=["POST"])
@login_required
@admin_required
def room_delete(room_id):
    try:
        db.delete_room(room_id)
        flash("Room deleted.", "success")
    except sqlite3.IntegrityError:
        flash("This room has bookings, so it cannot be deleted. Set it to Maintenance instead.", "error")
    return redirect(url_for("rooms"))


# ---------- customers ----------
@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    if request.method == "POST":
        name, country = request.form["name"].strip(), request.form["country"].strip()
        if name and country:
            db.add_customer(name, country, request.form["customer_type"])
            flash("Customer added.", "success")
        else:
            flash("Name and country are required.", "error")
        return redirect(url_for("customers"))
    return render_template("customers.html", customers=db.list_customers(),
                           types=services.CUSTOMER_TYPES)


# ---------- bookings ----------
@app.route("/bookings")
@login_required
def bookings():
    status = request.args.get("status", "")
    return render_template("bookings.html", bookings=db.list_bookings(status or None),
                           statuses=services.BOOKING_STATUSES, selected=status)


@app.route("/bookings/new", methods=["GET", "POST"])
@login_required
def booking_new():
    if request.method == "POST":
        room = db.get_room(request.form["room_id"])
        err, total = services.validate_booking(room, request.form["check_in"], request.form["check_out"],
                                               request.form["booking_date"])
        if err:
            flash(err, "error")
        else:
            db.add_booking(int(request.form["customer_id"]), room["room_id"], request.form["check_in"],
                           request.form["check_out"], request.form["booking_date"], "Confirmed", total)
            flash(f"Booking saved. Total amount: {total:,.0f}", "success")
            return redirect(url_for("bookings"))
    return render_template("booking_form.html", customers=db.list_customers(), rooms=db.list_rooms(),
                           today=date.today().isoformat())


@app.route("/bookings/<int:booking_id>/status", methods=["POST"])
@login_required
def booking_status(booking_id):
    status = request.form["status"]
    if status in ("Cancelled", "Completed"):
        db.set_booking_status(booking_id, status)
        flash(f"Booking #{booking_id} marked {status}.", "success")
    return redirect(request.referrer or url_for("bookings"))


# ---------- upload ----------
@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    result = None
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Please choose a file.", "error")
        elif not file.filename.lower().endswith(".csv"):
            flash("Only .csv files are allowed.", "error")
        else:
            safe = datetime.now().strftime("%Y%m%d%H%M%S_") + secure_filename(file.filename)
            path = os.path.join(UPLOAD_DIR, safe)
            file.save(path)
            result = services.import_bookings_csv(path)
            flash(f"{result[0]} bookings imported.", "success" if result[0] else "error")
    return render_template("upload.html", result=result)


# ---------- analytics ----------
@app.route("/analytics")
@login_required
def analytics():
    return render_template("analytics.html")


@app.route("/api/analytics")
@login_required
def api_analytics():
    return jsonify(services.get_analytics(request.args.get("start") or None,
                                          request.args.get("end") or None))


# ---------- prediction ----------
@app.route("/prediction")
@login_required
def prediction():
    return render_template("prediction.html", info=services.load_metrics(),
                           risky=db.risky_bookings(15))


@app.route("/prediction/train", methods=["POST"])
@login_required
def prediction_train():
    try:
        info = services.train_models()
        flash(f"Training done. Best model: {info['best']}.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("prediction"))


@app.route("/prediction/run", methods=["POST"])
@login_required
def prediction_run():
    try:
        n = services.predict_upcoming()
        flash(f"Scored {n} upcoming bookings.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("prediction"))


@app.route("/prediction/<int:booking_id>", methods=["POST"])
@login_required
def prediction_one(booking_id):
    try:
        services.predict_bookings([booking_id])
        flash(f"Prediction saved for booking #{booking_id}.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(request.referrer or url_for("bookings"))


@app.route("/history")
@login_required
def history():
    risk = request.args.get("risk", "")
    return render_template("history.html", rows=db.list_predictions(risk or None), selected=risk)


# ---------- reports ----------
@app.route("/reports")
@login_required
def reports():
    return render_template("reports.html", room_rows=services.room_type_report(),
                           country_rows=services.country_report())


@app.route("/reports/export.csv")
@login_required
def export_csv():
    df = services.bookings_df().drop(columns=["cancelled", "check_in_month"])
    return Response(df.to_csv(index=False), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=bookings_report.csv"})


# ---------- first-run setup ----------
def first_run_setup():
    """If there is no database yet: create tables, add demo data and train the model."""
    if os.path.exists(db.DB_PATH):
        return
    with app.app_context():
        db.init_db()
        seed.seed()
        services.train_models()
        services.predict_upcoming()
        print("Demo data created. Login: admin / admin123")


first_run_setup()

if __name__ == "__main__":
    app.run(debug=True)
