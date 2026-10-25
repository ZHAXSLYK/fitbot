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
