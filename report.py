#!/usr/bin/env python3
"""
Workout report tool.

Usage:
    python3 report.py sessions          # List all sessions
    python3 report.py exercise <name>   # 1RM progress for one exercise
    python3 report.py top               # Top exercises by latest 1RM
    python3 report.py summary           # Overall stats
"""

import argparse
import psycopg2
from psycopg2.extras import RealDictCursor


def connect(dsn: str):
    return psycopg2.connect(dsn, cursor_factory=RealDictCursor)


# ── Reports ──────────────────────────────────────────────────────────────────

def report_sessions(cur) -> None:
    cur.execute("""
        SELECT ws.session_date, ws.day_of_week, ws.start_time, ws.end_time,
               ws.rep_count, ws.total_exp,
               COUNT(se.id) AS exercise_count
        FROM workout_sessions ws
        LEFT JOIN session_exercises se ON se.session_id = ws.id
        GROUP BY ws.id
        ORDER BY ws.session_date
    """)
    rows = cur.fetchall()
    print(f"{'Date':<14}{'Day':<4}{'Time':<18}{'Reps':<6}{'Exp':>8}  {'Exercises':>10}")
    print("-" * 62)
    for r in rows:
        t = ""
        if r["start_time"] and r["end_time"]:
            t = f"{str(r['start_time'])[:5]}-{str(r['end_time'])[:5]}"
        print(f"{str(r['session_date']):<14}{r['day_of_week'] or '':<4}{t:<18}"
              f"{r['rep_count'] or 0:<6}{r['total_exp'] or 0:>8}  {r['exercise_count']:>10}")
    print(f"\nTotal: {len(rows)} sessions")


def report_exercise(cur, name: str) -> None:
    cur.execute("""
        SELECT ws.session_date, ws.day_of_week,
               se.one_rep_max, se.weight_setting, se.ratio_pct,
               se.set1_completed, se.set2_completed, se.set3_completed,
               se.exp_earned
        FROM session_exercises se
        JOIN workout_sessions ws ON ws.id = se.session_id
        JOIN exercises ex ON ex.id = se.exercise_id
        WHERE ex.name ILIKE %s AND se.exp_earned > 0
        ORDER BY ws.session_date
    """, (f"%{name}%",))
    rows = cur.fetchall()
    if not rows:
        print(f"No data found for: {name}")
        return
    print(f"\n{'Date':<14}{'1RM':>8}{'Setting':>10}{'Ratio':>8}  Sets       {'Exp':>8}")
    print("-" * 58)
    for r in rows:
        sets = "".join(
            ("O" if r[f"set{i}_completed"] else "X") for i in (1, 2, 3)
        )
        print(f"{str(r['session_date']):<14}"
              f"{r['one_rep_max'] or '-':>8}"
              f"{r['weight_setting'] or '-':>10}"
              f"{str(r['ratio_pct'] or '') + '%':>8}  {sets:<10}"
              f"{r['exp_earned'] or 0:>8}")


def report_top(cur) -> None:
    cur.execute("""
        SELECT ex.name,
               MAX(se.one_rep_max)       AS max_1rm,
               MAX(ws.session_date)      AS last_date,
               COUNT(DISTINCT ws.id)     AS sessions,
               SUM(se.exp_earned)        AS total_exp
        FROM session_exercises se
        JOIN exercises ex ON ex.id = se.exercise_id
        JOIN workout_sessions ws ON ws.id = se.session_id
        WHERE se.one_rep_max IS NOT NULL AND se.one_rep_max > 0
        GROUP BY ex.id, ex.name
        ORDER BY max_1rm DESC
    """)
    rows = cur.fetchall()
    print(f"\n{'Exercise':<24}{'Max 1RM':>10}{'Sessions':>10}{'Total Exp':>12}  Last date")
    print("-" * 70)
    for r in rows:
        print(f"{r['name']:<24}{r['max_1rm']:>10.1f}{r['sessions']:>10}"
              f"{r['total_exp'] or 0:>12}  {r['last_date']}")


def report_summary(cur) -> None:
    cur.execute("""
        SELECT COUNT(*)         AS sessions,
               SUM(total_exp)   AS total_exp,
               MIN(session_date)AS first,
               MAX(session_date)AS last
        FROM workout_sessions
    """)
    s = cur.fetchone()
    cur.execute("SELECT COUNT(*) AS cnt FROM exercises")
    ex_cnt = cur.fetchone()["cnt"]

    print(f"\n=== Workout Summary ===")
    print(f"Period      : {s['first']}  →  {s['last']}")
    print(f"Sessions    : {s['sessions']}")
    print(f"Total EXP   : {s['total_exp'] or 0:,}")
    print(f"Exercises   : {ex_cnt} unique")

    cur.execute("""
        SELECT ex.name, SUM(se.exp_earned) AS exp
        FROM session_exercises se
        JOIN exercises ex ON ex.id = se.exercise_id
        GROUP BY ex.name
        ORDER BY exp DESC
        LIMIT 5
    """)
    top = cur.fetchall()
    print(f"\nTop 5 by EXP:")
    for r in top:
        print(f"  {r['name']:<24} {r['exp'] or 0:>8,}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Workout report")
    parser.add_argument("command", choices=["sessions", "exercise", "top", "summary"])
    parser.add_argument("args", nargs="*")
    parser.add_argument("--dsn", default="dbname=workout_report")
    opts = parser.parse_args()

    conn = connect(opts.dsn)
    try:
        cur = conn.cursor()
        if opts.command == "sessions":
            report_sessions(cur)
        elif opts.command == "exercise":
            if not opts.args:
                parser.error("exercise requires a name argument")
            report_exercise(cur, " ".join(opts.args))
        elif opts.command == "top":
            report_top(cur)
        elif opts.command == "summary":
            report_summary(cur)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
