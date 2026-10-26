"""График веса для «📊 Прогресс». Нужен matplotlib (на PythonAnywhere уже установлен)."""
import io
from datetime import date, timedelta

BLUE = "#2a78d6"      # линия средней
DOTS = "#9b9a96"      # взвешивания по дням — приглушённо
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e6e5e1"
SURFACE = "#fcfcfb"


def rolling_avg(rows):
    """Средняя за 7 дней (по имеющимся взвешиваниям) для каждой даты."""
    pts = [(date.fromisoformat(d), kg) for d, kg in rows]
    out = []
    for d, _ in pts:
        win = [kg for dd, kg in pts if d - timedelta(days=6) <= dd <= d]
        out.append((d, sum(win) / len(win)))
    return pts, out


def weight_chart(rows):
    """rows: [(YYYY-MM-DD, kg)], по возрастанию дат. Возвращает PNG (bytes) или None."""
    if len(rows) < 2:
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except Exception:
        return None

    pts, avg = rolling_avg(rows[-60:])
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    ax.scatter([d for d, _ in pts], [k for _, k in pts], s=22, color=DOTS, zorder=2,
               edgecolors=SURFACE, linewidths=1)
    ax.plot([d for d, _ in avg], [k for _, k in avg], color=BLUE, linewidth=2.2, zorder=3,
            solid_capstyle="round")

    # прямые подписи вместо легенды
    last_d, last_avg = avg[-1]
    ax.annotate(f"{last_avg:.1f} кг", (last_d, last_avg), xytext=(8, 0), textcoords="offset points",
                va="center", fontsize=11, fontweight="bold", color=INK)
    first_avg = avg[0][1]
    delta = last_avg - first_avg
    ax.set_title(f"Вес: средняя за 7 дней  ({delta:+.1f} кг с {pts[0][0]:%d.%m})",
                 loc="left", fontsize=12, color=INK, pad=12)
    ax.text(0, -0.16, "● взвешивания по дням   — средняя за 7 дней", transform=ax.transAxes,
            fontsize=9, color=INK2)

    lo = min(k for _, k in pts)
    hi = max(k for _, k in pts)
    pad = max(0.5, (hi - lo) * 0.15)
    ax.set_ylim(lo - pad, hi + pad)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=8))
    ax.margins(x=0.06)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    return buf.getvalue()
