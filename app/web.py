"""Web katmanı ortak yardımcıları: şablonlar, filtreler, yönlendirme, form ayrıştırma."""
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import markdown as md_lib
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import ai, config, db, domain
from .auth import can_see_project

APP_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=APP_DIR / "templates")


def md(text: str | None) -> Markup:
    """Markdown → güvenli HTML. Ham HTML ve javascript: linkleri temizlenir; [D12] doküman atıfları linke çevrilir."""
    if not text:
        return Markup("")
    m = md_lib.Markdown(extensions=["tables", "sane_lists"])
    m.preprocessors.deregister("html_block")
    m.inlinePatterns.deregister("html")
    html = m.convert(text)
    html = re.sub(r'href="\s*(javascript|data|vbscript):[^"]*"', 'href="#"', html, flags=re.I)
    html = re.sub(r"\[D(\d{1,7})\]", r'<a class="cite" href="/dokumanlar/\1" title="Kaynak doküman">D\1</a>', html)
    return Markup(html)


def money(v) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:,.1f} M TL".replace(".", ",")
    return f"{v:,.0f} TL".replace(",", ".")


def num(v) -> str:
    if v is None:
        return "—"
    if float(v).is_integer():
        return f"{v:,.0f}".replace(",", ".")
    return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def fdate(v) -> str:
    if not v:
        return "—"
    try:
        d = datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return str(v)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def ago(v) -> str:
    if not v:
        return "—"
    try:
        d = datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return str(v)
    delta = datetime.now() - d
    if delta.days >= 30 or delta.days < 0:
        return fdate(v)
    if delta.days >= 1:
        return f"{delta.days} gün önce"
    if delta.seconds >= 3600:
        return f"{delta.seconds // 3600} saat önce"
    return f"{max(1, delta.seconds // 60)} dk önce"


def period(p: str) -> str:
    try:
        y, m = p.split("-")
        return f"{MONTHS[int(m) - 1]} {y[2:]}"
    except (ValueError, IndexError):
        return p


def overdue(d) -> bool:
    return bool(d) and str(d)[:10] < date.today().isoformat()


def size(n) -> str:
    n = n or 0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024


templates.env.filters.update(md=md, money=money, num=num, date=fdate, ago=ago, period=period, overdue=overdue, size=size,
                             fromjson=lambda s: json.loads(s or "[]"))
templates.env.globals.update(D=domain, APP_NAME=config.APP_NAME, ORG_NAME=config.ORG_NAME, ai_label=ai.provider_label,
                             ai_live=ai.is_live, AUTH_ENABLED=config.AUTH_ENABLED, MAX_UPLOAD_MB=config.MAX_UPLOAD_MB,
                             GATES=domain.gate_checks({}, [], set()), today=lambda: date.today().isoformat())


def nav_counts() -> dict:
    return {"pending": db.scalar("SELECT COUNT(*) FROM facts WHERE status = 'oneri'") or 0,
            "processing": db.scalar("SELECT COUNT(*) FROM documents WHERE status IN ('sirada', 'isleniyor')") or 0}


def render(request: Request, name: str, user: dict, **ctx) -> HTMLResponse:
    flash_msg = request.session.pop("flash", None)
    return templates.TemplateResponse(request, name, {"user": user, "flash": flash_msg, "path": request.url.path,
                                                      "nav": nav_counts(), **ctx})


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def back(request: Request, fallback: str = "/") -> RedirectResponse:
    parsed = urlparse(request.headers.get("referer") or "")
    target = parsed.path + (f"?{parsed.query}" if parsed.query else "") if parsed.path.startswith("/") else fallback
    return redirect(target or fallback)


def parse_float(v) -> float | None:
    """Türkçe ve İngilizce sayı yazımlarını kabul eder: 1.500.000 · 1500000 · 12,5 · 12.5"""
    s = str(v or "").strip().replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def get_project(pid: int, user: dict) -> dict:
    p = db.row("SELECT p.*, d.name AS dept FROM projects p LEFT JOIN departments d ON d.id = p.department_id WHERE p.id = ?", (pid,))
    if not p or not can_see_project(user, p):
        raise HTTPException(404, "Proje bulunamadı")
    return p


def visible_projects(user: dict, where: str = "1=1", params=()) -> list[dict]:
    if user["role"] == "dt":
        where += " AND p.visible_to_dt = 1"
    return db.rows(f"SELECT p.*, d.name AS dept FROM projects p LEFT JOIN departments d ON d.id = p.department_id "
                   f"WHERE {where} ORDER BY p.code", params)


def departments(active_only: bool = True) -> list[dict]:
    return db.rows("SELECT * FROM departments" + (" WHERE active = 1" if active_only else "") + " ORDER BY sort, name")
