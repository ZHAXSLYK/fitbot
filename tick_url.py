"""Показывает адрес для cron-job.org (напоминания каждый час).  Запуск:  python3.12 tick_url.py"""
import getpass
import os

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
login = os.getenv("PA_LOGIN") or getpass.getuser()
print("\nСкопируй этот адрес в cron-job.org (поле URL):\n")
print(f"https://{login}.pythonanywhere.com/tick\n")
