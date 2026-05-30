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

app.jinja_env.globals['category_bg']     = lambda bp: _CATEGORY_BG.get(bp or "", "")
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
    return render_template("dashboard.html",
                           stats=stats,
                           today_plan=today_plan,
                           today_training_plan=today_training_plan,
                           latest_weight=latest_weight,
                           today_session=today_session,
                           today=_today())


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
    for ex in exercises:
        bp = ex.get("body_part")
        if bp in category_exp:
            category_exp[bp] += ex.get("exp_earned") or 0
    return render_template("sessions/detail.html",
                           session=session, exercises=exercises,
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
        db.create_session_exercise(
            session_id=session_id,
            exercise_id=exercise_id,
            one_rep_max=_parse_float(request.form.get("one_rep_max")),
            weight_setting=_parse_float(request.form.get("weight_setting")),
            weight_low_load=_parse_float(request.form.get("weight_low_load")),
            reps=_parse_int(request.form.get("reps")),
            set1=_parse_bool(request.form.get("set1_completed", "false")),
            set2=_parse_bool(request.form.get("set2_completed", "false")),
            set3=_parse_bool(request.form.get("set3_completed", "false")),
            exp_earned=_parse_int(request.form.get("exp_earned")) or 0,
            muscle_groups=request.form.get("muscle_groups") or None,
        )
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
        db.update_session_exercise(
            se_id=se_id,
            session_id=session_id,
            exercise_id=exercise_id,
            one_rep_max=_parse_float(request.form.get("one_rep_max")),
            weight_setting=_parse_float(request.form.get("weight_setting")),
            weight_low_load=_parse_float(request.form.get("weight_low_load")),
            reps=_parse_int(request.form.get("reps")),
            set1=_parse_bool(request.form.get("set1_completed", "false")),
            set2=_parse_bool(request.form.get("set2_completed", "false")),
            set3=_parse_bool(request.form.get("set3_completed", "false")),
            exp_earned=_parse_int(request.form.get("exp_earned")) or 0,
            muscle_groups=request.form.get("muscle_groups") or None,
        )
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
    count = db.copy_exercises_to_session(from_session_id=from_id, to_session_id=session_id)
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
    advice, intensity = db.build_advice(session, exercises)
    completed_count = sum(
        1 for ex in exercises
        if ex["set1_completed"] and ex["set2_completed"] and ex["set3_completed"]
    )
    return render_template("sessions/advice.html",
                           session=session, exercises=exercises,
                           advice=advice, intensity=intensity,
                           completed_count=completed_count)


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


# ── My Sets ───────────────────────────────────────────────────────────────────

@app.route("/my-sets")
def my_sets_list():
    my_sets = db.list_my_sets()
    return render_template("my_sets/list.html", my_sets=my_sets)


@app.route("/my-sets/new", methods=["GET", "POST"])
def my_set_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("名前を入力してください。", "danger")
            return render_template("my_sets/form.html", my_set=None)
        my_set_id = db.create_my_set(name, request.form.get("description", ""))
        flash(f"「{name}」を作成しました。", "success")
        return redirect(url_for("my_set_detail", my_set_id=my_set_id))
    return render_template("my_sets/form.html", my_set=None)


@app.route("/my-sets/<int:my_set_id>")
def my_set_detail(my_set_id):
    my_set, exercises = db.get_my_set_with_exercises(my_set_id)
    if my_set is None:
        return redirect(url_for("my_sets_list"))
    all_exercises = db.list_exercises()
    return render_template("my_sets/detail.html",
                           my_set=my_set, exercises=exercises, all_exercises=all_exercises)


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


@app.route("/my-sets/<int:my_set_id>/exercises/new", methods=["GET", "POST"])
def my_set_exercise_new(my_set_id):
    my_set = db.get_my_set(my_set_id)
    if my_set is None:
        return redirect(url_for("my_sets_list"))
    all_exercises = db.list_exercises()
    if request.method == "POST":
        exercise_id = _parse_int(request.form.get("exercise_id"))
        if not exercise_id:
            flash("種目を選択してください。", "danger")
            return render_template("my_sets/exercise_form.html",
                                   my_set=my_set, mse=None, all_exercises=all_exercises)
        db.create_my_set_exercise(
            my_set_id=my_set_id,
            exercise_id=exercise_id,
            one_rep_max=_parse_float(request.form.get("one_rep_max")),
            weight_setting=_parse_float(request.form.get("weight_setting")),
            weight_low_load=_parse_float(request.form.get("weight_low_load")),
            reps=_parse_int(request.form.get("reps")),
            muscle_groups=request.form.get("muscle_groups") or None,
        )
        flash("種目を追加しました。", "success")
        return redirect(url_for("my_set_detail", my_set_id=my_set_id))
    return render_template("my_sets/exercise_form.html",
                           my_set=my_set, mse=None, all_exercises=all_exercises)


@app.route("/my-sets/<int:my_set_id>/exercises/<int:mse_id>/edit", methods=["GET", "POST"])
def my_set_exercise_edit(my_set_id, mse_id):
    my_set = db.get_my_set(my_set_id)
    if my_set is None:
        return redirect(url_for("my_sets_list"))
    all_exercises = db.list_exercises()
    if request.method == "POST":
        exercise_id = _parse_int(request.form.get("exercise_id"))
        if not exercise_id:
            flash("種目を選択してください。", "danger")
        else:
            db.update_my_set_exercise(
                mse_id=mse_id,
                exercise_id=exercise_id,
                one_rep_max=_parse_float(request.form.get("one_rep_max")),
                weight_setting=_parse_float(request.form.get("weight_setting")),
                weight_low_load=_parse_float(request.form.get("weight_low_load")),
                reps=_parse_int(request.form.get("reps")),
                muscle_groups=request.form.get("muscle_groups") or None,
            )
            flash("更新しました。", "success")
            return redirect(url_for("my_set_detail", my_set_id=my_set_id))
    with db._conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM my_set_exercises WHERE id = %s", (mse_id,))
        mse = cur.fetchone()
    return render_template("my_sets/exercise_form.html",
                           my_set=my_set, mse=mse, all_exercises=all_exercises)


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
    exercises = db.list_exercises()
    return render_template("exercises/index.html", exercises=exercises)


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
        db.update_exercise_meta(
            exercise_id,
            body_part=request.form.get("body_part") or None,
            needs_bench=request.form.get("needs_bench") == "on",
            primary_muscle=request.form.get("primary_muscle") or None,
        )
        flash("種目情報を更新しました", "success")
        return redirect(url_for("exercise_progress", exercise_id=exercise_id))
    muscles = db.list_muscles()
    return render_template("exercises/meta_form.html", exercise=exercise, muscles=muscles)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
