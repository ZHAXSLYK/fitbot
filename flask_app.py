"""Веб-приложение для PythonAnywhere: принимает сообщения от Telegram (вебхук)."""
import logging
import os

import telebot
from flask import Flask, abort, request

from botcore import bot  # загружает .env

SECRET = os.getenv("WEBHOOK_SECRET", "")
app = Flask(__name__)


@app.get("/")
def index():
    return "Фитнес-бот работает ✅"


@app.get("/version")
def version():
    """Какая версия программы сейчас работает (для проверки после обновления)."""
    import subprocess
    import data
    try:
        rev = subprocess.run(["git", "-C", os.path.dirname(os.path.abspath(__file__)), "log", "--oneline", "-1"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        rev = "?"
    days = "; ".join(f"{w['title']}: " + ", ".join(e[0] for e in w["exercises"]) for w in data.PROGRAM_3)
    return f"{rev}\n{days}"


@app.get("/tick")
def tick():
    """Раз в час дёргает cron-job.org — бот рассылает напоминания вовремя.
    Секрет не нужен: повторный вызов ничего не дублирует (каждое напоминание — раз в день)."""
    from botcore import tick as run_tick
    return f"ok, sent {run_tick()}"


@app.post(f"/{SECRET or 'not-configured'}")
def webhook():
    if not SECRET or request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET:
        abort(403)
    update = telebot.types.Update.de_json(request.get_data(as_text=True))
    try:
        bot.process_new_updates([update])
    except Exception:
        logging.exception("update failed")
    return "ok"
