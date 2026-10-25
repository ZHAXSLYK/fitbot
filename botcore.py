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


def workout_text(w):
    lines = [f"🏋️ <b>{w['title']}</b>\n",
             "Разминка: 5–7 мин дорожка + 2 лёгких подхода первого упражнения.\n"]
    lines += [f"{i}. <b>{n}</b> — {s}" for i, (n, s) in enumerate(w["exercises"], 1)]
    lines += ["", PROGRESSION_NOTE, "", CARDIO_NOTE]
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
    return (
        f"☀️ Доброе утро, {html.escape(u.get('name') or 'чемпион')}!\n\n" + yesterday +
        "1. Взвесься натощак и пришли число сюда.\n"
        f"2. Норма дня: {u['kcal']} ккал, белок {u['protein']} г.\n"
        f"3. {train}\n"
        "4. Еду записывай фото в этот чат — посчитаю КБЖУ.\n\n" + day_menu_text(wd)
    )


def send_morning(only_hour=None):
    """Рассылает утренний план. only_hour=None — всем, кто ещё не получил сегодня."""
    now = datetime.now(TZ)
    day = now.date().isoformat()
    sent = 0
    for u in store.users_to_remind(day, only_hour):
        try:
            bot.send_message(u["user_id"], morning_text(u), reply_markup=day_menu_kb(now.weekday()))
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
        bot.send_message(chat, workout_text(w),
                         reply_markup=ikb([[("✅ Тренировка сделана", f"done:{w['key']}")]]))


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
    lines.append("\n" + html.escape(tr["advice"]))
    bot.send_message(chat, "\n".join(lines))


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
            reply = "Не получилось связаться с AI-тренером, попробуй ещё раз через минуту."
    send(chat, reply, parse_mode=None, reply_markup=menu_kb())


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


def day_summary(u, t):
    left = u["kcal"] - t["kcal"]
    left_txt = f"осталось <b>{left}</b>" if left >= 0 else f"перебор <b>{-left}</b>"
    lines = [
        f"🔥 {bar(t['kcal'], u['kcal'])} {t['kcal']} из {u['kcal']} ккал — {left_txt}",
        f"🥩 Белок {t['protein']}/{u['protein']} · Жиры {t['fat']}/{u['fat']} · Углеводы {t['carbs']}/{u['carbs']}",
    ]
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
    lines.append(day_summary(u, t))
    return "\n".join(lines)


def diary_kb(day):
    is_today = day == today().isoformat()
    prev_day = (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()
    rows = []
    if is_today:
        rows.append([("➕ Записать текстом", "eat:text"), ("↩ Удалить последнее", "eat:undo")])
        rows.append([("◀️ Вчера", f"dy:{prev_day}")])
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
    return "Не получилось распознать, попробуй ещё раз через минуту или запиши текстом: /eat гречка 200 г"


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
