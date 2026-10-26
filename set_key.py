"""Добавить или сменить ключ AI-тренера, не трогая остальные настройки.  Запуск:  python3.12 set_key.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, ".env")
NAMES = {"1": "GEMINI_API_KEY", "2": "GROQ_API_KEY", "3": "ANTHROPIC_API_KEY"}

if not os.path.exists(ENV):
    sys.exit("Нет файла .env — сначала запусти setup.py")

print("\nКакой AI подключаем? Можно подключить несколько — если один не ответит, бот спросит следующий.\n"
      "  1) Gemini — бесплатно (aistudio.google.com)\n"
      "  2) Groq — бесплатно, запасной (console.groq.com → API Keys)\n  3) Claude — платно (console.anthropic.com)")
choice = input("Номер [1]: ").strip() or "1"
name = NAMES.get(choice)
if not name:
    sys.exit("Нужно 1, 2 или 3")
key = input("Вставь ключ и нажми Enter: ").strip()
if len(key) < 20 or " " in key or key.startswith("python"):
    sys.exit("✖ Это не похоже на ключ (вставилось что-то другое). Скопируй ключ ещё раз и запусти снова.")
if name == "GROQ_API_KEY" and not key.startswith("gsk_"):
    sys.exit("✖ Ключ Groq должен начинаться с gsk_ — скопируй его ещё раз и запусти снова.")
if name == "ANTHROPIC_API_KEY" and not key.startswith("sk-ant-"):
    sys.exit("✖ Ключ Claude должен начинаться с sk-ant- — скопируй его ещё раз и запусти снова.")

lines = [l for l in open(ENV, encoding="utf-8").read().splitlines() if not l.startswith(name + "=")]
lines.append(f"{name}={key}")  # остальные ключи сохраняются — они станут запасными
open(ENV, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(f"✔ Ключ сохранён ({name}).\n\nОсталось: вкладка Web → зелёная кнопка Reload, потом нажми в боте «🤖 Спросить тренера»\n")
