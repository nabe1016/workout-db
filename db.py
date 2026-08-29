"""Database access layer for workout_report."""

import os
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# Railway / production uses DATABASE_URL; local uses dbname shorthand
_DATABASE_URL = os.environ.get("DATABASE_URL", "dbname=workout_report")
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

_JST = datetime.timezone(datetime.timedelta(hours=9))

def _today() -> datetime.date:
    return datetime.datetime.now(_JST).date()

def _now_jst() -> datetime.datetime:
    return datetime.datetime.now(_JST)

DOW_MAP = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}


def _conn():
    return psycopg2.connect(_DATABASE_URL, cursor_factory=RealDictCursor)


def ensure_schema():
    """Add missing columns to existing tables without dropping data."""
    migrations = [
        # workout_sessions summary columns
        "ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS session_rpe INTEGER",
        "ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS duration_min INTEGER",
        "ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS session_load INTEGER",
        "ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS session_type TEXT",
        "ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS strength_volume_kg FLOAT",
        "ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS plyometric_contacts INTEGER",
        "ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS power_throws INTEGER",
        "ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS avg_quality FLOAT",
        "ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS post_notes TEXT",
        # session_exercises extra columns
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS load_mode TEXT DEFAULT 'high'",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS weight_low_load FLOAT",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS low_load_pct INTEGER",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS reps_low INTEGER",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS quality INTEGER",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS pain_flag BOOLEAN DEFAULT false",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS contacts INTEGER",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS throws INTEGER",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS skipped BOOLEAN DEFAULT false",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS sort_order INTEGER",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS bench_angle INTEGER",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS one_rep_max FLOAT",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS weight_setting FLOAT",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set1_completed BOOLEAN DEFAULT false",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set2_completed BOOLEAN DEFAULT false",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set3_completed BOOLEAN DEFAULT false",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set4_completed BOOLEAN DEFAULT false",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set5_completed BOOLEAN DEFAULT false",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set6_completed BOOLEAN DEFAULT false",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS exp_earned INTEGER DEFAULT 0",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS completed BOOLEAN DEFAULT false",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS stop_reason TEXT",
        # timestamp tracking
        "ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set1_at TIMESTAMP",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set2_at TIMESTAMP",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set3_at TIMESTAMP",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set4_at TIMESTAMP",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set5_at TIMESTAMP",
        "ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set6_at TIMESTAMP",
    ]
    with _conn() as conn:
        cur = conn.cursor()
        for sql in migrations:
            cur.execute(sql)


def date_to_dow(d) -> str:
    return DOW_MAP[d.weekday()]


# ── Sessions ─────────────────────────────────────────────────────────────────

def list_sessions() -> list:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ws.id, ws.session_date, ws.day_of_week,
                   ws.start_time, ws.end_time, ws.rep_count, ws.total_exp,
                   COUNT(se.id) AS exercise_count
            FROM workout_sessions ws
            LEFT JOIN session_exercises se ON se.session_id = ws.id
            GROUP BY ws.id
            ORDER BY ws.session_date DESC
        """)
        return cur.fetchall()


def get_session(session_id: int):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM workout_sessions WHERE id = %s", (session_id,))
        return cur.fetchone()


def get_session_with_exercises(session_id: int):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM workout_sessions WHERE id = %s", (session_id,))
        session = cur.fetchone()
        cur.execute("""
            SELECT se.*, ex.name AS exercise_name,
                   ex.body_part, ex.needs_bench, ex.primary_muscle,
                   ex.bodyweight_ratio, ex.is_time_based,
                   ex.lvup_high, ex.lvup_low,
                   COALESCE(ex.exercise_type, 'strength') AS exercise_type,
                   COALESCE(ex.measurement_type, 'reps')  AS measurement_type,
                   COALESCE(
                     se.one_rep_max,
                     ex.one_rep_max,
                     (SELECT se2.one_rep_max FROM session_exercises se2
                      WHERE se2.exercise_id = se.exercise_id
                        AND se2.one_rep_max IS NOT NULL
                      ORDER BY se2.id DESC LIMIT 1)
                   ) AS one_rep_max,
                   COALESCE(
                     se.weight_setting,
                     ROUND((COALESCE(
                       se.one_rep_max,
                       ex.one_rep_max,
                       (SELECT se2.one_rep_max FROM session_exercises se2
                        WHERE se2.exercise_id = se.exercise_id
                          AND se2.one_rep_max IS NOT NULL
                        ORDER BY se2.id DESC LIMIT 1)
                     ) * 0.8)::numeric, 1)
                   ) AS weight_setting
            FROM session_exercises se
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.session_id = %s
            ORDER BY COALESCE(se.completed, false), COALESCE(se.sort_order, 999), se.id
        """, (session_id,))
        exercises = cur.fetchall()
        return session, exercises


def create_session(session_date, start_time, end_time, rep_count) -> int:
    dow = date_to_dow(session_date)
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO workout_sessions (session_date, day_of_week, start_time, end_time, rep_count, total_exp)
            VALUES (%s, %s, %s, %s, %s, 0)
            RETURNING id
        """, (session_date, dow, start_time or None, end_time or None, rep_count or None))
        return cur.fetchone()["id"]


def update_session(session_id: int, session_date, start_time, end_time, rep_count) -> None:
    dow = date_to_dow(session_date)
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE workout_sessions
            SET session_date = %s, day_of_week = %s,
                start_time = %s, end_time = %s, rep_count = %s
            WHERE id = %s
        """, (session_date, dow, start_time or None, end_time or None, rep_count or None, session_id))
    recalculate_session_exp(session_id)


def delete_session(session_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM workout_sessions WHERE id = %s", (session_id,))


def recalculate_session_exp(session_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE workout_sessions
            SET total_exp = COALESCE(
                (SELECT SUM(exp_earned) FROM session_exercises WHERE session_id = %s), 0
            )
            WHERE id = %s
        """, (session_id, session_id))


# ── Session exercises ─────────────────────────────────────────────────────────

def get_session_exercise(se_id: int):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT se.*, ex.name AS exercise_name
            FROM session_exercises se
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.id = %s
        """, (se_id,))
        return cur.fetchone()


def _next_sort_order(cur, session_id: int) -> int:
    cur.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_sort FROM session_exercises WHERE session_id = %s",
        (session_id,)
    )
    return cur.fetchone()["next_sort"]


def create_session_exercise(session_id, exercise_id, one_rep_max,
                             weight_setting, weight_low_load, reps,
                             set1, set2, set3, exp_earned, muscle_groups) -> int:
    weight_pct80 = round(float(one_rep_max) * 0.8, 1) if one_rep_max else None
    if not weight_low_load and one_rep_max:
        weight_low_load = round(float(one_rep_max) * 0.30, 1)
    ratio_pct = (round(float(weight_setting) / float(one_rep_max) * 100, 1)
                 if weight_setting and one_rep_max else None)
    with _conn() as conn:
        cur = conn.cursor()
        sort_order = _next_sort_order(cur, session_id)
        cur.execute("""
            INSERT INTO session_exercises
                (session_id, exercise_id, sort_order,
                 one_rep_max, weight_pct80, weight_setting, weight_low_load, reps,
                 ratio_pct, set1_completed, set2_completed, set3_completed,
                 exp_earned, muscle_groups)
            VALUES (%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s)
            ON CONFLICT (session_id, exercise_id) DO UPDATE
                SET sort_order=%s, one_rep_max=%s, weight_pct80=%s,
                    weight_setting=%s, weight_low_load=%s, reps=%s,
                    ratio_pct=%s, set1_completed=%s, set2_completed=%s,
                    set3_completed=%s, exp_earned=%s, muscle_groups=%s
            RETURNING id
        """, (
            session_id, exercise_id, sort_order,
            one_rep_max, weight_pct80, weight_setting, weight_low_load or None, reps or None,
            ratio_pct, set1, set2, set3,
            exp_earned or 0, muscle_groups or None,
            # ON CONFLICT values
            sort_order, one_rep_max, weight_pct80,
            weight_setting, weight_low_load or None, reps or None,
            ratio_pct, set1, set2, set3,
            exp_earned or 0, muscle_groups or None,
        ))
        new_id = cur.fetchone()["id"]
    recalculate_session_exp(session_id)
    return new_id


def update_session_exercise(se_id, session_id, exercise_id, one_rep_max,
                             weight_setting, weight_low_load, reps,
                             set1, set2, set3, exp_earned, muscle_groups) -> None:
    weight_pct80 = round(float(one_rep_max) * 0.8, 1) if one_rep_max else None
    ratio_pct = (round(float(weight_setting) / float(one_rep_max) * 100, 1)
                 if weight_setting and one_rep_max else None)
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE session_exercises
            SET exercise_id=%s, one_rep_max=%s, weight_pct80=%s,
                weight_setting=%s, weight_low_load=%s, reps=%s,
                ratio_pct=%s, set1_completed=%s, set2_completed=%s,
                set3_completed=%s, exp_earned=%s, muscle_groups=%s
            WHERE id=%s
        """, (
            exercise_id, one_rep_max, weight_pct80,
            weight_setting, weight_low_load or None, reps or None,
            ratio_pct, set1, set2, set3,
            exp_earned or 0, muscle_groups or None,
            se_id,
        ))
    recalculate_session_exp(session_id)


def delete_session_exercise(se_id: int, session_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM session_exercises WHERE id = %s", (se_id,))
    recalculate_session_exp(session_id)


def bulk_delete_session_exercises(session_id: int, se_ids: list) -> None:
    if not se_ids:
        return
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM session_exercises WHERE session_id = %s AND id = ANY(%s)",
            (session_id, se_ids)
        )
    recalculate_session_exp(session_id)


def toggle_skip_exercise(se_id: int) -> dict:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE session_exercises
            SET skipped = NOT COALESCE(skipped, false)
            WHERE id = %s
            RETURNING skipped
        """, (se_id,))
        row = cur.fetchone()
    return {"skipped": bool(row["skipped"])}


def toggle_complete_exercise(se_id: int) -> dict:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE session_exercises
            SET completed = NOT COALESCE(completed, false),
                completed_at = CASE WHEN NOT COALESCE(completed, false) THEN NOW() ELSE NULL END
            WHERE id = %s
            RETURNING completed, completed_at
        """, (se_id,))
        row = cur.fetchone()
    return {"completed": bool(row["completed"])}


def record_session_start(session_id: int) -> dict:
    """Record the moment the user presses the Start button (first press only)."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE workout_sessions
            SET started_at = COALESCE(started_at, NOW())
            WHERE id = %s
            RETURNING started_at
        """, (session_id,))
        row = cur.fetchone()
    return {"started_at": row["started_at"].isoformat() if row else None}


_MISSING = object()


def quick_edit_se(se_id: int, one_rep_max=None, reps=None,
                  low_load_pct=None, load_mode=None,
                  bench_angle=_MISSING) -> dict | None:
    """Inline update of 1RM / reps / low_load_pct / load_mode / bench_angle. Recalculates weights and EXP."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT se.*, ex.bodyweight_ratio
            FROM session_exercises se
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.id = %s
        """, (se_id,))
        se = cur.fetchone()
        if se is None:
            return None

        new_orm  = one_rep_max if one_rep_max is not None else se["one_rep_max"]
        new_pct  = float(low_load_pct) if low_load_pct is not None \
                   else float(se.get("low_load_pct") or 50)
        new_mode = load_mode if load_mode is not None else (se.get("load_mode") or "high")

        # Keep high/low reps separately; update only the active mode's reps
        stored_reps_high = se.get("reps")     or 8
        stored_reps_low  = se.get("reps_low") or 20
        if reps is not None:
            if new_mode == "low":
                new_reps_high = stored_reps_high
                new_reps_low  = int(reps)
            else:
                new_reps_high = int(reps)
                new_reps_low  = stored_reps_low
        else:
            new_reps_high = stored_reps_high
            new_reps_low  = stored_reps_low
        display_reps = new_reps_low if new_mode == "low" else new_reps_high

        bw_ratio = se.get("bodyweight_ratio")
        if new_orm:
            # Explicit 1RM always takes priority over bodyweight ratio
            new_ws = round(float(new_orm) * 0.8, 1)
            new_wl = round(float(new_orm) * new_pct / 100, 1)
        elif bw_ratio:
            bw_row = get_latest_weight()
            body_weight = float(bw_row["weight_kg"]) if bw_row else 65.0
            eff_weight = round(body_weight * bw_ratio, 1)
            new_ws = eff_weight
            new_wl = eff_weight
        else:
            new_ws = se["weight_setting"]
            new_wl = se["weight_low_load"]

        completions = {i: bool(se.get(f"set{i}_completed")) for i in range(1, 11)}
        completed_count = sum(1 for v in completions.values() if v)
        w = (new_wl if new_mode == "low" else new_ws) or (new_wl or new_ws)
        exp = round((w or 1) * display_reps * completed_count)

        cur.execute("""
            UPDATE session_exercises
            SET one_rep_max=%s, weight_pct80=%s, weight_setting=%s, weight_low_load=%s,
                reps=%s, reps_low=%s, load_mode=%s, low_load_pct=%s, exp_earned=%s
            WHERE id = %s
        """, (new_orm, new_ws, new_ws, new_wl,
              new_reps_high, new_reps_low, new_mode, new_pct, exp, se_id))
        if bench_angle is not _MISSING:
            cur.execute("UPDATE session_exercises SET bench_angle=%s WHERE id=%s",
                        (bench_angle, se_id))
        session_id = se["session_id"]

    recalculate_session_exp(session_id)
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT total_exp FROM workout_sessions WHERE id = %s", (session_id,))
        total = cur.fetchone()["total_exp"]

    result = {
        "one_rep_max":       new_orm,
        "weight_setting":    new_ws,
        "weight_low_load":   new_wl,
        "reps":              display_reps,
        "reps_high":         new_reps_high,
        "reps_low":          new_reps_low,
        "load_mode":         new_mode,
        "low_load_pct":      new_pct,
        "exp_earned":        exp,
        "session_total_exp": total,
    }
    if bench_angle is not _MISSING:
        result["bench_angle"] = bench_angle
    return result


# ── Exercises master ──────────────────────────────────────────────────────────

# ── Muscles master ───────────────────────────────────────────────────────────

def list_muscles() -> list:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, sort_order FROM muscles ORDER BY sort_order, name")
        return cur.fetchall()


def create_muscle(name: str) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO muscles (name) VALUES (%s) ON CONFLICT DO NOTHING",
            (name.strip(),)
        )


def update_muscle(muscle_id: int, name: str) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE muscles SET name = %s WHERE id = %s",
            (name.strip(), muscle_id)
        )


def delete_muscle(muscle_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM muscles WHERE id = %s", (muscle_id,))


def list_exercises() -> list:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, body_part, needs_bench, primary_muscle
            FROM exercises ORDER BY name
        """)
        return cur.fetchall()


def list_exercises_by_location(location: str) -> list:
    """Returns exercises filtered by my_set location ('gym' or 'home')."""
    with _conn() as conn:
        cur = conn.cursor()
        if location == 'home':
            cur.execute("""
                SELECT id, name, body_part, needs_bench, primary_muscle
                FROM exercises
                WHERE COALESCE(location, 'gym') IN ('home', 'both')
                ORDER BY name
            """)
        else:
            cur.execute("""
                SELECT id, name, body_part, needs_bench, primary_muscle
                FROM exercises
                WHERE COALESCE(location, 'gym') IN ('gym', 'both')
                ORDER BY name
            """)
        return cur.fetchall()


def list_exercises_with_latest_data() -> list:
    """All exercises with master data + fallback from latest session logs. Derived cols computed in Python."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                e.id, e.name, e.body_part, e.needs_bench, e.primary_muscle,
                e.one_rep_max    AS stored_orm,
                e.reps           AS stored_reps,
                e.weight_low_load AS stored_wll,
                e.reps_low       AS stored_reps_low,
                COALESCE(e.one_rep_max,     orm_log.one_rep_max)   AS one_rep_max,
                COALESCE(e.reps,            reps_log.reps)         AS eff_reps,
                COALESCE(e.weight_low_load, wll_log.weight_low_load) AS eff_wll
            FROM exercises e
            LEFT JOIN LATERAL (
                SELECT se.one_rep_max FROM session_exercises se
                JOIN workout_sessions ws ON ws.id = se.session_id
                WHERE se.exercise_id = e.id AND se.one_rep_max IS NOT NULL
                ORDER BY ws.session_date DESC LIMIT 1
            ) orm_log ON true
            LEFT JOIN LATERAL (
                SELECT se.reps FROM session_exercises se
                JOIN workout_sessions ws ON ws.id = se.session_id
                WHERE se.exercise_id = e.id AND se.reps IS NOT NULL
                ORDER BY ws.session_date DESC LIMIT 1
            ) reps_log ON true
            LEFT JOIN LATERAL (
                SELECT se.weight_low_load FROM session_exercises se
                JOIN workout_sessions ws ON ws.id = se.session_id
                WHERE se.exercise_id = e.id AND se.weight_low_load IS NOT NULL
                ORDER BY ws.session_date DESC LIMIT 1
            ) wll_log ON true
            ORDER BY e.body_part NULLS LAST, e.name
        """)
        rows = cur.fetchall()

    result = []
    for row in rows:
        r = dict(row)
        orm = r['one_rep_max']
        r['high_load_weight'] = round(orm * 0.8, 1) if orm else None
        r['high_load_reps']   = r['eff_reps'] or 8
        wll = r['eff_wll']
        r['low_load_weight']  = wll if wll else (round(orm * 0.5, 1) if orm else None)
        r['low_load_reps']    = r['stored_reps_low'] or 20
        r['has_log_data']     = orm is not None
        result.append(r)
    return result


def get_exercise(exercise_id: int):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, body_part, needs_bench, primary_muscle,
                   one_rep_max, reps, weight_low_load, reps_low
            FROM exercises WHERE id = %s
        """, (exercise_id,))
        return cur.fetchone()


def update_exercise_meta(exercise_id: int, body_part, needs_bench: bool, primary_muscle) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE exercises
            SET body_part = %s, needs_bench = %s, primary_muscle = %s
            WHERE id = %s
        """, (body_part or None, bool(needs_bench), primary_muscle or None, exercise_id))


def update_exercise_full(exercise_id: int, body_part, needs_bench: bool, primary_muscle,
                          one_rep_max, reps, weight_low_load, reps_low) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE exercises
            SET body_part=%s, needs_bench=%s, primary_muscle=%s,
                one_rep_max=%s, reps=%s, weight_low_load=%s, reps_low=%s
            WHERE id=%s
        """, (body_part or None, bool(needs_bench), primary_muscle or None,
              one_rep_max, reps, weight_low_load, reps_low, exercise_id))


def update_exercise_one_rep_max(exercise_id: int, one_rep_max: float) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE exercises SET one_rep_max = %s WHERE id = %s",
                    (one_rep_max, exercise_id))


def delete_exercise(exercise_id: int):
    """
    Returns error message if exercise has completed sets.
    If only registered (never performed), deletes all related records then the exercise.
    """
    with _conn() as conn:
        cur = conn.cursor()
        # 1セットでも完了している = 削除不可
        cur.execute("""
            SELECT COUNT(*) AS n FROM session_exercises
            WHERE exercise_id = %s
            AND (
                COALESCE(set1_completed, false) OR
                COALESCE(set2_completed, false) OR
                COALESCE(set3_completed, false) OR
                COALESCE(completed, false) OR
                COALESCE(exp_earned, 0) > 0
            )
        """, (exercise_id,))
        completed_count = cur.fetchone()["n"]
        if completed_count > 0:
            return f"このメニューは {completed_count} 回トレーニング実施済みのため削除できません"
        # 登録はあるが未実施の場合は関連レコードごと削除
        cur.execute("DELETE FROM session_exercises WHERE exercise_id = %s", (exercise_id,))
        cur.execute("DELETE FROM my_set_exercises WHERE exercise_id = %s", (exercise_id,))
        cur.execute("DELETE FROM exercises WHERE id = %s", (exercise_id,))
        return None


def find_duplicate_exercise_groups() -> list:
    """NFKC正規化で同一名とみなせる種目グループを返す（各グループはdict のlist）。"""
    import unicodedata
    from collections import defaultdict
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.id, e.name, e.body_part, e.needs_bench, e.primary_muscle, e.one_rep_max,
                   COUNT(se.id) AS session_count,
                   SUM(CASE WHEN COALESCE(se.exp_earned, 0) > 0 THEN 1 ELSE 0 END) AS completed_count
            FROM exercises e
            LEFT JOIN session_exercises se ON se.exercise_id = e.id
            GROUP BY e.id
            ORDER BY e.name
        """)
        exercises = cur.fetchall()

    groups = defaultdict(list)
    for ex in exercises:
        norm = unicodedata.normalize('NFKC', ex['name']).strip()
        groups[norm].append(dict(ex))
    return [g for g in groups.values() if len(g) > 1]


def auto_merge_duplicate_exercises() -> list:
    """重複種目を自動統合し、(kept_name, deleted_name) のリストを返す。"""
    import unicodedata
    from collections import defaultdict

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.id, e.name, e.body_part, e.needs_bench, e.primary_muscle, e.one_rep_max,
                   COUNT(se.id) AS session_count,
                   COALESCE(SUM(CASE WHEN COALESCE(se.exp_earned,0) > 0 THEN 1 ELSE 0 END), 0) AS completed_count
            FROM exercises e
            LEFT JOIN session_exercises se ON se.exercise_id = e.id
            GROUP BY e.id
        """)
        exercises = cur.fetchall()

        groups = defaultdict(list)
        for ex in exercises:
            norm = unicodedata.normalize('NFKC', ex['name']).strip()
            groups[norm].append(dict(ex))

        merged = []
        for norm, group in groups.items():
            if len(group) <= 1:
                continue
            # 実施回数・セッション数・1RMが多い方を残す
            sorted_group = sorted(
                group,
                key=lambda x: (x['completed_count'] or 0, x['session_count'] or 0, x['one_rep_max'] or 0),
                reverse=True,
            )
            keep = sorted_group[0]
            keep_id = keep['id']

            for delete in sorted_group[1:]:
                delete_id = delete['id']

                # session_exercises: 両方に同一セッションがある場合は delete 側を削除
                cur.execute("""
                    DELETE FROM session_exercises
                    WHERE exercise_id = %s
                    AND session_id IN (
                        SELECT session_id FROM session_exercises WHERE exercise_id = %s
                    )
                """, (delete_id, keep_id))
                cur.execute(
                    "UPDATE session_exercises SET exercise_id = %s WHERE exercise_id = %s",
                    (keep_id, delete_id)
                )

                # my_set_exercises: 同様に重複を解消してから移行
                cur.execute("""
                    DELETE FROM my_set_exercises
                    WHERE exercise_id = %s
                    AND my_set_id IN (
                        SELECT my_set_id FROM my_set_exercises WHERE exercise_id = %s
                    )
                """, (delete_id, keep_id))
                cur.execute(
                    "UPDATE my_set_exercises SET exercise_id = %s WHERE exercise_id = %s",
                    (keep_id, delete_id)
                )

                # keep 側に body_part 等が無く delete 側にある場合はコピー
                if not keep.get('body_part') and delete.get('body_part'):
                    cur.execute("""
                        UPDATE exercises
                        SET body_part=%s, needs_bench=%s, primary_muscle=%s
                        WHERE id=%s
                    """, (delete['body_part'], delete['needs_bench'], delete['primary_muscle'], keep_id))
                    keep['body_part'] = delete['body_part']

                # 名前を正規化済みの名前に統一
                cur.execute("UPDATE exercises SET name=%s WHERE id=%s", (norm, keep_id))

                cur.execute("DELETE FROM exercises WHERE id=%s", (delete_id,))
                merged.append((keep['name'], delete['name']))

        return merged


def bulk_update_exercise_meta(updates: list) -> None:
    """updates: list of {exercise_id, body_part, needs_bench, primary_muscle}"""
    with _conn() as conn:
        cur = conn.cursor()
        for u in updates:
            cur.execute("""
                UPDATE exercises
                SET body_part = %s, needs_bench = %s, primary_muscle = %s
                WHERE id = %s
            """, (u["body_part"] or None, bool(u["needs_bench"]),
                  u["primary_muscle"] or None, u["exercise_id"]))


# ── My Sets ───────────────────────────────────────────────────────────────────

def list_my_sets() -> list:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ms.id, ms.name, ms.description, ms.location,
                   ms.program_name, ms.session_type,
                   COUNT(mse.id) AS exercise_count
            FROM my_sets ms
            LEFT JOIN my_set_exercises mse ON mse.my_set_id = ms.id
            GROUP BY ms.id
            ORDER BY ms.program_name NULLS LAST, ms.name
        """)
        return cur.fetchall()


def get_my_set(my_set_id: int):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM my_sets WHERE id = %s", (my_set_id,))
        return cur.fetchone()


def get_my_set_with_exercises(my_set_id: int):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM my_sets WHERE id = %s", (my_set_id,))
        my_set = cur.fetchone()
        cur.execute("""
            SELECT mse.*, ex.name AS exercise_name,
                   ex.body_part, ex.needs_bench, ex.primary_muscle,
                   ex.bodyweight_ratio, ex.lvup_high, ex.lvup_low
            FROM my_set_exercises mse
            JOIN exercises ex ON ex.id = mse.exercise_id
            WHERE mse.my_set_id = %s
            ORDER BY COALESCE(mse.sort_order, 999), mse.id
        """, (my_set_id,))
        exercises = cur.fetchall()
        return my_set, exercises


def quick_edit_mse(mse_id: int, target_sets=None, reps=None,
                   one_rep_max=None, low_load_pct=None,
                   body_weight: float = 65.0) -> dict:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT mse.*, ex.body_part, ex.bodyweight_ratio
            FROM my_set_exercises mse
            JOIN exercises ex ON ex.id = mse.exercise_id
            WHERE mse.id = %s
        """, (mse_id,))
        mse = cur.fetchone()
        if not mse:
            return {}
        mse = dict(mse)

        new_sets = int(target_sets) if target_sets is not None else (mse.get('target_sets') or 3)
        new_reps = int(reps)       if reps       is not None else (mse.get('reps') or 10)
        new_orm  = float(one_rep_max) if one_rep_max is not None else mse.get('one_rep_max')
        new_pct  = float(low_load_pct) if low_load_pct is not None else float(mse.get('low_load_pct') or 30)
        new_sets = max(1, new_sets)
        new_reps = max(1, new_reps)

        new_ws = mse.get('weight_setting')
        new_wl = mse.get('weight_low_load')
        if new_orm:
            new_ws = round(float(new_orm) * 0.8, 1)
            new_wl = round(float(new_orm) * new_pct / 100, 1)

        cur.execute("""
            UPDATE my_set_exercises
            SET target_sets=%s, reps=%s, one_rep_max=%s,
                weight_setting=%s, weight_low_load=%s, low_load_pct=%s
            WHERE id=%s
        """, (new_sets, new_reps, new_orm, new_ws, new_wl, new_pct, mse_id))

        bw_ratio = mse.get('bodyweight_ratio')
        weight = (body_weight * bw_ratio) if bw_ratio else (new_ws or 0)
        exp = round(weight * new_reps * new_sets)

        return {
            'id':            mse_id,
            'target_sets':   new_sets,
            'reps':          new_reps,
            'one_rep_max':   new_orm,
            'weight_setting': new_ws,
            'weight_low_load': new_wl,
            'low_load_pct':  new_pct,
            'exp':           exp,
            'body_part':     mse.get('body_part'),
        }


_HOME_PRESET = [
    # (name, reps, target_sets, muscle_groups)
    ("アブローラー",            8,  3, "腹直筋,腸腰筋"),
    ("プッシュアップバー",     10,  3, "大胸筋,上腕三頭筋,三角筋前部"),
    ("ブルガリアンスクワット",  8,  2, "大臀筋,大腿四頭筋,中臀筋"),
    ("片脚カーフレイズ",       20,  2, "カーフ,腓腹筋,ヒラメ筋"),
    ("ベンチレッグレイズ",     10,  2, "腹直筋,腸腰筋"),
]


def find_my_set_by_name(name: str):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM my_sets WHERE name = %s", (name,))
        return cur.fetchone()


def create_my_set(name: str, description: str, location: str = 'gym', purpose: str = None) -> int:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO my_sets (name, description, location, purpose) VALUES (%s, %s, %s, %s) RETURNING id",
            (name, description or None, location, purpose or None)
        )
        return cur.fetchone()["id"]


def seed_home_preset_exercises(my_set_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE my_sets SET purpose='自宅メンテナンス' WHERE id=%s",
            (my_set_id,)
        )
        for i, (name, reps, target_sets, muscle_groups) in enumerate(_HOME_PRESET, 1):
            cur.execute("SELECT id FROM exercises WHERE name = %s", (name,))
            ex = cur.fetchone()
            if ex is None:
                continue
            cur.execute("""
                INSERT INTO my_set_exercises
                    (my_set_id, exercise_id, sort_order, reps, target_sets, muscle_groups)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (my_set_id, exercise_id) DO NOTHING
            """, (my_set_id, ex["id"], i, reps, target_sets, muscle_groups))


def update_my_set(my_set_id: int, name: str, description: str) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE my_sets SET name=%s, description=%s WHERE id=%s",
            (name, description or None, my_set_id)
        )


def delete_my_set(my_set_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM my_sets WHERE id = %s", (my_set_id,))


def _mse_next_sort(cur, my_set_id: int) -> int:
    cur.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_sort FROM my_set_exercises WHERE my_set_id = %s",
        (my_set_id,)
    )
    return cur.fetchone()["next_sort"]


def get_exercise_quick_data(exercise_id: int):
    """種目マスタデータ（ログフォールバック付き）＋直近3回の実施ログを返す。"""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                e.id, e.name, e.body_part, e.primary_muscle, e.needs_bench,
                COALESCE(e.one_rep_max, orm_log.one_rep_max) AS one_rep_max,
                COALESCE(e.reps,        reps_log.reps)       AS reps,
                COALESCE(e.weight_low_load, wll_log.weight_low_load) AS weight_low_load,
                e.reps_low
            FROM exercises e
            LEFT JOIN LATERAL (
                SELECT se.one_rep_max FROM session_exercises se
                JOIN workout_sessions ws ON ws.id = se.session_id
                WHERE se.exercise_id = e.id AND se.one_rep_max IS NOT NULL
                ORDER BY ws.session_date DESC LIMIT 1
            ) orm_log ON true
            LEFT JOIN LATERAL (
                SELECT se.reps FROM session_exercises se
                JOIN workout_sessions ws ON ws.id = se.session_id
                WHERE se.exercise_id = e.id AND se.reps IS NOT NULL
                ORDER BY ws.session_date DESC LIMIT 1
            ) reps_log ON true
            LEFT JOIN LATERAL (
                SELECT se.weight_low_load FROM session_exercises se
                JOIN workout_sessions ws ON ws.id = se.session_id
                WHERE se.exercise_id = e.id AND se.weight_low_load IS NOT NULL
                ORDER BY ws.session_date DESC LIMIT 1
            ) wll_log ON true
            WHERE e.id = %s
        """, (exercise_id,))
        ex = cur.fetchone()
        if not ex:
            return None
        ex = dict(ex)
        orm = ex['one_rep_max']
        ex['high_load_weight'] = round(orm * 0.8, 1) if orm else None
        ex['high_load_reps']   = ex['reps'] or 8
        wll = ex['weight_low_load']
        ex['low_load_weight']  = wll if wll else (round(orm * 0.5, 1) if orm else None)
        ex['low_load_reps']    = ex['reps_low'] or 20

        cur.execute("""
            SELECT ws.session_date, se.load_mode,
                   se.weight_setting, se.weight_low_load, se.reps, se.one_rep_max,
                   (COALESCE(se.set1_completed::int,0) +
                    COALESCE(se.set2_completed::int,0) +
                    COALESCE(se.set3_completed::int,0)) AS sets_done
            FROM session_exercises se
            JOIN workout_sessions ws ON ws.id = se.session_id
            WHERE se.exercise_id = %s
              AND (COALESCE(se.exp_earned,0) > 0
                   OR COALESCE(se.set1_completed,false)
                   OR COALESCE(se.set2_completed,false)
                   OR COALESCE(se.set3_completed,false))
            ORDER BY ws.session_date DESC
            LIMIT 3
        """, (exercise_id,))
        sessions = []
        for s in cur.fetchall():
            s = dict(s)
            s['session_date'] = str(s['session_date'])
            s['load_mode'] = s['load_mode'] or 'high'
            s['weight'] = (s['weight_setting'] if s['load_mode'] == 'high'
                           else s['weight_low_load'])
            sessions.append(s)

    return {'exercise': ex, 'recent_sessions': sessions}


def create_my_set_exercise(my_set_id, exercise_id, one_rep_max,
                            weight_setting, weight_low_load, reps, reps_low,
                            muscle_groups) -> int:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM my_set_exercises WHERE my_set_id = %s AND exercise_id = %s",
            (my_set_id, exercise_id)
        )
        existing = cur.fetchone()
        if existing:
            cur.execute("""
                UPDATE my_set_exercises
                SET one_rep_max=%s, weight_setting=%s,
                    weight_low_load=%s, reps=%s, reps_low=%s, muscle_groups=%s
                WHERE id=%s
                RETURNING id
            """, (
                one_rep_max, weight_setting,
                weight_low_load or None, reps or None, reps_low or None,
                muscle_groups or None, existing["id"]
            ))
        else:
            sort_order = _mse_next_sort(cur, my_set_id)
            cur.execute("""
                INSERT INTO my_set_exercises
                    (my_set_id, exercise_id, sort_order,
                     one_rep_max, weight_setting, weight_low_load, reps, reps_low, muscle_groups)
                VALUES (%s,%s,%s, %s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (
                my_set_id, exercise_id, sort_order,
                one_rep_max, weight_setting, weight_low_load or None,
                reps or None, reps_low or None, muscle_groups or None
            ))
        return cur.fetchone()["id"]


def update_my_set_exercise(mse_id, exercise_id, one_rep_max,
                            weight_setting, weight_low_load, reps, reps_low,
                            muscle_groups) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE my_set_exercises
            SET exercise_id=%s, one_rep_max=%s, weight_setting=%s,
                weight_low_load=%s, reps=%s, reps_low=%s, muscle_groups=%s
            WHERE id=%s
        """, (exercise_id, one_rep_max, weight_setting,
              weight_low_load or None, reps or None, reps_low or None,
              muscle_groups or None, mse_id))


def delete_my_set_exercise(mse_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM my_set_exercises WHERE id = %s", (mse_id,))


def bulk_delete_my_set_exercises(my_set_id: int, mse_ids: list) -> None:
    if not mse_ids:
        return
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM my_set_exercises WHERE my_set_id = %s AND id = ANY(%s)",
            (my_set_id, mse_ids)
        )


def reorder_my_set_exercises(my_set_id: int, ordered_ids: list) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        for i, mse_id in enumerate(ordered_ids, 1):
            cur.execute(
                "UPDATE my_set_exercises SET sort_order=%s WHERE id=%s AND my_set_id=%s",
                (i, mse_id, my_set_id)
            )


def reorder_session_exercises(session_id: int, ordered_ids: list) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        for i, se_id in enumerate(ordered_ids, 1):
            cur.execute(
                "UPDATE session_exercises SET sort_order=%s WHERE id=%s AND session_id=%s",
                (i, se_id, session_id)
            )


def copy_session_to_my_set(session_id: int, my_set_id: int) -> int:
    """Import all exercises from a session into a my-set (replaces existing exercises)."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT se.*, ex.name
            FROM session_exercises se
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.session_id = %s
            ORDER BY COALESCE(se.sort_order, 999), se.id
        """, (session_id,))
        exercises = cur.fetchall()

        cur.execute("DELETE FROM my_set_exercises WHERE my_set_id = %s", (my_set_id,))

        for i, ex in enumerate(exercises, 1):
            cur.execute("""
                INSERT INTO my_set_exercises
                    (my_set_id, exercise_id, sort_order,
                     one_rep_max, weight_setting, weight_low_load, reps, muscle_groups)
                VALUES (%s,%s,%s, %s,%s,%s,%s,%s)
            """, (
                my_set_id, ex["exercise_id"], i,
                ex["one_rep_max"], ex["weight_setting"],
                ex["weight_low_load"], ex["reps"], ex["muscle_groups"],
            ))

        return len(exercises)


def copy_my_set_to_session(my_set_id: int, session_id: int) -> int:
    """Apply a my-set preset to a session. Clears existing exercises first."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT mse.*, ex.name
            FROM my_set_exercises mse
            JOIN exercises ex ON ex.id = mse.exercise_id
            WHERE mse.my_set_id = %s
            ORDER BY COALESCE(mse.sort_order, 999), mse.id
        """, (my_set_id,))
        exercises = cur.fetchall()

        cur.execute("DELETE FROM session_exercises WHERE session_id = %s", (session_id,))

        for i, ex in enumerate(exercises, 1):
            weight_pct80 = round(float(ex["one_rep_max"]) * 0.8, 1) if ex["one_rep_max"] else None
            ratio_pct = (round(float(ex["weight_setting"]) / float(ex["one_rep_max"]) * 100, 1)
                         if ex["weight_setting"] and ex["one_rep_max"] else None)
            low_pct = float(ex.get("low_load_pct") or 50)
            new_wl = ex["weight_low_load"]
            if ex["one_rep_max"] and not new_wl:
                new_wl = round(float(ex["one_rep_max"]) * low_pct / 100, 1)
            cur.execute("""
                INSERT INTO session_exercises
                    (session_id, exercise_id, sort_order,
                     one_rep_max, weight_pct80, weight_setting, weight_low_load,
                     reps, reps_low, low_load_pct,
                     ratio_pct, set1_completed, set2_completed, set3_completed,
                     exp_earned, muscle_groups)
                VALUES (%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s, %s,%s)
            """, (
                session_id, ex["exercise_id"], i,
                ex["one_rep_max"], weight_pct80, ex["weight_setting"], new_wl,
                ex.get("reps") or 8, ex.get("reps_low") or 20, low_pct,
                ratio_pct, False, False, False, 0, ex["muscle_groups"],
            ))

        count = len(exercises)
    recalculate_session_exp(session_id)
    return count


# ── Inline set toggle ─────────────────────────────────────────────────────────

def toggle_set_completion(se_id: int, set_num: int) -> dict:
    """Toggle one set for a session_exercise. Returns updated state dict."""
    col = f"set{set_num}_completed"
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT se.*, ws.rep_count AS session_rep_count,
                   ex.bodyweight_ratio
            FROM session_exercises se
            JOIN workout_sessions ws ON ws.id = se.session_id
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.id = %s
        """, (se_id,))
        se = cur.fetchone()
        if se is None:
            return None

        new_val = not bool(se[col])
        completions = {i: bool(se.get(f"set{i}_completed")) for i in range(1, 11)}
        completions[set_num] = new_val
        completed_count = sum(1 for v in completions.values() if v)

        mode = se.get("load_mode") or "high"
        bw_ratio = se.get("bodyweight_ratio")
        orm = se.get("one_rep_max")
        if orm:
            # Explicit 1RM takes priority: use stored weight_setting/weight_low_load
            if mode == "low":
                weight = se["weight_low_load"] or se["weight_setting"]
            else:
                weight = se["weight_setting"] or se["weight_low_load"]
        elif bw_ratio:
            bw_row = get_latest_weight()
            body_weight = float(bw_row["weight_kg"]) if bw_row else 65.0
            weight = round(body_weight * bw_ratio, 1)
        elif mode == "low":
            weight = se["weight_low_load"] if se["weight_low_load"] else se["weight_setting"]
        else:
            weight = se["weight_setting"] if se["weight_setting"] else se["weight_low_load"]
        default_reps = 25 if mode == "low" else 10
        reps = se["reps"] or se["session_rep_count"] or default_reps
        exp = round((weight or 1) * reps * completed_count)

        # Check progressive overload criteria
        reps_val = se.get("reps") or 0
        exercise_id = se["exercise_id"]
        lvup_high_achieved = False
        lvup_low_achieved  = False
        if new_val:
            if mode == "high" and reps_val >= 12 and completed_count >= 3:
                lvup_high_achieved = True
                cur.execute("UPDATE exercises SET lvup_high = TRUE WHERE id = %s", (exercise_id,))
            elif mode == "low" and reps_val >= 40 and completed_count >= 3:
                lvup_low_achieved = True
                cur.execute("UPDATE exercises SET lvup_low = TRUE WHERE id = %s", (exercise_id,))

        at_col = f"set{set_num}_at"
        if new_val:
            cur.execute(f"""
                UPDATE session_exercises
                SET {col} = %s, {at_col} = NOW(), exp_earned = %s
                WHERE id = %s
            """, (new_val, exp, se_id))
        else:
            cur.execute(f"""
                UPDATE session_exercises
                SET {col} = %s, {at_col} = NULL, exp_earned = %s
                WHERE id = %s
            """, (new_val, exp, se_id))

        session_id = se["session_id"]

    recalculate_session_exp(session_id)

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT total_exp FROM workout_sessions WHERE id = %s", (session_id,))
        total = cur.fetchone()["total_exp"]
        cur.execute("""
            SELECT ex.body_part, COALESCE(SUM(se.exp_earned), 0) AS cat_exp
            FROM session_exercises se
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.session_id = %s
            GROUP BY ex.body_part
        """, (session_id,))
        category_exp = {"上肢": 0, "下肢": 0, "体幹": 0}
        for row in cur.fetchall():
            if row["body_part"] in category_exp:
                category_exp[row["body_part"]] = int(row["cat_exp"])

    return {
        "set_num": set_num,
        "completed": new_val,
        "exp_earned": exp,
        "session_total_exp": total,
        "category_exp": category_exp,
        "lvup_high": lvup_high_achieved,
        "lvup_low":  lvup_low_achieved,
        "exercise_id": exercise_id,
    }


def clear_lvup(exercise_id: int, lvup_type: str) -> None:
    """Clear the lvup_high or lvup_low flag on an exercise."""
    col = "lvup_high" if lvup_type == "high" else "lvup_low"
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE exercises SET {col} = FALSE WHERE id = %s", (exercise_id,))


def get_recent_sessions_for_copy(exclude_session_id: int = None, limit: int = 2) -> list:
    """Return the last N sessions (with exercise list) excluding the given session."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ws.id, ws.session_date, ws.day_of_week,
                   ws.start_time, ws.end_time, ws.rep_count,
                   COUNT(se.id) AS exercise_count
            FROM workout_sessions ws
            LEFT JOIN session_exercises se ON se.session_id = ws.id
            WHERE (%s IS NULL OR ws.id != %s)
            GROUP BY ws.id
            ORDER BY ws.session_date DESC
            LIMIT %s
        """, (exclude_session_id, exclude_session_id, limit))
        sessions = cur.fetchall()

        result = []
        for s in sessions:
            cur.execute("""
                SELECT ex.name, se.one_rep_max, se.weight_setting, se.weight_low_load,
                       se.reps, se.load_mode,
                       (COALESCE(se.set1_completed::int,0) + COALESCE(se.set2_completed::int,0) +
                        COALESCE(se.set3_completed::int,0) + COALESCE(se.set4_completed::int,0) +
                        COALESCE(se.set5_completed::int,0) + COALESCE(se.set6_completed::int,0)) AS sets_done
                FROM session_exercises se
                JOIN exercises ex ON ex.id = se.exercise_id
                WHERE se.session_id = %s
                ORDER BY COALESCE(se.sort_order, 999), se.id
            """, (s["id"],))
            exercises = cur.fetchall()
            result.append({"session": s, "exercises": exercises})
        return result


def copy_exercises_to_session(from_session_id: int, to_session_id: int,
                              copy_type: str = "full") -> int:
    """Copy all exercises from one session to another.
    copy_type='full'       : copy 1RM/weight/reps/load_mode, reset set completions
    copy_type='menu_only'  : copy exercise names only, clear weight/1RM/reps
    copy_type='with_sets'  : copy everything + actual set completion states
    """
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT se.*, ex.name
            FROM session_exercises se
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.session_id = %s
            ORDER BY COALESCE(se.sort_order, 999), se.id
        """, (from_session_id,))
        exercises = cur.fetchall()

        cur.execute("DELETE FROM session_exercises WHERE session_id = %s", (to_session_id,))

        for i, ex in enumerate(exercises, 1):
            orm = ex["one_rep_max"]
            low_pct = float(ex["low_load_pct"] or 30) if ex["low_load_pct"] else 30.0
            wll = ex["weight_low_load"]
            if not wll and orm:
                wll = round(float(orm) * low_pct / 100, 1)

            if copy_type == "menu_only":
                cur.execute("""
                    INSERT INTO session_exercises
                        (session_id, exercise_id, sort_order,
                         set1_completed, set2_completed, set3_completed,
                         exp_earned, muscle_groups)
                    VALUES (%s,%s,%s, %s,%s,%s, %s,%s)
                """, (
                    to_session_id, ex["exercise_id"], i,
                    False, False, False,
                    0, ex["muscle_groups"],
                ))
            elif copy_type == "with_sets":
                cur.execute("""
                    INSERT INTO session_exercises
                        (session_id, exercise_id, sort_order,
                         one_rep_max, weight_pct80, weight_setting, weight_low_load, reps, reps_low,
                         ratio_pct, load_mode, low_load_pct,
                         set1_completed, set2_completed, set3_completed,
                         set4_completed, set5_completed, set6_completed,
                         set7_completed, set8_completed, set9_completed, set10_completed,
                         exp_earned, muscle_groups)
                    VALUES (%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,
                            %s,%s,%s, %s,%s,%s, %s,%s,%s,%s,
                            %s,%s)
                """, (
                    to_session_id, ex["exercise_id"], i,
                    orm, ex["weight_pct80"], ex["weight_setting"],
                    wll, ex["reps"], ex.get("reps_low"),
                    ex["ratio_pct"], ex["load_mode"], ex["low_load_pct"],
                    ex["set1_completed"], ex["set2_completed"], ex["set3_completed"],
                    ex["set4_completed"], ex["set5_completed"], ex["set6_completed"],
                    ex["set7_completed"], ex["set8_completed"], ex["set9_completed"], ex["set10_completed"],
                    ex["exp_earned"], ex["muscle_groups"],
                ))
            else:
                cur.execute("""
                    INSERT INTO session_exercises
                        (session_id, exercise_id, sort_order,
                         one_rep_max, weight_pct80, weight_setting, weight_low_load, reps, reps_low,
                         ratio_pct, load_mode, low_load_pct,
                         set1_completed, set2_completed, set3_completed,
                         exp_earned, muscle_groups)
                    VALUES (%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s, %s,%s,%s, %s,%s)
                """, (
                    to_session_id, ex["exercise_id"], i,
                    orm, ex["weight_pct80"], ex["weight_setting"],
                    wll, ex["reps"], ex.get("reps_low"),
                    ex["ratio_pct"], ex["load_mode"], ex["low_load_pct"],
                    False, False, False,
                    0, ex["muscle_groups"],
                ))

        count = len(exercises)

    recalculate_session_exp(to_session_id)
    return count


def apply_overload_tip(exercise_id: int, se_id: int, action: str, new_value, mode: str = "high") -> int:
    """Update my_set_exercises AND current session_exercises for both session-start flows.

    Updating session_exercises ensures the change carries over when the user copies
    from the previous session (copy_exercises_to_session flow).
    Updating my_set_exercises ensures the change carries over when starting from a My Set.
    """
    with _conn() as conn:
        cur = conn.cursor()
        count = 0
        if action == "reps" and new_value is not None:
            reps_int = int(new_value)
            col = "reps_low" if mode == "low" else "reps"
            cur.execute(f"UPDATE my_set_exercises SET {col} = %s WHERE exercise_id = %s",
                        (reps_int, exercise_id))
            count = max(count, cur.rowcount)
            cur.execute(f"UPDATE session_exercises SET {col} = %s WHERE id = %s",
                        (reps_int, se_id))
            count = max(count, 1)
        elif action == "low_load_pct" and new_value is not None:
            # my_set_exercises has no low_load_pct column; update session_exercises only
            cur.execute("UPDATE session_exercises SET low_load_pct = %s WHERE id = %s",
                        (float(new_value), se_id))
            count = max(count, cur.rowcount)
        return count


def sync_my_set_from_latest(my_set_id: int) -> int:
    """Update each my_set_exercise with the latest values from session_exercises."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM my_set_exercises WHERE my_set_id = %s", (my_set_id,))
        mse_list = cur.fetchall()
        updated = 0
        for mse in mse_list:
            cur.execute("""
                SELECT se.one_rep_max, se.weight_setting, se.weight_low_load, se.reps
                FROM session_exercises se
                JOIN workout_sessions ws ON ws.id = se.session_id
                WHERE se.exercise_id = %s
                  AND se.one_rep_max IS NOT NULL
                ORDER BY ws.session_date DESC
                LIMIT 1
            """, (mse["exercise_id"],))
            latest = cur.fetchone()
            if latest:
                cur.execute("""
                    UPDATE my_set_exercises
                    SET one_rep_max   = COALESCE(%s, one_rep_max),
                        weight_setting  = COALESCE(%s, weight_setting),
                        weight_low_load = COALESCE(%s, weight_low_load),
                        reps            = COALESCE(%s, reps)
                    WHERE id = %s
                """, (latest["one_rep_max"], latest["weight_setting"],
                      latest["weight_low_load"], latest["reps"], mse["id"]))
                updated += 1
        return updated


def get_prev_exercise_values_batch(session_id: int) -> dict:
    """Return {exercise_id: prev_row} for all exercises in a session (most recent previous session each)."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (prev.exercise_id)
                   prev.exercise_id,
                   prev.one_rep_max, prev.weight_setting, prev.weight_low_load,
                   prev.reps, prev.reps_low, prev.load_mode, prev.low_load_pct,
                   (COALESCE(prev.set1_completed::int,0) + COALESCE(prev.set2_completed::int,0) +
                    COALESCE(prev.set3_completed::int,0) + COALESCE(prev.set4_completed::int,0) +
                    COALESCE(prev.set5_completed::int,0) + COALESCE(prev.set6_completed::int,0)) AS sets_done,
                   ws.session_date
            FROM session_exercises prev
            JOIN workout_sessions ws ON ws.id = prev.session_id
            WHERE prev.exercise_id IN (
                SELECT exercise_id FROM session_exercises WHERE session_id = %s
            )
            AND prev.session_id != %s
            ORDER BY prev.exercise_id, ws.session_date DESC
        """, (session_id, session_id))
        return {row["exercise_id"]: row for row in cur.fetchall()}


def get_last_exercise_values(exercise_id: int, exclude_session_id: int = None):
    """Return the most recent session_exercises row for this exercise."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT se.*
            FROM session_exercises se
            JOIN workout_sessions ws ON ws.id = se.session_id
            WHERE se.exercise_id = %s
              AND (%s IS NULL OR se.session_id != %s)
            ORDER BY ws.session_date DESC
            LIMIT 1
        """, (exercise_id, exclude_session_id, exclude_session_id))
        return cur.fetchone()


# ── Today plan ───────────────────────────────────────────────────────────────

def get_today_plan():
    import datetime
    today = _today()
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT tp.*, ms.name AS my_set_name
            FROM today_plans tp
            LEFT JOIN my_sets ms ON ms.id = tp.my_set_id
            WHERE tp.plan_date = %s
        """, (today,))
        return cur.fetchone()


def save_today_plan(plan_date, name: str, my_set_id) -> int:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO today_plans (plan_date, name, my_set_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (plan_date) DO UPDATE
                SET name = EXCLUDED.name, my_set_id = EXCLUDED.my_set_id,
                    session_id = NULL
            RETURNING id
        """, (plan_date, name.strip(), my_set_id or None))
        return cur.fetchone()["id"]


def start_today_plan(plan_id: int) -> int:
    """Create (or reuse) today's session, apply my_set, link to plan. Returns session_id."""
    import datetime
    today = _today()
    now = _now_jst()

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM today_plans WHERE id = %s", (plan_id,))
        plan = cur.fetchone()
        if plan is None:
            raise ValueError("plan not found")

        # Already started → return existing session
        if plan["session_id"]:
            return plan["session_id"]

        # Reuse today's session or create new one
        cur.execute("SELECT id FROM workout_sessions WHERE session_date = %s", (today,))
        row = cur.fetchone()
        if row:
            session_id = row["id"]
        else:
            dow = DOW_MAP[today.weekday()]
            cur.execute("""
                INSERT INTO workout_sessions
                    (session_date, day_of_week, start_time, total_exp)
                VALUES (%s, %s, %s, 0)
                RETURNING id
            """, (today, dow, now.strftime("%H:%M")))
            session_id = cur.fetchone()["id"]

        # Apply my_set if set and session has no exercises yet
        if plan["my_set_id"]:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM session_exercises WHERE session_id = %s",
                (session_id,)
            )
            if cur.fetchone()["cnt"] == 0:
                cur.execute("""
                    SELECT mse.*, ex.name
                    FROM my_set_exercises mse
                    JOIN exercises ex ON ex.id = mse.exercise_id
                    WHERE mse.my_set_id = %s
                    ORDER BY COALESCE(mse.sort_order, 999), mse.id
                """, (plan["my_set_id"],))
                exercises = cur.fetchall()
                for i, ex in enumerate(exercises, 1):
                    w80 = round(float(ex["one_rep_max"]) * 0.8, 1) if ex["one_rep_max"] else None
                    cur.execute("""
                        INSERT INTO session_exercises
                            (session_id, exercise_id, sort_order,
                             one_rep_max, weight_pct80, weight_setting,
                             weight_low_load, reps, exp_earned, muscle_groups)
                        VALUES (%s,%s,%s, %s,%s,%s,%s,%s, 0,%s)
                    """, (session_id, ex["exercise_id"], i,
                          ex["one_rep_max"], w80, ex["weight_setting"],
                          ex["weight_low_load"], ex["reps"], ex["muscle_groups"]))

        # Link plan → session
        cur.execute(
            "UPDATE today_plans SET session_id = %s WHERE id = %s",
            (session_id, plan_id)
        )

    return session_id


def delete_today_plan(plan_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM today_plans WHERE id = %s", (plan_id,))


def get_today_session():
    import datetime
    today = _today()
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM workout_sessions WHERE session_date = %s", (today,))
        return cur.fetchone()


def get_exercise_progress(exercise_id: int) -> list:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ws.session_date, ws.day_of_week,
                   se.one_rep_max, se.weight_setting, se.weight_low_load, se.reps,
                   se.ratio_pct,
                   se.set1_completed, se.set2_completed, se.set3_completed,
                   se.exp_earned
            FROM session_exercises se
            JOIN workout_sessions ws ON ws.id = se.session_id
            WHERE se.exercise_id = %s
            ORDER BY ws.session_date ASC
        """, (exercise_id,))
        return cur.fetchall()


# ── Weekly schedule ───────────────────────────────────────────────────────────

def get_weekly_schedule() -> list:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ws.day_of_week, ws.location, ws.notes,
                   ms.id AS my_set_id, ms.name AS my_set_name
            FROM weekly_schedule ws
            LEFT JOIN my_sets ms ON ms.id = ws.my_set_id
            ORDER BY ws.day_of_week
        """)
        return cur.fetchall()


def update_weekly_schedule(day_of_week: int, location: str,
                            my_set_id, notes: str) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO weekly_schedule (day_of_week, location, my_set_id, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (day_of_week) DO UPDATE
                SET location=%s, my_set_id=%s, notes=%s
        """, (day_of_week, location, my_set_id or None, notes or None,
              location, my_set_id or None, notes or None))


def get_today_schedule():
    import datetime
    dow = _today().weekday()
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ws.day_of_week, ws.location, ws.notes,
                   ms.id AS my_set_id, ms.name AS my_set_name
            FROM weekly_schedule ws
            LEFT JOIN my_sets ms ON ms.id = ws.my_set_id
            WHERE ws.day_of_week = %s
        """, (dow,))
        return cur.fetchone()


# ── Body weight log ───────────────────────────────────────────────────────────

def list_weight_log(limit: int = 30) -> list:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT logged_date, weight_kg, notes
            FROM body_weight_log
            ORDER BY logged_date DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def upsert_weight(logged_date, weight_kg: float, notes: str) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO body_weight_log (logged_date, weight_kg, notes)
            VALUES (%s, %s, %s)
            ON CONFLICT (logged_date) DO UPDATE
                SET weight_kg=%s, notes=%s
        """, (logged_date, weight_kg, notes or None, weight_kg, notes or None))


def get_latest_weight():
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT logged_date, weight_kg
            FROM body_weight_log
            ORDER BY logged_date DESC LIMIT 1
        """)
        return cur.fetchone()


# ── Dashboard stats ───────────────────────────────────────────────────────────

def get_exp_trend(limit: int = 8) -> list:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT session_date, day_of_week, COALESCE(total_exp, 0) AS total_exp
            FROM workout_sessions
            ORDER BY session_date DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        return list(reversed(rows))


def get_weight_trend(limit: int = 14) -> list:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT logged_date, weight_kg
            FROM body_weight_log
            ORDER BY logged_date DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        return list(reversed(rows))


def get_personal_records(limit: int = 6) -> list:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ex.name AS exercise_name, ex.body_part, ex.primary_muscle,
                   MAX(se.one_rep_max) AS best_1rm,
                   MAX(se.weight_setting) AS best_weight
            FROM session_exercises se
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.one_rep_max IS NOT NULL AND se.one_rep_max > 0
            GROUP BY ex.id, ex.name, ex.body_part, ex.primary_muscle
            ORDER BY best_1rm DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def get_dashboard_stats() -> dict:
    import datetime
    with _conn() as conn:
        cur = conn.cursor()

        # Sessions in last 7 days
        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM workout_sessions
            WHERE session_date >= CURRENT_DATE - 6
        """)
        week_count = cur.fetchone()["cnt"]

        # Total sessions
        cur.execute("SELECT COUNT(*) AS cnt FROM workout_sessions")
        total_sessions = cur.fetchone()["cnt"]

        # Total EXP
        cur.execute("SELECT COALESCE(SUM(total_exp),0) AS total FROM workout_sessions")
        total_exp = cur.fetchone()["total"]

        # Consecutive weeks with at least 1 session
        cur.execute("""
            SELECT DATE_TRUNC('week', session_date) AS wk
            FROM workout_sessions
            GROUP BY wk
            ORDER BY wk DESC
        """)
        weeks = [r["wk"] for r in cur.fetchall()]
        streak = 0
        today_week = _today() - datetime.timedelta(days=_today().weekday())
        for i, wk in enumerate(weeks):
            expected = today_week - datetime.timedelta(weeks=i)
            if wk.date() == expected:
                streak += 1
            else:
                break

        # Recent sessions (last 3)
        cur.execute("""
            SELECT ws.id, ws.session_date, ws.day_of_week, ws.total_exp,
                   COUNT(se.id) AS exercise_count
            FROM workout_sessions ws
            LEFT JOIN session_exercises se ON se.session_id = ws.id
            GROUP BY ws.id
            ORDER BY ws.session_date DESC
            LIMIT 3
        """)
        recent_sessions = cur.fetchall()

    return {
        "week_count": week_count,
        "total_sessions": total_sessions,
        "total_exp": total_exp,
        "streak_weeks": streak,
        "recent_sessions": recent_sessions,
    }


# ── Session finish & advice ───────────────────────────────────────────────────

def finish_session(session_id: int, post_notes: str) -> None:
    import datetime
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE workout_sessions
            SET finished_at = COALESCE(finished_at, NOW()),
                end_time    = COALESCE(end_time, %s::time),
                post_notes  = %s
            WHERE id = %s
        """, (_now_jst().strftime("%H:%M"), post_notes or None, session_id))


def build_advice(session, exercises: list, body_weight: float = 65.0) -> tuple:
    """Return (advice_list, intensity_label, overload_tips)."""
    total_exp = session["total_exp"] or 0

    if total_exp >= 8000:
        intensity = "high"
    elif total_exp >= 3000:
        intensity = "medium"
    else:
        intensity = "light"

    # タンパク質目標量（体重ベース）
    protein_int  = round(body_weight * 1.6)   # 中級者最適量
    protein_max  = round(body_weight * 2.4)   # 科学的上限

    advice = []

    # 強度サマリー
    if intensity == "high":
        advice.append({"icon": "⚡", "cat": "リカバリー",
                        "title": "高強度セッション完了！",
                        "body": f"今日の {total_exp:,} EXP は素晴らしい成果です。同部位の次のトレーニングまで48〜72時間の回復期間を設けましょう。"})
    elif intensity == "medium":
        advice.append({"icon": "💪", "cat": "リカバリー",
                        "title": "充実したトレーニング完了",
                        "body": f"{total_exp:,} EXP 獲得。適切な負荷は継続の鍵。24〜48時間後には次のセッションに挑めます。"})
    else:
        advice.append({"icon": "✅", "cat": "リカバリー",
                        "title": "軽めのトレーニング完了",
                        "body": f"{total_exp:,} EXP 獲得。軽負荷セッションは回復を促進します。翌日もトレーニング可能です。"})

    # 栄養：科学的タンパク質ガイドライン（2018・2024年研究）
    advice.append({"icon": "🍗", "cat": "栄養",
                    "title": f"今日の目標タンパク質：{protein_int}〜{protein_max}g",
                    "body": (
                        f"中級者の最適量は体重×1.6g（{body_weight:.0f}kgなら約{protein_int}g/日）。"
                        f"2.4g/kg（{protein_max}g）を超えると過剰分はエネルギーとして燃焼されるだけで、炭水化物など他の必須栄養素を圧迫します。"
                        "トレーニング後30分以内にプロテイン＋糖質で合成を最大化。"
                    )})

    # 睡眠：週ボリューム優先の最新エビデンス
    advice.append({"icon": "😴", "cat": "睡眠 × ボリューム",
                    "title": "頻度より「質」と「7時間睡眠」",
                    "body": (
                        "最新研究（2026年フロリダ・アトランティック大学）では、筋肥大を決めるのは「週の総ボリューム（重量×回数×セット数）」であり、"
                        "週4回以上と週2〜3回で差はないと結論。ジムに通う回数より1セットの質と7時間以上の睡眠を優先することが現代のスタンダードです。"
                    )})

    # サプリメント：BCAA/EAA戦略的活用法
    if intensity == "high":
        advice.append({"icon": "💊", "cat": "サプリメント",
                        "title": "BCAA：激しい筋肉痛を予防する",
                        "body": (
                            "今日のような高強度セッション後はBCAAが有効です。"
                            "2024年スファックス大学の研究では、BCAAが活性酸素による二次損傷を抑制し、96時間以内の筋肉痛を大幅軽減することが確認されています。"
                            "プロテインの代替にはなりませんが、筋肉痛ケアの補助として活用を。"
                        )})
    else:
        advice.append({"icon": "💊", "cat": "サプリメント",
                        "title": "EAA：空腹時トレーニング前の切り札",
                        "body": (
                            "朝食前や空腹時にトレーニングする場合はEAA 6gが効果的。"
                            "研究では4時間の絶食後のトレーニングで筋分解が56%増加するところ、EAA摂取で27%まで抑制できると示されています。"
                            "BCAAやEAAはプロテイン（3〜5時間の合成維持）の代替にはならず、あくまで補助的に活用してください。"
                        )})

    advice.append({"icon": "💧", "cat": "水分",
                    "title": "水分補給を忘れずに",
                    "body": "トレーニング後2〜3時間かけて水500ml〜1L補給を。尿が薄い黄色になれば十分な水分量のサインです。"})

    if intensity == "high":
        advice.append({"icon": "🗓️", "cat": "翌日の目安",
                        "title": "明日の身体の状態を確認",
                        "body": "軽い筋肉痛→回復が順調なサイン。強い痛みや疲労感が残る場合はもう1日休息を。週の総ボリュームを維持するほうが、無理して追加セッションをこなすより効果的です。"})
    else:
        advice.append({"icon": "🗓️", "cat": "翌日の目安",
                        "title": "明日は積極的リカバリーを",
                        "body": "ウォーキングや軽いストレッチで血流を促進すると回復が早まります。週2〜3回の高品質セッションを継続することが、最新科学が示す最も効率的な筋肥大戦略です。"})

    # ── 漸進性過負荷の分析（exerciseType別ロジック）────────────────────────
    overload_tips = []
    for ex in exercises:
        name     = ex.get("exercise_name") or "この種目"
        mode     = ex.get("load_mode") or "high"
        ex_type  = (ex.get("exercise_type") or "strength").lower()
        reps     = int(ex.get("reps_low") or 20) if mode == "low" else int(ex.get("reps") or 0)
        done     = sum(1 for i in range(1, 11) if ex.get(f"set{i}_completed"))
        quality  = ex.get("quality")
        se_id_val = ex.get("id")

        if done < 1 or reps <= 0:
            continue

        # ── Plyometric：rep増加は提案しない。Quality・完遂を優先 ───────────
        if ex_type == "plyometric":
            if done >= 3 and quality and quality >= 4:
                overload_tips.append({
                    "icon": "⚡", "name": name,
                    "title": "高品質で完遂！この水準を維持",
                    "body": f"Q{quality}で{done}セット完遂。次回も同じ強度・リズムで質の高いジャンプを意識してください。",
                    "se_id": se_id_val, "action": "maintain", "new_value": None,
                })
            elif done >= 3:
                overload_tips.append({
                    "icon": "🎯", "name": name,
                    "title": "全セット完遂！動作品質を高めよう",
                    "body": f"{done}セット完遂。次回は踏切のタイミング・腕振り・高さの一貫性をさらに意識してみましょう。",
                    "se_id": se_id_val, "action": "maintain", "new_value": None,
                })
            else:
                overload_tips.append({
                    "icon": "🏃", "name": name,
                    "title": "次回は全3セット完遂を目標に",
                    "body": f"今回は{done}セット実施。重量・rep増加より「全セット高品質で完遂」を優先してください。",
                    "se_id": se_id_val, "action": "maintain", "new_value": None,
                })
            continue

        # ── Power：Quality・速度優先。Q4〜5維持で微増候補 ─────────────────
        if ex_type == "power":
            if quality and quality >= 4 and done >= 3:
                overload_tips.append({
                    "icon": "🚀", "name": name,
                    "title": "高Quality継続中！次回も速度優先で",
                    "body": f"Q{quality}×{done}セット達成。速度と爆発力を最優先に維持してください。Quality4〜5を安定して達成できたら負荷の微増を検討します。",
                    "se_id": se_id_val, "action": "maintain", "new_value": None,
                })
            else:
                overload_tips.append({
                    "icon": "🎯", "name": name,
                    "title": "速度・Quality優先で継続",
                    "body": f"Power系種目は重量増加より「速度・爆発力・Quality」を優先します。Q4〜5を安定させることが次のステップです。",
                    "se_id": se_id_val, "action": "maintain", "new_value": None,
                })
            continue

        # ── Low-load mode（strength / core / accessory 共通）───────────────
        if mode == "low":
            if done < 3:
                continue
            if reps >= 30:
                pct = float(ex.get("low_load_pct") or 30)
                new_pct = round(pct + 5)
                if new_pct <= 60:
                    overload_tips.append({
                        "icon": "📈", "name": name,
                        "title": "低負荷%を上げましょう",
                        "body": f"{reps}rep × {done}セット達成！次回は低負荷% を {int(pct)}% → {new_pct}% に上げてみましょう。",
                        "se_id": se_id_val, "action": "low_load_pct", "new_value": new_pct,
                    })
                else:
                    overload_tips.append({
                        "icon": "🚀", "name": name,
                        "title": "高負荷へ切り替えのチャンス",
                        "body": f"低負荷で{reps}rep × {done}セット達成！次回は高負荷（1RM×80%）での8-12repに挑戦しましょう。",
                        "se_id": se_id_val, "action": "mode_switch", "new_value": "high",
                    })
            else:
                new_reps = reps + 2
                overload_tips.append({
                    "icon": "📊", "name": name,
                    "title": "rep数を増やしましょう",
                    "body": f"低負荷{reps}rep × {done}セット達成！次回は {reps} → {new_reps} rep に増やしてみましょう。30repで%アップです。",
                    "se_id": se_id_val, "action": "reps", "new_value": new_reps,
                })
            continue

        # ── High-load: strength ────────────────────────────────────────────
        if ex_type == "strength":
            if done < 3:
                continue
            if reps >= 12:
                overload_tips.append({
                    "icon": "📈", "name": name,
                    "title": "次回は重量アップのチャンス！",
                    "body": f"高負荷{reps}rep × {done}セット達成（RIR2〜3を確保できている目安）。1RMを更新して重量を1段階上げましょう。重量アップ後はrep数を8に戻してOKです。",
                    "se_id": se_id_val, "action": "weight_up", "new_value": None,
                })
            elif reps >= 8:
                new_reps = reps + 1
                overload_tips.append({
                    "icon": "📊", "name": name,
                    "title": f"次回は {new_reps} rep を目標に",
                    "body": f"高負荷{reps}rep × {done}セット達成！次回は {reps} → {new_reps} rep に増やしましょう。12repで重量アップのサインです。",
                    "se_id": se_id_val, "action": "reps", "new_value": new_reps,
                })
            else:
                overload_tips.append({
                    "icon": "🎯", "name": name,
                    "title": "フォームを固めながら継続",
                    "body": f"高負荷{reps}rep × {done}セット。まずはフォームを安定させて8repを目標にしましょう。",
                    "se_id": se_id_val, "action": "maintain", "new_value": None,
                })

        # ── High-load: core / accessory ───────────────────────────────────
        elif ex_type in ("core", "accessory"):
            if done < 3:
                continue
            if reps >= 12:
                new_reps = reps + 1
                overload_tips.append({
                    "icon": "📊", "name": name,
                    "title": f"次回は {new_reps} rep を目標に",
                    "body": f"{reps}rep × {done}セット達成！フォームと制御を保ちながら {reps} → {new_reps} rep に進めましょう。",
                    "se_id": se_id_val, "action": "reps", "new_value": new_reps,
                })
            else:
                overload_tips.append({
                    "icon": "🎯", "name": name,
                    "title": "フォームと制御を優先して継続",
                    "body": f"{reps}rep × {done}セット。体幹・補助系はフォーム品質とRIR2〜3を最優先に。焦らず積み上げましょう。",
                    "se_id": se_id_val, "action": "maintain", "new_value": None,
                })

    return advice, intensity, overload_tips


def recalculate_all_exp(session_id: int) -> dict:
    """全種目のEXPを現在の計算式で再計算してDBを更新する。"""
    bw_row = get_latest_weight()
    body_weight = float(bw_row["weight_kg"]) if bw_row else 65.0

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT se.*,
                   ex.bodyweight_ratio,
                   COALESCE(
                     se.weight_setting,
                     ROUND((COALESCE(
                       se.one_rep_max,
                       ex.one_rep_max,
                       (SELECT se2.one_rep_max FROM session_exercises se2
                        WHERE se2.exercise_id = se.exercise_id
                          AND se2.one_rep_max IS NOT NULL
                        ORDER BY se2.id DESC LIMIT 1)
                     ) * 0.8)::numeric, 1)
                   ) AS weight_setting,
                   COALESCE(
                     se.weight_low_load,
                     ROUND((COALESCE(
                       se.one_rep_max,
                       ex.one_rep_max,
                       (SELECT se2.one_rep_max FROM session_exercises se2
                        WHERE se2.exercise_id = se.exercise_id
                          AND se2.one_rep_max IS NOT NULL
                        ORDER BY se2.id DESC LIMIT 1)
                     ) * 0.3)::numeric, 1)
                   ) AS weight_low_load
            FROM session_exercises se
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.session_id = %s
        """, (session_id,))
        exercises = cur.fetchall()

        exercise_exp = {}
        for se in exercises:
            mode = se.get("load_mode") or "high"
            bw_ratio = se.get("bodyweight_ratio")
            reps = se.get("reps") or 10

            completions = {i: bool(se.get(f"set{i}_completed")) for i in range(1, 11)}
            completed_count = sum(1 for v in completions.values() if v)

            if bw_ratio:
                weight = round(body_weight * float(bw_ratio), 1)
            elif mode == "low":
                weight = se["weight_low_load"] or se["weight_setting"]
            else:
                weight = se["weight_setting"] or se["weight_low_load"]

            exp = round((weight or 1) * reps * completed_count)
            cur.execute(
                "UPDATE session_exercises SET exp_earned = %s WHERE id = %s",
                (exp, se["id"])
            )
            exercise_exp[str(se["id"])] = exp

    recalculate_session_exp(session_id)

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT total_exp FROM workout_sessions WHERE id = %s", (session_id,))
        total = cur.fetchone()["total_exp"]
        cur.execute("""
            SELECT ex.body_part, COALESCE(SUM(se.exp_earned), 0) AS cat_exp
            FROM session_exercises se
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.session_id = %s
            GROUP BY ex.body_part
        """, (session_id,))
        category_exp = {"上肢": 0, "下肢": 0, "体幹": 0}
        for row in cur.fetchall():
            if row["body_part"] in category_exp:
                category_exp[row["body_part"]] = int(row["cat_exp"])

    return {
        "exercise_exp":      exercise_exp,
        "session_total_exp": total,
        "category_exp":      category_exp,
    }


def build_volume_metrics(session, exercises: list, body_weight: float = 65.0) -> dict:
    """Calculate muscle volume metrics for a session.

    Returns dict with:
      cat_exp: {上肢, 下肢, 体幹}
      muscle_exp_list: [{name, exp, pct, body_part}] sorted by exp desc
      has_bodyweight: bool
      purpose: str
      gym_eq_pct: int  (bodyweight volume as % of gym-equivalent, only when pure BW)
    """
    cat_exp    = {"上肢": 0, "下肢": 0, "体幹": 0}
    muscle_exp = {}   # primary_muscle -> exp
    muscle_bp  = {}   # primary_muscle -> body_part

    total_gym_volume = 0.0
    total_bw_volume  = 0.0
    gym_count = 0
    bw_count  = 0

    for ex in exercises:
        bp       = ex.get("body_part") or ""
        bw_ratio = ex.get("bodyweight_ratio")
        mode     = ex.get("load_mode") or "high"
        reps     = ex.get("reps") or 10
        muscle   = ex.get("primary_muscle") or ex.get("exercise_name") or "その他"

        if mode == "low":
            weight = ex.get("weight_low_load") or ex.get("weight_setting")
        else:
            weight = ex.get("weight_setting") or ex.get("weight_low_load")

        done = sum(1 for i in range(1, 11) if ex.get(f"set{i}_completed"))
        if done == 0:
            continue

        exp = ex.get("exp_earned") or 0

        if bw_ratio:
            bw_count += 1
            eff_weight = body_weight * bw_ratio
            total_bw_volume += eff_weight * reps * done
        else:
            gym_count += 1
            w = float(weight or 0)
            total_gym_volume += w * reps * done

        if bp in cat_exp:
            cat_exp[bp] += exp

        muscle_exp[muscle] = muscle_exp.get(muscle, 0) + exp
        if muscle not in muscle_bp:
            muscle_bp[muscle] = bp

    total_volume = total_gym_volume + total_bw_volume
    has_bodyweight = bw_count > 0 and gym_count == 0
    gym_eq_pct = (min(100, int(total_bw_volume / total_volume * 100))
                  if has_bodyweight and total_volume > 0 else 0)

    total_exp = session.get("total_exp") or 0
    if total_exp >= 500 and has_bodyweight and not total_gym_volume:
        purpose = "自宅メンテナンス"
    elif total_exp >= 8000:
        purpose = "筋肥大"
    elif total_exp >= 3000:
        purpose = "筋力向上"
    else:
        purpose = "維持・回復"

    # Per-muscle list sorted by EXP descending, with relative % of total muscle exp
    total_muscle_exp = sum(muscle_exp.values()) or 1
    muscle_exp_list = sorted(
        [{"name": m, "exp": v, "pct": round(v / total_muscle_exp * 100),
          "body_part": muscle_bp.get(m, "")}
         for m, v in muscle_exp.items()],
        key=lambda x: x["exp"], reverse=True
    )

    return {
        "cat_exp":         cat_exp,
        "muscle_exp_list": muscle_exp_list,
        "has_bodyweight":  has_bodyweight,
        "purpose":         purpose,
        "gym_eq_pct":      gym_eq_pct,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Volleyball Performance v1.0
# ─────────────────────────────────────────────────────────────────────────────

def record_se_quality_pain(se_id: int, quality: int = None,
                            pain_flag: bool = None,
                            contacts: int = None,
                            throws: int = None,
                            stop_reason: str = None) -> dict:
    """Record quality / pain_flag / contacts / throws / stop_reason for a session exercise."""
    with _conn() as conn:
        cur = conn.cursor()
        sets = []
        vals = []
        if quality is not None:
            sets.append("quality = %s")
            vals.append(int(quality))
        if pain_flag is not None:
            sets.append("pain_flag = %s")
            vals.append(bool(pain_flag))
        if contacts is not None:
            sets.append("contacts = %s")
            vals.append(int(contacts))
        if throws is not None:
            sets.append("throws = %s")
            vals.append(int(throws))
        if stop_reason is not None:
            sets.append("stop_reason = %s")
            vals.append(str(stop_reason))
        if not sets:
            return {}
        vals.append(se_id)
        cur.execute(f"UPDATE session_exercises SET {', '.join(sets)} WHERE id = %s", vals)
        cur.execute(
            "SELECT quality, pain_flag, contacts, throws, stop_reason FROM session_exercises WHERE id = %s",
            (se_id,)
        )
        row = cur.fetchone()
    return dict(row) if row else {}


def record_session_finish(session_id: int, duration_min: int, session_rpe: int,
                           session_type: str = None) -> dict:
    """Record RPE, duration, session_load; compute and store session summary metrics."""
    session_load = (duration_min or 0) * session_rpe
    result = {
        "session_load": session_load,
        "strength_volume_kg": 0,
        "plyometric_contacts": 0,
        "power_throws": 0,
        "avg_quality": None,
    }

    # ── Step 1: Always save core fields (these columns definitely exist) ──────
    core_parts = ["session_rpe=%s", "duration_min=%s", "session_load=%s"]
    core_vals  = [session_rpe, duration_min, session_load]
    if session_type:
        core_parts.append("session_type=%s")
        core_vals.append(session_type)
    core_vals.append(session_id)
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE workout_sessions SET {', '.join(core_parts)} WHERE id = %s",
            core_vals
        )

    # ── Step 2: Compute & save extended metrics (best-effort) ─────────────────
    try:
        with _conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                SELECT COALESCE(SUM(
                    CASE WHEN COALESCE(se.load_mode,'high') = 'low' THEN
                        COALESCE(se.weight_low_load, se.weight_setting, 0)
                    ELSE COALESCE(se.weight_setting, 0)
                    END *
                    COALESCE(se.reps, 0) *
                    (COALESCE(se.set1_completed::int,0)+COALESCE(se.set2_completed::int,0)+
                     COALESCE(se.set3_completed::int,0)+COALESCE(se.set4_completed::int,0)+
                     COALESCE(se.set5_completed::int,0)+COALESCE(se.set6_completed::int,0))
                ), 0)
                FROM session_exercises se
                JOIN exercises ex ON ex.id = se.exercise_id
                WHERE se.session_id = %s
                  AND COALESCE(ex.exercise_type,'strength') = 'strength'
            """, (session_id,))
            strength_vol = float(cur.fetchone()[0] or 0)

            cur.execute("""
                SELECT COALESCE(SUM(COALESCE(se.contacts, se.reps, 0) *
                    (COALESCE(se.set1_completed::int,0)+COALESCE(se.set2_completed::int,0)+
                     COALESCE(se.set3_completed::int,0)+COALESCE(se.set4_completed::int,0)+
                     COALESCE(se.set5_completed::int,0)+COALESCE(se.set6_completed::int,0))), 0)
                FROM session_exercises se
                JOIN exercises ex ON ex.id = se.exercise_id
                WHERE se.session_id = %s
                  AND COALESCE(ex.exercise_type,'strength') = 'plyometric'
            """, (session_id,))
            plyo_contacts = int(cur.fetchone()[0] or 0)

            cur.execute("""
                SELECT COALESCE(SUM(COALESCE(se.throws, se.reps, 0) *
                    (COALESCE(se.set1_completed::int,0)+COALESCE(se.set2_completed::int,0)+
                     COALESCE(se.set3_completed::int,0)+COALESCE(se.set4_completed::int,0)+
                     COALESCE(se.set5_completed::int,0)+COALESCE(se.set6_completed::int,0))), 0)
                FROM session_exercises se
                JOIN exercises ex ON ex.id = se.exercise_id
                WHERE se.session_id = %s
                  AND COALESCE(ex.exercise_type,'strength') = 'power'
            """, (session_id,))
            power_throws = int(cur.fetchone()[0] or 0)

            cur.execute("""
                SELECT AVG(se.quality)
                FROM session_exercises se
                JOIN exercises ex ON ex.id = se.exercise_id
                WHERE se.session_id = %s
                  AND se.quality IS NOT NULL
                  AND COALESCE(ex.exercise_type,'strength') IN ('plyometric','power')
            """, (session_id,))
            avg_q_row = cur.fetchone()[0]
            avg_quality = round(float(avg_q_row), 2) if avg_q_row else None

            cur.execute("""
                UPDATE workout_sessions
                SET strength_volume_kg=%s, plyometric_contacts=%s,
                    power_throws=%s, avg_quality=%s
                WHERE id = %s
            """, (strength_vol, plyo_contacts, power_throws, avg_quality, session_id))

            result.update({
                "strength_volume_kg":  strength_vol,
                "plyometric_contacts": plyo_contacts,
                "power_throws":        power_throws,
                "avg_quality":         avg_quality,
            })
    except Exception:
        import traceback
        traceback.print_exc()

    return result


# ── Volleyball Program 3プラン my-set seed ────────────────────────────────────

_VOLLEYBALL_PLANS = [
    {
        "name":         "DAY A - FORCE",
        "program_name": "Volleyball Performance v1.0",
        "session_type": "DAY_A_FORCE",
        "location":     "gym",
        "exercises": [
            # (exercise_name, reps, target_sets, weight_setting, muscle_groups, note)
            ("アプローチジャンプ",       2,  3, None, "大腿四頭筋,大臀筋", None),
            ("ブルガリアンスクワット",   5,  3, 12.0, "大臀筋,大腿四頭筋", None),
            ("ルーマニアンデッドリフト", 5,  3, 50.0, "ハムストリングス,大臀筋", None),
            ("インクラインダンベルプレス", 6, 2, 18.0, "大胸筋,三角筋前部,上腕三頭筋", None),
            ("シーテッドロー",           6,  2, None, "広背筋,僧帽筋", None),
            ("カーフ&トゥレイズ",        8,  2, None, "カーフ", None),
            ("パロフプレス",             8,  2, None, "腹斜筋,腹直筋", None),
            ("アブローラー",             6,  2, None, "腹直筋,腸腰筋", None),
        ],
    },
    {
        "name":         "DAY B - POWER GYM",
        "program_name": "Volleyball Performance v1.0",
        "session_type": "DAY_B_POWER_GYM",
        "location":     "gym",
        "exercises": [
            ("ポゴジャンプ",               8,  2, None, "カーフ,大腿四頭筋", None),
            ("アプローチジャンプ",         2,  4, None, "大腿四頭筋,大臀筋", None),
            ("スクワットジャンプ",         3,  3, None, "大腿四頭筋,大臀筋", None),
            ("ロテーショナルMBスロー",     3,  3, 3.0,  "腹斜筋,三角筋", None),
            ("オーバーヘッドMBスロー",     3,  2, 3.0,  "三角筋前部,体幹", None),
            ("シーテッドレッグカール",     8,  2, None, "ハムストリングス", None),
            ("フェイスプル",              10,  2, None, "三角筋後部,菱形筋", None),
            ("サイドプランクローテーション", 6, 2, None, "腹斜筋", None),
        ],
    },
    {
        "name":         "DAY B - POWER OUTDOOR",
        "program_name": "Volleyball Performance v1.0",
        "session_type": "DAY_B_POWER_OUTDOOR",
        "location":     "both",
        "exercises": [
            ("ポゴジャンプ",               8,  2, None, "カーフ,大腿四頭筋", None),
            ("アプローチジャンプ",         2,  4, None, "大腿四頭筋,大臀筋", None),
            ("スクワットジャンプ",         3,  3, None, "大腿四頭筋,大臀筋", None),
            ("スプリットスクワット",       8,  2, None, "大臀筋,大腿四頭筋", None),
            ("サイドプランクローテーション", 6, 2, None, "腹斜筋", None),
            ("ウォーククールダウン",        1,  1, None, None, None),
        ],
    },
]


def seed_volleyball_program() -> int:
    """Create Volleyball Performance v1.0 my-sets if not present. Returns number created."""
    created = 0
    with _conn() as conn:
        cur = conn.cursor()
        for plan in _VOLLEYBALL_PLANS:
            # Skip if already exists
            cur.execute("SELECT id FROM my_sets WHERE name = %s", (plan["name"],))
            existing = cur.fetchone()
            if existing:
                # Ensure program_name / session_type are set
                cur.execute(
                    "UPDATE my_sets SET program_name=%s, session_type=%s WHERE id=%s",
                    (plan["program_name"], plan["session_type"], existing["id"])
                )
                ms_id = existing["id"]
            else:
                cur.execute("""
                    INSERT INTO my_sets (name, program_name, session_type, location)
                    VALUES (%s, %s, %s, %s) RETURNING id
                """, (plan["name"], plan["program_name"], plan["session_type"], plan["location"]))
                ms_id = cur.fetchone()["id"]
                created += 1

            for i, (ex_name, reps, target_sets, weight, muscles, _note) in enumerate(plan["exercises"], 1):
                cur.execute("SELECT id FROM exercises WHERE name = %s", (ex_name,))
                ex_row = cur.fetchone()
                if not ex_row:
                    continue
                ex_id = ex_row["id"]
                weight_setting = weight
                weight_low_load = round(weight * 0.30, 1) if weight else None
                cur.execute("""
                    INSERT INTO my_set_exercises
                        (my_set_id, exercise_id, sort_order, reps, target_sets,
                         weight_setting, weight_low_load, muscle_groups)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (my_set_id, exercise_id) DO UPDATE
                        SET sort_order=%s, reps=%s, target_sets=%s,
                            weight_setting=%s, weight_low_load=%s, muscle_groups=%s
                """, (
                    ms_id, ex_id, i, reps, target_sets,
                    weight_setting, weight_low_load, muscles,
                    i, reps, target_sets,
                    weight_setting, weight_low_load, muscles,
                ))
    return created
