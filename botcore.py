"""Логика фитнес-бота: онбординг, тренировки, рецепты, меню дня, покупки, вес, AI-тренер.

Один и тот же код работает:
  • на PythonAnywhere (бесплатно) — через вебхук, файл flask_app.py;
  • на компьютере или VPS — через опрос, файл run_local.py.
"""
import html
import logging
import os
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

import telebot  # noqa: E402
from telebot import apihelper, types  # noqa: E402

# Прокси бесплатного PythonAnywhere иногда отвечает 503 — повторяем запрос
apihelper.RETRY_ON_ERROR = True
apihelper.MAX_RETRIES = 5
apihelper.RETRY_TIMEOUT = 2

import calc  # noqa: E402
import charts  # noqa: E402
import coach  # noqa: E402
import store  # noqa: E402
from data import (  # noqa: E402
    BY_NUM,
    CARDIO_NOTE,
    COOK_DAYS,
    PROGRAMS,
    PROGRESSION_NOTE,
    RECIPE_CATS,
    RECIPES,
    SHOPPING,
    WEEK_MENU,
)

TOKEN = os.getenv("BOT_TOKEN", "")
TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Almaty"))

bot = telebot.TeleBot(TOKEN or "0:none", parse_mode="HTML", threaded=False)
store.init()

BTN_WORKOUT = "🏋️ Тренировка"
BTN_DAY = "📅 Меню дня"
BTN_RECIPE = "🍲 Рецепт"
BTN_SHOP = "🛒 Покупки"
BTN_WEIGHT = "⚖️ Вес"
BTN_PROGRESS = "📊 Прогресс"
BTN_NORM = "🎯 Моя норма"
BTN_ASK = "🤖 Спросить тренера"
BTN_DIARY = "🍽 Дневник"

COMMANDS = [
    ("workout", "Тренировка на сегодня"),
    ("menu", "Меню на сегодня"),
    ("recipe", "ПП-рецепты для Термомикса"),
    ("diary", "Дневник питания за сегодня"),
    ("eat", "Записать еду: /eat гречка 200 г"),
    ("shop", "Список покупок на неделю"),
    ("weight", "Записать вес: /weight 83.6"),
    ("progress", "Прогресс и тренд веса"),
    ("week", "Итоги недели"),
    ("steps", "Шаги за сегодня: /steps 8500"),
    ("water", "Вода: /water 500 (мл)"),
    ("waist", "Талия: /waist 92 (см)"),
    ("photo", "Фото прогресса (до/после)"),
    ("compare", "Сравнить фото до/после"),
    ("norm", "Моя норма КБЖУ"),
    ("ask", "Вопрос AI-тренеру"),
    ("remind", "Утренний план: /remind 7 или off"),
    ("reset", "Заново ввести данные"),
]


# ======================= helpers =======================

def today():
    return datetime.now(TZ).date()


def menu_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(BTN_WORKOUT, BTN_DAY)
    kb.row(BTN_DIARY, BTN_RECIPE)
    kb.row(BTN_WEIGHT, BTN_PROGRESS)
    kb.row(BTN_SHOP, BTN_NORM)
    kb.row(BTN_ASK)
    return kb


def ikb(rows):
    kb = types.InlineKeyboardMarkup()
    for r in rows:
        kb.row(*[types.InlineKeyboardButton(t, callback_data=d) for t, d in r])
    return kb


def parse_num(text):
    m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*(кг)?\s*$", text or "", re.I)
    return float(m.group(1).replace(",", ".")) if m else None


def send(chat_id, text, **kw):
    """Отправка с разбивкой длинных сообщений."""
    for i in range(0, len(text), 4000):
        bot.send_message(chat_id, text[i : i + 4000], **kw)


def norm_text(u):
    return (
        "🎯 <b>Твоя норма на сброс жира</b>\n"
        f"Калории: <b>{u['kcal']} ккал</b>\n"
        f"Белок: <b>{u['protein']} г</b> · Жиры: <b>{u['fat']} г</b> · Углеводы: <b>{u['carbs']} г</b>\n\n"
        "Белок добирай в каждом приёме пищи (30–45 г). Норма пересчитается сама, "
        "когда средний вес сдвинется на 2 кг."
    )


def next_workout(u, done):
    prog = PROGRAMS.get(u["days"], PROGRAMS[3])
    return prog[done % len(prog)]


def scheme_info(scheme):
    m = re.search(r"(\d+)×(\d+)(?:–(\d+))?", scheme)
    sets, lo, hi = (int(m.group(1)), int(m.group(2)), int(m.group(3) or m.group(2))) if m else (3, 8, 12)
    if "макс" in scheme:
        hi = None
    return {"sets": sets, "lo": lo, "hi": hi, "secs": bool(re.search(r"×\s*\d+(?:–\d+)?\s*сек", scheme))}


def fmt_lift(l, secs=False):
    reps = ",".join(str(r) for r in l["reps"])
    if secs:
        return f"{reps} сек"
    w = f"{l['weight']:g} кг" if l["weight"] else "свой вес"
    return f"{w} × {reps}"


def lift_advice(name, scheme, last):
    info = scheme_info(scheme)
    if not last:
        if info["secs"]:
            return "Первый раз — держи, сколько получается с ровной спиной; запиши секунды каждого подхода."
        return "Первый раз — подбери вес, с которым в последнем подходе остаётся 1–2 повтора в запасе."
    reps, w = last["reps"], last["weight"]
    if info["secs"]:
        return "📈 Добавь 10 сек" if min(reps) >= (info["hi"] or 60) else f"Цель: {info['hi']} сек во всех подходах"
    if info["hi"] is None:
        return "📈 Попробуй на 1 повтор больше в каждом подходе"
    done = len(reps) >= info["sets"] and min(reps[: info["sets"]]) >= info["hi"]
    if not done:
        return f"Цель: {info['hi']} повторов во всех {info['sets']} подходах{f' с {w:g} кг' if w else ''}"
    if not w:
        return "📈 Все повторы сделаны — добавь отягощение (пояс/гантель) или +2 повтора"
    inc = 1 if "гантел" in name.lower() or w < 20 else 2.5
    return f"📈 Пора добавить вес: {w + inc:g} кг"


def workout_text(w, uid=None):
    lines = [f"🏋️ <b>{w['title']}</b>\n",
             "Разминка: 5–7 мин дорожка + 2 лёгких подхода первого упражнения.\n"]
    for i, (n, sch) in enumerate(w["exercises"], 1):
        lines.append(f"{i}. <b>{n}</b> — {sch}")
        last = store.last_lift(uid, n) if uid else None
        if last:
            lines.append(f"    ↳ прошлый раз: {fmt_lift(last, scheme_info(sch)['secs'])} → {lift_advice(n, sch, last)}")
    lines += ["", PROGRESSION_NOTE, "", CARDIO_NOTE]
    if uid:
        lines.append("\n📝 Нажми «Записать веса» — запомню результаты и подскажу, когда добавлять вес.")
    return "\n".join(lines)


def recipe_text(r):
    ing = "\n".join(f"• {i}" for i in r["ingredients"])
    steps = "\n".join(f"{n}. {s}" for n, s in enumerate(r["steps"], 1))
    text = (
        f"🍲 <b>№{r['num']}. {r['title']}</b>\n"
        f"{RECIPE_CATS[r['cat']]} · порций: {r['portions']}\n"
        f"<i>{r['kbju']} (на порцию)</i>\n\n"
        f"<b>Ингредиенты:</b>\n{ing}\n\n"
        f"<b>Термомикс:</b>\n{steps}"
    )
    return text + (f"\n\n💡 {r['tip']}" if r.get("tip") else "")


def day_menu_text(wd):
    d = WEEK_MENU[wd]
    head = f"📅 <b>{d['day']}</b>" + (f" · 🏋️ {d['gym']}" if d["gym"] else " · отдых, 8–10 тыс. шагов")
    lines = [head, ""] + [f"<b>{meal}:</b> {name} (№{num})" for meal, name, num in d["meals"]]
    lines.append("\nОстаток до нормы — фрукт или хлебец.")
    if wd in COOK_DAYS:
        titles = ", ".join(f"№{n} {BY_NUM[n]['title']}" for n in COOK_DAYS[wd])
        lines.append(f"\n🔪 <b>Сегодня день заготовок:</b> {titles}")
    return "\n".join(lines)


def day_menu_kb(wd):
    nums = []
    for _, _, n in WEEK_MENU[wd]["meals"]:
        if n not in nums:
            nums.append(n)
    nums += [n for n in COOK_DAYS.get(wd, []) if n not in nums]
    btns = [(f"№{n} {BY_NUM[n]['title'][:24]}", f"r:{n}") for n in nums]
    rows = [btns[i : i + 2] for i in range(0, len(btns), 2)]
    rows.append([("◀️ Вчера", f"day:{(wd - 1) % 7}"), ("Завтра ▶️", f"day:{(wd + 1) % 7}")])
    return ikb(rows)


STEP_BTNS = [("до 5к", 3000), ("5–8к", 6500), ("8–10к", 9000), ("10к+", 11500)]


def morning_kb(wd):
    kb = day_menu_kb(wd)
    kb.row(*[types.InlineKeyboardButton(f"👣 {t}", callback_data=f"st:{v}") for t, v in STEP_BTNS])
    return kb


def water_goal(u):
    return int(round(u["weight"] * 33 / 250) * 250)


def shopping_text():
    parts = ["🛒 <b>Покупки на неделю</b> (под меню из «📅 Меню дня»)"]
    for group, items in SHOPPING.items():
        parts.append(f"\n<b>{group}</b>")
        parts += [f"☐ {i}" for i in items]
    parts.append("\nЛучше закупаться в субботу — в воскресенье первая готовка.")
    return "\n".join(parts)


def morning_text(u):
    wd = today().weekday()
    w = next_workout(u, store.workouts_count(u["user_id"]))
    if u["days"] == 4:
        train = f"Следующая тренировка: <b>{w['title']}</b> (жми 🏋️)."
    elif WEEK_MENU[wd]["gym"]:
        train = f"Сегодня зал — <b>{w['title']}</b> (жми 🏋️)."
    else:
        train = "Сегодня отдых от зала — 8–10 тыс. шагов."
    y = store.day_totals(u["user_id"], (today() - timedelta(days=1)).isoformat())
    yesterday = ""
    if y["n"]:
        yesterday = (f"📒 Вчера: {y['kcal']} из {u['kcal']} ккал, белок {y['protein']} из {u['protein']} г"
                     f"{' ✅' if y['kcal'] <= u['kcal'] * 1.05 else ' — перебор, сегодня без перекусов сверх меню'}.\n\n")
    weekly = ""
    if wd == 0:  # понедельник — итоги прошлой недели + замеры
        start = today() - timedelta(days=7)
        weekly = week_report(u, start, start + timedelta(days=6), "прошлой недели") + "\n\n"
        weekly += ("📏 <b>Понедельник — день замеров.</b> Утром натощак обхват талии на уровне пупка, "
                   "сантиметр не затягивать: пришли <code>/waist 92</code>.\n")
        photos = store.body_photos(u["user_id"])
        if not photos or (today() - datetime.fromisoformat(photos[-1]["day"]).date()).days >= 13:
            weekly += ("📸 И пора <b>фото прогресса</b>: тот же ракурс, свет и одежда, что в прошлый раз — "
                       "нажми /photo и пришли снимок.\n")
        weekly += "\n"
    return (
        f"☀️ Доброе утро, {html.escape(u.get('name') or 'чемпион')}!\n\n" + weekly + yesterday +
        "1. Взвесься натощак и пришли число сюда.\n"
        f"2. Норма дня: {u['kcal']} ккал, белок {u['protein']} г.\n"
        f"3. {train}\n"
        "4. Еду записывай фото в этот чат — посчитаю КБЖУ.\n"
        f"5. Вода сегодня: {water_goal(u) / 1000:g} л.\n\n"
        "👣 <b>Сколько шагов было вчера?</b> Нажми кнопку внизу (точное число: /steps вчера 8540).\n\n"
        + day_menu_text(wd)
    )


def send_morning(only_hour=None):
    """Рассылает утренний план. only_hour=None — всем, кто ещё не получил сегодня."""
    now = datetime.now(TZ)
    day = now.date().isoformat()
    sent = 0
    for u in store.users_to_remind(day, only_hour):
        try:
            bot.send_message(u["user_id"], morning_text(u), reply_markup=morning_kb(now.weekday()))
            sent += 1
        except Exception as e:  # пользователь мог заблокировать бота
            logging.warning("remind %s failed: %s", u["user_id"], e)
        store.save_user(u["user_id"], last_remind=day)
    return sent


def require_user(chat_id, uid):
    u = store.get_user(uid)
    if not u or not u.get("kcal"):
        bot.send_message(chat_id, "Сначала давай познакомимся — нажми /start")
        return None
    return u


# ======================= онбординг =======================

def begin_onboarding(chat_id, uid):
    store.set_state(uid, "sex")
    bot.send_message(
        chat_id,
        "Привет! Я твой тренер: программа в зале, ПП-рецепты под Термомикс и контроль веса.\n\n"
        "Посчитаю норму — 5 коротких вопросов. Твой пол?",
        reply_markup=ikb([[("👨 Мужчина", "sex:m"), ("👩 Женщина", "sex:f")]]),
    )


@bot.message_handler(commands=["start"])
def cmd_start(m):
    store.clear_state(m.from_user.id)
    u = store.get_user(m.from_user.id)
    if u and u.get("kcal"):
        bot.send_message(m.chat.id, "С возвращением! 💪", reply_markup=menu_kb())
        bot.send_message(m.chat.id, norm_text(u))
    else:
        begin_onboarding(m.chat.id, m.from_user.id)


@bot.message_handler(commands=["reset"])
def cmd_reset(m):
    begin_onboarding(m.chat.id, m.from_user.id)


def _drop_kb(c):
    try:
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data.split(":")[0] in ("sex", "act", "days"))
def onb_buttons(c):
    uid, chat = c.from_user.id, c.message.chat.id
    state, data = store.get_state(uid)
    kind, val = c.data.split(":")
    if state != kind:
        return bot.answer_callback_query(c.id, "Эта кнопка уже неактуальна")
    _drop_kb(c)
    bot.answer_callback_query(c.id)
    if kind == "sex":
        data["sex"] = val
        store.set_state(uid, "age", data)
        bot.send_message(chat, "Сколько тебе полных лет?")
    elif kind == "act":
        data["activity"] = calc.ACTIVITY[int(val)][1]
        store.set_state(uid, "days", data)
        bot.send_message(chat, "Сколько раз в неделю ходишь в зал?",
                         reply_markup=ikb([[("3 раза — фулбади", "days:3"), ("4 раза — верх/низ", "days:4")]]))
    elif kind == "days":
        finish_onboarding(chat, c.from_user, data, int(val))


def onb_text(m, state, data):
    v = parse_num(m.text)
    uid, chat = m.from_user.id, m.chat.id
    if state == "age":
        if not v or not 14 <= v <= 90:
            return bot.send_message(chat, "Напиши возраст числом, например 38")
        data["age"] = int(v)
        store.set_state(uid, "height", data)
        bot.send_message(chat, "Рост в см?")
    elif state == "height":
        if not v or not 130 <= v <= 230:
            return bot.send_message(chat, "Напиши рост в сантиметрах, например 176")
        data["height"] = v
        store.set_state(uid, "weight", data)
        bot.send_message(chat, "Вес сейчас, кг? (лучше утром натощак)")
    elif state == "weight":
        if not v or not 35 <= v <= 250:
            return bot.send_message(chat, "Напиши вес в кг, например 84 или 84.5")
        data["weight"] = v
        store.set_state(uid, "act", data)
        rows = [[(label, f"act:{i}")] for i, (label, _) in enumerate(calc.ACTIVITY)]
        bot.send_message(chat, "Какая у тебя активность?", reply_markup=ikb(rows))
    else:  # ждём нажатия кнопки
        bot.send_message(chat, "Выбери вариант кнопкой выше 👆")


def finish_onboarding(chat, user, d, days):
    t = calc.targets(d["sex"], d["age"], d["height"], d["weight"], d["activity"])
    store.save_user(user.id, name=user.first_name, sex=d["sex"], age=d["age"], height=d["height"],
                    weight=d["weight"], activity=d["activity"], days=days, kcal=t["kcal"],
                    protein=t["protein"], fat=t["fat"], carbs=t["carbs"])
    store.add_weight(user.id, today().isoformat(), d["weight"])
    store.clear_state(user.id)
    bot.send_message(
        chat,
        f"Готово! Обмен веществ в покое ≈{t['bmr']} ккал, расход за день ≈{t['tdee']} ккал.\n\n"
        + norm_text(store.get_user(user.id))
        + "\n\nКаждое утро пришлю план дня: тренировку и меню. Выключить: /remind off.",
        reply_markup=menu_kb(),
    )


# ======================= тренировки =======================

def show_workout(chat, uid):
    u = require_user(chat, uid)
    if u:
        w = next_workout(u, store.workouts_count(uid))
        bot.send_message(chat, workout_text(w, uid),
                         reply_markup=ikb([[("📝 Записать веса", f"lg:{w['key']}"),
                                            ("✅ Сделана", f"done:{w['key']}")]]))


@bot.callback_query_handler(func=lambda c: c.data.startswith("done:"))
def workout_done(c):
    uid, chat = c.from_user.id, c.message.chat.id
    u = store.get_user(uid)
    if not u:
        return bot.answer_callback_query(c.id, "Нажми /start", show_alert=True)
    d = today()
    store.log_workout(uid, d.isoformat(), c.data.split(":")[1])
    week = store.workouts_count(uid, since=(d - timedelta(days=d.weekday())).isoformat())
    total = store.workouts_count(uid)
    _drop_kb(c)
    bot.answer_callback_query(c.id, "💪")
    bot.send_message(
        chat,
        f"✅ Записал! На этой неделе: {week} из {u['days']}. Всего тренировок: {total}.\n"
        f"Следующая — <b>{next_workout(u, total)['title']}</b>.\n\n"
        "Сейчас — белок + углеводы: протеиновый смузи, рецепт №16.",
        reply_markup=ikb([[("🥤 Рецепт смузи", "r:16")]]),
    )


# ======================= рецепты, меню, покупки =======================

def recipe_menu(chat):
    rows = [[(f"{title} — список", f"rlist:{key}")] for key, title in RECIPE_CATS.items()]
    rows.append([("🎲 Случайный рецепт", "rcat:any")])
    rows.append([("✨ Новый рецепт от AI", "airec:menu")])
    bot.send_message(chat, f"Что готовим в Термомиксе? Всего рецептов: {len(RECIPES)}.",
                     reply_markup=ikb(rows))


@bot.callback_query_handler(func=lambda c: c.data.split(":")[0] in ("rlist", "r", "rcat", "day"))
def recipe_buttons(c):
    chat = c.message.chat.id
    kind, val = c.data.split(":")
    bot.answer_callback_query(c.id)
    if kind == "rlist":
        btns = [[(f"№{r['num']} {r['title'][:28]}", f"r:{r['num']}")] for r in RECIPES if r["cat"] == val]
        bot.send_message(chat, RECIPE_CATS[val], reply_markup=ikb(btns))
    elif kind == "r":
        r = BY_NUM.get(int(val))
        if r:
            bot.send_message(chat, recipe_text(r), reply_markup=ikb([[("🍽 Съел порцию", f"ate:{r['num']}")]]))
    elif kind == "rcat":
        pool = RECIPES if val == "any" else [r for r in RECIPES if r["cat"] == val]
        r = random.choice(pool)
        bot.send_message(chat, recipe_text(r),
                         reply_markup=ikb([[("🍽 Съел порцию", f"ate:{r['num']}"), ("🔁 Другой", c.data)]]))
    elif kind == "day":
        wd = int(val)
        bot.edit_message_text(day_menu_text(wd), chat, c.message.message_id, reply_markup=day_menu_kb(wd))


def show_day(chat):
    wd = today().weekday()
    bot.send_message(chat, day_menu_text(wd), reply_markup=day_menu_kb(wd))


# ======================= вес и прогресс =======================

def save_weight(chat, uid, kg):
    u = store.get_user(uid)
    d = today()
    store.add_weight(uid, d.isoformat(), kg)
    tr = calc.trend(store.get_weights(uid), d)
    text = f"⚖️ Записал: <b>{kg:.1f} кг</b>."
    if tr["cur"] is not None:
        text += f"\nСредний за 7 дней: {tr['cur']:.1f} кг."
        if abs(tr["cur"] - u["weight"]) >= 2:  # вес сдвинулся — пересчитать норму
            t = calc.targets(u["sex"], u["age"], u["height"], tr["cur"], u["activity"])
            store.save_user(uid, weight=round(tr["cur"], 1), kcal=t["kcal"],
                            protein=t["protein"], fat=t["fat"], carbs=t["carbs"])
            text += (f"\n\n🔄 Вес сдвинулся на 2+ кг — новая норма: {t['kcal']} ккал, "
                     f"Б {t['protein']} / Ж {t['fat']} / У {t['carbs']}.")
    bot.send_message(chat, text, reply_markup=menu_kb())


def show_progress(chat, uid):
    u = require_user(chat, uid)
    if not u:
        return
    d = today()
    rows = store.get_weights(uid)
    tr = calc.trend(rows, d)
    week = store.workouts_count(uid, since=(d - timedelta(days=d.weekday())).isoformat())
    lines = ["📊 <b>Прогресс</b>\n", f"Тренировок на этой неделе: {week} из {u['days']}"]
    if rows:
        start = rows[0][0]
        lines.append(f"Старт: {rows[0][1]:.1f} кг ({start[8:10]}.{start[5:7]}) → сейчас: {rows[-1][1]:.1f} кг")
        lines.append("\nПоследние взвешивания:")
        lines += [f"{day[8:10]}.{day[5:7]} — {kg:.1f}" for day, kg in rows[-10:]]
    if tr["delta"] is not None:
        lines.append(f"\nНеделя к неделе: {tr['delta']:+.1f} кг ({tr['pct']:+.1f}%)")
    days, avg = store.avg_kcal(uid, (d - timedelta(days=6)).isoformat(), d.isoformat())
    if days:
        lines.append(f"\n🍽 Питание за 7 дней: в среднем {avg} ккал при норме {u['kcal']} (записано дней: {days})")
    hist = store.lift_history(uid)
    grown = [(ex, h) for ex, h in hist.items() if h["n"] > 1 and h["first"]["weight"]]
    if grown:
        lines.append("\n💪 <b>Силовые</b> (первая запись → последняя):")
        grown.sort(key=lambda x: x[1]["last"]["weight"] - x[1]["first"]["weight"], reverse=True)
        for ex, h in grown[:6]:
            a, b = h["first"]["weight"], h["last"]["weight"]
            lines.append(f"{html.escape(ex)}: {a:g} → {b:g} кг ({b - a:+g})")
    da = store.daily_avgs(uid, (d - timedelta(days=6)).isoformat(), d.isoformat())
    if da["steps"]:
        lines.append(f"\n👣 Шаги за 7 дней: в среднем {da['steps']:,}".replace(",", " ") +
                     (" ✅" if da["steps"] >= 8000 else " — цель 8–10 тыс."))
    lines.append("\n" + html.escape(tr["advice"]))
    png = charts.weight_chart(rows) if len(rows) >= 3 else None
    if png:
        try:
            bot.send_photo(chat, png)
        except Exception:
            logging.exception("chart send failed")
    elif len(rows) < 3:
        lines.append("\n📈 График веса появится после 3 взвешиваний.")
    ws = store.get_waists(uid)
    if ws:
        a, b = ws[0][1], ws[-1][1]
        lines.insert(-1, f"\n📏 Талия: {a:g} → {b:g} см ({b - a:+g})" if len(ws) > 1 else f"\n📏 Талия: {b:g} см")
    bot.send_message(chat, "\n".join(lines), reply_markup=ikb([
        [("📊 Итоги недели", "wk:7"), ("📏 Талия", "bd:waist")],
        [("📸 Фото прогресса", "bd:photo"), ("🔍 До / после", "bd:compare")]]))


# ======================= команды =======================

@bot.message_handler(commands=["workout"])
def c_workout(m):
    store.clear_state(m.from_user.id)
    show_workout(m.chat.id, m.from_user.id)


@bot.message_handler(commands=["menu"])
def c_menu(m):
    show_day(m.chat.id)


@bot.message_handler(commands=["recipe"])
def c_recipe(m):
    recipe_menu(m.chat.id)


@bot.message_handler(commands=["shop"])
def c_shop(m):
    bot.send_message(m.chat.id, shopping_text())


@bot.message_handler(commands=["progress"])
def c_progress(m):
    show_progress(m.chat.id, m.from_user.id)


@bot.message_handler(commands=["norm"])
def c_norm(m):
    u = require_user(m.chat.id, m.from_user.id)
    if u:
        bot.send_message(m.chat.id, norm_text(u))


@bot.message_handler(commands=["weight"])
def c_weight(m):
    if not require_user(m.chat.id, m.from_user.id):
        return
    kg = parse_num(telebot.util.extract_arguments(m.text))
    if kg and 35 <= kg <= 250:
        store.clear_state(m.from_user.id)
        return save_weight(m.chat.id, m.from_user.id, kg)
    store.set_state(m.from_user.id, "wait_weight")
    bot.send_message(m.chat.id, "Пришли вес числом, например 83.6")


@bot.message_handler(commands=["remind"])
def c_remind(m):
    if not require_user(m.chat.id, m.from_user.id):
        return
    arg = (telebot.util.extract_arguments(m.text) or "").strip().lower()
    if arg == "off":
        store.save_user(m.from_user.id, remind_hour=-1)
        return bot.send_message(m.chat.id, "Утренний план выключен. Включить: /remind on")
    if arg in ("on", "") or (arg.isdigit() and 0 <= int(arg) <= 23):
        hour = int(arg) if arg.isdigit() else 8
        store.save_user(m.from_user.id, remind_hour=hour)
        return bot.send_message(m.chat.id, "Утренний план включён ⏰")
    bot.send_message(m.chat.id, "Формат: /remind on, /remind off или /remind 7 (час)")


@bot.message_handler(commands=["ask"])
def c_ask(m):
    q = telebot.util.extract_arguments(m.text)
    if q:
        return answer_with_coach(m.chat.id, m.from_user.id, q)
    ask_button(m.chat.id, m.from_user.id)


# ======================= AI-тренер =======================

def ask_button(chat, uid):
    if not coach.enabled():
        return bot.send_message(chat, "AI-тренер выключен — добавь бесплатный ключ GEMINI_API_KEY в файл .env (см. README).")
    store.set_state(uid, "wait_ask")
    bot.send_message(chat, "Спрашивай: рецепт под Термомикс, замена упражнения, меню на день — что угодно.")


def answer_with_coach(chat, uid, question):
    u = require_user(chat, uid)
    if not u:
        return
    bot.send_chat_action(chat, "typing")
    try:
        reply = coach.ask(question, u)
    except Exception as e:
        logging.exception("coach error")
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code == 429:
            reply = "AI-тренер сейчас перегружен (лимит бесплатного тарифа). Попробуй через минуту."
        elif code in (401, 403):
            reply = "AI-тренер не принял ключ. Проверь ключ в файле .env и нажми Reload на вкладке Web."
        else:
            reply = (f"Не получилось связаться с AI-тренером (код: {code or type(e).__name__}). "
                     "Попробуй через минуту. Если повторяется — в консоли PythonAnywhere: python3.12 check_ai.py")
    send(chat, reply, parse_mode=None, reply_markup=menu_kb())


# ======================= журнал весов =======================

LIFT_HELP = ("Пришли вес и повторы через пробел: <code>60 8 8 7 7</code>\n"
             "Свой вес — ноль: <code>0 12 10 10</code> · Планка — секунды: <code>0 45 50 40</code>")


def find_workout(key):
    for prog in PROGRAMS.values():
        for w in prog:
            if w["key"] == key:
                return w
    return None


def ask_lift(chat, uid, data):
    w = find_workout(data["key"])
    name, sch = w["exercises"][data["idx"]]
    last = store.last_lift(uid, name)
    lines = [f"📝 {data['idx'] + 1}/{len(w['exercises'])} <b>{name}</b> — {sch}"]
    if last:
        lines.append(f"Прошлый раз ({last['day'][8:10]}.{last['day'][5:7]}): {fmt_lift(last, scheme_info(sch)['secs'])}")
    lines.append(lift_advice(name, sch, last))
    lines.append("\n" + LIFT_HELP)
    store.set_state(uid, "wait_lift", data)
    bot.send_message(chat, "\n".join(lines), reply_markup=ikb([[("⏭ Пропустить", "lgs:skip"), ("🏁 Закончить", "lgs:end")]]))


def finish_lifts(chat, uid, data):
    store.clear_state(uid)
    u = store.get_user(uid)
    if not data.get("logged"):
        return bot.send_message(chat, "Ничего не записал. Веса можно внести в любой момент кнопкой 📝 у тренировки.",
                                reply_markup=menu_kb())
    d = today()
    if not store.workout_logged(uid, d.isoformat(), data["key"]):
        store.log_workout(uid, d.isoformat(), data["key"])
    week = store.workouts_count(uid, since=(d - timedelta(days=d.weekday())).isoformat())
    nxt = next_workout(u, store.workouts_count(uid))
    rec = f"\n🏆 Рекорды: {', '.join(data['records'])}" if data.get("records") else ""
    bot.send_message(
        chat,
        f"🏁 <b>Тренировка записана!</b> Упражнений: {data['logged']}, тоннаж: {int(data.get('volume', 0))} кг{rec}\n"
        f"На этой неделе: {week} из {u['days']}. Следующая — <b>{nxt['title']}</b>.\n\n"
        "Сейчас — белок + углеводы: протеиновый смузи, рецепт №16.",
        reply_markup=ikb([[("🥤 Рецепт смузи", "r:16")]]),
    )


def next_lift(chat, uid, data):
    data["idx"] += 1
    if data["idx"] >= len(find_workout(data["key"])["exercises"]):
        return finish_lifts(chat, uid, data)
    ask_lift(chat, uid, data)


def lift_input(chat, uid, text, data):
    t = (text or "").strip().lower()
    if t in ("-", "—", "пропустить", "skip"):
        return next_lift(chat, uid, data)
    if t in ("стоп", "всё", "все", "конец", "stop"):
        return finish_lifts(chat, uid, data)
    nums = [x.replace(",", ".") for x in re.findall(r"\d+(?:[.,]\d+)?", t)]
    if len(nums) < 2:
        return bot.send_message(chat, "Не понял 🙂 " + LIFT_HELP + "\nПропустить упражнение: <code>-</code>")
    w = float(nums[0])
    reps = [int(float(x)) for x in nums[1:9]]
    if not (0 <= w <= 500 and all(0 < r <= 300 for r in reps)):
        return bot.send_message(chat, "Проверь числа: вес 0–500 кг, повторы 1–300.")
    name, sch = find_workout(data["key"])["exercises"][data["idx"]]
    prev = store.lift_history(uid).get(name)
    best = max(prev["first"]["weight"], prev["last"]["weight"]) if prev else None
    store.add_lift(uid, today().isoformat(), name, w, reps)
    data["logged"] = data.get("logged", 0) + 1
    data["volume"] = data.get("volume", 0) + w * sum(reps)
    note = ""
    if best is not None and w > best and w > 0:
        note = " 🏆 новый рекорд!"
        data.setdefault("records", []).append(f"{name} {w:g} кг")
    bot.send_message(chat, f"✔ {name}: {fmt_lift({'weight': w, 'reps': reps}, scheme_info(sch)['secs'])}{note}")
    next_lift(chat, uid, data)


@bot.callback_query_handler(func=lambda c: c.data.split(":")[0] in ("lg", "lgs"))
def lift_buttons(c):
    uid, chat = c.from_user.id, c.message.chat.id
    kind, val = c.data.split(":", 1)
    bot.answer_callback_query(c.id)
    if not store.get_user(uid):
        return
    if kind == "lg":
        if not find_workout(val):
            return
        _drop_kb(c)
        return ask_lift(chat, uid, {"key": val, "idx": 0, "logged": 0, "volume": 0})
    state, data = store.get_state(uid)
    if state != "wait_lift":
        return bot.send_message(chat, "Запись весов уже закончена.")
    _drop_kb(c)
    if val == "skip":
        next_lift(chat, uid, data)
    else:
        finish_lifts(chat, uid, data)


# ======================= итоги недели =======================

def week_report(u, start, end, title):
    uid = u["user_id"]
    s, e = start.isoformat(), end.isoformat()
    lines = [f"📊 <b>Итоги {title}</b> ({s[8:10]}.{s[5:7]}–{e[8:10]}.{e[5:7]})"]
    wk = store.workouts_between(uid, s, e)
    lines.append(f"🏋️ Тренировок: {wk} из {u['days']}" + (" ✅" if wk >= u["days"] else ""))
    rows = store.get_weights(uid, 120)
    cur, _ = calc._avg(rows, start, end)
    prev, _ = calc._avg(rows, start - timedelta(days=7), start - timedelta(days=1))
    if cur is not None and prev is not None:
        lines.append(f"⚖️ Средний вес: {prev:.1f} → {cur:.1f} кг ({cur - prev:+.1f})")
    elif cur is not None:
        lines.append(f"⚖️ Средний вес: {cur:.1f} кг")
    days, avg = store.avg_kcal(uid, s, e)
    if days:
        lines.append(f"🍽 Калории: в среднем {avg} при норме {u['kcal']} (записано дней: {days} из 7)")
    grown = []
    for ex, h in store.lift_history(uid, since=s).items():
        before = store.last_lift(uid, ex, before_day=s)
        if before and h["last"]["weight"] > before["weight"]:
            grown.append(f"{ex} {before['weight']:g}→{h['last']['weight']:g}")
    if grown:
        lines.append("💪 Рост весов: " + "; ".join(grown[:5]))
    wk_w = store.get_waists(uid, since=s)
    wk_w = [x for x in wk_w if x[0] <= e]
    if wk_w:
        before = store.last_waist_before(uid, s)
        cm = wk_w[-1][1]
        lines.append(f"📏 Талия: {before[1]:g} → {cm:g} см ({cm - before[1]:+g})" if before else f"📏 Талия: {cm:g} см")
    da = store.daily_avgs(uid, s, e)
    if da["steps"]:
        lines.append(f"👣 Шаги: в среднем {da['steps']:,} в день".replace(",", " ") + f" (отмечено дней: {da['steps_days']})")
    if da["water"]:
        lines.append(f"💧 Вода: в среднем {da['water'] / 1000:.1f} л из {water_goal(u) / 1000:g} л")
    # совет
    tips = []
    if da["steps"] and da["steps"] < 7000:
        tips.append("шагов мало — цель 8–10 тыс. в день, это главный жиросжигатель вне зала")
    if wk < u["days"]:
        tips.append(f"добери тренировки: цель {u['days']} в неделю")
    if days and avg > u["kcal"] * 1.08:
        tips.append("калорий больше нормы — убери перекусы вне меню")
    if days and days < 4:
        tips.append("записывай еду хотя бы 5 дней из 7 — фото в чат")
    if cur is not None and prev is not None:
        pct = (cur - prev) / prev * 100
        if pct > -0.25 and days and avg <= u["kcal"] * 1.05:
            tips.append("вес стоит при норме калорий — добавь 2–3 тыс. шагов в день")
        elif pct < -1.2:
            tips.append("худеешь слишком быстро — добавь ~150 ккал")
        elif pct <= -0.25:
            tips.append("темп отличный, так держать")
    if tips:
        lines.append("\n💡 " + "; ".join(tips).capitalize() + ".")
    return "\n".join(lines)


def show_week(chat, uid):
    u = require_user(chat, uid)
    if u:
        d = today()
        bot.send_message(chat, week_report(u, d - timedelta(days=6), d, "7 дней"))


@bot.message_handler(commands=["week"])
def c_week(m):
    store.clear_state(m.from_user.id)
    show_week(m.chat.id, m.from_user.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("wk:"))
def week_button(c):
    bot.answer_callback_query(c.id)
    show_week(c.message.chat.id, c.from_user.id)


# ======================= дневник питания =======================

KBJU_RE = re.compile(r"(\d+)\s*ккал.*?Б\s*(\d+)\s*/\s*Ж\s*(\d+)\s*/\s*У\s*(\d+)", re.S)
NO_AI_FOOD = ("📷 Распознавать еду по фото и тексту я научусь, когда подключишь бесплатный ключ Gemini "
              "(в консоли PythonAnywhere: <code>python3.12 set_key.py</code>).\n\n"
              "А пока можно записать калории числом: <code>/eat 450</code> "
              "или с БЖУ: <code>/eat 450 30 15 40</code> (ккал, белки, жиры, углеводы).")


def now_hm():
    return datetime.now(TZ).strftime("%H:%M")


def parse_kbju(text):
    m = KBJU_RE.search(text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def bar(done, total, width=10):
    filled = max(0, min(width, round(width * done / total))) if total else 0
    return "▓" * filled + "░" * (width - filled)


def day_summary(u, t, day=None):
    left = u["kcal"] - t["kcal"]
    left_txt = f"осталось <b>{left}</b>" if left >= 0 else f"перебор <b>{-left}</b>"
    lines = [
        f"🔥 {bar(t['kcal'], u['kcal'])} {t['kcal']} из {u['kcal']} ккал — {left_txt}",
        f"🥩 Белок {t['protein']}/{u['protein']} · Жиры {t['fat']}/{u['fat']} · Углеводы {t['carbs']}/{u['carbs']}",
    ]
    dly = store.get_daily(u["user_id"], day or today().isoformat())
    goal = water_goal(u)
    steps = f" · 👣 {dly['steps']:,}".replace(",", " ") if dly["steps"] else ""
    lines.append(f"💧 Вода {dly['water'] / 1000:g} из {goal / 1000:g} л {bar(dly['water'], goal, 6)}{steps}")
    hour = datetime.now(TZ).hour
    if t["n"] and hour >= 15 and t["protein"] < u["protein"] * 0.6:
        lines.append("💡 Белка мало — на ужин курица, рыба или творог (рецепты №11, №12, №17).")
    return "\n".join(lines)


def diary_text(u, day):
    meals = store.meals_for_day(u["user_id"], day)
    t = store.day_totals(u["user_id"], day)
    title = "сегодня" if day == today().isoformat() else f"{day[8:10]}.{day[5:7]}"
    lines = [f"🍽 <b>Дневник за {title}</b>\n"]
    if meals:
        for ml in meals:
            lines.append(f"{ml['time']} {html.escape(ml['title'])} — <b>{ml['kcal']}</b> ккал "
                         f"(Б{ml['protein']} Ж{ml['fat']} У{ml['carbs']})")
        lines.append("")
    else:
        lines.append("Пока пусто. <b>Сфотографируй еду и пришли сюда</b> — посчитаю КБЖУ и запишу.\n")
    lines.append(day_summary(u, t, day))
    return "\n".join(lines)


def diary_kb(day):
    is_today = day == today().isoformat()
    prev_day = (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()
    rows = []
    if is_today:
        rows.append([("➕ Записать текстом", "eat:text"), ("↩ Удалить последнее", "eat:undo")])
        rows.append([("💧 +250 мл", "wt:250"), ("💧 +500 мл", "wt:500"), ("◀️ Вчера", f"dy:{prev_day}")])
    else:
        rows.append([("◀️ Раньше", f"dy:{prev_day}"), ("Сегодня ▶️", f"dy:{today().isoformat()}")])
    return ikb(rows)


def show_diary(chat, uid):
    u = require_user(chat, uid)
    if u:
        day = today().isoformat()
        bot.send_message(chat, diary_text(u, day), reply_markup=diary_kb(day))


def save_meal(chat, uid, title, kcal, p, f, c):
    store.add_meal(uid, today().isoformat(), now_hm(), title[:100], kcal, p, f, c)
    u = store.get_user(uid)
    t = store.day_totals(uid, today().isoformat())
    bot.send_message(chat, f"✅ Записал: {html.escape(title[:100])} — {kcal} ккал\n\n" + day_summary(u, t),
                     reply_markup=ikb([[("🍽 Дневник за день", f"dy:{today().isoformat()}")]]))


def ai_error_text(e):
    if isinstance(e, RuntimeError) and str(e) == "no_ai":
        return NO_AI_FOOD
    code = getattr(getattr(e, "response", None), "status_code", None)
    if code == 429:
        return "AI сейчас перегружен (лимит бесплатного тарифа). Попробуй через минуту."
    if code in (401, 403):
        return "AI не принял ключ. Проверь ключ (<code>python3.12 set_key.py</code>) и нажми Reload."
    return (f"Не получилось распознать (код: {code or type(e).__name__}). Попробуй через минуту "
            "или запиши текстом: /eat гречка 200 г. Если повторяется — <code>python3.12 check_ai.py</code>")


def analyze_and_confirm(chat, uid, text="", image_bytes=None):
    bot.send_chat_action(chat, "typing")
    try:
        res = coach.analyze_food(text, image_bytes)
    except Exception as e:
        if str(e) != "no_ai":
            logging.exception("food analyze error")
        return bot.send_message(chat, ai_error_text(e))
    items = res["items"]
    if not items:
        return bot.send_message(chat, "🤔 " + html.escape(res["comment"] or "Не нашёл еду. Попробуй другое фото "
                                                          "или опиши текстом: /eat гречка 200 г, курица 150 г"))
    tot = {k: sum(i[k] for i in items) for k in ("kcal", "protein", "fat", "carbs")}
    pid = store.save_pending(uid, {"items": items, **tot}, datetime.now(TZ).isoformat())
    lines = ["🍽 <b>Вот что я вижу:</b>"]
    lines += [f"• {html.escape(i['name'])} ~{i['grams']} г — {i['kcal']} ккал (Б{i['protein']} Ж{i['fat']} У{i['carbs']})"
              for i in items]
    lines.append(f"\n<b>Итого: {tot['kcal']} ккал</b> · Б {tot['protein']} · Ж {tot['fat']} · У {tot['carbs']}")
    if res["comment"]:
        lines.append(f"💬 {html.escape(res['comment'])}")
    lines.append("\n<i>Оценка примерная. Если граммы не те — нажми ✖ и пришли фото с подписью, "
                 "например «гречки 150 г».</i>")
    bot.send_message(chat, "\n".join(lines),
                     reply_markup=ikb([[("✅ Записать", f"ms:{pid}"), ("✖ Отмена", f"mx:{pid}")]]))


def log_food_text(chat, uid, text):
    nums = re.findall(r"\d+", text or "")
    if nums and re.fullmatch(r"[\d\s.,]+(ккал)?", (text or "").strip(), re.I) and len(nums) in (1, 4):
        k, p, f, c = (int(nums[0]), 0, 0, 0) if len(nums) == 1 else tuple(int(x) for x in nums)
        if not 1 <= k <= 5000:
            return bot.send_message(chat, "Калорий должно быть от 1 до 5000")
        return save_meal(chat, uid, "Записано вручную", k, p, f, c)
    if not text or not text.strip():
        return bot.send_message(chat, "Напиши, что съел: /eat гречка 200 г, куриная грудка 150 г")
    analyze_and_confirm(chat, uid, text=text)


@bot.message_handler(commands=["eat"])
def c_eat(m):
    if not require_user(m.chat.id, m.from_user.id):
        return
    store.clear_state(m.from_user.id)
    arg = telebot.util.extract_arguments(m.text)
    if arg:
        return log_food_text(m.chat.id, m.from_user.id, arg)
    store.set_state(m.from_user.id, "wait_eat")
    bot.send_message(m.chat.id, "Что съел? Напиши, например: «гречка 200 г, куриная грудка 150 г, огурец».\n"
                                "Или просто пришли фото тарелки.")


@bot.message_handler(commands=["diary"])
def c_diary(m):
    store.clear_state(m.from_user.id)
    show_diary(m.chat.id, m.from_user.id)


@bot.message_handler(content_types=["photo"])
def on_photo(m):
    uid, chat = m.from_user.id, m.chat.id
    if not require_user(chat, uid):
        return
    state, _ = store.get_state(uid)
    if state == "wait_body_photo":
        store.clear_state(uid)
        return save_body_photo(chat, uid, m.photo[-1].file_id)
    store.clear_state(uid)
    if not coach.enabled():
        return bot.send_message(chat, NO_AI_FOOD)
    sizes = [p for p in m.photo if max(p.width, p.height) <= 1600] or m.photo[:1]
    try:
        info = bot.get_file(sizes[-1].file_id)
        data = bot.download_file(info.file_path)
    except Exception:
        logging.exception("photo download error")
        return bot.send_message(chat, "Не смог скачать фото, пришли ещё раз.")
    analyze_and_confirm(chat, uid, text=m.caption or "", image_bytes=data)


@bot.callback_query_handler(func=lambda c: c.data.split(":")[0] in ("ms", "mx", "ate", "eat", "dy"))
def diary_buttons(c):
    uid, chat = c.from_user.id, c.message.chat.id
    kind, val = c.data.split(":", 1)
    u = store.get_user(uid)
    if not u or not u.get("kcal"):
        return bot.answer_callback_query(c.id, "Нажми /start", show_alert=True)
    if kind in ("ms", "mx"):
        data = store.pop_pending(uid, int(val))
        _drop_kb(c)
        if not data:
            return bot.answer_callback_query(c.id, "Уже обработано")
        bot.answer_callback_query(c.id)
        if kind == "mx":
            return bot.send_message(chat, "Не записал. Можешь прислать фото с подписью граммов или /eat текстом.")
        title = ", ".join(i["name"] for i in data["items"])
        return save_meal(chat, uid, title, data["kcal"], data["protein"], data["fat"], data["carbs"])
    bot.answer_callback_query(c.id)
    if kind == "ate":
        r = BY_NUM.get(int(val))
        k = parse_kbju(r["kbju"]) if r else None
        if k:
            save_meal(chat, uid, f"№{r['num']} {r['title']}", *k)
    elif kind == "eat" and val == "text":
        store.set_state(uid, "wait_eat")
        bot.send_message(chat, "Что съел? Например: «плов 250 г, салат из огурцов». Или пришли фото.")
    elif kind == "eat" and val == "undo":
        gone = store.delete_last_meal(uid, today().isoformat())
        msg = f"↩ Удалил: {html.escape(gone['title'])} — {gone['kcal']} ккал" if gone else "Сегодня ещё ничего не записано."
        bot.send_message(chat, msg)
        show_diary(chat, uid)
    elif kind == "dy":
        try:
            bot.edit_message_text(diary_text(u, val), chat, c.message.message_id, reply_markup=diary_kb(val))
        except Exception:
            bot.send_message(chat, diary_text(u, val), reply_markup=diary_kb(val))


# ======================= шаги и вода =======================

def record_steps(chat, uid, steps, day):
    if not 0 <= steps <= 100000:
        return bot.send_message(chat, "Шагов должно быть от 0 до 100 000")
    store.set_steps(uid, day.isoformat(), steps)
    when = "сегодня" if day == today() else ("вчера" if day == today() - timedelta(days=1) else day.strftime("%d.%m"))
    note = ("✅ Отлично!" if steps >= 10000 else "👍 Хорошо, цель 8–10 тыс." if steps >= 8000
            else "Маловато — сегодня добавь прогулку 20–30 минут, это ≈3 тыс. шагов.")
    num = f"{steps:,}".replace(",", " ")
    bot.send_message(chat, f"👣 Записал {num} шагов за {when}. {note}")


def record_water(chat, uid, ml):
    u = store.get_user(uid)
    store.add_water(uid, today().isoformat(), ml)
    w = store.get_daily(uid, today().isoformat())["water"]
    goal = water_goal(u)
    done = " ✅ Норма выполнена!" if w >= goal else f" Осталось {(goal - w) / 1000:g} л."
    bot.send_message(chat, f"💧 {w / 1000:g} из {goal / 1000:g} л {bar(w, goal, 8)}{done}",
                     reply_markup=ikb([[("💧 +250 мл", "wt:250"), ("💧 +500 мл", "wt:500"), ("↩ −250", "wt:-250")]]))


@bot.message_handler(commands=["steps"])
def c_steps(m):
    if not require_user(m.chat.id, m.from_user.id):
        return
    arg = (telebot.util.extract_arguments(m.text) or "").lower()
    nums = re.findall(r"\d+", arg.replace("вчера", "").replace(" ", ""))
    if not nums:
        return bot.send_message(m.chat.id, "Формат: <code>/steps 8500</code> — за сегодня, "
                                           "<code>/steps вчера 8500</code> — за вчера.")
    day = today() - timedelta(days=1) if "вчера" in arg else today()
    record_steps(m.chat.id, m.from_user.id, int(nums[0]), day)


@bot.message_handler(commands=["water"])
def c_water(m):
    if not require_user(m.chat.id, m.from_user.id):
        return
    nums = re.findall(r"\d+", telebot.util.extract_arguments(m.text) or "")
    ml = int(nums[0]) if nums else 250
    if ml < 20:  # ввели литры: /water 1
        ml *= 1000
    record_water(m.chat.id, m.from_user.id, min(ml, 3000))


@bot.callback_query_handler(func=lambda c: c.data.split(":")[0] in ("st", "wt"))
def steps_water_buttons(c):
    uid, chat = c.from_user.id, c.message.chat.id
    kind, val = c.data.split(":", 1)
    if not store.get_user(uid):
        return bot.answer_callback_query(c.id, "Нажми /start", show_alert=True)
    if kind == "st":
        bot.answer_callback_query(c.id, "👣 Записал")
        record_steps(chat, uid, int(val), today() - timedelta(days=1))
    else:
        bot.answer_callback_query(c.id, "💧")
        record_water(chat, uid, int(val))


# ======================= талия и фото прогресса =======================

def record_waist(chat, uid, cm):
    d = today().isoformat()
    prev = store.last_waist_before(uid, d)
    store.add_waist(uid, d, cm)
    msg = f"📏 Записал талию: <b>{cm:g} см</b>."
    if prev:
        diff = cm - prev[1]
        msg += f"\nВ прошлый раз ({prev[0][8:10]}.{prev[0][5:7]}): {prev[1]:g} см → {diff:+g} см"
        if diff < 0:
            msg += " 🔥 Жир уходит!"
        elif diff == 0:
            msg += ". Держим курс — талия меняется медленнее веса."
        else:
            msg += ". Бывает из-за воды и соли — смотри на тренд за 2–3 недели."
    else:
        msg += "\nЭто точка старта. Меряй раз в неделю, в понедельник утром натощак."
    bot.send_message(chat, msg)


def save_body_photo(chat, uid, file_id):
    u = store.get_user(uid)
    d = today().isoformat()
    ws = store.get_waists(uid)
    rows = store.get_weights(uid, 1)
    kg = rows[-1][1] if rows else u["weight"]
    store.add_body_photo(uid, d, file_id, kg, ws[-1][1] if ws else None)
    n = len(store.body_photos(uid))
    extra = ("\nЧерез 2 недели напомню сделать следующее — тогда сравним «до / после»." if n == 1
             else "\nСравнить с первым: /compare")
    bot.send_message(chat, f"📸 Фото прогресса №{n} сохранено ({kg:.1f} кг).{extra}\n\n"
                           "🔒 Фото хранятся только в этом чате Telegram, бот запоминает лишь ссылку на них.")


def ask_body_photo(chat, uid):
    store.set_state(uid, "wait_body_photo")
    bot.send_message(chat, "📸 Пришли фото прогресса.\n\nСоветы, чтобы сравнение было честным:\n"
                           "• утро, натощак, одинаковый свет и место;\n• одинаковая одежда (или без футболки);\n"
                           "• анфас и бок, телефон на уровне груди.\n\n"
                           "Это фото не пойдёт в дневник питания.")


def show_compare(chat, uid):
    ph = store.body_photos(uid)
    if len(ph) < 2:
        return bot.send_message(chat, "Для сравнения нужно минимум 2 фото прогресса. "
                                      "Сделай первое сейчас (/photo), следующее — через 2 недели.")
    first, last = ph[0], ph[-1]

    def cap(p, label):
        w = f", талия {p['waist']:g} см" if p.get("waist") else ""
        return f"{label}: {p['day'][8:10]}.{p['day'][5:7]} — {p['weight']:.1f} кг{w}"

    try:
        bot.send_media_group(chat, [types.InputMediaPhoto(first["file_id"], caption=cap(first, "До")),
                                    types.InputMediaPhoto(last["file_id"], caption=cap(last, "После"))])
    except Exception:
        logging.exception("compare send failed")
        return bot.send_message(chat, "Не получилось показать фото, попробуй ещё раз.")
    days = (datetime.fromisoformat(last["day"]) - datetime.fromisoformat(first["day"])).days
    dk = last["weight"] - first["weight"]
    msg = f"🔍 За {days} дн.: вес {dk:+.1f} кг"
    if first.get("waist") and last.get("waist"):
        msg += f", талия {last['waist'] - first['waist']:+g} см"
    bot.send_message(chat, msg + ". Сравнивай силуэт, а не цифры — так видно реальный прогресс 💪")


@bot.message_handler(commands=["waist"])
def c_waist(m):
    if not require_user(m.chat.id, m.from_user.id):
        return
    v = parse_num((telebot.util.extract_arguments(m.text) or "").replace("см", ""))
    if v and 40 <= v <= 200:
        store.clear_state(m.from_user.id)
        return record_waist(m.chat.id, m.from_user.id, v)
    store.set_state(m.from_user.id, "wait_waist")
    bot.send_message(m.chat.id, "📏 Обхват талии на уровне пупка, утром натощак, сантиметр не затягивая. "
                                "Пришли число, например 92")


@bot.message_handler(commands=["photo"])
def c_photo(m):
    if require_user(m.chat.id, m.from_user.id):
        ask_body_photo(m.chat.id, m.from_user.id)


@bot.message_handler(commands=["compare"])
def c_compare(m):
    store.clear_state(m.from_user.id)
    if require_user(m.chat.id, m.from_user.id):
        show_compare(m.chat.id, m.from_user.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bd:"))
def body_buttons(c):
    uid, chat = c.from_user.id, c.message.chat.id
    bot.answer_callback_query(c.id)
    if not store.get_user(uid):
        return
    val = c.data.split(":", 1)[1]
    if val == "waist":
        store.set_state(uid, "wait_waist")
        bot.send_message(chat, "📏 Пришли обхват талии в см (на уровне пупка, утром натощак), например 92")
    elif val == "photo":
        ask_body_photo(chat, uid)
    elif val == "compare":
        show_compare(chat, uid)


# ======================= AI-рецепты =======================

AI_CATS = {"breakfast": "завтрак", "main": "обед или ужин", "snack": "перекус или десерт"}


@bot.callback_query_handler(func=lambda c: c.data.startswith("airec:"))
def ai_recipe(c):
    uid, chat = c.from_user.id, c.message.chat.id
    val = c.data.split(":", 1)[1]
    bot.answer_callback_query(c.id)
    if not coach.enabled():
        return bot.send_message(chat, "Для новых рецептов нужен бесплатный ключ Gemini: "
                                      "<code>python3.12 set_key.py</code> в консоли PythonAnywhere.")
    if val == "menu":
        return bot.send_message(chat, "Какой рецепт придумать?", reply_markup=ikb(
            [[("🌅 Завтрак", "airec:breakfast"), ("🍗 Обед/ужин", "airec:main"), ("🥤 Перекус", "airec:snack")]]))
    u = require_user(chat, uid)
    if not u or val not in AI_CATS:
        return
    known = ", ".join(r["title"] for r in RECIPES if r["cat"] == val)
    prompt = (
        f"Придумай ОДИН новый ПП-рецепт ({AI_CATS[val]}) для Термомикса из продуктов, которые легко купить в Казахстане. "
        f"Не повторяй эти: {known}. Каждый раз предлагай что-то другое (вариация №{random.randint(1, 999)}).\n"
        "Формат строго такой:\n"
        "Название\n"
        "Порций: N\n"
        "КБЖУ на порцию: 420 ккал · Б 35 / Ж 12 / У 40\n"
        "Ингредиенты: список с граммами\n"
        "Термомикс: нумерованные шаги с режимами «время / температура / ↺ / скорость»\n"
        "Совет: одна строка."
    )
    bot.send_chat_action(chat, "typing")
    try:
        text = coach.ask(prompt, u)
    except Exception as e:
        logging.exception("ai recipe error")
        return bot.send_message(chat, ai_error_text(e))
    buttons = [("🔁 Ещё вариант", f"airec:{val}")]
    k = parse_kbju(text)
    if k:
        title = text.strip().splitlines()[0][:60]
        pid = store.save_pending(uid, {"items": [{"name": title}], "kcal": k[0], "protein": k[1],
                                       "fat": k[2], "carbs": k[3]}, datetime.now(TZ).isoformat())
        buttons.insert(0, ("🍽 Съел порцию", f"ms:{pid}"))
    send(chat, "✨ " + text, parse_mode=None, reply_markup=ikb([buttons]))


# ======================= любой текст =======================

BUTTONS = {
    BTN_WORKOUT: lambda c, u: show_workout(c, u),
    BTN_DAY: lambda c, u: show_day(c),
    BTN_RECIPE: lambda c, u: recipe_menu(c),
    BTN_SHOP: lambda c, u: bot.send_message(c, shopping_text()),
    BTN_PROGRESS: lambda c, u: show_progress(c, u),
    BTN_NORM: lambda c, u: c_norm_by_id(c, u),
    BTN_ASK: lambda c, u: ask_button(c, u),
    BTN_DIARY: lambda c, u: show_diary(c, u),
}


def c_norm_by_id(chat, uid):
    u = require_user(chat, uid)
    if u:
        bot.send_message(chat, norm_text(u))


@bot.message_handler(content_types=["text"])
def on_text(m):
    uid, chat, text = m.from_user.id, m.chat.id, m.text
    state, data = store.get_state(uid)

    if text in BUTTONS or text == BTN_WEIGHT:
        if state in ("sex", "age", "height", "weight", "act", "days"):
            return bot.send_message(chat, "Сначала закончим знакомство 🙂 Ответь на вопрос выше.")
        store.clear_state(uid)
        if text == BTN_WEIGHT:
            if require_user(chat, uid):
                store.set_state(uid, "wait_weight")
                bot.send_message(chat, "Сколько весишь сегодня? Пришли число, например 83.6")
            return
        return BUTTONS[text](chat, uid)

    if state in ("sex", "age", "height", "weight", "act", "days"):
        return onb_text(m, state, data)
    if state == "wait_weight":
        kg = parse_num(text)
        if not kg or not 35 <= kg <= 250:
            return bot.send_message(chat, "Нужно число, например 83.6")
        store.clear_state(uid)
        return save_weight(chat, uid, kg)
    if state == "wait_lift":
        return lift_input(chat, uid, text, data)
    if state == "wait_waist":
        v = parse_num(text.replace("см", ""))
        if not v or not 40 <= v <= 200:
            return bot.send_message(chat, "Пришли обхват талии в сантиметрах, например 92 или 91.5")
        store.clear_state(uid)
        return record_waist(chat, uid, v)
    if state == "wait_body_photo":
        return bot.send_message(chat, "Жду именно фото 📸 — пришли снимок, или нажми любую кнопку меню для отмены.")
    if state == "wait_eat":
        store.clear_state(uid)
        return log_food_text(chat, uid, text)
    if state == "wait_ask":
        store.clear_state(uid)
        return answer_with_coach(chat, uid, text)

    kg = parse_num(text)
    if kg and 35 <= kg <= 250 and require_user(chat, uid):
        return save_weight(chat, uid, kg)  # просто число = вес
    if coach.enabled():
        return answer_with_coach(chat, uid, text)
    bot.send_message(chat, "Выбери действие в меню 👇", reply_markup=menu_kb())


def setup_commands():
    bot.set_my_commands([types.BotCommand(c, d) for c, d in COMMANDS])
