"""Мастер установки на PythonAnywhere. Запуск в консоли Bash:  python3 setup.py

Спросит токен бота, сам настроит .env, файл веб-приложения и вебхук Telegram.
"""
import os
import secrets
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def ask(prompt, default=""):
    v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return v or default


def main():
    print("\n=== Установка фитнес-бота ===\n")
    token = ask("1) Вставь токен от @BotFather")
    if ":" not in token:
        sys.exit("Похоже, это не токен. Он выглядит так: 123456789:AAH...")
    user = ask("2) Логин на PythonAnywhere", os.getenv("USER", ""))
    api_key = ask("3) Ключ Claude API для AI-тренера (Enter — пропустить)")
    secret = secrets.token_hex(16)

    with open(os.path.join(HERE, ".env"), "w", encoding="utf-8") as f:
        f.write(f"BOT_TOKEN={token}\nWEBHOOK_SECRET={secret}\nANTHROPIC_API_KEY={api_key}\nTZ_NAME=Asia/Almaty\n")
    print("✔ Настройки сохранены в .env")

    wsgi = f"/var/www/{user.lower()}_pythonanywhere_com_wsgi.py"
    if os.path.exists(wsgi):
        with open(wsgi, "w", encoding="utf-8") as f:
            f.write(f"import sys\nsys.path.insert(0, {HERE!r})\nfrom flask_app import app as application\n")
        print("✔ Веб-приложение подключено к боту")
    else:
        print(f"⚠ Не нашёл {wsgi}. Сначала создай веб-приложение на вкладке Web (шаг 4 в README), "
              "потом запусти setup.py ещё раз.")
        sys.exit(1)

    from botcore import bot, setup_commands  # импорт после записи .env

    url = f"https://{user.lower()}.pythonanywhere.com/{secret}"
    print("… Подключаюсь к Telegram (если прокси PythonAnywhere занят — повторю сам)")
    for attempt in range(1, 11):
        try:
            me = bot.get_me()
            bot.remove_webhook()
            bot.set_webhook(url=url, secret_token=secret, drop_pending_updates=True)
            setup_commands()
            break
        except Exception as e:
            msg = str(e).replace(token, "<ТОКЕН>")
            if "401" in msg or "Unauthorized" in msg:
                sys.exit("✖ Telegram не принял токен. Проверь, что скопировал его целиком, и запусти снова.")
            print(f"  попытка {attempt}/10 не удалась ({msg[-80:]}), жду 15 сек…")
            time.sleep(15)
    else:
        sys.exit("✖ Telegram сейчас недоступен через прокси PythonAnywhere. Запусти setup.py ещё раз через 10–15 минут.")
    print(f"✔ Вебхук установлен для @{me.username}")
    print("\nОсталось: вкладка Web → зелёная кнопка Reload, потом напиши боту /start\n")


if __name__ == "__main__":
    main()
