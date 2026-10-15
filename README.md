# Hotel Booking Analytics & Cancellation Prediction

Flask + SQLite + pandas + scikit-learn + Chart.js.

## Run
    pip install -r requirements.txt
    python app.py
Open http://127.0.0.1:5000  -  login `admin / admin123` (or `staff / staff123`).

On the first run the app creates `hotel.db`, adds 30 rooms, 400 customers and 2000 demo bookings,
trains the models and scores upcoming bookings. Delete `hotel.db` and `models/*` to reset.

## Code layout (3 layers)
| File | Layer | Job |
|------|-------|-----|
| `app.py` | Presentation | Flask routes, login, flash messages, render templates |
| `services.py` | Business logic | validation, CSV import, analytics (pandas), ML training/prediction |
| `db.py` | Data access | all SQL, table creation |
| `seed.py` | Demo data | fake rooms / customers / bookings |
| `templates/` | Jinja pages | one file per screen, all extend `base.html` |
| `static/charts.js` | Browser JS | one fetch to `/api/analytics`, draws all charts, handles date filter |

## Database (5 tables)
users, rooms, customers, bookings (FK customer_id, room_id), predictions (FK booking_id).
Extra columns added to `predictions`: `model_name`, `created_at` (audit history).

## Analytics
- Descriptive: occupancy trend, revenue by room type, customer origin, ADR, cancellation rate.
- Diagnostic: cancellation % by lead time and by customer type.
- Predictive: Logistic Regression vs Random Forest (75/25 split, scaled numbers, one-hot text);
  the best F1 model is saved to `models/best_model.joblib`.

Risk level: Low < 25%, Medium 25-45%, High >= 45% (edit `risk_level()` in `services.py`).

## Security notes
Passwords are hashed, uploads are limited to 2 MB `.csv` with `secure_filename`, SQL uses `?` placeholders.
For production also set the `SECRET_KEY` environment variable and add CSRF protection (Flask-WTF).
"# Hotal_analytics" 
