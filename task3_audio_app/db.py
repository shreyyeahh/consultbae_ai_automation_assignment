"""
Shared SQLite access for Task 3 - extends the same consultbae.db that
Task 1's pipeline.py builds: adds a `submissions` table (idempotently, so
it's safe to call on every app run) and the person-lookup-or-create logic
used when someone submits audio.
"""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TASK1_DIR = SCRIPT_DIR.parent / "task1_merge"
DB_PATH = TASK1_DIR / "consultbae.db"

# Reuse Task 1's exact phone normalization instead of re-implementing it -
# two slightly different copies could normalize the same real phone number
# differently and silently create a duplicate person. pipeline.py guards
# its own execution with `if __name__ == "__main__"`, so importing it here
# only pulls in the functions/constants, nothing runs.
sys.path.insert(0, str(TASK1_DIR))
from pipeline import normalize_phone  # noqa: E402

SUBMISSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    submission_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id         INTEGER NOT NULL REFERENCES people(person_id),
    audio_path        TEXT NOT NULL,
    original_filename TEXT,
    audio_format      TEXT,
    duration_sec      REAL,
    sample_rate_hz    INTEGER,
    bitrate_kbps      REAL,
    loudness_dbfs     REAL,
    quality_label     TEXT,
    submitted_at      TEXT NOT NULL
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SUBMISSIONS_SCHEMA)
    conn.commit()
    return conn


def find_or_create_person(conn, name, raw_phone):
    """Match-or-create by phone, mirroring Task 1's matching logic exactly.
    Returns (person_id, is_new). Never modifies an existing people row -
    people.source_count from Task 1's merge is left untouched either way.
    """
    phone_norm = normalize_phone(raw_phone)
    if not phone_norm:
        raise ValueError(f"'{raw_phone}' doesn't look like a valid phone number")

    row = conn.execute(
        "SELECT person_id FROM people WHERE canonical_phone = ?", (phone_norm,)
    ).fetchone()
    if row:
        return row[0], False

    # source_count=0 is a value Task 1's pipeline can never itself produce
    # (every person it creates came from at least 1 of the 3 CSVs) - so it
    # unambiguously flags "created via Task 3, not part of the original merge".
    cur = conn.execute(
        "INSERT INTO people (canonical_name, canonical_email, canonical_phone, "
        "canonical_city, source_count) VALUES (?, NULL, ?, NULL, 0)",
        (name.strip(), phone_norm),
    )
    conn.commit()
    return cur.lastrowid, True


def insert_submission(conn, person_id, audio_path, original_filename, metadata):
    conn.execute(
        "INSERT INTO submissions (person_id, audio_path, original_filename, "
        "audio_format, duration_sec, sample_rate_hz, bitrate_kbps, "
        "loudness_dbfs, quality_label, submitted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            person_id, str(audio_path), original_filename,
            metadata["audio_format"], metadata["duration_sec"],
            metadata["sample_rate_hz"], metadata["bitrate_kbps"],
            metadata["loudness_dbfs"], metadata["quality_label"],
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def list_submissions(conn):
    return conn.execute(
        "SELECT s.submission_id, p.canonical_name, p.canonical_phone, "
        "s.audio_path, s.duration_sec, s.sample_rate_hz, s.bitrate_kbps, "
        "s.loudness_dbfs, s.quality_label, s.submitted_at "
        "FROM submissions s JOIN people p ON s.person_id = p.person_id "
        "ORDER BY s.submitted_at DESC"
    ).fetchall()
