-- Workout Report Database Schema

CREATE TABLE IF NOT EXISTS exercises (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS workout_sessions (
    id            SERIAL PRIMARY KEY,
    session_date  DATE    NOT NULL UNIQUE,
    day_of_week   TEXT,
    start_time    TIME,
    end_time      TIME,
    rep_count     INTEGER,
    total_exp     INTEGER,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS session_exercises (
    id               SERIAL PRIMARY KEY,
    session_id       INTEGER NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
    exercise_id      INTEGER NOT NULL REFERENCES exercises(id),
    sort_order       INTEGER,
    one_rep_max      REAL,
    weight_pct80     REAL,
    weight_setting   REAL,   -- 高負荷 / 設定
    weight_low_load  REAL,   -- 低負荷 (added later in spreadsheet)
    reps             INTEGER, -- rep count column
    ratio_pct        REAL,
    set1_completed   BOOLEAN,
    set2_completed   BOOLEAN,
    set3_completed   BOOLEAN,
    exp_earned       INTEGER,
    muscle_groups    TEXT,   -- comma-separated (added later in spreadsheet)
    UNIQUE (session_id, exercise_id)
);

CREATE INDEX IF NOT EXISTS idx_se_session ON session_exercises(session_id);
CREATE INDEX IF NOT EXISTS idx_se_exercise ON session_exercises(exercise_id);
CREATE INDEX IF NOT EXISTS idx_ws_date ON workout_sessions(session_date);

CREATE TABLE IF NOT EXISTS my_sets (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS my_set_exercises (
    id SERIAL PRIMARY KEY,
    my_set_id INTEGER NOT NULL REFERENCES my_sets(id) ON DELETE CASCADE,
    exercise_id INTEGER NOT NULL REFERENCES exercises(id),
    sort_order INTEGER,
    one_rep_max REAL,
    weight_setting REAL,
    weight_low_load REAL,
    reps INTEGER,
    muscle_groups TEXT,
    UNIQUE (my_set_id, exercise_id)
);

CREATE INDEX IF NOT EXISTS idx_mse_my_set ON my_set_exercises(my_set_id);

ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set4_completed  BOOLEAN;
ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set5_completed  BOOLEAN;
ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set6_completed  BOOLEAN;
ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set7_completed  BOOLEAN;
ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set8_completed  BOOLEAN;
ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set9_completed  BOOLEAN;
ALTER TABLE session_exercises ADD COLUMN IF NOT EXISTS set10_completed BOOLEAN;
ALTER TABLE my_sets ADD COLUMN IF NOT EXISTS location TEXT DEFAULT 'gym';
ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS finished_at TIMESTAMP;
ALTER TABLE workout_sessions ADD COLUMN IF NOT EXISTS post_notes TEXT;

CREATE TABLE IF NOT EXISTS weekly_schedule (
    day_of_week SMALLINT PRIMARY KEY,
    location    TEXT DEFAULT 'gym',
    my_set_id   INTEGER REFERENCES my_sets(id) ON DELETE SET NULL,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS body_weight_log (
    logged_date DATE PRIMARY KEY,
    weight_kg   REAL NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);
