"""Creates demo data (rooms, customers, ~2000 bookings) so charts and ML work immediately."""
import random
from datetime import date, timedelta
from werkzeug.security import generate_password_hash
import db

COUNTRIES = ["India", "USA", "UK", "Germany", "France", "UAE", "Singapore", "Australia", "Japan", "Canada"]
COUNTRY_W = [30, 15, 10, 8, 6, 8, 6, 6, 5, 6]
TYPES = ["Online", "Corporate", "Walk-in", "Repeat"]
TYPE_W = [45, 20, 15, 20]
FIRST = ["Aarav", "Maya", "John", "Emma", "Liam", "Sofia", "Ravi", "Anita", "Chen", "Yuki",
         "Omar", "Layla", "Lucas", "Mia", "Noah", "Zara", "Karan", "Priya", "Hans", "Elena"]
LAST = ["Sharma", "Smith", "Brown", "Khan", "Patel", "Muller", "Dubois", "Tan", "Sato", "Singh",
        "Wilson", "Garcia", "Ali", "Nair", "Lee"]
ROOM_TYPES = {"Single": (80, 10), "Double": (120, 10), "Deluxe": (180, 6), "Suite": (300, 4)}
# busier summer / December
SEASON = {1: .6, 2: .6, 3: .7, 4: .7, 5: .8, 6: 1, 7: 1, 8: 1, 9: .8, 10: .7, 11: .7, 12: 1}
TYPE_RISK = {"Online": .15, "Corporate": -.05, "Walk-in": -.08, "Repeat": -.08}


def seed(n_bookings=2000):
    rnd = random.Random(7)
    today = date.today()
    db.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
               ("admin", generate_password_hash("admin123"), "admin"))
    db.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
               ("staff", generate_password_hash("staff123"), "staff"))

    rooms = []
    num = 0
    for rtype, (price, count) in ROOM_TYPES.items():
        for _ in range(count):
            num += 1
            room_no = str(100 * ((num - 1) // 10 + 1) + (num - 1) % 10 + 1)
            rid = db.add_room(room_no, rtype, price)
            rooms.append((rid, price))

    customers = []
    for _ in range(400):
        name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
        cid = db.add_customer(name, rnd.choices(COUNTRIES, COUNTRY_W)[0], rnd.choices(TYPES, TYPE_W)[0])
        customers.append(cid)
    ctype = {r["customer_id"]: r["customer_type"] for r in db.query("SELECT * FROM customers")}

    busy = {rid: [] for rid, _ in rooms}   # non-cancelled stays per room, to avoid double booking
    made = 0
    while made < n_bookings:
        offset = rnd.randint(0, 330 + 45)
        check_in = today - timedelta(days=330) + timedelta(days=offset)
        if rnd.random() > SEASON[check_in.month]:
            continue
        nights = rnd.choices([1, 2, 3, 4, 5, 6, 7], [10, 25, 25, 15, 10, 8, 7])[0]
        check_out = check_in + timedelta(days=nights)
        lead = min(int(rnd.expovariate(1 / 45)), 300)
        booking_date = check_in - timedelta(days=lead)
        if booking_date > today:
            booking_date = today - timedelta(days=rnd.randint(0, 20))
            lead = (check_in - booking_date).days
        cid = rnd.choice(customers)
        rid, price = rnd.choice(rooms)

        p = 0.10 + min(lead, 200) / 400 + TYPE_RISK[ctype[cid]] + (0.05 if price >= 180 else 0)
        p = max(0.03, min(p, 0.85))
        past = check_in < today
        if past:
            status = "Cancelled" if rnd.random() < p else "Completed"
        else:
            status = "Cancelled" if rnd.random() < p * 0.5 else "Confirmed"

        if status != "Cancelled":
            if any(check_in < e and check_out > s for s, e in busy[rid]):
                continue
            busy[rid].append((check_in, check_out))
        db.add_booking(cid, rid, check_in.isoformat(), check_out.isoformat(),
                       booking_date.isoformat(), status, nights * price)
        made += 1
