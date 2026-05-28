#!/usr/bin/env python3
"""
Import workout data from Google Sheets CSV into PostgreSQL.

Usage:
    python3 import_data.py
    python3 import_data.py --dry-run   # parse only, no DB write
    python3 import_data.py --dsn "host=localhost dbname=workout_report"
"""

import csv
import io
import re
import sys
import urllib.request
import argparse
import psycopg2
from datetime import date, time

SPREADSHEET_ID = "1DvQFcuF5YX1GgLdGaMOZDuYWMwg_9yEZdZKbsBsaXY4"
SHEET_GID      = "562391497"
EXPORT_URL     = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
    f"/export?format=csv&gid={SHEET_GID}"
)

DAY_MAP = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}

# ── CSV fetch ────────────────────────────────────────────────────────────────

def fetch_csv() -> list[list[str]]:
    req = urllib.request.Request(EXPORT_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        data = resp.read().decode("utf-8")
    return list(csv.reader(io.StringIO(data)))


# ── Parsing helpers ──────────────────────────────────────────────────────────

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})[（(（]?([月火水木金土日])[）)）]?")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})")
EXP_RE  = re.compile(r"Exp:\s*(\d+)", re.IGNORECASE)
REPS_RE = re.compile(r"(\d+)\s*回")
PCT_RE  = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_date(cell: str, year_hint: int) -> tuple[date, str] | None:
    m = DATE_RE.search(cell)
    if not m:
        return None
    month, day, dow = int(m.group(1)), int(m.group(2)), m.group(3)
    year = year_hint if month >= 10 else year_hint + 1
    return date(year, month, day), dow


def parse_time_range(cell: str) -> tuple[time, time] | None:
    m = TIME_RE.search(cell)
    if not m:
        return None
    sh, sm, eh, em = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return time(sh, sm), time(eh, em)


def parse_bool(cell: str) -> bool | None:
    v = cell.strip().upper()
    if v == "TRUE":
        return True
    if v == "FALSE":
        return False
    return None


def safe_float(cell: str) -> float | None:
    try:
        v = float(cell.strip().replace(",", ""))
        return v if v != 0.0 else None
    except (ValueError, AttributeError):
        return None


def safe_int(cell: str) -> int | None:
    try:
        return int(cell.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return None


def get_cell(row: list[str], idx: int) -> str:
    return row[idx].strip() if idx < len(row) else ""


def is_empty_row(row: list[str]) -> bool:
    return not any(c.strip() for c in row)


# ── Layout detection ─────────────────────────────────────────────────────────

def detect_layout(header_row: list[str]) -> str:
    """
    Detect which column layout is in use.

    'old': ,,1RM,80%,,,,設定,1RM対比,1set,2set,3set,...
    'new': ,,1RM,80%,,低負荷,rep,高負荷,1RM対比,1set,2set,3set,...
           (adds 低負荷 at col5, rep at col6; setting moves to col7 labeled 高負荷)
    """
    if get_cell(header_row, 5) in ("低負荷",) or get_cell(header_row, 6) == "rep":
        return "new"
    return "old"


def parse_exercise_row(row: list[str], layout: str) -> dict | None:
    """Parse a single exercise row according to the detected layout."""
    name = get_cell(row, 1)
    if not name:
        return None

    sort_raw = get_cell(row, 0)
    sort_order = int(sort_raw) if sort_raw.isdigit() else None

    one_rm    = safe_float(get_cell(row, 2))
    pct80     = safe_float(get_cell(row, 3))

    if layout == "new":
        low_load = safe_float(get_cell(row, 5))
        reps     = safe_int(get_cell(row, 6))
        setting  = safe_float(get_cell(row, 7))
        muscle   = get_cell(row, 13) or None
    else:
        low_load = None
        reps     = None
        setting  = safe_float(get_cell(row, 7))
        muscle   = None

    ratio_raw = get_cell(row, 8)
    ratio_m   = PCT_RE.search(ratio_raw)
    ratio     = float(ratio_m.group(1)) if ratio_m else None

    return {
        "sort_order":     sort_order,
        "name":           name,
        "one_rep_max":    one_rm,
        "weight_pct80":   pct80,
        "weight_setting": setting,
        "weight_low_load":low_load,
        "reps":           reps,
        "ratio_pct":      ratio,
        "set1":           parse_bool(get_cell(row, 9)),
        "set2":           parse_bool(get_cell(row, 10)),
        "set3":           parse_bool(get_cell(row, 11)),
        "exp_earned":     safe_int(get_cell(row, 12)),
        "muscle_groups":  muscle,
    }


# ── Block parser ─────────────────────────────────────────────────────────────

def find_date_in_row(row: list[str], year_hint: int) -> tuple[date, str, int] | None:
    """Search cols 7 and 8 for a date pattern. Returns (date, dow, col_idx)."""
    for col in (7, 8):
        cell = get_cell(row, col)
        result = parse_date(cell, year_hint)
        if result:
            return result[0], result[1], col
    return None


def parse_blocks(rows: list[list[str]], base_year: int = 2024) -> list[dict]:
    sessions: list[dict] = []
    i = 0

    while i < len(rows):
        row = rows[i]
        date_result = find_date_in_row(row, base_year)
        if date_result is None:
            i += 1
            continue

        session_date, dow, date_col = date_result
        i += 1

        # --- session info row ---
        info_row = rows[i] if i < len(rows) else []
        rep_count = None
        start_t = end_t = None
        total_exp = None

        reps_m = REPS_RE.search(get_cell(info_row, 3))
        if reps_m:
            rep_count = int(reps_m.group(1))

        time_result = parse_time_range(get_cell(info_row, 8))
        if time_result:
            start_t, end_t = time_result

        # Exp can be in col 12 (both layouts)
        for exp_col in (12, 11):
            exp_m = EXP_RE.search(get_cell(info_row, exp_col))
            if exp_m:
                total_exp = int(exp_m.group(1))
                break

        i += 1  # advance past info row

        # --- header row ---
        header_row = rows[i] if i < len(rows) else []
        layout = detect_layout(header_row)
        i += 1  # advance past header row

        # --- exercise rows ---
        exercises: list[dict] = []
        while i < len(rows):
            ex_row = rows[i]

            if is_empty_row(ex_row):
                i += 1
                break

            # If next session's date row appears, stop (no empty separator)
            if find_date_in_row(ex_row, base_year) is not None:
                break

            ex = parse_exercise_row(ex_row, layout)
            if ex:
                exercises.append(ex)
            i += 1

        sessions.append({
            "date":       session_date,
            "dow":        dow,
            "start_time": start_t,
            "end_time":   end_t,
            "rep_count":  rep_count,
            "total_exp":  total_exp,
            "exercises":  exercises,
        })

    return sessions


# ── Database import ──────────────────────────────────────────────────────────

def get_or_create_exercise(cur, name: str) -> int:
    cur.execute("SELECT id FROM exercises WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO exercises (name) VALUES (%s) RETURNING id", (name,))
    return cur.fetchone()[0]


def import_sessions(sessions: list[dict], dsn: str) -> None:
    conn = psycopg2.connect(dsn)
    try:
        with conn:
            cur = conn.cursor()
            inserted = skipped = 0
            for s in sessions:
                cur.execute(
                    "SELECT id FROM workout_sessions WHERE session_date = %s",
                    (s["date"],)
                )
                if cur.fetchone():
                    print(f"  skip (already exists): {s['date']}")
                    skipped += 1
                    continue

                cur.execute(
                    """
                    INSERT INTO workout_sessions
                        (session_date, day_of_week, start_time, end_time, rep_count, total_exp)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (s["date"], s["dow"], s["start_time"], s["end_time"],
                     s["rep_count"], s["total_exp"]),
                )
                session_id = cur.fetchone()[0]

                for ex in s["exercises"]:
                    ex_id = get_or_create_exercise(cur, ex["name"])
                    cur.execute(
                        """
                        INSERT INTO session_exercises
                            (session_id, exercise_id, sort_order,
                             one_rep_max, weight_pct80, weight_setting,
                             weight_low_load, reps,
                             ratio_pct,
                             set1_completed, set2_completed, set3_completed,
                             exp_earned, muscle_groups)
                        VALUES (%s,%s,%s, %s,%s,%s, %s,%s, %s, %s,%s,%s, %s,%s)
                        ON CONFLICT (session_id, exercise_id) DO NOTHING
                        """,
                        (session_id, ex_id, ex["sort_order"],
                         ex["one_rep_max"], ex["weight_pct80"], ex["weight_setting"],
                         ex["weight_low_load"], ex["reps"],
                         ex["ratio_pct"],
                         ex["set1"], ex["set2"], ex["set3"],
                         ex["exp_earned"], ex["muscle_groups"]),
                    )
                inserted += 1
                print(f"  imported: {s['date']} ({s['dow']})  "
                      f"exercises={len(s['exercises'])}  exp={s['total_exp']}")

        print(f"\nDone — inserted: {inserted}, skipped: {skipped}")
    finally:
        conn.close()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Import workout sheet to PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no DB write")
    parser.add_argument("--dsn", default="dbname=workout_report",
                        help="PostgreSQL DSN (default: dbname=workout_report)")
    args = parser.parse_args()

    print("Fetching CSV from Google Sheets…")
    rows = fetch_csv()
    print(f"  {len(rows)} rows downloaded")

    print("Parsing session blocks…")
    sessions = parse_blocks(rows, base_year=2024)
    print(f"  {len(sessions)} sessions found\n")
    total_exercises = 0
    for s in sessions:
        total_exercises += len(s["exercises"])
        print(f"  {s['date']} ({s['dow']})  "
              f"exercises={len(s['exercises']):<3}  exp={s['total_exp']}")
    print(f"\n  Total: {len(sessions)} sessions, {total_exercises} exercise records")

    if args.dry_run:
        print("\n--dry-run: skipping database write")
        return

    print(f"\nImporting into PostgreSQL ({args.dsn})…")
    import_sessions(sessions, args.dsn)


if __name__ == "__main__":
    main()
