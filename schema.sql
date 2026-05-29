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

ALTER TABLE exercises ADD COLUMN IF NOT EXISTS body_part      TEXT;
ALTER TABLE exercises ADD COLUMN IF NOT EXISTS needs_bench    BOOLEAN DEFAULT FALSE;
ALTER TABLE exercises ADD COLUMN IF NOT EXISTS primary_muscle TEXT;

-- Seed known exercise metadata (only when not yet set)
UPDATE exercises SET body_part='上肢', needs_bench=false, primary_muscle='広背筋'     WHERE name='シーテッドロー'           AND body_part IS NULL;
UPDATE exercises SET body_part='上肢', needs_bench=false, primary_muscle='広背筋'     WHERE name='ラットアイソレータ'        AND body_part IS NULL;
UPDATE exercises SET body_part='下肢', needs_bench=false, primary_muscle='カーフ'     WHERE name='カーフ＆トゥレイズ'        AND body_part IS NULL;
UPDATE exercises SET body_part='下肢', needs_bench=false, primary_muscle='カーフ'     WHERE name='カーフ&トゥレイズ'         AND body_part IS NULL;
UPDATE exercises SET body_part='下肢', needs_bench=false, primary_muscle='大腿四頭筋' WHERE name='レッグプレス'              AND body_part IS NULL;
UPDATE exercises SET body_part='下肢', needs_bench=false, primary_muscle='大臀筋'     WHERE name='トータルヒップ'            AND body_part IS NULL;
UPDATE exercises SET body_part='体幹', needs_bench=false, primary_muscle='腹直筋'     WHERE name='インクライントーソ'        AND body_part IS NULL;
UPDATE exercises SET body_part='下肢', needs_bench=false, primary_muscle='大腿四頭筋' WHERE name='レッグエクステンション'    AND body_part IS NULL;
UPDATE exercises SET body_part='下肢', needs_bench=false, primary_muscle='ハムストリングス' WHERE name='シーテッドレッグカール' AND body_part IS NULL;
UPDATE exercises SET body_part='体幹', needs_bench=false, primary_muscle='脊柱起立筋' WHERE name='バックエクステンション'    AND body_part IS NULL;
UPDATE exercises SET body_part='体幹', needs_bench=false, primary_muscle='腹直筋'     WHERE name='アブアイソレーター'        AND body_part IS NULL;
UPDATE exercises SET body_part='上肢', needs_bench=false, primary_muscle='大胸筋'     WHERE name='チェストプレス'            AND body_part IS NULL;
UPDATE exercises SET body_part='上肢', needs_bench=false, primary_muscle='上腕三頭筋' WHERE name='アームエクステンション'    AND body_part IS NULL;
UPDATE exercises SET body_part='上肢', needs_bench=false, primary_muscle='上腕二頭筋' WHERE name='アームカール'              AND body_part IS NULL;
UPDATE exercises SET body_part='下肢', needs_bench=false, primary_muscle='大腿四頭筋' WHERE name='バーベルスクワット'        AND body_part IS NULL;
UPDATE exercises SET body_part='下肢', needs_bench=false, primary_muscle='大腿四頭筋' WHERE name='ブルガリアンスクワット'    AND body_part IS NULL;
UPDATE exercises SET body_part='上肢', needs_bench=true,  primary_muscle='上腕二頭筋' WHERE name='インクラインアームカール'  AND body_part IS NULL;
UPDATE exercises SET body_part='上肢', needs_bench=true,  primary_muscle='大胸筋'     WHERE name='インクラインダンベルプレス' AND body_part IS NULL;
UPDATE exercises SET body_part='上肢', needs_bench=true,  primary_muscle='大胸筋'     WHERE name='ベンチプレス'              AND body_part IS NULL;
UPDATE exercises SET body_part='上肢', needs_bench=true,  primary_muscle='三角筋'     WHERE name='ベンチダンベルサイドレイズ' AND body_part IS NULL;
UPDATE exercises SET body_part='下肢', needs_bench=false, primary_muscle='ハムストリングス' WHERE name='ランニング'          AND body_part IS NULL;
CREATE TABLE IF NOT EXISTS muscles (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0
);

INSERT INTO muscles (name, sort_order) VALUES ('広背筋',           1)  ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('大胸筋',           2)  ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('大腿四頭筋',       3)  ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('ハムストリングス', 4)  ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('大腿二頭筋',       5)  ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('三角筋',           6)  ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('上腕二頭筋',       7)  ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('上腕三頭筋',       8)  ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('大臀筋',           9)  ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('腹直筋',           10) ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('腹斜筋',           11) ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('僧帽筋',           12) ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('脊柱起立筋',       13) ON CONFLICT DO NOTHING;
INSERT INTO muscles (name, sort_order) VALUES ('カーフ',           14) ON CONFLICT DO NOTHING;

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
