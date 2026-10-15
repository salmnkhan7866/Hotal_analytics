"""BUSINESS LOGIC LAYER - validation, analytics (pandas) and machine learning (scikit-learn)."""
import json
import os
from datetime import date, datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

import db

MODEL_DIR = os.path.join(db.BASE_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "best_model.joblib")
METRICS_PATH = os.path.join(MODEL_DIR, "metrics.json")

CUSTOMER_TYPES = ["Online", "Corporate", "Walk-in", "Repeat"]
BOOKING_STATUSES = ["Confirmed", "Cancelled", "Completed"]
ROOM_TYPES = ["Single", "Double", "Deluxe", "Suite"]


# =====================================================================
# 1. VALIDATION
# =====================================================================
def parse_date(text):
    try:
        return date.fromisoformat(str(text).strip()[:10])
    except ValueError:
        return None


def validate_booking(room, check_in, check_out, booking_date, status="Confirmed"):
    """Returns (error_message, total_amount). error_message is None when everything is fine."""
    ci, co, bd = parse_date(check_in), parse_date(check_out), parse_date(booking_date)
    if not (ci and co and bd):
        return "Dates must look like YYYY-MM-DD.", 0
    if co <= ci:
        return "Check-out must be after check-in.", 0
    if bd > ci:
        return "Booking date cannot be after check-in.", 0
    if room is None:
        return "Room not found.", 0
    if room["status"] != "Available":
        return f"Room {room['room_no']} is under maintenance.", 0
    if status != "Cancelled" and db.room_is_booked(room["room_id"], ci.isoformat(), co.isoformat()):
        return f"Room {room['room_no']} is already booked for those dates.", 0
    return None, (co - ci).days * room["price"]


def import_bookings_csv(path):
    """Reads an uploaded CSV and inserts valid rows. Returns (imported_count, list_of_errors)."""
    needed = ["customer_name", "country", "customer_type", "room_no",
              "check_in", "check_out", "booking_date", "booking_status"]
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return 0, ["File could not be read as CSV."]
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        return 0, [f"Missing columns: {', '.join(missing)}"]

    imported, errors = 0, []
    for i, row in df.head(5000).iterrows():
        line = i + 2
        if row["customer_type"] not in CUSTOMER_TYPES:
            errors.append(f"Line {line}: customer_type must be one of {CUSTOMER_TYPES}")
            continue
        if row["booking_status"] not in BOOKING_STATUSES:
            errors.append(f"Line {line}: booking_status must be one of {BOOKING_STATUSES}")
            continue
        room = db.find_room_by_no(row["room_no"].strip())
        err, total = validate_booking(room, row["check_in"], row["check_out"],
                                      row["booking_date"], row["booking_status"])
        if err:
            errors.append(f"Line {line}: {err}")
            continue
        cid = db.find_or_create_customer(row["customer_name"].strip(), row["country"].strip(),
                                         row["customer_type"])
        db.add_booking(cid, room["room_id"], row["check_in"][:10], row["check_out"][:10],
                       row["booking_date"][:10], row["booking_status"], total)
        imported += 1
    return imported, errors[:20]


# =====================================================================
# 2. DATA PREPARATION (one dataframe used by analytics AND the ML model)
# =====================================================================
def bookings_df(start=None, end=None):
    sql = """SELECT b.booking_id, b.check_in, b.check_out, b.booking_date, b.booking_status,
                    b.total_amount, r.room_no, r.room_type, r.price,
                    c.name, c.country, c.customer_type
             FROM bookings b
             JOIN rooms r ON r.room_id = b.room_id
             JOIN customers c ON c.customer_id = b.customer_id"""
    df = pd.read_sql_query(sql, db.get_db())
    for col in ["check_in", "check_out", "booking_date"]:
        df[col] = pd.to_datetime(df[col])
    df["lead_time"] = (df["check_in"] - df["booking_date"]).dt.days
    df["nights"] = (df["check_out"] - df["check_in"]).dt.days
    df["check_in_month"] = df["check_in"].dt.month
    df["cancelled"] = (df["booking_status"] == "Cancelled").astype(int)
    if start:
        df = df[df["check_in"] >= pd.to_datetime(start)]
    if end:
        df = df[df["check_in"] <= pd.to_datetime(end)]
    return df


# =====================================================================
# 3. ANALYTICS  (descriptive + diagnostic)
# =====================================================================
def _pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def _series(s):
    return {"labels": [str(i) for i in s.index], "values": [float(v) for v in s.values]}


def _occupancy_monthly(active, total_rooms):
    """Occupancy % per month = room-nights sold / (rooms x days)."""
    if active.empty or total_rooms == 0:
        return pd.Series(dtype=float), 0.0
    stays = [pd.date_range(ci, periods=n) for ci, n in zip(active["check_in"], active["nights"])]
    days = pd.Series(np.concatenate([s.values for s in stays]))
    daily = days.value_counts().sort_index()
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max()), fill_value=0)
    month = daily.index.to_period("M")
    nights = daily.groupby(month).sum()
    n_days = daily.groupby(month).size()
    occ = (nights / (n_days * total_rooms) * 100).clip(upper=100).round(1)
    overall = round(100 * daily.sum() / (len(daily) * total_rooms), 1)
    return occ, overall


def get_analytics(start=None, end=None):
    df = bookings_df(start, end)
    total_rooms = db.count_rooms()
    empty = {"labels": [], "values": []}
    if df.empty:
        return {"kpis": dict(total_bookings=0, cancel_rate=0, revenue=0, adr=0, occupancy=0, avg_lead_time=0),
                "occupancy": empty, "cancel_trend": empty, "revenue_room": empty,
                "origin": empty, "cancel_lead": empty, "cancel_type": empty}

    active = df[df["cancelled"] == 0]                      # bookings that really generate stay
    revenue = float(active["total_amount"].sum())
    room_nights = int(active["nights"].sum())
    occ, overall_occ = _occupancy_monthly(active, total_rooms)

    # Descriptive: what happened?
    cancel_trend = (df.groupby(df["check_in"].dt.to_period("M"))["cancelled"].mean() * 100).round(1)
    revenue_room = active.groupby("room_type")["total_amount"].sum().round(0)
    origin = df["country"].value_counts().head(8)

    # Diagnostic: why do cancellations happen?
    buckets = pd.cut(df["lead_time"], [-1, 7, 30, 90, 180, 10000],
                     labels=["0-7 days", "8-30 days", "31-90 days", "91-180 days", "180+ days"])
    cancel_lead = (df.groupby(buckets, observed=True)["cancelled"].mean() * 100).round(1)
    cancel_type = (df.groupby("customer_type")["cancelled"].mean() * 100).round(1)

    return {
        "kpis": {
            "total_bookings": int(len(df)),
            "cancel_rate": _pct(df["cancelled"].sum(), len(df)),
            "revenue": round(revenue),
            "adr": round(revenue / room_nights, 2) if room_nights else 0,   # Average Daily Rate
            "occupancy": overall_occ,
            "avg_lead_time": round(float(df["lead_time"].mean()), 1),
        },
        "occupancy": _series(occ),
        "cancel_trend": _series(cancel_trend),
        "revenue_room": _series(revenue_room),
        "origin": _series(origin),
        "cancel_lead": _series(cancel_lead),
        "cancel_type": _series(cancel_type),
    }


def room_type_report():
    """Table for the Reports page: per room type bookings, cancellations, revenue, ADR."""
    df = bookings_df()
    rows = []
    for rtype, g in df.groupby("room_type"):
        act = g[g["cancelled"] == 0]
        nights = int(act["nights"].sum())
        rev = float(act["total_amount"].sum())
        rows.append({"room_type": rtype, "bookings": len(g), "cancelled": int(g["cancelled"].sum()),
                     "cancel_rate": _pct(g["cancelled"].sum(), len(g)), "revenue": round(rev),
                     "adr": round(rev / nights, 2) if nights else 0})
    return rows


def country_report():
    df = bookings_df()
    out = df.groupby("country").agg(bookings=("booking_id", "count"), cancelled=("cancelled", "sum"))
    out["cancel_rate"] = (out["cancelled"] / out["bookings"] * 100).round(1)
    return out.sort_values("bookings", ascending=False).reset_index().to_dict("records")


# =====================================================================
# 4. MACHINE LEARNING  (predictive)
# =====================================================================
NUM_FEATURES = ["lead_time", "nights", "price", "total_amount", "check_in_month"]
CAT_FEATURES = ["room_type", "country", "customer_type"]
FEATURES = NUM_FEATURES + CAT_FEATURES


def risk_level(p):
    return "Low" if p < 0.25 else "Medium" if p < 0.45 else "High"


def train_models():
    """Train 2 models on bookings with a known outcome, compare them, save the best one."""
    df = bookings_df()
    df = df[df["booking_status"].isin(["Cancelled", "Completed"])]
    if len(df) < 100 or df["cancelled"].nunique() < 2:
        raise ValueError("Need at least 100 finished bookings (cancelled + completed) to train.")

    X_train, X_test, y_train, y_test = train_test_split(
        df[FEATURES], df["cancelled"], test_size=0.25, random_state=42, stratify=df["cancelled"])

    # scale numbers, one-hot encode text columns
    def make_pipeline(model):
        prep = ColumnTransformer([("num", StandardScaler(), NUM_FEATURES),
                                  ("cat", OneHotEncoder(handle_unknown="ignore"), CAT_FEATURES)])
        return Pipeline([("prep", prep), ("model", model)])

    candidates = {
        "Logistic Regression": LogisticRegression(max_iter=1000),
        "Random Forest": RandomForestClassifier(n_estimators=150, min_samples_leaf=5, random_state=42),
    }
    results, fitted = [], {}
    for name, model in candidates.items():
        pipe = make_pipeline(model).fit(X_train, y_train)
        pred = pipe.predict(X_test)
        results.append({
            "name": name,
            "accuracy": round(accuracy_score(y_test, pred), 3),
            "precision": round(precision_score(y_test, pred, zero_division=0), 3),
            "recall": round(recall_score(y_test, pred, zero_division=0), 3),
            "f1": round(f1_score(y_test, pred, zero_division=0), 3),
            "confusion_matrix": confusion_matrix(y_test, pred).tolist(),   # [[TN, FP], [FN, TP]]
        })
        fitted[name] = pipe

    best = max(results, key=lambda r: r["f1"])
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(fitted[best["name"]], MODEL_PATH)
    info = {"best": best["name"], "results": results, "train_rows": len(X_train),
            "test_rows": len(X_test), "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    with open(METRICS_PATH, "w") as f:
        json.dump(info, f, indent=2)
    return info


def load_metrics():
    if os.path.exists(METRICS_PATH):
        with open(METRICS_PATH) as f:
            return json.load(f)
    return None


def predict_bookings(booking_ids):
    """Score bookings and store every result (with timestamp) in the predictions table."""
    info = load_metrics()
    if not info or not os.path.exists(MODEL_PATH):
        raise ValueError("No trained model yet. Train the model first.")
    pipe = joblib.load(MODEL_PATH)
    df = bookings_df()
    df = df[df["booking_id"].isin(booking_ids)]
    if df.empty:
        return 0
    probs = pipe.predict_proba(df[FEATURES])[:, 1]
    for bid, p in zip(df["booking_id"], probs):
        db.save_prediction(int(bid), round(float(p), 4), risk_level(p), info["best"])
    return len(df)


def predict_upcoming():
    return predict_bookings(db.upcoming_confirmed_ids(date.today().isoformat()))
