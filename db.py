import os
import time
import logging
import pyodbc
from dotenv import load_dotenv

# Load env variables from .env if present
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_driver():
    """Detect available SQL Server ODBC drivers on the system."""
    available_drivers = pyodbc.drivers()
    preferred = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server",
    ]
    for p in preferred:
        if p in available_drivers:
            return p
    for d in available_drivers:
        if "SQL Server" in d or "ODBC" in d:
            return d
    return None


def get_conn_string():
    """Build connection string from env variables or a full SQL_CONN_STR."""
    # Priority 1: Full custom connection string
    full_conn_str = os.getenv("SQL_CONN_STR")
    if full_conn_str:
        return full_conn_str

    # Priority 2: Structured environment variables
    server = os.getenv("SQL_SERVER")
    database = os.getenv("SQL_DATABASE")
    username = os.getenv("SQL_USER")
    password = os.getenv("SQL_PASSWORD")

    if not all([server, database, username, password]):
        return None

    driver = get_driver()
    if not driver:
        logger.error(
            "No SQL Server ODBC drivers detected. Drivers found: %s", pyodbc.drivers()
        )
        raise RuntimeError(
            "No SQL Server ODBC drivers found on this system. "
            "Please install Microsoft ODBC Driver 17 or 18 for SQL Server."
        )

    encrypt = os.getenv("SQL_ENCRYPT", "yes")
    trust_cert = os.getenv("SQL_TRUST_CERT", "no")

    conn_str = (
        f"Driver={{{driver}}};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust_cert};"
        f"Connection Timeout=30;"
    )
    return conn_str


def get_db_connection():
    """Establish a connection to Azure SQL with automatic retries."""
    conn_str = get_conn_string()
    if not conn_str:
        raise ValueError(
            "Database credentials are not configured. "
            "Set SQL_SERVER, SQL_DATABASE, SQL_USER, and SQL_PASSWORD in your .env file."
        )

    retries = 3
    delay = 2
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Database connection attempt {attempt} of {retries}...")
            conn = pyodbc.connect(conn_str)
            logger.info("Database connection established successfully.")
            return conn
        except Exception as e:
            last_error = e
            logger.warning(f"Connection attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(delay)
                delay *= 2

    raise last_error


def init_db():
    """Initialize the services and appointments tables if they do not exist."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Create services table
        cursor.execute("""
            IF NOT EXISTS (
                SELECT * FROM sysobjects WHERE name='services' AND xtype='U'
            )
            BEGIN
                CREATE TABLE services (
                    id           INT IDENTITY(1,1) PRIMARY KEY,
                    name         NVARCHAR(100) NOT NULL,
                    duration_mins INT NOT NULL DEFAULT 30
                )
            END
        """)

        # Create appointments table
        cursor.execute("""
            IF NOT EXISTS (
                SELECT * FROM sysobjects WHERE name='appointments' AND xtype='U'
            )
            BEGIN
                CREATE TABLE appointments (
                    id                INT IDENTITY(1,1) PRIMARY KEY,
                    patient_name      NVARCHAR(100) NOT NULL,
                    patient_email     NVARCHAR(100) NOT NULL,
                    patient_phone     NVARCHAR(20),
                    service_id        INT REFERENCES services(id),
                    appointment_date  DATE NOT NULL,
                    appointment_time  TIME NOT NULL,
                    status            NVARCHAR(20) NOT NULL DEFAULT 'Pending',
                    notes             NVARCHAR(MAX),
                    created_at        DATETIME DEFAULT GETDATE()
                )
            END
        """)

        conn.commit()

        # Seed default services if table is empty
        cursor.execute("SELECT COUNT(*) FROM services")
        count = cursor.fetchone()[0]
        if count == 0:
            default_services = [
                ("General Consultation", 30),
                ("Dental Checkup", 45),
                ("Eye Examination", 30),
                ("Physiotherapy", 60),
                ("Cardiology Checkup", 45),
                ("Dermatology Consultation", 30),
            ]
            cursor.executemany(
                "INSERT INTO services (name, duration_mins) VALUES (?, ?)",
                default_services,
            )
            conn.commit()
            logger.info("Seeded default services.")

        conn.close()
        logger.info("Database initialization complete.")
        return True, "Database initialized successfully."
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Database initialization failed: {err_msg}")
        return False, err_msg


# -------------------------------------------------------------------
# Service queries
# -------------------------------------------------------------------

def get_services():
    """Return all available services."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, duration_mins FROM services ORDER BY name")
    columns = [col[0] for col in cursor.description]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return results


# -------------------------------------------------------------------
# Appointment queries
# -------------------------------------------------------------------

def book_appointment(patient_name, patient_email, patient_phone,
                     service_id, appt_date, appt_time, notes):
    """Insert a new appointment record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO appointments
            (patient_name, patient_email, patient_phone,
             service_id, appointment_date, appointment_time, notes, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending')
        """,
        (patient_name, patient_email, patient_phone,
         service_id, appt_date, appt_time, notes),
    )
    conn.commit()
    conn.close()


def get_appointments(status_filter=None, date_filter=None):
    """Return appointments with optional status/date filter, newest first."""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT
            a.id, a.patient_name, a.patient_email, a.patient_phone,
            s.name AS service_name, s.duration_mins,
            a.appointment_date, a.appointment_time,
            a.status, a.notes, a.created_at
        FROM appointments a
        LEFT JOIN services s ON a.service_id = s.id
        WHERE 1=1
    """
    params = []

    if status_filter and status_filter != "All":
        query += " AND a.status = ?"
        params.append(status_filter)

    if date_filter:
        query += " AND a.appointment_date = ?"
        params.append(date_filter)

    query += " ORDER BY a.appointment_date DESC, a.appointment_time DESC"

    cursor.execute(query, params)
    columns = [col[0] for col in cursor.description]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return results


def cancel_appointment(appt_id):
    """Set an appointment's status to Cancelled."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE appointments SET status = 'Cancelled' WHERE id = ?",
        (appt_id,)
    )
    conn.commit()
    conn.close()


def confirm_appointment(appt_id):
    """Set an appointment's status to Confirmed."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE appointments SET status = 'Confirmed' WHERE id = ?",
        (appt_id,)
    )
    conn.commit()
    conn.close()


def get_stats():
    """Return aggregate counts for the dashboard summary cards."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(*)                                        AS total,
            SUM(CASE WHEN status = 'Pending'   THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN status = 'Confirmed' THEN 1 ELSE 0 END) AS confirmed,
            SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled
        FROM appointments
    """)
    row = cursor.fetchone()
    conn.close()
    return {
        "total": row[0] or 0,
        "pending": row[1] or 0,
        "confirmed": row[2] or 0,
        "cancelled": row[3] or 0,
    }
