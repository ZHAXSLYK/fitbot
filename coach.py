"""AI-тренер. Работает с любым из трёх сервисов — какой ключ задан в .env, тот и используется:

  GEMINI_API_KEY     — Google Gemini, бесплатно (aistudio.google.com)
  GROQ_API_KEY       — Groq (Llama), бесплатно (console.groq.com)
  ANTHROPIC_API_KEY  — Claude, платно (console.anthropic.com)

Все три адреса есть в белом списке бесплатного PythonAnywhere.
"""
import os

import requests

SYSTEM = """Ты — персональный фитнес-тренер и нутрициолог в Telegram. Цель клиента — сбросить жир, \
сохранив мышцы. Он тренируется в тренажёрном зале и готовит в Термомиксе.

Правила:
- Отвечай по-русски, коротко и по делу (до 15 строк), без воды и без markdown-разметки (никаких * и #).
- Рецепты — только ПП, под Термомикс: режимы «время / температура / ↺ / скорость», граммовки, \
примерное КБЖУ на порцию.
- Тренировки — с подходами, повторениями и отдыхом; технику — ключевые моменты списком.
- Опирайся на норму клиента ниже. Не предлагай голодание, диеты ниже нормы и «жиросжигатели».
- При боли, травмах, лекарствах или проблемах со здоровьем — советуй обратиться к врачу.
- Поддерживай, но честно: если план клиента плохой — скажи прямо и предложи лучше."""

TIMEOUT = 45


def provider():
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    return None


def enabled():
    return provider() is not None


def _system_for(user):
    return SYSTEM + (
        f"\n\nДанные клиента: пол {'М' if user['sex'] == 'm' else 'Ж'}, {user['age']} лет, "
        f"рост {user['height']:.0f} см, вес {user['weight']:.1f} кг, зал {user['days']} р/нед. "
        f"Норма: {user['kcal']} ккал, Б {user['protein']} / Ж {user['fat']} / У {user['carbs']} г."
    )


def _gemini(system, question):
    model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": question}]}],
            "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.6},
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


def _groq(system, question):
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        json={
            "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}],
            "max_tokens": 1500,
            "temperature": 0.6,
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _claude(system, question):
    from anthropic import Anthropic

    resp = Anthropic(timeout=TIMEOUT).messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        max_tokens=1200,
        system=system,
        messages=[{"role": "user", "content": question}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def ask(question, user):
    p = provider()
    if not p:
        return "AI-тренер выключен. Добавь в файл .env ключ GEMINI_API_KEY (бесплатно, см. README)."
    fn = {"gemini": _gemini, "groq": _groq, "claude": _claude}[p]
    text = fn(_system_for(user), question).strip()
    return text.replace("**", "").replace("##", "") or "Не смог ответить, попробуй переформулировать."
