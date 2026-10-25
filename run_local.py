"""Запуск на своём компьютере или VPS (без вебхука):  python run_local.py

Бот работает, пока открыт этот процесс. Утренний план уходит в час из /remind (по умолчанию 8:00).
"""
import logging
import threading
import time
from datetime import datetime

from botcore import TOKEN, TZ, bot, send_morning, setup_commands


def reminder_loop():
    while True:
        try:
            send_morning(only_hour=datetime.now(TZ).hour)
        except Exception:
            logging.exception("reminder error")
        time.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if not TOKEN:
        raise SystemExit("Нет BOT_TOKEN — создай файл .env (см. .env.example)")
    bot.remove_webhook()
    setup_commands()
    threading.Thread(target=reminder_loop, daemon=True).start()
    print(f"Бот @{bot.get_me().username} запущен. Остановить: Ctrl+C")
    bot.infinity_polling(skip_pending=True)
