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
                   ex.bodyweight_ratio, ex.is_time_based
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
            SET completed = NOT COALESCE(completed, false)
            WHERE id = %s
            RETURNING completed
        """, (se_id,))
        row = cur.fetchone()
    return {"completed": bool(row["completed"])}


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

        new_orm  = one_rep_max  if one_rep_max  is not None else se["one_rep_max"]
        new_reps = reps         if reps         is not None else se["reps"]
        new_pct  = float(low_load_pct) if low_load_pct is not None \
                   else float(se.get("low_load_pct") or 30)
        new_mode = load_mode if load_mode is not None else (se.get("load_mode") or "high")

        bw_ratio = se.get("bodyweight_ratio")
        if bw_ratio:
            bw_row = get_latest_weight()
            body_weight = float(bw_row["weight_kg"]) if bw_row else 65.0
            eff_weight = round(body_weight * bw_ratio, 1)
            new_ws = eff_weight
            new_wl = eff_weight
        elif new_orm:
            new_ws  = round(float(new_orm) * 0.8, 1)
            new_wl  = round(float(new_orm) * new_pct / 100, 1)
        else:
            new_ws = se["weight_setting"]
            new_wl = se["weight_low_load"]

        completions = {i: bool(se.get(f"set{i}_completed")) for i in range(1, 11)}
        completed_count = sum(1 for v in completions.values() if v)
        w = (new_wl if new_mode == "low" else new_ws) or (new_wl or new_ws)
        exp = round((w or 1) * (new_reps or 0) * completed_count)

        cur.execute("""
            UPDATE session_exercises
            SET one_rep_max=%s, weight_pct80=%s, weight_setting=%s, weight_low_load=%s,
                reps=%s, load_mode=%s, low_load_pct=%s, exp_earned=%s
            WHERE id = %s
        """, (new_orm, new_ws, new_ws, new_wl, new_reps, new_mode, new_pct, exp, se_id))
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
        "reps":              new_reps,
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
                   COUNT(mse.id) AS exercise_count
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
                   ex.body_part, ex.needs_bench, ex.primary_muscle,
                   ex.bodyweight_ratio
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
        if bw_ratio:
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


def copy_exercises_to_session(from_session_id: int, to_session_id: int,
                              copy_type: str = "full") -> int:
    """Copy all exercises from one session to another.
    copy_type='full'      : copy 1RM/weight/reps, reset set completions
    copy_type='menu_only' : copy exercise names only, clear weight/1RM/reps
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
            else:
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


def apply_overload_tip(exercise_id: int, action: str, new_value) -> int:
    """Apply a progressive overload suggestion to all my_set_exercises for this exercise."""
    with _conn() as conn:
        cur = conn.cursor()
        if action == "reps" and new_value is not None:
            cur.execute(
                "UPDATE my_set_exercises SET reps = %s WHERE exercise_id = %s",
                (int(new_value), exercise_id)
            )
        elif action == "low_load_pct" and new_value is not None:
            cur.execute(
                "UPDATE my_set_exercises SET reps_low = %s WHERE exercise_id = %s",
                (int(new_value), exercise_id)
            )
        return cur.rowcount


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


def build_advice(session, exercises: list) -> tuple:
    """Return (advice_list, intensity_label, overload_tips)."""
    total_exp = session["total_exp"] or 0

    if total_exp >= 8000:
        intensity = "high"
    elif total_exp >= 3000:
        intensity = "medium"
    else:
        intensity = "light"

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

    advice.append({"icon": "🍗", "cat": "栄養",
                    "title": "トレーニング後30分以内に",
                    "body": "プロテイン20〜30g ＋ 糖質（バナナ・ご飯など）を摂取すると筋タンパク合成が最大化されます。"})

    advice.append({"icon": "😴", "cat": "睡眠",
                    "title": "睡眠が最強のリカバリー",
                    "body": "成長ホルモンは深い睡眠中に最も多く分泌されます。今夜は7〜9時間を確保し、就寝1時間前はスマホを置きましょう。"})

    advice.append({"icon": "💧", "cat": "水分",
                    "title": "水分補給を忘れずに",
                    "body": "トレーニング後2〜3時間かけて水500ml〜1L補給を。尿が薄い黄色になれば十分な水分量のサインです。"})

    if intensity == "high":
        advice.append({"icon": "🗓️", "cat": "翌日の目安",
                        "title": "明日の身体の状態を確認",
                        "body": "軽い筋肉痛→回復が順調なサイン。強い痛みや疲労感が残る場合はもう1日休息を。無理は逆効果です。"})
    else:
        advice.append({"icon": "🗓️", "cat": "翌日の目安",
                        "title": "明日は積極的リカバリーを",
                        "body": "ウォーキングや軽いストレッチで血流を促進すると回復が早まります。翌日のコンディションも記録してみましょう。"})

    # ── 漸進性過負荷の分析 ────────────────────────────────────────────────────
    overload_tips = []
    for ex in exercises:
        name = ex.get("exercise_name") or "この種目"
        mode = ex.get("load_mode") or "high"
        reps = ex.get("reps") or 0
        done = sum(1 for i in range(1, 11) if ex.get(f"set{i}_completed"))
        if done < 3 or reps <= 0:
            continue

        se_id_val = ex.get("id")
        if mode == "low":
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
            elif reps < 30:
                new_reps = reps + 2
                overload_tips.append({
                    "icon": "📊", "name": name,
                    "title": "rep数を増やしましょう",
                    "body": f"低負荷{reps}rep × {done}セット達成！次回は {reps} → {new_reps} rep に増やしてみましょう。30repで重量アップです。",
                    "se_id": se_id_val, "action": "reps", "new_value": new_reps,
                })
        else:
            if reps >= 12:
                overload_tips.append({
                    "icon": "📈", "name": name,
                    "title": "次回は重量アップのチャンス！",
                    "body": f"高負荷{reps}rep × {done}セット達成！1RMを更新して重量を1段階上げましょう。重量アップ後はrep数を8に戻してOKです。",
                    "se_id": se_id_val, "action": "weight_up", "new_value": None,
                })
            else:
                new_reps = reps + 1
                overload_tips.append({
                    "icon": "📊", "name": name,
                    "title": f"次回は {new_reps} rep を目標に",
                    "body": f"高負荷{reps}rep × {done}セット達成！次回は {reps} → {new_reps} rep に増やしましょう。12repで重量アップです。",
                    "se_id": se_id_val, "action": "reps", "new_value": new_reps,
                })

    return advice, intensity, overload_tips


def recalculate_all_exp(session_id: int) -> dict:
    """全種目のEXPを現在の計算式で再計算してDBを更新する。"""
    bw_row = get_latest_weight()
    body_weight = float(bw_row["weight_kg"]) if bw_row else 65.0

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT se.*, ex.bodyweight_ratio
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
      has_bodyweight: bool
      purpose: str | None  (determined from session's my_set or exercise mix)
      fatigue_pct: int  (estimated CNS fatigue 0-100)
      neural_pct: int   (neural vs metabolic ratio 0-100)
      gym_eq_pct: int   (bodyweight volume as % of gym-equivalent)
    """
    cat_exp = {"上肢": 0, "下肢": 0, "体幹": 0}
    total_gym_volume = 0.0
    total_bw_volume  = 0.0
    gym_count        = 0
    bw_count         = 0
    heavy_sets       = 0
    total_sets       = 0

    for ex in exercises:
        bp = ex.get("body_part") or ""
        bw_ratio = ex.get("bodyweight_ratio")
        mode = ex.get("load_mode") or "high"
        reps = ex.get("reps") or 10

        if mode == "low":
            weight = ex.get("weight_low_load") or ex.get("weight_setting")
        else:
            weight = ex.get("weight_setting") or ex.get("weight_low_load")

        done = sum(1 for i in range(1, 11) if ex.get(f"set{i}_completed"))
        if done == 0:
            continue

        total_sets += done
        exp = ex.get("exp_earned") or 0

        if bw_ratio:
            bw_count += 1
            eff_weight = body_weight * bw_ratio
            bw_vol = eff_weight * reps * done
            total_bw_volume += bw_vol
            gym_eq = bw_vol
        else:
            gym_count += 1
            w = float(weight or 0)
            gym_eq = w * reps * done
            total_gym_volume += gym_eq
            if (weight or 0) >= 40:
                heavy_sets += done

        if bp in cat_exp:
            cat_exp[bp] += exp

    total_volume = total_gym_volume + total_bw_volume
    has_bodyweight = bw_count > 0 and gym_count == 0

    fatigue_pct = min(100, int(heavy_sets / max(total_sets, 1) * 100))

    if total_volume > 0:
        neural_pct = min(100, int(total_gym_volume / total_volume * 100))
        gym_eq_pct = min(100, int(total_bw_volume / total_volume * 100)) if has_bodyweight else 0
    else:
        neural_pct = 0
        gym_eq_pct = 0

    total_exp = session.get("total_exp") or 0
    if total_exp >= 500 and has_bodyweight and not total_gym_volume:
        purpose = "自宅メンテナンス"
    elif total_exp >= 8000:
        purpose = "筋肥大"
    elif total_exp >= 3000:
        purpose = "筋力向上"
    else:
        purpose = "維持・回復"

    return {
        "cat_exp":       cat_exp,
        "has_bodyweight": has_bodyweight,
        "purpose":        purpose,
        "fatigue_pct":    fatigue_pct,
        "neural_pct":     neural_pct,
        "gym_eq_pct":     gym_eq_pct,
    }
