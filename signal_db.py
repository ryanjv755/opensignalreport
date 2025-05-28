import sqlite3
import time
import uuid

SQLITE_DB_PATH = "signal_reports.db"
SQLITE_TABLE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS signal_reports (
    uid TEXT PRIMARY KEY,
    timestamp TEXT,
    callsign TEXT,
    s_meter TEXT,
    snr_db REAL,
    duration_sec REAL,
    vad_trigger_threshold REAL,
    recognized_text TEXT
);
'''

def get_sqlite_connection():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    return conn

def ensure_table_exists():
    with get_sqlite_connection() as conn:
        conn.execute(SQLITE_TABLE_SCHEMA)
        conn.commit()

def log_signal_report(callsign, s_meter, snr, recognized_text, duration_sec, timestamp=None, uid=None):
    if timestamp is None:
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    if uid is None:
        uid = uuid.uuid4().hex[:16]
    with get_sqlite_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO signal_reports (uid, timestamp, callsign, s_meter, snr_db, duration_sec, recognized_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (uid, timestamp, callsign, s_meter, snr, duration_sec, recognized_text)
        )
        conn.commit()

def get_all_signal_reports():
    with get_sqlite_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM signal_reports ORDER BY timestamp DESC")
        return cur.fetchall()
