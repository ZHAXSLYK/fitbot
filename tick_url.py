"""Показывает адрес для cron-job.org (напоминания каждый час).  Запуск:  python3.12 tick_url.py"""
import getpass
import os

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
secret = os.getenv("WEBHOOK_SECRET", "")
if not secret:
    raise SystemExit("Нет WEBHOOK_SECRET в .env — сначала запусти setup.py")
login = os.getenv("PA_LOGIN") or getpass.getuser()
print("\nСкопируй этот адрес в cron-job.org (поле URL):\n")
print(f"https://{login}.pythonanywhere.com/tick/{secret}\n")
print("Никому его не показывай и не присылай скриншот с ним.\n")
