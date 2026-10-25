"""AI-тренер на Claude (необязательно — работает, если задан ANTHROPIC_API_KEY)."""
import os

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

SYSTEM = """Ты — персональный фитнес-тренер и нутрициолог в Telegram. Цель клиента — сбросить жир, \
сохранив мышцы. Он тренируется в тренажёрном зале и готовит в Термомиксе.

Правила:
- Отвечай по-русски, коротко и по делу (до 15 строк), без воды и без markdown-разметки.
- Рецепты — только ПП, под Термомикс: режимы «время / температура / ↺ / скорость», граммовки, \
примерное КБЖУ на порцию.
- Тренировки — с подходами, повторениями и отдыхом; технику — ключевые моменты списком.
- Опирайся на норму клиента ниже. Не предлагай голодание, диеты ниже нормы и «жиросжигатели».
- При боли, травмах, лекарствах или проблемах со здоровьем — советуй обратиться к врачу.
- Поддерживай, но честно: если план клиента плохой — скажи прямо и предложи лучше."""


def enabled():
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def ask(question, user):
    if not enabled():
        return "AI-тренер выключен. Добавь ANTHROPIC_API_KEY в файл .env (см. README)."
    from anthropic import Anthropic

    ctx = (
        f"\n\nДанные клиента: пол {'М' if user['sex'] == 'm' else 'Ж'}, {user['age']} лет, "
        f"рост {user['height']:.0f} см, вес {user['weight']:.1f} кг, зал {user['days']} р/нед. "
        f"Норма: {user['kcal']} ккал, Б {user['protein']} / Ж {user['fat']} / У {user['carbs']} г."
    )
    resp = Anthropic(timeout=50).messages.create(
        model=MODEL,
        max_tokens=1200,
        system=SYSTEM + ctx,
        messages=[{"role": "user", "content": question}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
