"""AI-тренер. Работает с любым из трёх сервисов — какой ключ задан в .env, тот и используется:

  GEMINI_API_KEY     — Google Gemini, бесплатно (aistudio.google.com)
  GROQ_API_KEY       — Groq (Llama), бесплатно (console.groq.com)
  ANTHROPIC_API_KEY  — Claude, платно (console.anthropic.com)

Все три адреса есть в белом списке бесплатного PythonAnywhere.
"""
import os
import re

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


# ======================= распознавание еды =======================

FOOD_PROMPT = """Ты нутрициолог. Определи, что съел человек, и оцени вес и КБЖУ каждой позиции.
Ориентируйся на типичные порции в Казахстане/СНГ. Если на фото тарелка — оцени по размеру тарелки и приборов.
Если человек указал граммы в подписи — используй их. Не выдумывай блюда, которых не видно и не названо.
Если еды нет — верни пустой список items и в comment напиши, что еду не нашёл.

Ответь ТОЛЬКО JSON без пояснений, строго в таком формате:
{"items":[{"name":"гречка варёная","grams":200,"kcal":220,"protein":8,"fat":2,"carbs":42}],
 "comment":"одна короткая фраза: оценка приёма пищи для цели сбросить жир"}
Названия — по-русски, коротко. Числа — целые."""


def _gemini_food(parts):
    model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json",
                                 "maxOutputTokens": 2000},
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])


def _groq_food(text, image_b64):
    content = [{"type": "text", "text": text}]
    if image_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        json={
            "model": os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 1500,
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _claude_food(text, image_b64):
    from anthropic import Anthropic

    content = []
    if image_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
    content.append({"type": "text", "text": text})
    resp = Anthropic(timeout=TIMEOUT).messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        max_tokens=1500,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _parse_food_json(raw):
    import json

    m = re.search(r"\{.*\}", raw or "", re.S)
    data = json.loads(m.group(0)) if m else {}
    items = []
    for it in data.get("items") or []:
        try:
            items.append({
                "name": str(it.get("name", "еда"))[:60],
                "grams": int(round(float(it.get("grams") or 0))),
                "kcal": int(round(float(it.get("kcal") or 0))),
                "protein": int(round(float(it.get("protein") or 0))),
                "fat": int(round(float(it.get("fat") or 0))),
                "carbs": int(round(float(it.get("carbs") or 0))),
            })
        except (TypeError, ValueError):
            continue
    return {"items": items, "comment": str(data.get("comment") or "")[:200]}


def analyze_food(text="", image_bytes=None):
    """Фото и/или описание еды → {"items": [...], "comment": "..."}."""
    import base64

    p = provider()
    if not p:
        raise RuntimeError("no_ai")
    prompt = FOOD_PROMPT + (f"\n\nОписание от человека: {text}" if text else "")
    b64 = base64.b64encode(image_bytes).decode() if image_bytes else None
    if p == "gemini":
        parts = [{"text": prompt}]
        if b64:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
        raw = _gemini_food(parts)
    elif p == "groq":
        raw = _groq_food(prompt, b64)
    else:
        raw = _claude_food(prompt, b64)
    return _parse_food_json(raw)


def ask(question, user):
    p = provider()
    if not p:
        return "AI-тренер выключен. Добавь в файл .env ключ GEMINI_API_KEY (бесплатно, см. README)."
    fn = {"gemini": _gemini, "groq": _groq, "claude": _claude}[p]
    text = fn(_system_for(user), question).strip()
    return text.replace("**", "").replace("##", "") or "Не смог ответить, попробуй переформулировать."
