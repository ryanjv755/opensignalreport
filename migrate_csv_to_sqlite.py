import csv
import sqlite3
import os

CSV_PATH = "signal_reports.csv"
DB_PATH = "signal_reports.db"
TABLE_NAME = "signal_reports"

# Define the schema (matches CSV columns)
CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    uid TEXT PRIMARY KEY,
    timestamp TEXT,
    callsign TEXT,
    s_meter TEXT,
    snr_db REAL,
    duration_sec REAL,
    vad_trigger_threshold REAL,
    recognized_text TEXT
);
"""

INSERT_SQL = f"""
INSERT OR IGNORE INTO {TABLE_NAME} (
    uid, timestamp, callsign, s_meter, snr_db, duration_sec, vad_trigger_threshold, recognized_text
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

def migrate_csv_to_sqlite(csv_path=CSV_PATH, db_path=DB_PATH):
    if not os.path.isfile(csv_path):
        print(f"CSV file not found: {csv_path}")
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(CREATE_TABLE_SQL)
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        rows = [
            (
                row['uid'],
                row['timestamp'],
                row['callsign'],
                row['s_meter'],
                float(row['snr_db']) if row['snr_db'] else None,
                float(row['duration_sec']) if row['duration_sec'] else None,
                float(row['vad_trigger_threshold']) if row['vad_trigger_threshold'] else None,
                row['recognized_text']
            )
            for row in reader
        ]
        cur.executemany(INSERT_SQL, rows)
        conn.commit()
    print(f"Migrated {len(rows)} rows from {csv_path} to {db_path}.")
    conn.close()

if __name__ == "__main__":
    migrate_csv_to_sqlite()
