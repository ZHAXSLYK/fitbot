"""Утренний план дня. На PythonAnywhere — ежедневная задача (вкладка Tasks)."""
from botcore import send_morning

if __name__ == "__main__":
    print("Отправлено:", send_morning())
