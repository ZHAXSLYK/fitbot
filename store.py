"""SQLite-хранилище (синхронное): профиль, вес, тренировки, состояние диалога."""
import json
import os
import sqlite3
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH") or os.path.join(HERE, "fitbot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    user_id     INTEGER PRIMARY KEY,
    name        TEXT,
    sex         TEXT,
    age         INTEGER,
    height      REAL,
    weight      REAL,
    activity    REAL,
    days        INTEGER,
    kcal        INTEGER,
    protein     INTEGER,
    fat         INTEGER,
    carbs       INTEGER,
    remind_hour INTEGER DEFAULT 8,
    last_remind TEXT
);
CREATE TABLE IF NOT EXISTS weights(
    user_id INTEGER, day TEXT, kg REAL,
    PRIMARY KEY(user_id, day)
);
CREATE TABLE IF NOT EXISTS workouts(
    user_id INTEGER, day TEXT, workout TEXT
);
CREATE TABLE IF NOT EXISTS states(
    user_id INTEGER PRIMARY KEY, state TEXT, data TEXT
);
"""


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _exec(sql, args=()):
    with closing(_conn()) as c, c:
        c.execute(sql, args)


def _all(sql, args=()):
    with closing(_conn()) as c:
        return c.execute(sql, args).fetchall()


def init():
    with closing(_conn()) as c, c:
        c.executescript(SCHEMA)


# ---------- users ----------

def save_user(user_id, **fields):
    cols = ["user_id", *fields]
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields)
    _exec(
        f"INSERT INTO users({', '.join(cols)}) VALUES({', '.join('?' * len(cols))}) "
        f"ON CONFLICT(user_id) DO UPDATE SET {updates}",
        [user_id, *fields.values()],
    )


def get_user(user_id):
    rows = _all("SELECT * FROM users WHERE user_id=?", (user_id,))
    return dict(rows[0]) if rows else None


def users_to_remind(today, hour=None):
    sql = ("SELECT * FROM users WHERE kcal IS NOT NULL AND remind_hour>=0 "
           "AND (last_remind IS NULL OR last_remind<>?)")
    args = [today]
    if hour is not None:
        sql += " AND remind_hour=?"
        args.append(hour)
    return [dict(r) for r in _all(sql, args)]


# ---------- weights / workouts ----------

def add_weight(user_id, day, kg):
    _exec("INSERT INTO weights(user_id, day, kg) VALUES(?,?,?) "
          "ON CONFLICT(user_id, day) DO UPDATE SET kg=excluded.kg", (user_id, day, kg))


def get_weights(user_id, limit=60):
    rows = _all("SELECT day, kg FROM weights WHERE user_id=? ORDER BY day DESC LIMIT ?",
                (user_id, limit))
    return [(r["day"], r["kg"]) for r in reversed(rows)]


def log_workout(user_id, day, key):
    _exec("INSERT INTO workouts(user_id, day, workout) VALUES(?,?,?)", (user_id, day, key))


def workouts_count(user_id, since=None):
    sql, args = "SELECT COUNT(*) AS n FROM workouts WHERE user_id=?", [user_id]
    if since:
        sql += " AND day>=?"
        args.append(since)
    return _all(sql, args)[0]["n"]


# ---------- состояние диалога ----------

def get_state(user_id):
    rows = _all("SELECT state, data FROM states WHERE user_id=?", (user_id,))
    if not rows:
        return None, {}
    return rows[0]["state"], json.loads(rows[0]["data"] or "{}")


def set_state(user_id, state, data=None):
    _exec("INSERT INTO states(user_id, state, data) VALUES(?,?,?) "
          "ON CONFLICT(user_id) DO UPDATE SET state=excluded.state, data=excluded.data",
          (user_id, state, json.dumps(data or {}, ensure_ascii=False)))


def clear_state(user_id):
    _exec("DELETE FROM states WHERE user_id=?", (user_id,))
