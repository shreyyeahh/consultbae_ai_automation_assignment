"""
Task 1 - merge the 3 source CSVs into one SQLite database, deduplicating
people who appear in more than one file. There is no common ID across files,
so matching runs on normalized email/phone instead (Strategy A - see README
"Matching Strategy" section for why this was chosen over fuzzy name matching).

Run with: python pipeline.py
No manual steps - paths are resolved relative to this file, and the database
is rebuilt from scratch on every run.

Uses only the Python standard library (csv, sqlite3, re, datetime) instead of
pandas, so there's nothing to `pip install` before this runs.
"""

import csv
import re
import sqlite3
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"
DB_PATH = SCRIPT_DIR / "consultbae.db"

SOURCE1_PATH = DATA_DIR / "source1_naukri_applicants.csv"
SOURCE2_PATH = DATA_DIR / "source2_gig_workers.csv"
SOURCE3_PATH = DATA_DIR / "source3_cbnexus_contacts.csv"

# Plain-CSV copies of the final tables, written alongside the DB so the
# result can be reviewed without any SQLite tool at all.
EXPORT_DIR = SCRIPT_DIR / "exported_csv"

# City spelling aliases: old official name -> current official name. These
# are normalized because they're literally the same city, not just a casing
# difference - see task4_report.md issue #4.
CITY_ALIASES = {
    "gurgaon": "Gurugram",
    "bangalore": "Bengaluru",
    "new delhi": "Delhi",
    "delhi ncr": "Delhi",
}

# CTC values below this are almost certainly lakhs (e.g. "4.2" meaning 4.2L),
# not raw rupees - see task4_report.md issue #5. The threshold has a huge
# safety margin: the smallest raw-rupee CTC in the data is ~327,000 and the
# largest lakh-style value is 11.9, so nothing in between exists to misfire on.
CTC_LAKH_THRESHOLD = 1000

# A person's canonical display fields prefer source1, then source2, then
# source3, when more than one source contributed a value. This is an
# arbitrary but consistent tie-break (source1 has the richest, cleanest data)
# - documented here so it's a stated decision, not a hidden default.
SOURCE_PRIORITY = {"source1": 0, "source2": 1, "source3": 2}


# ---------------------------------------------------------------------------
# Field normalizers - one function per messy column type, reused across files
# ---------------------------------------------------------------------------

def normalize_phone(raw):
    """Strip to digits only, then drop a leading country code (91) or
    domestic trunk prefix (0), leaving a canonical 10-digit number.
    e.g. '+91-9000000131' -> '9000000131', '09000000287' -> '9000000287'
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def normalize_email(raw):
    if not raw:
        return None
    return raw.strip().lower()


def normalize_city(raw):
    if not raw:
        return None
    cleaned = raw.strip()
    return CITY_ALIASES.get(cleaned.lower(), cleaned.title())


def normalize_ctc(raw):
    """Returns (raw_string, normalized_rupees). See CTC_LAKH_THRESHOLD."""
    raw = raw.strip()
    value = float(raw)
    if value < CTC_LAKH_THRESHOLD:
        return raw, value * 100_000
    return raw, value


# Date shapes seen in source1, tried in this order: (regex to detect the
# shape, strptime format to parse it).
DATE_PATTERNS = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d"),
    (re.compile(r"^\d{2}-\d{2}-\d{4}$"), "%d-%m-%Y"),
    # Confirmed MM/DD/YYYY (not DD/MM) by a row with day=13, e.g. 07/13/2026
    # - 13 can't be a month, so every slash-separated date follows this rule.
    (re.compile(r"^\d{2}/\d{2}/\d{4}$"), "%m/%d/%Y"),
    (re.compile(r"^\d{1,2} [A-Za-z]{3} \d{4}$"), "%d %b %Y"),
]


def parse_date(raw):
    raw = raw.strip()
    for pattern, fmt in DATE_PATTERNS:
        if pattern.match(raw):
            return datetime.strptime(raw, fmt).date().isoformat()
    return None  # left blank rather than guessed - see task4_report.md #6


def normalize_skills(raw):
    if not raw:
        return ""
    items = sorted({s.strip().lower() for s in raw.split(",") if s.strip()})
    return ", ".join(items)


def parse_rate(raw):
    """Returns (raw_string, amount, unit). Two shapes appear: '1415/hr' and
    '15k/month'. Deliberately NOT converted to one unit - see task4_report.md
    issue #9, there's no safe hours-per-month assumption to convert between them.
    """
    raw = raw.strip()
    hourly = re.match(r"^(\d+)/hr$", raw)
    if hourly:
        return raw, int(hourly.group(1)), "hr"
    monthly = re.match(r"^(\d+)k/month$", raw)
    if monthly:
        return raw, int(monthly.group(1)) * 1000, "month"
    return raw, None, None


def normalize_status(raw):
    return raw.strip().lower()


def normalize_verified(raw):
    return raw.strip().lower() in ("y", "yes")


# ---------------------------------------------------------------------------
# Loaders - read + clean each CSV into a list of dicts ("candidate rows")
# ---------------------------------------------------------------------------

def load_source1():
    rows = []
    with open(SOURCE1_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ctc_raw, ctc_normalized = normalize_ctc(row["Current CTC"])
            rows.append({
                "source": "source1",
                "full_name": row["Full Name"].strip(),
                "email_norm": normalize_email(row["Email"]),
                "phone_norm": normalize_phone(row["Phone"]),
                "city": normalize_city(row["City"]),
                "experience_years": float(row["Experience (Years)"]),
                "ctc_raw": ctc_raw,
                "ctc_normalized": ctc_normalized,
                "applied_date": parse_date(row["Applied Date"]),
                "skills": normalize_skills(row["Skills"]),
            })
    return rows, len(rows)


def load_source2():
    rows = []
    raw_count = 0
    dropped_blank = 0
    dropped_malformed = 0
    with open(SOURCE2_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw_count += 1
            values = [v.strip() for v in row.values() if v is not None]
            if not any(values):
                dropped_blank += 1  # e.g. the fully empty line 12
                continue
            if "@" not in row["email_id"]:
                # Column-shifted row (see task4_report.md #8) - its content
                # duplicates another valid row anyway, so drop rather than
                # write one-off realignment logic for a single bad row.
                dropped_malformed += 1
                continue
            rate_raw, rate_amount, rate_unit = parse_rate(row["rate"])
            rows.append({
                "source": "source2",
                "worker_name": row["worker_name"].strip(),
                "email_norm": normalize_email(row["email_id"]),
                "phone_norm": None,  # no phone column exists in this file
                "city": normalize_city(row["location"]),
                "rate_raw": rate_raw,
                "rate_amount": rate_amount,
                "rate_unit": rate_unit,
                "status": normalize_status(row["status"]),
                "skill_tags": normalize_skills(row["skill_tags"]),
            })
    return rows, raw_count, dropped_blank, dropped_malformed


def load_source3():
    rows = []
    raw_count = 0
    dropped_header_repeat = 0
    with open(SOURCE3_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw_count += 1
            if row["Name"] == "Name":
                # The header row leaked into the data - see task4_report.md #12
                dropped_header_repeat += 1
                continue
            rows.append({
                "source": "source3",
                "name": row["Name"].strip(),
                "email_norm": None,  # no email column exists in this file
                "phone_norm": normalize_phone(row["Phone Number"]),
                "city": normalize_city(row["City"]),
                "verified": normalize_verified(row["Verified"]),
                "projects_completed": int(row["Projects Completed"]),
            })
    return rows, raw_count, dropped_header_repeat


def display_name(candidate):
    return candidate.get("full_name") or candidate.get("worker_name") or candidate.get("name")


# ---------------------------------------------------------------------------
# Matching - Strategy A: union-find over ALL rows from ALL files at once.
#
# Two rows are the same person if their normalized email matches, OR their
# normalized phone matches - checked across the whole pool, not file-by-file.
# This makes merges transitive: if row A matches row B on email, and row B
# matches row C on phone, all three end up as one person even though A and C
# never matched each other directly. A sequential "join source1+source2,
# then join the result with source3" approach would miss exactly this case,
# and would give different results depending on which file you joined first.
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]  # path compression
            i = self.parent[i]
        return i

    def union(self, i, j):
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[ri] = rj


def match_people(candidates):
    uf = UnionFind(len(candidates))

    by_email = {}
    by_phone = {}
    for idx, c in enumerate(candidates):
        if c["email_norm"]:
            by_email.setdefault(c["email_norm"], []).append(idx)
        if c["phone_norm"]:
            by_phone.setdefault(c["phone_norm"], []).append(idx)

    for group in list(by_email.values()) + list(by_phone.values()):
        for idx in group[1:]:
            uf.union(group[0], idx)

    groups = {}
    for idx in range(len(candidates)):
        root = uf.find(idx)
        groups.setdefault(root, []).append(idx)
    return list(groups.values())


def canonical_fields(members):
    ordered = sorted(members, key=lambda c: SOURCE_PRIORITY[c["source"]])
    name = next((display_name(c) for c in ordered if display_name(c)), None)
    email = next((c["email_norm"] for c in ordered if c["email_norm"]), None)
    phone = next((c["phone_norm"] for c in ordered if c["phone_norm"]), None)
    city = next((c["city"] for c in ordered if c.get("city")), None)
    return name, email, phone, city


def match_reason(members):
    """Which field(s) actually tied this group together: at least 2 members
    must contribute that field for it to count as "shared" (a group with one
    email-having member and one email-less member never shared an email).
    """
    emails_present = [m["email_norm"] for m in members if m["email_norm"]]
    phones_present = [m["phone_norm"] for m in members if m["phone_norm"]]
    reasons = []
    if len(emails_present) >= 2:
        reasons.append("shared email")
    if len(phones_present) >= 2:
        reasons.append("shared phone")
    return " + ".join(reasons) if reasons else "bridged transitively"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE people (
    person_id       INTEGER PRIMARY KEY,
    canonical_name  TEXT,
    canonical_email TEXT,
    canonical_phone TEXT,
    canonical_city  TEXT,
    source_count    INTEGER
);

CREATE TABLE naukri_applications (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id         INTEGER REFERENCES people(person_id),
    full_name         TEXT,
    email             TEXT,
    phone             TEXT,
    city              TEXT,
    experience_years  REAL,
    ctc_raw           TEXT,
    current_ctc_inr   REAL,
    applied_date      TEXT,
    skills            TEXT
);

CREATE TABLE gig_worker_profiles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id    INTEGER REFERENCES people(person_id),
    email        TEXT,
    worker_name  TEXT,
    city         TEXT,
    rate_raw     TEXT,
    rate_amount  REAL,
    rate_unit    TEXT,
    status       TEXT,
    skill_tags   TEXT
);

CREATE TABLE cbnexus_contacts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id           INTEGER REFERENCES people(person_id),
    name                TEXT,
    phone               TEXT,
    city                TEXT,
    verified            INTEGER,
    projects_completed  INTEGER
);
"""


def build_database(candidates, groups):
    if DB_PATH.exists():
        DB_PATH.unlink()  # rebuilt fresh every run - no incremental/manual step
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    for person_id, member_indices in enumerate(groups, start=1):
        members = [candidates[i] for i in member_indices]
        name, email, phone, city = canonical_fields(members)
        conn.execute(
            "INSERT INTO people VALUES (?, ?, ?, ?, ?, ?)",
            (person_id, name, email, phone, city, len({m["source"] for m in members})),
        )
        # Every raw row a person contributed is kept (not collapsed) in the
        # source-specific table - identity is deduped, source history isn't.
        for m in members:
            if m["source"] == "source1":
                conn.execute(
                    "INSERT INTO naukri_applications "
                    "(person_id, full_name, email, phone, city, experience_years, "
                    " ctc_raw, current_ctc_inr, applied_date, skills) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (person_id, m["full_name"], m["email_norm"], m["phone_norm"], m["city"],
                     m["experience_years"], m["ctc_raw"], m["ctc_normalized"],
                     m["applied_date"], m["skills"]),
                )
            elif m["source"] == "source2":
                conn.execute(
                    "INSERT INTO gig_worker_profiles "
                    "(person_id, email, worker_name, city, rate_raw, rate_amount, "
                    " rate_unit, status, skill_tags) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (person_id, m["email_norm"], m["worker_name"], m["city"],
                     m["rate_raw"], m["rate_amount"], m["rate_unit"],
                     m["status"], m["skill_tags"]),
                )
            else:  # source3
                conn.execute(
                    "INSERT INTO cbnexus_contacts "
                    "(person_id, name, phone, city, verified, projects_completed) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (person_id, m["name"], m["phone_norm"], m["city"],
                     int(m["verified"]), m["projects_completed"]),
                )

    conn.commit()
    export_tables_to_csv(conn)
    conn.close()


def export_tables_to_csv(conn):
    """Dump every table to a plain CSV, so the final merged data can be
    reviewed by opening a file in Excel/a text editor - no SQLite tool needed.
    """
    EXPORT_DIR.mkdir(exist_ok=True)
    for table in ("people", "naukri_applications", "gig_worker_profiles", "cbnexus_contacts"):
        cur = conn.execute(f"SELECT * FROM {table}")
        columns = [description[0] for description in cur.description]
        with open(EXPORT_DIR / f"{table}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(cur.fetchall())


# ---------------------------------------------------------------------------
# Console reporting
# ---------------------------------------------------------------------------

def print_normalization_log(counts):
    print("=" * 72)
    print("NORMALIZATION APPLIED")
    print("=" * 72)
    print("Phone        -> digits only, dropped leading 91/0 -> canonical 10-digit")
    print("Email        -> lowercased + trimmed")
    print(f"City         -> trimmed, title-cased, aliases mapped: {CITY_ALIASES}")
    print(f"Current CTC  -> values < {CTC_LAKH_THRESHOLD} treated as lakhs, x100,000")
    print("Applied Date -> parsed via 4 detected formats (ISO / DD-MM-YYYY / MM-DD-YYYY / D Mon YYYY)")
    print("Skills       -> split on comma, trimmed, lowercased, deduped, sorted")
    print("Rate         -> parsed into (amount, unit) pairs, NOT unit-converted")
    print("Status       -> lowercased + trimmed")
    print("Verified     -> Y/Yes -> True, N/No -> False")
    print()
    print(f"Dropped from source2: {counts['blank']} fully blank row(s), "
          f"{counts['malformed']} column-shifted row(s)")
    print(f"Dropped from source3: {counts['header_repeat']} embedded header-repeat row(s)")
    print()


def print_groups_table(candidates, groups):
    print("=" * 72)
    print("MATCH GROUPS (person identity resolution)")
    print("=" * 72)
    merged = [g for g in groups if len(g) > 1]
    print(f"{len(merged)} of {len(groups)} people were built from more than one raw row:\n")
    for person_id, member_indices in enumerate(groups, start=1):
        if len(member_indices) == 1:
            continue
        members = [candidates[i] for i in member_indices]
        name, _, _, _ = canonical_fields(members)
        print(f"Person #{person_id}: {name}  (matched via: {match_reason(members)})")
        for m in members:
            print(f"   - [{m['source']:8s}] {display_name(m):20s} "
                  f"email={m['email_norm']}  phone={m['phone_norm']}")
        print()


def print_summary(s1_count, s2_count, s2_dropped, s3_count, s3_dropped, candidates, groups):
    print("=" * 72)
    print("MERGE SUMMARY")
    print("=" * 72)
    print(f"source1_naukri_applicants.csv : {s1_count} rows read")
    print(f"source2_gig_workers.csv       : {s2_count} rows read, {s2_dropped} dropped -> "
          f"{s2_count - s2_dropped} usable")
    print(f"source3_cbnexus_contacts.csv  : {s3_count} rows read, {s3_dropped} dropped -> "
          f"{s3_count - s3_dropped} usable")
    print(f"Total candidate rows matched  : {len(candidates)}")
    print()

    merged = sum(1 for g in groups if len(g) > 1)
    single = len(groups) - merged
    print(f"Unique people found           : {len(groups)}")
    print(f"  - from a single raw row     : {single}")
    print(f"  - merged from multiple rows : {merged}")
    print()

    by_source_count = {}
    for g in groups:
        n = len({candidates[i]["source"] for i in g})
        by_source_count[n] = by_source_count.get(n, 0) + 1
    labels = {1: "in exactly 1 source", 2: "in exactly 2 sources", 3: "in all 3 sources"}
    for n in sorted(by_source_count):
        print(f"  - people found {labels[n]}: {by_source_count[n]}")
    print()
    print(f"Database written to: {DB_PATH}")
    print(f"Plain-CSV copies of every table written to: {EXPORT_DIR}")


# ---------------------------------------------------------------------------

def main():
    source1, s1_count = load_source1()
    source2, s2_count, s2_blank, s2_malformed = load_source2()
    source3, s3_count, s3_header_repeat = load_source3()

    candidates = source1 + source2 + source3
    groups = match_people(candidates)

    print_normalization_log({
        "blank": s2_blank,
        "malformed": s2_malformed,
        "header_repeat": s3_header_repeat,
    })
    print_groups_table(candidates, groups)
    build_database(candidates, groups)
    print_summary(
        s1_count, s2_count, s2_blank + s2_malformed,
        s3_count, s3_header_repeat, candidates, groups,
    )


if __name__ == "__main__":
    main()
