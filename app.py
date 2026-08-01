"""Workout Report Web App."""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import datetime
import os
import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "workout-secret-key-dev")

_JST = datetime.timezone(datetime.timedelta(hours=9))

def _today() -> datetime.date:
    return datetime.datetime.now(_JST).date()

def _now_jst() -> datetime.datetime:
    return datetime.datetime.now(_JST)


def run_migrations():
    import psycopg2
    from db import _DATABASE_URL
    conn = psycopg2.connect(_DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        sql = f.read()
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        try:
            cur.execute(stmt)
        except Exception:
            pass
    # Seed weekly_schedule
    cur.execute("SELECT COUNT(*) FROM weekly_schedule")
    if cur.fetchone()[0] == 0:
        for dow in range(7):
            cur.execute(
                "INSERT INTO weekly_schedule (day_of_week) VALUES (%s) ON CONFLICT DO NOTHING",
                (dow,)
            )
    cur.close()
    conn.close()


run_migrations()

# body_part → card background tint  (上肢 / 下肢 / 体幹)
_CATEGORY_BG = {
    "上肢": "rgba(10,132,255,0.16)",   # blue
    "下肢": "rgba(255,159,10,0.16)",   # orange
    "体幹": "rgba(0,199,190,0.16)",    # mint
}

CATEGORY_LEGEND = [
    {"label": "上肢", "rgb": "10,132,255"},
    {"label": "下肢", "rgb": "255,159,10"},
    {"label": "体幹", "rgb": "0,199,190"},
]

_CATEGORY_RGB = {
    "上肢": "10,132,255",
    "下肢": "255,159,10",
    "体幹": "0,199,190",
}
app.jinja_env.globals['category_bg']     = lambda bp: _CATEGORY_BG.get(bp or "", "")
app.jinja_env.globals['category_bg_rgb'] = lambda bp: _CATEGORY_RGB.get(bp or "", "128,128,128")
app.jinja_env.globals['category_legend'] = CATEGORY_LEGEND


def _parse_date(s: str):
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _parse_bool(s: str) -> bool:
    return str(s).lower() == "true"


def _parse_float(s):
    try:
        v = float(s)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_int(s):
    try:
        v = int(s)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


# ── Sessions ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    stats = db.get_dashboard_stats()
    today_plan = db.get_today_schedule()
    today_training_plan = db.get_today_plan()
    latest_weight = db.get_latest_weight()
    today_session = db.get_today_session()
    exp_trend = db.get_exp_trend(8)
    weight_trend = db.get_weight_trend(14)
    personal_records = db.get_personal_records(6)
    return render_template("dashboard.html",
                           stats=stats,
                           today_plan=today_plan,
                           today_training_plan=today_training_plan,
                           latest_weight=latest_weight,
                           today_session=today_session,
                           today=_today(),
                           exp_trend=exp_trend,
                           weight_trend=weight_trend,
                           personal_records=personal_records)


@app.route("/today")
def today():
    row = db.get_today_session()
    if row:
        return redirect(url_for("session_detail", session_id=row["id"]))
    session_id = db.create_session(
        session_date=_today(),
        start_time=_now_jst().strftime("%H:%M"),
        end_time=None,
        rep_count=None,
    )
    flash("今日のセッションを作成しました。", "success")
    return redirect(url_for("session_detail", session_id=session_id))


# ── Today training plan ────────────────────────────────────────────────────────

@app.route("/today-plan/new")
def today_plan_new():
    my_set_id = _parse_int(request.args.get("my_set_id"))
    my_set = db.get_my_set(my_set_id) if my_set_id else None
    today = _today()
    dow = ["月", "火", "水", "木", "金", "土", "日"][today.weekday()]
    preset_name = f"{today.month}/{today.day}({dow})"
    if my_set:
        preset_name += f"_{my_set['name']}"
    return render_template("today_plan/form.html",
                           preset_name=preset_name,
                           my_set=my_set,
                           today=today)


@app.route("/today-plan/save", methods=["POST"])
def today_plan_save():
    name = request.form.get("name", "").strip()
    my_set_id = _parse_int(request.form.get("my_set_id"))
    if not name:
        flash("名前を入力してください", "warning")
        return redirect(request.referrer or url_for("dashboard"))
    db.save_today_plan(_today(), name, my_set_id)
    flash(f"「{name}」を今日のプランとして保存しました", "success")
    return redirect(url_for("dashboard"))


@app.route("/today-plan/<int:plan_id>/start", methods=["POST"])
def today_plan_start(plan_id):
    session_id = db.start_today_plan(plan_id)
    return redirect(url_for("session_detail", session_id=session_id))


@app.route("/today-plan/<int:plan_id>/delete", methods=["POST"])
def today_plan_delete(plan_id):
    db.delete_today_plan(plan_id)
    flash("今日のプランをキャンセルしました", "success")
    return redirect(url_for("dashboard"))


@app.route("/my-sets/<int:my_set_id>/start-now", methods=["POST"])
def my_set_start_now(my_set_id):
    """Create session immediately from a my_set and redirect to it."""
    today = _today()
    dow = ["月", "火", "水", "木", "金", "土", "日"][today.weekday()]
    row = db.get_today_session()
    if row:
        session_id = row["id"]
    else:
        session_id = db.create_session(
            session_date=today,
            start_time=_now_jst().strftime("%H:%M"),
            end_time=None,
            rep_count=None,
        )
    db.copy_my_set_to_session(my_set_id, session_id)
    flash("マイセットを適用してトレーニングを開始しました", "success")
    return redirect(url_for("session_detail", session_id=session_id))


@app.route("/sessions")
def sessions_list():
    sessions = db.list_sessions()
    return render_template("sessions/list.html", sessions=sessions)


@app.route("/sessions/new", methods=["GET", "POST"])
def session_new():
    if request.method == "POST":
        d = _parse_date(request.form.get("session_date", ""))
        if not d:
            flash("日付を入力してください。", "danger")
            return render_template("sessions/form.html",
                                   session=None,
                                   today=_today().isoformat())
        session_id = db.create_session(
            session_date=d,
            start_time=request.form.get("start_time") or None,
            end_time=request.form.get("end_time") or None,
            rep_count=_parse_int(request.form.get("rep_count")),
        )
        flash("セッションを作成しました。", "success")
        return redirect(url_for("session_detail", session_id=session_id))

    return render_template("sessions/form.html",
                           session=None,
                           today=_today().isoformat())


@app.route("/sessions/<int:session_id>")
def session_detail(session_id):
    session, exercises = db.get_session_with_exercises(session_id)
    if session is None:
        flash("セッションが見つかりません。", "danger")
        return redirect(url_for("sessions_list"))
    category_exp = {"上肢": 0, "下肢": 0, "体幹": 0}
    prev_map = db.get_prev_exercise_values_batch(session_id)
    merged = []
    for ex in exercises:
        ex = dict(ex)
        bp = ex.get("body_part")
        if bp in category_exp:
            category_exp[bp] += ex.get("exp_earned") or 0
        prev = prev_map.get(ex["exercise_id"])
        if prev:
            prev_mode      = prev.get("load_mode") or "high"
            prev_high_reps = prev.get("reps")     or 8
            prev_low_reps  = prev.get("reps_low") or 20
            # Show what was ACTUALLY done in the prev session (prev session's own mode)
            if prev_mode == "low":
                ex["prev_weight"] = prev.get("weight_low_load")
                ex["prev_reps"]   = prev_low_reps
            else:
                ex["prev_weight"] = prev.get("weight_setting")
                ex["prev_reps"]   = prev_high_reps
            ex["prev_sets"]        = prev.get("sets_done")
            ex["prev_mode"]        = prev_mode
            ex["prev_high_weight"] = prev.get("weight_setting")
            ex["prev_high_reps"]   = prev_high_reps
            ex["prev_low_weight"]  = prev.get("weight_low_load")
            ex["prev_low_reps"]    = prev_low_reps
        merged.append(ex)
    return render_template("sessions/detail.html",
                           session=session, exercises=merged,
                           category_exp=category_exp)


@app.route("/sessions/<int:session_id>/edit", methods=["GET", "POST"])
def session_edit(session_id):
    session = db.get_session(session_id)
    if session is None:
        flash("セッションが見つかりません。", "danger")
        return redirect(url_for("sessions_list"))

    if request.method == "POST":
        d = _parse_date(request.form.get("session_date", ""))
        if not d:
            flash("日付を入力してください。", "danger")
            return render_template("sessions/form.html", session=session)
        db.update_session(
            session_id=session_id,
            session_date=d,
            start_time=request.form.get("start_time") or None,
            end_time=request.form.get("end_time") or None,
            rep_count=_parse_int(request.form.get("rep_count")),
        )
        flash("セッションを更新しました。", "success")
        return redirect(url_for("session_detail", session_id=session_id))

    return render_template("sessions/form.html", session=session)


@app.route("/sessions/<int:session_id>/delete", methods=["POST"])
def session_delete(session_id):
    db.delete_session(session_id)
    flash("セッションを削除しました。", "success")
    return redirect(url_for("sessions_list"))


# ── Session exercises ─────────────────────────────────────────────────────────

@app.route("/sessions/<int:session_id>/exercises/new", methods=["GET", "POST"])
def exercise_new(session_id):
    session = db.get_session(session_id)
    if session is None:
        return redirect(url_for("sessions_list"))

    exercises = db.list_exercises()

    if request.method == "POST":
        exercise_id = _parse_int(request.form.get("exercise_id"))
        if not exercise_id:
            flash("種目を選択してください。", "danger")
            return render_template("exercises/form.html",
                                   session=session, se=None, exercises=exercises,
                                   last_values=None)
        one_rep_max = _parse_float(request.form.get("one_rep_max"))
        db.create_session_exercise(
            session_id=session_id,
            exercise_id=exercise_id,
            one_rep_max=one_rep_max,
            weight_setting=_parse_float(request.form.get("weight_setting")),
            weight_low_load=_parse_float(request.form.get("weight_low_load")),
            reps=_parse_int(request.form.get("reps")),
            set1=_parse_bool(request.form.get("set1_completed", "false")),
            set2=_parse_bool(request.form.get("set2_completed", "false")),
            set3=_parse_bool(request.form.get("set3_completed", "false")),
            exp_earned=_parse_int(request.form.get("exp_earned")) or 0,
            muscle_groups=request.form.get("muscle_groups") or None,
        )
        if one_rep_max:
            db.update_exercise_one_rep_max(exercise_id, one_rep_max)
        flash("種目を追加しました。", "success")
        return redirect(url_for("session_detail", session_id=session_id))

    prefill_id = _parse_int(request.args.get("exercise_id"))
    last_values = db.get_last_exercise_values(prefill_id, exclude_session_id=session_id) if prefill_id else None
    return render_template("exercises/form.html",
                           session=session, se=None, exercises=exercises,
                           last_values=last_values, prefill_exercise_id=prefill_id)


@app.route("/sessions/<int:session_id>/exercises/<int:se_id>/edit", methods=["GET", "POST"])
def exercise_edit(session_id, se_id):
    session = db.get_session(session_id)
    se = db.get_session_exercise(se_id)
    if session is None or se is None:
        return redirect(url_for("session_detail", session_id=session_id))

    exercises = db.list_exercises()

    if request.method == "POST":
        exercise_id = _parse_int(request.form.get("exercise_id"))
        if not exercise_id:
            flash("種目を選択してください。", "danger")
            return render_template("exercises/form.html",
                                   session=session, se=se, exercises=exercises)
        one_rep_max = _parse_float(request.form.get("one_rep_max"))
        db.update_session_exercise(
            se_id=se_id,
            session_id=session_id,
            exercise_id=exercise_id,
            one_rep_max=one_rep_max,
            weight_setting=_parse_float(request.form.get("weight_setting")),
            weight_low_load=_parse_float(request.form.get("weight_low_load")),
            reps=_parse_int(request.form.get("reps")),
            set1=_parse_bool(request.form.get("set1_completed", "false")),
            set2=_parse_bool(request.form.get("set2_completed", "false")),
            set3=_parse_bool(request.form.get("set3_completed", "false")),
            exp_earned=_parse_int(request.form.get("exp_earned")) or 0,
            muscle_groups=request.form.get("muscle_groups") or None,
        )
        if one_rep_max:
            db.update_exercise_one_rep_max(exercise_id, one_rep_max)
        flash("種目を更新しました。", "success")
        return redirect(url_for("session_detail", session_id=session_id))

    return render_template("exercises/form.html",
                           session=session, se=se, exercises=exercises)


@app.route("/sessions/<int:session_id>/exercises/<int:se_id>/delete", methods=["POST"])
def exercise_delete(session_id, se_id):
    db.delete_session_exercise(se_id, session_id)
    flash("種目を削除しました。", "success")
    return redirect(url_for("session_detail", session_id=session_id))


# ── Copy session ─────────────────────────────────────────────────────────────

@app.route("/sessions/<int:session_id>/copy-from")
def session_copy_from(session_id):
    session = db.get_session(session_id)
    if session is None:
        return redirect(url_for("sessions_list"))
    candidates = db.get_recent_sessions_for_copy(exclude_session_id=session_id, limit=2)
    return render_template("sessions/copy_from.html",
                           session=session, candidates=candidates)


@app.route("/sessions/<int:session_id>/copy-from/<int:from_id>", methods=["POST"])
def session_copy_execute(session_id, from_id):
    copy_type = request.form.get("copy_type", "full")
    count = db.copy_exercises_to_session(
        from_session_id=from_id, to_session_id=session_id, copy_type=copy_type
    )
    flash(f"{count} 種目をコピーしました。", "success")
    return redirect(url_for("session_detail", session_id=session_id))


# ── Weekly schedule ───────────────────────────────────────────────────────────

@app.route("/weekly-plan")
def weekly_plan():
    schedule = db.get_weekly_schedule()
    my_sets = db.list_my_sets()
    return render_template("weekly_plan.html", schedule=schedule, my_sets=my_sets)


@app.route("/weekly-plan/<int:dow>", methods=["GET", "POST"])
def weekly_plan_edit(dow):
    if dow not in range(7):
        return redirect(url_for("weekly_plan"))
    schedule = db.get_weekly_schedule()
    day = next((s for s in schedule if s["day_of_week"] == dow), None)
    my_sets = db.list_my_sets()
    if request.method == "POST":
        db.update_weekly_schedule(
            day_of_week=dow,
            location=request.form.get("location", "gym"),
            my_set_id=_parse_int(request.form.get("my_set_id")),
            notes=request.form.get("notes", ""),
        )
        flash("スケジュールを更新しました。", "success")
        return redirect(url_for("weekly_plan"))
    return render_template("weekly_plan_edit.html", day=day, dow=dow, my_sets=my_sets)


# ── Body weight log ───────────────────────────────────────────────────────────

@app.route("/weight")
def weight_log():
    logs = db.list_weight_log(limit=60)
    latest = db.get_latest_weight()
    return render_template("weight_log.html", logs=logs, latest=latest,
                           today=_today().isoformat())


@app.route("/weight/add", methods=["POST"])
def weight_add():
    d = _parse_date(request.form.get("logged_date", ""))
    w = _parse_float(request.form.get("weight_kg"))
    if not d or not w:
        flash("日付と体重を入力してください。", "danger")
        return redirect(url_for("weight_log"))
    db.upsert_weight(d, w, request.form.get("notes", ""))
    flash("体重を記録しました。", "success")
    return redirect(url_for("weight_log"))


@app.route("/weight/delete/<string:logged_date>", methods=["POST"])
def weight_delete(logged_date):
    d = _parse_date(logged_date)
    if d:
        with db._conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM body_weight_log WHERE logged_date=%s", (d,))
    flash("削除しました。", "success")
    return redirect(url_for("weight_log"))


# ── Session finish & advice ───────────────────────────────────────────────────

@app.route("/sessions/<int:session_id>/finish", methods=["GET", "POST"])
def session_finish(session_id):
    session = db.get_session(session_id)
    if session is None:
        return redirect(url_for("sessions_list"))
    if request.method == "POST":
        db.finish_session(session_id, request.form.get("post_notes", ""))
        return redirect(url_for("session_advice", session_id=session_id))
    session_obj, exercises = db.get_session_with_exercises(session_id)
    return render_template("sessions/finish.html", session=session_obj, exercises=exercises)


@app.route("/sessions/<int:session_id>/advice")
def session_advice(session_id):
    session, exercises = db.get_session_with_exercises(session_id)
    if session is None:
        return redirect(url_for("sessions_list"))
    advice, intensity, overload_tips = db.build_advice(session, exercises)
    completed_count = sum(
        1 for ex in exercises
        if ex["set1_completed"] and ex["set2_completed"] and ex["set3_completed"]
    )
    bw_row = db.get_latest_weight()
    body_weight = float(bw_row["weight_kg"]) if bw_row else 65.0
    volume_metrics = db.build_volume_metrics(session, exercises, body_weight)

    # Per-exercise comparison with previous session
    prev_map = db.get_prev_exercise_values_batch(session_id)
    comparison = []
    growth_count = save_count = same_count = new_count = skip_count = 0
    for ex in exercises:
        mode       = ex.get("load_mode") or "high"
        cur_weight = ex.get("weight_low_load") if mode == "low" else ex.get("weight_setting")
        cur_reps   = int(ex.get("reps_low") or 20) if mode == "low" else int(ex.get("reps") or 8)
        cur_sets   = sum(1 for i in range(1, 7) if ex.get(f"set{i}_completed"))
        is_skipped = bool(ex.get("skipped"))

        prev = prev_map.get(ex["exercise_id"])
        if prev:
            prev_weight = prev.get("weight_low_load") if mode == "low" else prev.get("weight_setting")
            prev_reps   = int(prev.get("reps_low") or 20) if mode == "low" else int(prev.get("reps") or 8)
            prev_sets   = int(prev.get("sets_done") or 0)
            w_diff = round(float(cur_weight or 0) - float(prev_weight or 0), 1) \
                     if cur_weight is not None and prev_weight is not None else None
            r_diff = (cur_reps - prev_reps) if not is_skipped else None
            s_diff = (cur_sets - prev_sets) if not is_skipped else None
            if is_skipped:
                status = "skipped"; skip_count += 1
            elif (w_diff and w_diff > 0) or (r_diff and r_diff > 0) or \
                 (w_diff == 0 and r_diff == 0 and s_diff and s_diff > 0):
                status = "growth"; growth_count += 1
            elif (w_diff and w_diff < 0) or (r_diff and r_diff < 0) or \
                 (s_diff is not None and s_diff < 0):
                status = "save"; save_count += 1
            else:
                status = "same"; same_count += 1
        else:
            prev_weight = prev_reps = prev_sets = None
            w_diff = r_diff = s_diff = None
            if is_skipped:
                status = "skipped"; skip_count += 1
            else:
                status = "new"; new_count += 1

        comparison.append({
            "name":        ex["exercise_name"],
            "body_part":   ex.get("body_part") or "",
            "mode":        mode,
            "cur_weight":  cur_weight,
            "cur_reps":    cur_reps,
            "cur_sets":    cur_sets,
            "prev_weight": prev_weight,
            "prev_reps":   prev_reps,
            "prev_sets":   prev_sets,
            "w_diff":      w_diff,
            "r_diff":      r_diff,
            "s_diff":      s_diff,
            "status":      status,
            "skipped":     is_skipped,
        })

    cmp_summary = {"growth": growth_count, "save": save_count,
                   "same": same_count, "new": new_count, "skip": skip_count}

    return render_template("sessions/advice.html",
                           session=session, exercises=exercises,
                           advice=advice, intensity=intensity,
                           overload_tips=overload_tips,
                           completed_count=completed_count,
                           volume_metrics=volume_metrics,
                           body_weight=body_weight,
                           comparison=comparison,
                           cmp_summary=cmp_summary)


# ── Reorder (AJAX) ───────────────────────────────────────────────────────────

@app.route("/my-sets/<int:my_set_id>/exercises/reorder", methods=["POST"])
def my_set_exercises_reorder(my_set_id):
    ids = request.json.get("ids", [])
    if not ids:
        return jsonify({"error": "no ids"}), 400
    db.reorder_my_set_exercises(my_set_id, [int(i) for i in ids])
    return jsonify({"ok": True})


@app.route("/sessions/<int:session_id>/exercises/reorder", methods=["POST"])
def session_exercises_reorder(session_id):
    ids = request.json.get("ids", [])
    if not ids:
        return jsonify({"error": "no ids"}), 400
    db.reorder_session_exercises(session_id, [int(i) for i in ids])
    return jsonify({"ok": True})


@app.route("/sessions/<int:session_id>/exercises/bulk-delete", methods=["POST"])
def session_exercises_bulk_delete(session_id):
    se_ids = [int(x) for x in request.form.getlist("se_ids") if x.isdigit()]
    if se_ids:
        db.bulk_delete_session_exercises(session_id, se_ids)
    return redirect(url_for("session_detail", session_id=session_id))


# ── Session EXP recalculate (AJAX) ────────────────────────────────────────────

@app.route("/api/sessions/<int:session_id>/recalculate-exp", methods=["POST"])
def session_recalculate_exp(session_id):
    result = db.recalculate_all_exp(session_id)
    return jsonify(result)


# ── Inline set toggle (AJAX) ──────────────────────────────────────────────────

@app.route("/api/se/<int:se_id>/toggle/<int:set_num>", methods=["POST"])
def toggle_set(se_id, set_num):
    if set_num not in range(1, 11):
        return jsonify({"error": "invalid set_num"}), 400
    result = db.toggle_set_completion(se_id, set_num)
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@app.route("/api/se/<int:se_id>/skip", methods=["POST"])
def api_toggle_skip(se_id):
    result = db.toggle_skip_exercise(se_id)
    return jsonify(result)


@app.route("/api/se/<int:se_id>/complete", methods=["POST"])
def api_toggle_complete(se_id):
    result = db.toggle_complete_exercise(se_id)
    return jsonify(result)


@app.route("/api/se/<int:se_id>/quick-edit", methods=["POST"])
def api_quick_edit_se(se_id):
    data = request.get_json(force=True) or {}
    kwargs = dict(
        one_rep_max=data.get("one_rep_max"),
        reps=data.get("reps"),
        low_load_pct=data.get("low_load_pct"),
        load_mode=data.get("load_mode"),
    )
    if "bench_angle" in data:
        kwargs["bench_angle"] = data.get("bench_angle")
    result = db.quick_edit_se(se_id, **kwargs)
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@app.route("/api/sessions/<int:session_id>/apply-overload-tip", methods=["POST"])
def api_apply_overload_tip(session_id):
    data = request.get_json(force=True) or {}
    se_id = data.get("se_id")
    action = data.get("action")
    new_value = data.get("new_value")
    se = db.get_session_exercise(se_id)
    if se is None:
        return jsonify({"error": "not found"}), 404
    count = db.apply_overload_tip(se["exercise_id"], action, new_value)
    return jsonify({"updated": count, "exercise_name": se.get("exercise_name", "")})


@app.route("/my-sets/<int:my_set_id>/sync-from-latest", methods=["POST"])
def my_set_sync_from_latest(my_set_id):
    my_set = db.get_my_set(my_set_id)
    if my_set is None:
        return jsonify({"error": "not found"}), 404
    count = db.sync_my_set_from_latest(my_set_id)
    return jsonify({"synced": count})


@app.route("/api/exercise/<int:exercise_id>/clear-lvup", methods=["POST"])
def api_clear_lvup(exercise_id):
    data = request.get_json(force=True) or {}
    lvup_type = data.get("type", "high")
    if lvup_type not in ("high", "low"):
        return jsonify({"error": "invalid type"}), 400
    db.clear_lvup(exercise_id, lvup_type)
    return jsonify({"ok": True})


@app.route("/api/mse/<int:mse_id>/quick-edit", methods=["POST"])
def api_quick_edit_mse(mse_id):
    data = request.get_json() or {}
    result = db.quick_edit_mse(
        mse_id,
        target_sets  = data.get("target_sets"),
        reps         = data.get("reps"),
        one_rep_max  = data.get("one_rep_max"),
        low_load_pct = data.get("low_load_pct"),
    )
    if not result:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


# ── My Sets ───────────────────────────────────────────────────────────────────

@app.route("/my-sets")
def my_sets_list():
    my_sets = db.list_my_sets()
    return render_template("my_sets/list.html", my_sets=my_sets)


@app.route("/my-sets/new", methods=["GET", "POST"])
def my_set_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        location = request.form.get("location", "gym")
        use_preset = request.form.get("use_preset") == "1"
        if not name:
            flash("名前を入力してください。", "danger")
            return render_template("my_sets/form.html", my_set=None)
        try:
            my_set_id = db.create_my_set(name, request.form.get("description", ""), location)
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                existing = db.find_my_set_by_name(name)
                if existing:
                    flash(f"「{name}」は既に存在します。", "warning")
                    return redirect(url_for("my_set_detail", my_set_id=existing["id"]))
            flash("作成に失敗しました。もう一度お試しください。", "danger")
            app.logger.exception("create_my_set failed")
            return render_template("my_sets/form.html", my_set=None)
        if location == "home" and use_preset:
            db.seed_home_preset_exercises(my_set_id)
        flash(f"「{name}」を作成しました。", "success")
        return redirect(url_for("my_set_detail", my_set_id=my_set_id))
    return render_template("my_sets/form.html", my_set=None)


@app.route("/my-sets/<int:my_set_id>")
def my_set_detail(my_set_id):
    my_set, exercises = db.get_my_set_with_exercises(my_set_id)
    if my_set is None:
        return redirect(url_for("my_sets_list"))
    all_exercises = db.list_exercises()

    # 理論EXP計算
    BODY_WEIGHT = 65.0
    cat_exp = {"上肢": 0, "下肢": 0, "体幹": 0}
    exercises_list = []
    for ex in exercises:
        ex = dict(ex)
        bw = ex.get("bodyweight_ratio")
        w  = (BODY_WEIGHT * bw) if bw else (ex.get("weight_setting") or 0)
        ex["theoretical_exp"] = round(w * (ex.get("reps") or 10) * (ex.get("target_sets") or 3))
        bp = ex.get("body_part") or ""
        if bp in cat_exp:
            cat_exp[bp] += ex["theoretical_exp"]
        exercises_list.append(ex)
    total_exp = sum(cat_exp.values())

    return render_template("my_sets/detail.html",
                           my_set=my_set, exercises=exercises_list,
                           all_exercises=all_exercises,
                           cat_exp=cat_exp, total_exp=total_exp)


@app.route("/my-sets/<int:my_set_id>/edit", methods=["GET", "POST"])
def my_set_edit(my_set_id):
    my_set = db.get_my_set(my_set_id)
    if my_set is None:
        return redirect(url_for("my_sets_list"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("名前を入力してください。", "danger")
            return render_template("my_sets/form.html", my_set=my_set)
        db.update_my_set(my_set_id, name, request.form.get("description", ""))
        flash("更新しました。", "success")
        return redirect(url_for("my_set_detail", my_set_id=my_set_id))
    return render_template("my_sets/form.html", my_set=my_set)


@app.route("/my-sets/<int:my_set_id>/delete", methods=["POST"])
def my_set_delete(my_set_id):
    db.delete_my_set(my_set_id)
    flash("削除しました。", "success")
    return redirect(url_for("my_sets_list"))


@app.route("/exercises/<int:exercise_id>/quick-data")
def exercise_quick_data(exercise_id):
    data = db.get_exercise_quick_data(exercise_id)
    if data is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)


@app.route("/my-sets/<int:my_set_id>/exercises/new", methods=["GET", "POST"])
def my_set_exercise_new(my_set_id):
    my_set = db.get_my_set(my_set_id)
    if my_set is None:
        return redirect(url_for("my_sets_list"))
    _loc = my_set.get("location") or "gym"
    all_exercises = db.list_exercises_by_location(_loc)
    muscles = db.list_muscles()
    if request.method == "POST":
        exercise_id = _parse_int(request.form.get("exercise_id"))
        if not exercise_id:
            flash("種目を選択してください。", "danger")
            return render_template("my_sets/exercise_form.html",
                                   my_set=my_set, mse=None,
                                   all_exercises=all_exercises, muscles=muscles)
        selected_muscles = [m for m in request.form.getlist("muscle_groups") if m]
        muscle_groups = ",".join(selected_muscles) if selected_muscles else None
        try:
            db.create_my_set_exercise(
                my_set_id=my_set_id,
                exercise_id=exercise_id,
                one_rep_max=_parse_float(request.form.get("one_rep_max")),
                weight_setting=_parse_float(request.form.get("weight_setting")),
                weight_low_load=_parse_float(request.form.get("weight_low_load")),
                reps=_parse_int(request.form.get("reps")),
                reps_low=_parse_int(request.form.get("reps_low")),
                muscle_groups=muscle_groups,
            )
        except Exception as e:
            import logging
            logging.exception("create_my_set_exercise failed")
            flash(f"保存に失敗しました: {e}", "danger")
            return render_template("my_sets/exercise_form.html",
                                   my_set=my_set, mse=None,
                                   all_exercises=all_exercises, muscles=muscles)
        flash("種目を追加しました。", "success")
        return redirect(url_for("my_set_detail", my_set_id=my_set_id))
    return render_template("my_sets/exercise_form.html",
                           my_set=my_set, mse=None,
                           all_exercises=all_exercises, muscles=muscles)


@app.route("/my-sets/<int:my_set_id>/exercises/<int:mse_id>/edit", methods=["GET", "POST"])
def my_set_exercise_edit(my_set_id, mse_id):
    my_set = db.get_my_set(my_set_id)
    if my_set is None:
        return redirect(url_for("my_sets_list"))
    _loc = my_set.get("location") or "gym"
    all_exercises = db.list_exercises_by_location(_loc)
    muscles = db.list_muscles()
    if request.method == "POST":
        exercise_id = _parse_int(request.form.get("exercise_id"))
        if not exercise_id:
            flash("種目を選択してください。", "danger")
        else:
            selected_muscles = [m for m in request.form.getlist("muscle_groups") if m]
            muscle_groups = ",".join(selected_muscles) if selected_muscles else None
            try:
                db.update_my_set_exercise(
                    mse_id=mse_id,
                    exercise_id=exercise_id,
                    one_rep_max=_parse_float(request.form.get("one_rep_max")),
                    weight_setting=_parse_float(request.form.get("weight_setting")),
                    weight_low_load=_parse_float(request.form.get("weight_low_load")),
                    reps=_parse_int(request.form.get("reps")),
                    reps_low=_parse_int(request.form.get("reps_low")),
                    muscle_groups=muscle_groups,
                )
            except Exception as e:
                import logging
                logging.exception("update_my_set_exercise failed")
                flash(f"保存に失敗しました: {e}", "danger")
            else:
                flash("更新しました。", "success")
                return redirect(url_for("my_set_detail", my_set_id=my_set_id))
    with db._conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM my_set_exercises WHERE id = %s", (mse_id,))
        mse = cur.fetchone()
    return render_template("my_sets/exercise_form.html",
                           my_set=my_set, mse=mse,
                           all_exercises=all_exercises, muscles=muscles)


@app.route("/my-sets/<int:my_set_id>/exercises/<int:mse_id>/delete", methods=["POST"])
def my_set_exercise_delete(my_set_id, mse_id):
    db.delete_my_set_exercise(mse_id)
    flash("削除しました。", "success")
    return redirect(url_for("my_set_detail", my_set_id=my_set_id))


@app.route("/my-sets/<int:my_set_id>/exercises/bulk-delete", methods=["POST"])
def my_set_exercises_bulk_delete(my_set_id):
    mse_ids = [int(x) for x in request.form.getlist("mse_ids") if x.isdigit()]
    if mse_ids:
        db.bulk_delete_my_set_exercises(my_set_id, mse_ids)
    return redirect(url_for("my_set_detail", my_set_id=my_set_id))


@app.route("/my-sets/<int:my_set_id>/load-from-session")
def my_set_load_from_session(my_set_id):
    my_set = db.get_my_set(my_set_id)
    if my_set is None:
        return redirect(url_for("my_sets_list"))
    candidates = db.get_recent_sessions_for_copy(limit=5)
    return render_template("my_sets/load_from_session.html",
                           my_set=my_set, candidates=candidates)


@app.route("/my-sets/<int:my_set_id>/load-from-session/<int:session_id>", methods=["POST"])
def my_set_load_from_session_execute(my_set_id, session_id):
    my_set = db.get_my_set(my_set_id)
    if my_set is None:
        return redirect(url_for("my_sets_list"))
    count = db.copy_session_to_my_set(session_id=session_id, my_set_id=my_set_id)
    flash(f"{count} 種目を読み込みました。内容を確認・編集してください。", "success")
    return redirect(url_for("my_set_detail", my_set_id=my_set_id))


@app.route("/sessions/<int:session_id>/apply-my-set")
def session_apply_my_set(session_id):
    session = db.get_session(session_id)
    if session is None:
        return redirect(url_for("sessions_list"))
    my_sets = db.list_my_sets()
    return render_template("sessions/apply_my_set.html",
                           session=session, my_sets=my_sets)


@app.route("/sessions/<int:session_id>/apply-my-set/<int:my_set_id>", methods=["POST"])
def session_apply_my_set_execute(session_id, my_set_id):
    count = db.copy_my_set_to_session(my_set_id=my_set_id, session_id=session_id)
    my_set = db.get_my_set(my_set_id)
    flash(f"「{my_set['name']}」から {count} 種目をコピーしました。", "success")
    return redirect(url_for("session_detail", session_id=session_id))


# ── Exercises index ───────────────────────────────────────────────────────────

@app.route("/exercises")
def exercises_index():
    import unicodedata
    from collections import defaultdict
    exercises = db.list_exercises_with_latest_data()
    null_count = sum(1 for ex in exercises if not ex['has_log_data'])
    # 重複検出（NFKC正規化で同一とみなせる種目）
    name_groups = defaultdict(int)
    for ex in exercises:
        norm = unicodedata.normalize('NFKC', ex['name']).strip()
        name_groups[norm] += 1
    dup_count = sum(1 for c in name_groups.values() if c > 1)
    return render_template("exercises/index.html", exercises=exercises,
                           null_count=null_count, dup_count=dup_count)


@app.route("/exercises/auto-merge-duplicates", methods=["POST"])
def exercises_auto_merge_duplicates():
    merged = db.auto_merge_duplicate_exercises()
    if merged:
        names = "、".join(f"「{d}」→「{k}」" for k, d in merged)
        flash(f"{len(merged)} 件の重複を統合しました: {names}", "success")
    else:
        flash("重複する種目はありませんでした", "info")
    return redirect(url_for("exercises_index"))


# ── Exercise progress ─────────────────────────────────────────────────────────

@app.route("/exercises/<int:exercise_id>/progress")
def exercise_progress(exercise_id):
    exercise = db.get_exercise(exercise_id)
    if exercise is None:
        return redirect(url_for("sessions_list"))
    history = db.get_exercise_progress(exercise_id)
    max_1rm = max((r["one_rep_max"] for r in history if r["one_rep_max"]), default=1)
    return render_template("exercises/progress.html",
                           exercise=exercise, history=history, max_1rm=max_1rm)


@app.route("/muscles", methods=["GET", "POST"])
def muscles_index():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            name = request.form.get("name", "").strip()
            if name:
                db.create_muscle(name)
                flash(f"「{name}」を追加しました", "success")
        elif action == "delete":
            db.delete_muscle(int(request.form.get("muscle_id")))
            flash("削除しました", "success")
        elif action == "edit":
            db.update_muscle(int(request.form.get("muscle_id")),
                             request.form.get("name", ""))
            flash("更新しました", "success")
        return redirect(url_for("muscles_index"))
    muscles = db.list_muscles()
    return render_template("muscles/index.html", muscles=muscles)


@app.route("/exercises/bulk-edit", methods=["GET", "POST"])
def exercises_bulk_edit():
    exercises = db.list_exercises()
    muscles = db.list_muscles()
    if request.method == "POST":
        updates = [
            {
                "exercise_id": ex["id"],
                "body_part": request.form.get(f"body_part_{ex['id']}") or None,
                "needs_bench": request.form.get(f"needs_bench_{ex['id']}") == "on",
                "primary_muscle": request.form.get(f"primary_muscle_{ex['id']}") or None,
            }
            for ex in exercises
        ]
        db.bulk_update_exercise_meta(updates)
        flash("種目情報を一括更新しました", "success")
        return redirect(url_for("exercises_bulk_edit"))
    return render_template("exercises/bulk_edit.html", exercises=exercises, muscles=muscles)


@app.route("/exercises/<int:exercise_id>/edit", methods=["GET", "POST"])
def exercise_meta_edit(exercise_id):
    exercise = db.get_exercise(exercise_id)
    if exercise is None:
        return redirect(url_for("exercises_index"))
    if request.method == "POST":
        selected_muscles = request.form.getlist("primary_muscle")
        db.update_exercise_full(
            exercise_id,
            body_part=request.form.get("body_part") or None,
            needs_bench=request.form.get("needs_bench") == "on",
            primary_muscle=",".join(selected_muscles) if selected_muscles else None,
            one_rep_max=_parse_float(request.form.get("one_rep_max")),
            reps=_parse_int(request.form.get("reps")),
            weight_low_load=_parse_float(request.form.get("weight_low_load")),
            reps_low=_parse_int(request.form.get("reps_low")),
        )
        flash("種目情報を更新しました", "success")
        return redirect(url_for("exercises_index"))
    muscles = db.list_muscles()
    return render_template("exercises/meta_form.html", exercise=exercise, muscles=muscles)


@app.route("/exercises/<int:exercise_id>/delete", methods=["POST"])
def exercise_delete_master(exercise_id):
    error = db.delete_exercise(exercise_id)
    if error:
        flash(error, "danger")
    else:
        flash("種目を削除しました", "success")
    return redirect(url_for("exercises_index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
