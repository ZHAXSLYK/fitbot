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
CREATE TABLE IF NOT EXISTS meals(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, day TEXT, time TEXT, title TEXT,
    kcal INTEGER, protein INTEGER, fat INTEGER, carbs INTEGER
);
CREATE INDEX IF NOT EXISTS meals_user_day ON meals(user_id, day);
CREATE TABLE IF NOT EXISTS lifts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, day TEXT, exercise TEXT, weight REAL, reps TEXT
);
CREATE INDEX IF NOT EXISTS lifts_user_ex ON lifts(user_id, exercise);
CREATE TABLE IF NOT EXISTS waist(
    user_id INTEGER, day TEXT, cm REAL, PRIMARY KEY(user_id, day)
);
CREATE TABLE IF NOT EXISTS body_photos(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, day TEXT, file_id TEXT, weight REAL, waist REAL
);
CREATE TABLE IF NOT EXISTS daily(
    user_id INTEGER, day TEXT, steps INTEGER, water INTEGER DEFAULT 0,
    PRIMARY KEY(user_id, day)
);
CREATE TABLE IF NOT EXISTS pending_meals(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, data TEXT, created TEXT
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


# ---------- дневник питания ----------

def add_meal(user_id, day, time, title, kcal, protein, fat, carbs):
    _exec("INSERT INTO meals(user_id, day, time, title, kcal, protein, fat, carbs) VALUES(?,?,?,?,?,?,?,?)",
          (user_id, day, time, title, kcal, protein, fat, carbs))


def meals_for_day(user_id, day):
    return [dict(r) for r in _all("SELECT * FROM meals WHERE user_id=? AND day=? ORDER BY time, id",
                                  (user_id, day))]


def day_totals(user_id, day):
    r = _all("SELECT COUNT(*) AS n, COALESCE(SUM(kcal),0) AS kcal, COALESCE(SUM(protein),0) AS protein, "
             "COALESCE(SUM(fat),0) AS fat, COALESCE(SUM(carbs),0) AS carbs FROM meals WHERE user_id=? AND day=?",
             (user_id, day))[0]
    return dict(r)


def avg_kcal(user_id, since, until):
    """Средние калории за дни, в которые что-то записано."""
    r = _all("SELECT COUNT(*) AS days, COALESCE(AVG(s),0) AS avg FROM "
             "(SELECT SUM(kcal) AS s FROM meals WHERE user_id=? AND day>=? AND day<=? GROUP BY day)",
             (user_id, since, until))[0]
    return r["days"], int(round(r["avg"]))


def delete_last_meal(user_id, day):
    rows = _all("SELECT id, title, kcal FROM meals WHERE user_id=? AND day=? ORDER BY id DESC LIMIT 1",
                (user_id, day))
    if not rows:
        return None
    _exec("DELETE FROM meals WHERE id=?", (rows[0]["id"],))
    return dict(rows[0])


def save_pending(user_id, data, created):
    with closing(_conn()) as c, c:
        cur = c.execute("INSERT INTO pending_meals(user_id, data, created) VALUES(?,?,?)",
                        (user_id, json.dumps(data, ensure_ascii=False), created))
        c.execute("DELETE FROM pending_meals WHERE user_id=? AND id < ?", (user_id, cur.lastrowid - 20))
        return cur.lastrowid


def pop_pending(user_id, pid):
    rows = _all("SELECT data FROM pending_meals WHERE id=? AND user_id=?", (pid, user_id))
    if not rows:
        return None
    _exec("DELETE FROM pending_meals WHERE id=?", (pid,))
    return json.loads(rows[0]["data"])


# ---------- талия и фото прогресса ----------

def add_waist(user_id, day, cm):
    _exec("INSERT INTO waist(user_id, day, cm) VALUES(?,?,?) "
          "ON CONFLICT(user_id, day) DO UPDATE SET cm=excluded.cm", (user_id, day, cm))


def get_waists(user_id, since=None):
    sql, args = "SELECT day, cm FROM waist WHERE user_id=?", [user_id]
    if since:
        sql += " AND day>=?"
        args.append(since)
    return [(r["day"], r["cm"]) for r in _all(sql + " ORDER BY day", args)]


def last_waist_before(user_id, day):
    rows = _all("SELECT day, cm FROM waist WHERE user_id=? AND day<? ORDER BY day DESC LIMIT 1", (user_id, day))
    return (rows[0]["day"], rows[0]["cm"]) if rows else None


def add_body_photo(user_id, day, file_id, weight, waist_cm):
    _exec("INSERT INTO body_photos(user_id, day, file_id, weight, waist) VALUES(?,?,?,?,?)",
          (user_id, day, file_id, weight, waist_cm))


def body_photos(user_id):
    return [dict(r) for r in _all("SELECT * FROM body_photos WHERE user_id=? ORDER BY day, id", (user_id,))]


# ---------- шаги и вода ----------

def set_steps(user_id, day, steps):
    _exec("INSERT INTO daily(user_id, day, steps) VALUES(?,?,?) "
          "ON CONFLICT(user_id, day) DO UPDATE SET steps=excluded.steps", (user_id, day, steps))


def add_water(user_id, day, ml):
    _exec("INSERT INTO daily(user_id, day, water) VALUES(?,?,?) "
          "ON CONFLICT(user_id, day) DO UPDATE SET water=MAX(0, COALESCE(water,0)+excluded.water)",
          (user_id, day, ml))


def get_daily(user_id, day):
    rows = _all("SELECT steps, water FROM daily WHERE user_id=? AND day=?", (user_id, day))
    return {"steps": rows[0]["steps"], "water": rows[0]["water"] or 0} if rows else {"steps": None, "water": 0}


def daily_avgs(user_id, since, until):
    r = _all("SELECT AVG(steps) AS s, COUNT(steps) AS sn, AVG(NULLIF(water,0)) AS w, COUNT(NULLIF(water,0)) AS wn "
             "FROM daily WHERE user_id=? AND day>=? AND day<=?", (user_id, since, until))[0]
    return {"steps": int(r["s"]) if r["s"] else None, "steps_days": r["sn"],
            "water": int(r["w"]) if r["w"] else None, "water_days": r["wn"]}


# ---------- рабочие веса ----------

def add_lift(user_id, day, exercise, weight, reps):
    _exec("INSERT INTO lifts(user_id, day, exercise, weight, reps) VALUES(?,?,?,?,?)",
          (user_id, day, exercise, weight, ",".join(str(r) for r in reps)))


def last_lift(user_id, exercise, before_day=None):
    sql, args = "SELECT * FROM lifts WHERE user_id=? AND exercise=?", [user_id, exercise]
    if before_day:
        sql += " AND day<?"
        args.append(before_day)
    rows = _all(sql + " ORDER BY day DESC, id DESC LIMIT 1", args)
    if not rows:
        return None
    r = dict(rows[0])
    r["reps"] = [int(x) for x in r["reps"].split(",") if x]
    return r


def lift_history(user_id, since=None):
    """Первая и последняя запись по каждому упражнению (для прогресса)."""
    sql, args = "SELECT exercise, day, weight, reps FROM lifts WHERE user_id=?", [user_id]
    if since:
        sql += " AND day>=?"
        args.append(since)
    out = {}
    for r in _all(sql + " ORDER BY day, id", args):
        e = out.setdefault(r["exercise"], {"first": dict(r), "last": dict(r), "n": 0})
        e["last"] = dict(r)
        e["n"] += 1
    return out


def workout_logged(user_id, day, key):
    return _all("SELECT COUNT(*) AS n FROM workouts WHERE user_id=? AND day=? AND workout=?",
                (user_id, day, key))[0]["n"] > 0


def workouts_between(user_id, since, until):
    return _all("SELECT COUNT(*) AS n FROM workouts WHERE user_id=? AND day>=? AND day<=?",
                (user_id, since, until))[0]["n"]


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
