"""Database access layer for workout_report."""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

# Railway / production uses DATABASE_URL; local uses dbname shorthand
_DATABASE_URL = os.environ.get("DATABASE_URL", "dbname=workout_report")
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

DOW_MAP = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}


def _conn():
    return psycopg2.connect(_DATABASE_URL, cursor_factory=RealDictCursor)


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
                   ex.body_part, ex.needs_bench, ex.primary_muscle
            FROM session_exercises se
            JOIN exercises ex ON ex.id = se.exercise_id
            WHERE se.session_id = %s
            ORDER BY COALESCE(se.sort_order, 999), se.id
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
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM session_exercises WHERE session_id = %s",
        (session_id,)
    )
    return cur.fetchone()[0]


def create_session_exercise(session_id, exercise_id, one_rep_max,
                             weight_setting, weight_low_load, reps,
                             set1, set2, set3, exp_earned, muscle_groups) -> int:
    weight_pct80 = round(float(one_rep_max) * 0.8, 1) if one_rep_max else None
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


def get_exercise(exercise_id: int):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, body_part, needs_bench, primary_muscle
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
            SELECT ms.id, ms.name, ms.description, COUNT(mse.id) AS exercise_count
            FROM my_sets ms
            LEFT JOIN my_set_exercises mse ON mse.my_set_id = ms.id
            GROUP BY ms.id
            ORDER BY ms.name
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
                   ex.body_part, ex.needs_bench, ex.primary_muscle
            FROM my_set_exercises mse
            JOIN exercises ex ON ex.id = mse.exercise_id
            WHERE mse.my_set_id = %s
            ORDER BY COALESCE(mse.sort_order, 999), mse.id
        """, (my_set_id,))
        exercises = cur.fetchall()
        return my_set, exercises


def create_my_set(name: str, description: str) -> int:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO my_sets (name, description) VALUES (%s, %s) RETURNING id",
            (name, description or None)
        )
        return cur.fetchone()["id"]


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
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM my_set_exercises WHERE my_set_id = %s",
        (my_set_id,)
    )
    return cur.fetchone()[0]


def create_my_set_exercise(my_set_id, exercise_id, one_rep_max,
                            weight_setting, weight_low_load, reps, muscle_groups) -> int:
    with _conn() as conn:
        cur = conn.cursor()
        sort_order = _mse_next_sort(cur, my_set_id)
        cur.execute("""
            INSERT INTO my_set_exercises
                (my_set_id, exercise_id, sort_order,
                 one_rep_max, weight_setting, weight_low_load, reps, muscle_groups)
            VALUES (%s,%s,%s, %s,%s,%s,%s,%s)
            ON CONFLICT (my_set_id, exercise_id) DO UPDATE
                SET sort_order=%s, one_rep_max=%s, weight_setting=%s,
                    weight_low_load=%s, reps=%s, muscle_groups=%s
            RETURNING id
        """, (
            my_set_id, exercise_id, sort_order,
            one_rep_max, weight_setting, weight_low_load or None, reps or None, muscle_groups or None,
            sort_order, one_rep_max, weight_setting, weight_low_load or None, reps or None, muscle_groups or None,
        ))
        return cur.fetchone()["id"]


def update_my_set_exercise(mse_id, exercise_id, one_rep_max,
                            weight_setting, weight_low_load, reps, muscle_groups) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE my_set_exercises
            SET exercise_id=%s, one_rep_max=%s, weight_setting=%s,
                weight_low_load=%s, reps=%s, muscle_groups=%s
            WHERE id=%s
        """, (exercise_id, one_rep_max, weight_setting,
              weight_low_load or None, reps or None, muscle_groups or None, mse_id))


def delete_my_set_exercise(mse_id: int) -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM my_set_exercises WHERE id = %s", (mse_id,))


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
            cur.execute("""
                INSERT INTO session_exercises
                    (session_id, exercise_id, sort_order,
                     one_rep_max, weight_pct80, weight_setting, weight_low_load, reps,
                     ratio_pct, set1_completed, set2_completed, set3_completed,
                     exp_earned, muscle_groups)
                VALUES (%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s)
            """, (
                session_id, ex["exercise_id"], i,
                ex["one_rep_max"], weight_pct80, ex["weight_setting"],
                ex["weight_low_load"], ex["reps"],
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
            SELECT se.*, ws.rep_count AS session_rep_count
            FROM session_exercises se
            JOIN workout_sessions ws ON ws.id = se.session_id
            WHERE se.id = %s
        """, (se_id,))
        se = cur.fetchone()
        if se is None:
            return None

        new_val = not bool(se[col])
        completions = {i: bool(se.get(f"set{i}_completed")) for i in range(1, 11)}
        completions[set_num] = new_val
        completed_count = sum(1 for v in completions.values() if v)

        weight = se["weight_low_load"] if se["weight_low_load"] else se["weight_setting"]
        reps = se["reps"] or se["session_rep_count"] or 0
        exp = round((weight or 0) * reps * completed_count)

        cur.execute(f"""
            UPDATE session_exercises
            SET {col} = %s, exp_earned = %s
            WHERE id = %s
        """, (new_val, exp, se_id))

        session_id = se["session_id"]

    recalculate_session_exp(session_id)

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT total_exp FROM workout_sessions WHERE id = %s", (session_id,))
        total = cur.fetchone()["total_exp"]

    return {
        "set_num": set_num,
        "completed": new_val,
        "exp_earned": exp,
        "session_total_exp": total,
    }


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
                SELECT ex.name, se.one_rep_max, se.weight_setting, se.weight_low_load, se.reps
                FROM session_exercises se
                JOIN exercises ex ON ex.id = se.exercise_id
                WHERE se.session_id = %s
                ORDER BY COALESCE(se.sort_order, 999), se.id
            """, (s["id"],))
            exercises = cur.fetchall()
            result.append({"session": s, "exercises": exercises})
        return result


def copy_exercises_to_session(from_session_id: int, to_session_id: int) -> int:
    """Copy all exercises from one session to another. Resets set completions and EXP."""
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
            cur.execute("""
                INSERT INTO session_exercises
                    (session_id, exercise_id, sort_order,
                     one_rep_max, weight_pct80, weight_setting, weight_low_load, reps,
                     ratio_pct, set1_completed, set2_completed, set3_completed,
                     exp_earned, muscle_groups)
                VALUES (%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s)
            """, (
                to_session_id, ex["exercise_id"], i,
                ex["one_rep_max"], ex["weight_pct80"], ex["weight_setting"],
                ex["weight_low_load"], ex["reps"],
                ex["ratio_pct"], False, False, False,
                0, ex["muscle_groups"],
            ))

        count = len(exercises)

    recalculate_session_exp(to_session_id)
    return count


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
    today = datetime.date.today()
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
    today = datetime.date.today()
    now = datetime.datetime.now()

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
                "SELECT COUNT(*) FROM session_exercises WHERE session_id = %s",
                (session_id,)
            )
            if cur.fetchone()[0] == 0:
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
    today = datetime.date.today()
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
    dow = datetime.date.today().weekday()
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
        today_week = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
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
        """, (datetime.datetime.now().strftime("%H:%M"), post_notes or None, session_id))


def build_advice(session, exercises: list) -> tuple:
    """Return (advice_list, intensity_label)."""
    total_exp = session["total_exp"] or 0
    completed_sets = sum(
        sum(1 for i in range(1, 11) if ex.get(f"set{i}_completed"))
        for ex in exercises
    )

    if total_exp >= 8000:
        intensity = "high"
    elif total_exp >= 3000:
        intensity = "medium"
    else:
        intensity = "light"

    muscle_set = set()
    for ex in exercises:
        if ex.get("muscle_groups"):
            for mg in ex["muscle_groups"].split(","):
                muscle_set.add(mg.strip())

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

    # 栄養
    advice.append({"icon": "🍗", "cat": "栄養",
                    "title": "トレーニング後30分以内に",
                    "body": "プロテイン20〜30g ＋ 糖質（バナナ・ご飯など）を摂取すると筋タンパク合成が最大化されます。"})

    # 睡眠
    advice.append({"icon": "😴", "cat": "睡眠",
                    "title": "睡眠が最強のリカバリー",
                    "body": "成長ホルモンは深い睡眠中に最も多く分泌されます。今夜は7〜9時間を確保し、就寝1時間前はスマホを置きましょう。"})

    # 水分
    advice.append({"icon": "💧", "cat": "水分",
                    "title": "水分補給を忘れずに",
                    "body": "トレーニング後2〜3時間かけて水500ml〜1L補給を。尿が薄い黄色になれば十分な水分量のサインです。"})

    # 翌日の目安
    if intensity == "high":
        advice.append({"icon": "🗓️", "cat": "翌日の目安",
                        "title": "明日の身体の状態を確認",
                        "body": "軽い筋肉痛→回復が順調なサイン。強い痛みや疲労感が残る場合はもう1日休息を。無理は逆効果です。"})
    else:
        advice.append({"icon": "🗓️", "cat": "翌日の目安",
                        "title": "明日は積極的リカバリーを",
                        "body": "ウォーキングや軽いストレッチで血流を促進すると回復が早まります。翌日のコンディションも記録してみましょう。"})

    return advice, intensity
