"""Zaman çizelgesi: proje Gantt şeması, çeyreklik başlayan/tamamlanan, kümülatif tamamlanma.

Tanımlar
- Başlangıç: projects.start_date
- Tamamlanma: projects.golive_date (canlıya geçiş). Aşama "Canlıda" veya "Ölçeklendirme" ise tamamlanmış sayılır.
- Planlanan bitiş: projects.target_date. Hedef geçtiyse ve proje canlıda değilse "gecikmiş".
"""
from datetime import date, timedelta
from html import escape

from . import charts, db
from .domain import STAGE_LABELS

_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
DONE = {"canli", "olcekleme"}


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _quarter(d: date) -> str:
    return f"{d.year} Ç{(d.month - 1) // 3 + 1}"


def load(department_id: int | None = None, stage: str | None = None, year: int | None = None) -> list[dict]:
    where, params = ["1=1"], []
    if department_id:
        where.append("p.department_id = ?")
        params.append(department_id)
    if stage:
        where.append("p.stage = ?")
        params.append(stage)
    rows = db.rows("SELECT p.*, d.name AS dept FROM projects p LEFT JOIN departments d ON d.id = p.department_id "
                   f"WHERE {' AND '.join(where)} ORDER BY COALESCE(p.start_date, '9999'), p.code", tuple(params))
    today = date.today()
    out = []
    for p in rows:
        s, t, g = _d(p["start_date"]), _d(p["target_date"]), _d(p["golive_date"])
        done = p["stage"] in DONE
        p.update(start=s, target=t, golive=g if done else None, done=done,
                 overdue=bool(t and t < today and not done and p["stage"] not in ("iptal",)),
                 duration=(g - s).days if done and g and s else None)
        if year and not any(x and x.year == year for x in (s, t, g)):
            continue
        out.append(p)
    return out


def summary(projects: list[dict]) -> dict:
    today = date.today()
    done = [p for p in projects if p["done"]]
    durations = [p["duration"] for p in done if p["duration"] is not None and p["duration"] >= 0]
    return {
        "total": len(projects),
        "done": len(done),
        "done_this_year": sum(1 for p in done if p["golive"] and p["golive"].year == today.year),
        "ongoing": sum(1 for p in projects if p["stage"] in ("onay", "gelistirme", "pilot")),
        "pipeline": sum(1 for p in projects if p["stage"] in ("fikir", "analiz")),
        "paused": sum(1 for p in projects if p["stage"] in ("beklemede", "iptal")),
        "overdue": sum(1 for p in projects if p["overdue"]),
        "avg_days": round(sum(durations) / len(durations)) if durations else None,
        "undated": sum(1 for p in projects if not p["start"]),
        "due_90": sum(1 for p in projects if not p["done"] and p["target"] and today <= p["target"] <= today + timedelta(days=90)),
    }


def gantt(projects: list[dict], group_by: str = "dept") -> str:
    today = date.today()
    dated = [p for p in projects if p["start"]]
    if not dated:
        return '<p class="muted">Başlangıç tarihi girilmiş proje yok.</p>'
    lo = min(p["start"] for p in dated).replace(day=1)
    hi = max([today] + [x for p in dated for x in (p["target"], p["golive"]) if x])
    hi = (hi.replace(day=1) + timedelta(days=62)).replace(day=1)
    label_w, w, row_h, head_h = 270, 1180, 26, 50
    span = (hi - lo).days or 1

    def x(d: date) -> float:
        return label_w + (d - lo).days / span * (w - label_w - 10)

    groups: dict[str, list] = {}
    for p in dated:
        key = (p["dept"] or "Departman atanmamış") if group_by == "dept" else STAGE_LABELS[p["stage"]]
        groups.setdefault(key, []).append(p)
    if group_by == "stage":
        order = list(STAGE_LABELS.values())
        groups = dict(sorted(groups.items(), key=lambda kv: order.index(kv[0])))
    n_rows = sum(len(v) + 1 for v in groups.values())
    h = head_h + n_rows * row_h + 8
    parts = [f'<svg class="chart gantt" viewBox="0 0 {w} {h}" role="img" aria-label="Proje zaman çizelgesi">']
    # ay/çeyrek ızgarası
    m = lo
    while m < hi:
        nx = x(m)
        is_q = m.month in (1, 4, 7, 10)
        parts.append(f'<line class="{"grid-q" if is_q else "grid"}" x1="{nx:.1f}" x2="{nx:.1f}" y1="{head_h - 6}" y2="{h}"/>')
        parts.append(f'<text class="tick" x="{nx + 3:.1f}" y="{head_h - 12}">{_MONTHS[m.month - 1]}</text>')
        if m.month == 1 or m == lo:
            parts.append(f'<text class="group" x="{nx + 3:.1f}" y="{head_h - 26}">{m.year}</text>')
        m = (m + timedelta(days=32)).replace(day=1)
    y = head_h
    for gname, items in groups.items():
        parts.append(f'<text class="group" x="4" y="{y + 17}">{escape(gname)} · {len(items)}</text>')
        parts.append(f'<line class="axis" x1="0" x2="{w}" y1="{y + row_h - 2}" y2="{y + row_h - 2}"/>')
        y += row_h
        for p in items:
            cy = y + row_h / 2
            name = p["name"] if len(p["name"]) <= 30 else p["name"][:29] + "…"
            parts.append(f'<a href="/projeler/{p["id"]}"><text class="label" x="14" y="{cy + 4:.1f}"><tspan class="code">{p["code"]}</tspan> {escape(name)}</text></a>')
            s = p["start"]
            end_actual = p["golive"] if p["done"] and p["golive"] else min(today, hi)
            if p["stage"] in ("beklemede", "iptal"):
                cls = "paused"
            elif p["done"]:
                cls = "done"
            else:
                cls = "active"
            tip = (f"{p['code']} {p['name']} · {STAGE_LABELS[p['stage']]} · başlangıç {s:%d.%m.%Y}"
                   + (f" · canlı {p['golive']:%d.%m.%Y} ({p['duration']} gün)" if p["golive"] else "")
                   + (f" · hedef {p['target']:%d.%m.%Y}" if p["target"] else "") + (" · GECİKMİŞ" if p["overdue"] else ""))
            g = [f'<g class="hit" data-tip="{escape(tip)}">']
            g.append(f'<rect x="{label_w - 4}" y="{y}" width="{w - label_w + 4}" height="{row_h}" fill="transparent"/>')
            x1, x2 = x(s), max(x(end_actual), x(s) + 3)
            g.append(f'<rect class="bar {cls}" x="{x1:.1f}" y="{cy - 6:.1f}" width="{x2 - x1:.1f}" height="12" rx="3"/>')
            if not p["done"] and p["target"] and p["target"] > end_actual:
                g.append(f'<rect class="bar plan" x="{x2:.1f}" y="{cy - 6:.1f}" width="{x(p["target"]) - x2:.1f}" height="12" rx="3"/>')
            if p["overdue"]:
                g.append(f'<rect class="bar late" x="{x(p["target"]):.1f}" y="{cy - 2:.1f}" width="{max(2, x(today) - x(p["target"])):.1f}" height="4" rx="2"/>')
            if p["target"]:
                tx = x(p["target"])
                g.append(f'<path class="target{" late" if p["overdue"] else ""}" d="M{tx:.1f},{cy - 6:.1f} l5,6 l-5,6 l-5,-6 z"/>')
            if p["golive"]:
                g.append(f'<circle class="golive" cx="{x(p["golive"]):.1f}" cy="{cy:.1f}" r="5"/>')
            g.append(f'<circle class="health-dot {p["health"]}" cx="{label_w - 12}" cy="{cy:.1f}" r="4"/>')
            g.append("</g>")
            parts += g
            y += row_h
    tx = x(today)
    parts.append(f'<line class="today" x1="{tx:.1f}" x2="{tx:.1f}" y1="{head_h - 6}" y2="{h}"/>')
    parts.append(f'<text class="today-label" x="{tx + 4:.1f}" y="{head_h - 1}">Bugün</text>')
    parts.append("</svg>")
    return "".join(parts)


def quarterly(projects: list[dict]) -> list[dict]:
    starts = [p["start"] for p in projects if p["start"]]
    if not starts:
        return []
    today = date.today()
    q = date(min(starts).year, ((min(starts).month - 1) // 3) * 3 + 1, 1)
    end = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    out, cum = [], 0
    while q <= end:
        label = _quarter(q)
        started = [p for p in projects if p["start"] and _quarter(p["start"]) == label]
        done = [p for p in projects if p["golive"] and _quarter(p["golive"]) == label]
        planned = [p for p in projects if not p["done"] and p["target"] and _quarter(p["target"]) == label]
        cum += len(done)
        out.append({"label": label, "started": started, "done": done, "planned": planned, "cum": cum})
        q = date(q.year + (q.month + 2) // 12, (q.month + 2) % 12 + 1, 1)
    return out


def quarterly_bars(rows: list[dict]) -> str:
    """Çeyrek başına başlayan ve tamamlanan proje sayısı (gruplu çubuk)."""
    if not rows:
        return '<p class="muted">Veri yok</p>'
    w, h, pl, pb, pt = 720, 200, 30, 28, 12
    mx = max(1, max(max(len(r["started"]), len(r["done"])) for r in rows))
    iw, ih = w - pl - 10, h - pt - pb
    gw = iw / len(rows)
    bw = min(18, (gw - 10) / 2)
    parts = [f'<svg class="chart bars" viewBox="0 0 {w} {h}" role="img" aria-label="Çeyreklik başlayan ve tamamlanan">']
    for t in range(0, mx + 1, max(1, mx // 4 or 1)):
        y = pt + ih - t / mx * ih
        parts.append(f'<line class="grid" x1="{pl}" x2="{w - 10}" y1="{y:.1f}" y2="{y:.1f}"/><text class="tick" x="{pl - 6}" y="{y + 4:.1f}" text-anchor="end">{t}</text>')
    for i, r in enumerate(rows):
        cx = pl + gw * i + gw / 2
        for j, (key, cls, label) in enumerate((("started", "s1", "Başlayan"), ("done", "s2", "Tamamlanan"))):
            n = len(r[key])
            bh = n / mx * ih
            bx = cx - bw - 1 + j * (bw + 2)
            names = ", ".join(p["code"] for p in r[key]) or "—"
            parts.append(f'<g class="hit" data-tip="{escape(r["label"])} · {label}: {n} ({escape(names)})">'
                         f'<rect x="{bx - 1:.1f}" y="{pt}" width="{bw + 2:.1f}" height="{ih}" fill="transparent"/>'
                         f'<rect class="bar {cls}" x="{bx:.1f}" y="{pt + ih - bh:.1f}" width="{bw:.1f}" height="{max(bh, 0):.1f}" rx="3"/></g>')
        parts.append(f'<text class="tick" x="{cx:.1f}" y="{h - 8}" text-anchor="middle">{escape(r["label"].replace(" Ç", " Ç"))}</text>')
    parts.append(f'<line class="axis" x1="{pl}" x2="{w - 10}" y1="{pt + ih}" y2="{pt + ih}"/></svg>')
    return "".join(parts)


def cumulative_chart(rows: list[dict]) -> str:
    return charts.line_chart([(r["label"], r["cum"]) for r in rows], "proje", height=170)
