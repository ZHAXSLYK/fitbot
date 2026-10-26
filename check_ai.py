"""Проверка AI-тренера: показывает, отвечает ли Gemini/Groq/Claude и почему нет.
Запуск:  python3.12 check_ai.py      (ключ на экран не выводится — скриншот можно присылать)
"""
import os

import requests
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

gem = os.getenv("GEMINI_API_KEY", "")
groq = os.getenv("GROQ_API_KEY", "")
claude = os.getenv("ANTHROPIC_API_KEY", "")
print("\n=== Проверка AI-тренера ===")
print(f"Ключи в .env: Gemini {'есть' if gem else 'нет'}, Groq {'есть' if groq else 'нет'}, "
      f"Claude {'есть' if claude else 'нет'}")


def show(r):
    body = r.text.replace(gem, "<KEY>") if gem else r.text
    print(f"Ответ сервера: {r.status_code}")
    if r.status_code != 200:
        print("Причина:", body[:600])
    return r.status_code == 200


try:
    if claude:
        print("Используется Claude (у него приоритет). Проверяю…")
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=40,
                          headers={"x-api-key": claude, "anthropic-version": "2023-06-01"},
                          json={"model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"), "max_tokens": 20,
                                "messages": [{"role": "user", "content": "Скажи «ок»"}]})
        ok = show(r)
    elif gem:
        models = [m.strip() for m in os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest,gemini-flash-latest").split(",")]
        ok = False
        r = None
        for model in models:
            print(f"Используется Gemini, модель {model}. Проверяю…")
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  headers={"x-goog-api-key": gem}, timeout=25,
                                  json={"contents": [{"role": "user", "parts": [{"text": "Скажи «ок»"}]}]})
            except requests.exceptions.Timeout:
                print("Не ответила за 25 сек — пробую запасную…\n")
                continue
            ok = show(r)
            if ok or r.status_code not in (429, 500, 503):
                break
            print("Модель занята — пробую запасную…\n")
        if not ok and groq:
            print("Gemini не ответил — проверяю запасной Groq…")
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", timeout=25,
                              headers={"Authorization": f"Bearer {groq}"},
                              json={"model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                                    "messages": [{"role": "user", "content": "Скажи «ок»"}]})
            ok = show(r)
        if not ok and not groq:
            print("\n💡 Совет: добавь запасной бесплатный AI — Groq (console.groq.com → API Keys),"
                  " затем python3.12 set_key.py → 2. Когда Google перегружен, ответит Groq.")
        if r is None:
            r = type("R", (), {"status_code": 0})()
        if r.status_code == 404:
            print("\nМодель не найдена. Доступные модели Flash для твоего ключа:")
            lst = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                               headers={"x-goog-api-key": gem}, timeout=40)
            for m in lst.json().get("models", []):
                if "flash" in m["name"] and "generateContent" in m.get("supportedGenerationMethods", []):
                    print("  ", m["name"].split("/")[-1])
    elif groq:
        print("Используется Groq. Проверяю…")
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", timeout=40,
                          headers={"Authorization": f"Bearer {groq}"},
                          json={"model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                                "messages": [{"role": "user", "content": "Скажи «ок»"}]})
        ok = show(r)
    else:
        print("Ни одного ключа нет — запусти python3.12 set_key.py")
        ok = False
    print("\n✔ AI работает! Нажми Reload на вкладке Web, если ещё не нажимал.\n" if ok else
          "\n✖ AI не отвечает. Пришли фото этого экрана в чат с Claude.\n")
except requests.exceptions.ProxyError:
    print("\n✖ Прокси PythonAnywhere не пустил запрос (временный сбой или сайт не в белом списке). "
          "Повтори через минуту.\n")
except Exception as e:
    msg = str(e).replace(gem, "<KEY>") if gem else str(e)
    print(f"\n✖ Ошибка: {type(e).__name__}: {msg[:300]}\n")
