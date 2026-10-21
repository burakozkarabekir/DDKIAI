"""Bağımlılıksız SVG grafikler (DMZ'de dış CDN'e ihtiyaç olmasın diye).

Her nokta/çubuk `data-tip` taşır; static/js/app.js bunları ortak bir tooltip ile gösterir.
"""
from html import escape


def _fmt(v: float, unit: str = "") -> str:
    if v is None:
        return "—"
    s = f"{v:,.0f}".replace(",", ".") if abs(v) >= 100 or float(v).is_integer() else f"{v:.1f}".replace(".", ",")
    return f"{s} {unit}".strip() if unit and unit != "%" else (s + "%" if unit == "%" else s)


def line_chart(points: list[tuple[str, float]], unit: str = "", height: int = 150, series_class: str = "s1") -> str:
    """Tek seri çizgi grafik. points: [(etiket, değer)]"""
    if not points:
        return '<p class="muted small">Veri yok</p>'
    w, h, pl, pr, pt, pb = 520, height, 44, 14, 14, 26
    vals = [v for _, v in points]
    lo, hi = 0, max(vals) or 1
    hi = _nice(hi)
    iw, ih = w - pl - pr, h - pt - pb
    step = iw / max(1, len(points) - 1)

    def x(i):
        return pl + (i * step if len(points) > 1 else iw / 2)

    def y(v):
        return pt + ih - (v - lo) / (hi - lo) * ih

    grid = []
    for t in (0, 0.5, 1):
        gv = lo + (hi - lo) * t
        gy = y(gv)
        grid.append(f'<line class="grid" x1="{pl}" x2="{w - pr}" y1="{gy:.1f}" y2="{gy:.1f}"/>'
                    f'<text class="tick" x="{pl - 6}" y="{gy + 4:.1f}" text-anchor="end">{escape(_fmt(gv))}</text>')
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(points))
    labels = []
    every = max(1, len(points) // 6)
    for i, (lab, _) in enumerate(points):
        if i % every == 0 or i == len(points) - 1:
            labels.append(f'<text class="tick" x="{x(i):.1f}" y="{h - 6}" text-anchor="middle">{escape(lab)}</text>')
    dots = []
    for i, (lab, v) in enumerate(points):
        tip = escape(f"{lab}: {_fmt(v, unit)}")
        last = i == len(points) - 1
        dots.append(f'<g class="hit" data-tip="{tip}"><rect x="{x(i) - step / 2:.1f}" y="{pt}" width="{max(step, 12):.1f}" height="{ih}" fill="transparent"/>'
                    f'<circle class="dot {series_class}{" last" if last else ""}" cx="{x(i):.1f}" cy="{y(v):.1f}" r="{4 if last else 3}"/></g>')
    end_label = f'<text class="end-label" x="{x(len(points) - 1) - 6:.1f}" y="{y(vals[-1]) - 9:.1f}" text-anchor="end">{escape(_fmt(vals[-1], unit))}</text>'
    return (f'<svg class="chart line" viewBox="0 0 {w} {h}" role="img" preserveAspectRatio="none">'
            f'{"".join(grid)}<line class="axis" x1="{pl}" x2="{w - pr}" y1="{y(lo):.1f}" y2="{y(lo):.1f}"/>'
            f'<path class="line {series_class}" d="{path}"/>{"".join(dots)}{end_label}{"".join(labels)}</svg>')


def _nice(v: float) -> float:
    if v <= 0:
        return 1
    import math
    mag = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * mag:
            return m * mag
    return 10 * mag
