"""Расчёт нормы КБЖУ и анализ динамики веса."""
from datetime import date, timedelta

ACTIVITY = [
    ("Сидячая работа, мало шагов", 1.2),
    ("Зал 3 р/нед, шагов мало", 1.375),
    ("Зал 3–4 р/нед + 8–10к шагов", 1.55),
    ("Физ. работа / очень активно", 1.725),
]


def targets(sex: str, age: int, height: float, weight: float, activity: float) -> dict:
    """Миффлин–Сан Жеор, дефицит 20%, белок 2 г/кг, жир 0,8 г/кг."""
    bmr = 10 * weight + 6.25 * height - 5 * age + (5 if sex == "m" else -161)
    tdee = bmr * activity
    floor = 1500 if sex == "m" else 1200
    kcal = max(round(tdee * 0.8 / 10) * 10, floor)
    protein = round(weight * (2.0 if weight <= 100 else 1.7))
    fat = round(weight * 0.8)
    carbs = max(round((kcal - protein * 4 - fat * 9) / 4), 50)
    return {
        "bmr": round(bmr),
        "tdee": round(tdee),
        "kcal": kcal,
        "protein": protein,
        "fat": fat,
        "carbs": carbs,
    }


def _avg(rows, start: date, end: date):
    vals = [kg for d, kg in rows if start <= date.fromisoformat(d) <= end]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def trend(rows: list[tuple[str, float]], today: date) -> dict:
    """Сравнивает средний вес последних 7 дней с предыдущими 7 днями."""
    cur, n_cur = _avg(rows, today - timedelta(days=6), today)
    prev, n_prev = _avg(rows, today - timedelta(days=13), today - timedelta(days=7))
    res = {"cur": cur, "prev": prev, "delta": None, "pct": None, "advice": None}
    if cur is None or prev is None:
        res["advice"] = "Взвешивайся каждое утро натощак — через 2 недели покажу тренд."
        return res
    delta = cur - prev
    pct = delta / prev * 100
    res.update(delta=delta, pct=pct)
    if n_cur < 3 or n_prev < 3:
        res["advice"] = "Мало взвешиваний для точного вывода — нужно хотя бы 3 в неделю."
    elif pct > -0.25:
        res["advice"] = (
            "Вес стоит. Если так уже 2 недели подряд — убери ~150 ккал (обычно из углеводов) "
            "или добавь 2–3 тыс. шагов в день. Проверь, не «плывут» ли порции и масло."
        )
    elif pct < -1.2:
        res["advice"] = (
            "Теряешь слишком быстро (>1,2% в неделю) — уйдёт и мышца. Добавь ~150 ккал."
        )
    else:
        res["advice"] = "Отличный темп: 0,3–1% веса в неделю. Ничего не меняй 👍"
    return res
