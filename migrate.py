"""Run schema migrations. Safe to re-run (idempotent)."""
import os
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "dbname=workout_report")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

with open("schema.sql") as f:
    sql = f.read()

# Execute statement by statement, skipping ALTER TABLE failures gracefully
import re
statements = [s.strip() for s in sql.split(";") if s.strip()]
for stmt in statements:
    try:
        cur.execute(stmt)
        print(f"OK: {stmt[:60].replace(chr(10),' ')}...")
    except Exception as e:
        print(f"SKIP ({e.__class__.__name__}): {stmt[:60].replace(chr(10),' ')}...")

# Seed weekly_schedule rows if empty
cur.execute("SELECT COUNT(*) FROM weekly_schedule")
if cur.fetchone()[0] == 0:
    for dow in range(7):
        cur.execute(
            "INSERT INTO weekly_schedule (day_of_week) VALUES (%s) ON CONFLICT DO NOTHING",
            (dow,)
        )
    print("Seeded weekly_schedule (7 rows)")

cur.close()
conn.close()
print("Migration complete.")
