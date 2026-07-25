import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
import db

app = Flask(__name__)

# ------------------------------------------------------------------ #
# Startup: try to initialize the database tables on first boot        #
# ------------------------------------------------------------------ #
db_initialized = False
db_init_error = None

try:
    success, msg = db.init_db()
    if success:
        db_initialized = True
    else:
        db_init_error = msg
except Exception as e:
    db_init_error = str(e)


def _try_init():
    """Attempt DB initialization if it hasn't succeeded yet."""
    global db_initialized, db_init_error
    if not db_initialized:
        try:
            success, msg = db.init_db()
            if success:
                db_initialized = True
                db_init_error = None
            else:
                db_init_error = msg
        except Exception as e:
            db_init_error = str(e)


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def index():
    _try_init()

    appointments = []
    stats = {"total": 0, "pending": 0, "confirmed": 0, "cancelled": 0}
    connection_status = "Disconnected"
    error_message = db_init_error

    detected_driver = db.get_driver()

    if not detected_driver:
        connection_status = "Missing ODBC Driver"
        error_message = (
            "No SQL Server ODBC driver found. "
            "Install 'ODBC Driver 17/18 for SQL Server' from Microsoft."
        )
    elif db_initialized:
        # Read filter params from query string
        status_filter = request.args.get("status", "All")
        date_filter = request.args.get("date", "")

        try:
            appointments = db.get_appointments(
                status_filter=status_filter if status_filter != "All" else None,
                date_filter=date_filter if date_filter else None,
            )
            stats = db.get_stats()
            connection_status = "Connected"
        except Exception as e:
            connection_status = "Query Error"
            error_message = str(e)

    return render_template(
        "index.html",
        appointments=appointments,
        stats=stats,
        connection_status=connection_status,
        error_message=error_message,
        driver_name=detected_driver or "None Detected",
        status_filter=request.args.get("status", "All"),
        date_filter=request.args.get("date", ""),
    )


@app.route("/book", methods=["GET"])
def book():
    _try_init()

    services = []
    error_message = None
    connection_status = "Disconnected"
    detected_driver = db.get_driver()

    if not detected_driver:
        connection_status = "Missing ODBC Driver"
        error_message = "No SQL Server ODBC driver found on this system."
    elif db_initialized:
        try:
            services = db.get_services()
            connection_status = "Connected"
        except Exception as e:
            error_message = str(e)

    form_error = request.args.get("error")
    if form_error:
        error_message = form_error

    return render_template(
        "book.html",
        services=services,
        connection_status=connection_status,
        error_message=error_message,
    )


@app.route("/book", methods=["POST"])
def book_submit():
    patient_name  = request.form.get("patient_name", "").strip()
    patient_email = request.form.get("patient_email", "").strip()
    patient_phone = request.form.get("patient_phone", "").strip()
    service_id    = request.form.get("service_id")
    appt_date     = request.form.get("appointment_date")
    appt_time     = request.form.get("appointment_time")
    notes         = request.form.get("notes", "").strip()

    if not all([patient_name, patient_email, service_id, appt_date, appt_time]):
        return redirect(url_for("book", error="Please fill in all required fields."))

    try:
        db.book_appointment(
            patient_name, patient_email, patient_phone,
            int(service_id), appt_date, appt_time, notes
        )
        return redirect(url_for("index"))
    except Exception as e:
        return redirect(url_for("book", error=str(e)))


@app.route("/cancel/<int:appt_id>", methods=["POST"])
def cancel(appt_id):
    try:
        db.cancel_appointment(appt_id)
    except Exception:
        pass
    return redirect(url_for("index"))


@app.route("/confirm/<int:appt_id>", methods=["POST"])
def confirm(appt_id):
    try:
        db.confirm_appointment(appt_id)
    except Exception:
        pass
    return redirect(url_for("index"))


@app.route("/api/health")
def health():
    driver = db.get_driver()
    status = {
        "status": "healthy",
        "odbc_driver_detected": driver is not None,
        "active_driver": driver,
        "db_initialized": db_initialized,
        "db_connected": False,
    }
    try:
        conn = db.get_db_connection()
        conn.close()
        status["db_connected"] = True
    except Exception as e:
        status["db_error"] = str(e)
    return jsonify(status)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
