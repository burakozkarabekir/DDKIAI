"""AI Impact Merkezi — FastAPI uygulaması."""
import json
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import markdown as md_lib
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.middleware.sessions import SessionMiddleware

from . import ai, charts, config, db, domain, reports, security, seed, trello
from .auth import (LoginRequired, authenticate, can_see_project, current_user, hash_password, require_admin,
                   require_editor, require_internal, require_uploader, require_user)
from .extract import ALLOWED_EXT, extract_text

APP_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    seed.ensure_admin()
    if config.SEED_DEMO:
        seed.seed_demo()
    yield


app = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, max_age=config.SESSION_HOURS * 3600,
                   same_site="lax", https_only=config.COOKIE_SECURE, session_cookie="aiimpact")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Basit CSRF koruması: form gönderimlerinde Origin başka bir siteyi gösteriyorsa reddet.
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return PlainTextResponse("Geçersiz istek kaynağı", status_code=403)
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'"
    return response


@app.exception_handler(LoginRequired)
async def _login_redirect(request: Request, _exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Oturum gerekli"}, status_code=401)
    return RedirectResponse(f"/giris?next={request.url.path}", status_code=303)


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    return templates.TemplateResponse(request, "error.html", {"user": current_user(request), "path": request.url.path, "code": exc.status_code,
                                                              "message": exc.detail}, status_code=exc.status_code)


# ------------------------------------------------------------------ şablon yardımcıları

def _md(text: str | None) -> Markup:
    if not text:
        return Markup("")
    m = md_lib.Markdown(extensions=["tables", "sane_lists"])
    m.preprocessors.deregister("html_block")
    m.inlinePatterns.deregister("html")
    html = m.convert(text)
    html = re.sub(r'href="\s*(javascript|data|vbscript):[^"]*"', 'href="#"', html, flags=re.I)
    return Markup(html)


def _money(v) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:,.1f} M TL".replace(".", ",")
    return f"{v:,.0f} TL".replace(",", ".")


def _num(v) -> str:
    if v is None:
        return "—"
    if float(v).is_integer():
        return f"{v:,.0f}".replace(",", ".")
    return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def _date(v) -> str:
    if not v:
        return "—"
    try:
        d = datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return str(v)
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def _ago(v) -> str:
    if not v:
        return "—"
    try:
        d = datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return str(v)
    delta = datetime.now() - d
    if delta.days >= 30:
        return _date(v)
    if delta.days >= 1:
        return f"{delta.days} gün önce"
    if delta.seconds >= 3600:
        return f"{delta.seconds // 3600} saat önce"
    return f"{max(1, delta.seconds // 60)} dk önce"


def _period(p: str) -> str:
    try:
        y, m = p.split("-")
        return f"{_MONTHS[int(m) - 1]} {y[2:]}"
    except (ValueError, IndexError):
        return p


def _overdue(d) -> bool:
    return bool(d) and str(d)[:10] < date.today().isoformat()


templates.env.filters.update(md=_md, money=_money, num=_num, date=_date, ago=_ago, period=_period,
                             fromjson=lambda s: json.loads(s or "[]"), overdue=_overdue)
templates.env.globals.update(D=domain, APP_NAME=config.APP_NAME, ORG_NAME=config.ORG_NAME, ai_label=ai.provider_label,
                             ai_live=ai.is_live, GATES=domain.gate_checks({}, [], set()), today=lambda: date.today().isoformat())


def render(request: Request, name: str, user: dict, **ctx) -> HTMLResponse:
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, name, {"user": user, "flash": flash, "path": request.url.path, **ctx})


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def back(request: Request, fallback: str = "/") -> RedirectResponse:
    ref = request.headers.get("referer") or fallback
    parsed = urlparse(ref)
    target = parsed.path + (f"?{parsed.query}" if parsed.query else "") if parsed.path.startswith("/") else fallback
    return RedirectResponse(target or fallback, status_code=303)


def _f(v) -> float | None:
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
    p = db.row("SELECT * FROM projects WHERE id = ?", (pid,))
    if not p or not can_see_project(user, p):
        raise HTTPException(404, "Proje bulunamadı")
    return p


def visible_projects(user: dict, where: str = "1=1", params=()) -> list[dict]:
    if user["role"] == "dt":
        where += " AND visible_to_dt = 1"
    return db.rows(f"SELECT * FROM projects WHERE {where} ORDER BY code", params)


# ------------------------------------------------------------------ oturum

@app.get("/giris", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None, "demo": config.SEED_DEMO})


@app.post("/giris")
def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/")):
    user = authenticate(email, password)
    if not user:
        return templates.TemplateResponse(request, "login.html", {"next": next, "demo": config.SEED_DEMO,
                                                                  "error": "E-posta veya parola hatalı (ya da çok fazla deneme)."},
                                          status_code=401)
    request.session.clear()
    request.session["uid"] = user["id"]
    db.log(user["id"], "login")
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    return RedirectResponse(safe_next, status_code=303)


@app.get("/cikis")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/giris", status_code=303)


@app.get("/saglik")
def health():
    return {"ok": True, "ai": ai.provider_label()}


# ------------------------------------------------------------------ yönetici özeti

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(require_user)):
    if user["role"] == "dt":
        return RedirectResponse("/projeler", status_code=303)
    projects = db.rows("SELECT * FROM projects ORDER BY code")
    active = [p for p in projects if p["stage"] in domain.ACTIVE_STAGES]
    live = [p for p in projects if p["stage"] in ("canli", "olcekleme")]
    measured = [p for p in live if domain.MEASUREMENT_RANK[p["measurement_status"]] >= domain.MEASUREMENT_RANK["olculuyor"]]
    stage_counts = [(k, label, sum(1 for p in projects if p["stage"] == k)) for k, label, _ in domain.STAGES]
    side_counts = [(k, label, sum(1 for p in projects if p["stage"] == k)) for k, label, _ in domain.SIDE_STAGES]
    health_counts = {h: sum(1 for p in active if p["health"] == h) for h in domain.HEALTH}
    risky = sorted([p for p in projects if p["stage"] not in ("iptal",) and (p["health"] != "yesil" or (p["ai_risk_score"] or 0) >= 50)],
                   key=lambda p: -(p["ai_risk_score"] or 0))
    unmeasured_live = [p for p in live if p not in measured]
    overdue_actions = db.rows("SELECT a.*, p.code, p.name AS pname FROM actions a LEFT JOIN projects p ON p.id = a.project_id "
                              "WHERE a.status = 'acik' ORDER BY a.due_date")
    latest_report = db.row("SELECT * FROM weekly_reports ORDER BY week_start DESC LIMIT 1")
    latest_insight = db.row("SELECT * FROM ai_insights WHERE kind = 'weekly' ORDER BY created_at DESC LIMIT 1")
    activity = db.rows("SELECT a.*, u.name AS uname FROM activity a LEFT JOIN users u ON u.id = a.user_id "
                       "WHERE a.action NOT IN ('login','seed') ORDER BY a.id DESC LIMIT 8")
    recent_comments = db.rows(
        "SELECT c.*, u.name AS uname, u.organization, "
        "COALESCE(p.code || ' ' || p.name, i.name) AS target_name, "
        "CASE c.target_type WHEN 'project' THEN '/projeler/' || c.target_id ELSE '/guvenlik/' || i.slug END AS link "
        "FROM comments c JOIN users u ON u.id = c.user_id "
        "LEFT JOIN projects p ON c.target_type = 'project' AND p.id = c.target_id "
        "LEFT JOIN initiatives i ON c.target_type = 'initiative' AND i.id = c.target_id "
        "WHERE c.kind != 'trello' ORDER BY c.id DESC LIMIT 6")
    value = {
        "estimated": sum(p["estimated_value"] or 0 for p in projects if p["stage"] != "iptal"),
        "live_estimated": sum(p["estimated_value"] or 0 for p in live),
        "realized": sum(p["realized_value"] or 0 for p in projects),
        "fte": sum(p["fte_saving"] or 0 for p in live),
    }
    return render(request, "dashboard.html", user, projects=projects, active=active, live=live, measured=measured,
                  stage_counts=stage_counts, side_counts=side_counts, health_counts=health_counts, risky=risky[:7],
                  unmeasured_live=unmeasured_live, actions=overdue_actions, latest_report=latest_report,
                  latest_insight=latest_insight, activity=activity, stale=ai.stale_projects(), value=value,
                  coverage=ai.coverage(), recent_comments=recent_comments)


# ------------------------------------------------------------------ projeler

PROJECT_FIELDS = ["name", "summary", "problem", "solution", "value_chain", "business_unit", "brands", "ai_type", "health",
                  "priority", "sponsor", "owner", "dt_lead", "start_date", "target_date", "golive_date", "measurement_status",
                  "estimated_value", "realized_value", "fte_saving", "security_review", "data_class"]
NUMERIC = {"estimated_value", "realized_value", "fte_saving"}


@app.get("/projeler", response_class=HTMLResponse)
def project_list(request: Request, view: str = "pano", q: str = "", stage: str = "", health: str = "", alan: str = "",
                 olcum: str = "", user=Depends(require_user)):
    where, params = ["1=1"], []
    if q:
        where.append("(name LIKE ? OR code LIKE ? OR summary LIKE ? OR brands LIKE ? OR business_unit LIKE ?)")
        params += [f"%{q}%"] * 5
    for col, val in (("stage", stage), ("health", health), ("value_chain", alan), ("measurement_status", olcum)):
        if val:
            where.append(f"{col} = ?")
            params.append(val)
    projects = visible_projects(user, " AND ".join(where), tuple(params))
    counts = {r["target_id"]: r["n"] for r in db.rows(
        "SELECT target_id, COUNT(*) AS n FROM comments WHERE target_type = 'project' GROUP BY target_id")}
    docs = {r["project_id"]: r["n"] for r in db.rows(
        "SELECT project_id, COUNT(*) AS n FROM documents WHERE project_id IS NOT NULL GROUP BY project_id")}
    return render(request, "projects.html", user, projects=projects, view=view, counts=counts, docs=docs,
                  filters={"q": q, "stage": stage, "health": health, "alan": alan, "olcum": olcum})


@app.get("/projeler/yeni", response_class=HTMLResponse)
def project_new(request: Request, user=Depends(require_editor)):
    return render(request, "project_form.html", user, project={"stage": "fikir", "health": "yesil", "priority": "Orta",
                                                               "measurement_status": "yok", "security_review": "yok",
                                                               "visible_to_dt": 1})


def _project_data(form) -> dict:
    data = {}
    for f in PROJECT_FIELDS:
        v = form.get(f)
        if v is None:
            continue
        v = v.strip()
        data[f] = _f(v) if f in NUMERIC else (v or None)
    data["visible_to_dt"] = 1 if form.get("visible_to_dt") else 0
    return data


@app.post("/projeler")
async def project_create(request: Request, user=Depends(require_editor)):
    form = await request.form()
    data = _project_data(form)
    if not data.get("name"):
        raise HTTPException(400, "Proje adı zorunludur")
    n = (db.scalar("SELECT MAX(CAST(substr(code, 4) AS INTEGER)) FROM projects WHERE code LIKE 'AI-%'") or 0) + 1
    ts = db.now()
    stage = form.get("stage") if form.get("stage") in domain.STAGE_LABELS else "fikir"
    pid = db.insert("projects", {**data, "code": f"AI-{n:03d}", "stage": stage, "created_at": ts, "updated_at": ts})
    db.insert("stage_history", {"project_id": pid, "from_stage": None, "to_stage": stage, "note": "Kayıt açıldı",
                                "user_id": user["id"], "at": ts})
    db.log(user["id"], "project_created", "project", pid, data["name"])
    flash(request, "Proje oluşturuldu.")
    return RedirectResponse(f"/projeler/{pid}", status_code=303)


@app.get("/projeler/{pid}", response_class=HTMLResponse)
def project_detail(request: Request, pid: int, tab: str = "genel", user=Depends(require_user)):
    p = get_project(pid, user)
    kpis = db.rows("SELECT * FROM kpis WHERE project_id = ? ORDER BY id", (pid,))
    documents = db.rows("SELECT d.*, u.name AS uname FROM documents d LEFT JOIN users u ON u.id = d.uploaded_by "
                        "WHERE project_id = ? ORDER BY uploaded_at DESC", (pid,))
    gates = domain.gate_checks(p, kpis, {d["category"] for d in documents})
    history = db.rows("SELECT h.*, u.name AS uname FROM stage_history h LEFT JOIN users u ON u.id = h.user_id "
                      "WHERE project_id = ? ORDER BY at DESC", (pid,))
    updates = db.rows("SELECT ru.*, wr.week_start, wr.id AS rid FROM report_updates ru JOIN weekly_reports wr ON wr.id = ru.report_id "
                      "WHERE ru.project_id = ? ORDER BY wr.week_start DESC", (pid,))
    comments = _comments("project", pid, user)
    actions = db.rows("SELECT * FROM actions WHERE project_id = ? ORDER BY status, due_date", (pid,))
    next_stage = None
    if p["stage"] in domain.STAGE_ORDER and p["stage"] != domain.STAGE_ORDER[-1]:
        next_stage = domain.STAGE_ORDER[domain.STAGE_ORDER.index(p["stage"]) + 1]
    return render(request, "project_detail.html", user, p=p, kpis=kpis, documents=documents, gates=gates, history=history,
                  updates=updates, comments=comments, actions=actions, tab=tab, next_stage=next_stage)


@app.get("/projeler/{pid}/duzenle", response_class=HTMLResponse)
def project_edit(request: Request, pid: int, user=Depends(require_editor)):
    return render(request, "project_form.html", user, project=get_project(pid, user))


@app.post("/projeler/{pid}")
async def project_update(request: Request, pid: int, user=Depends(require_editor)):
    get_project(pid, user)
    data = _project_data(await request.form())
    data["updated_at"] = db.now()
    db.update("projects", pid, data)
    db.log(user["id"], "project_updated", "project", pid)
    flash(request, "Proje güncellendi.")
    return RedirectResponse(f"/projeler/{pid}", status_code=303)


@app.post("/projeler/{pid}/sil")
def project_delete(request: Request, pid: int, user=Depends(require_admin)):
    p = get_project(pid, user)
    db.execute("DELETE FROM comments WHERE target_type = 'project' AND target_id = ?", (pid,))
    db.execute("DELETE FROM projects WHERE id = ?", (pid,))
    db.log(user["id"], "project_deleted", "project", pid, p["code"])
    flash(request, f"{p['code']} silindi.")
    return RedirectResponse("/projeler", status_code=303)


@app.post("/projeler/{pid}/asama")
def project_stage(request: Request, pid: int, to_stage: str = Form(...), note: str = Form(""), user=Depends(require_editor)):
    p = get_project(pid, user)
    if to_stage not in domain.STAGE_LABELS or to_stage == p["stage"]:
        return back(request)
    kpis = db.rows("SELECT * FROM kpis WHERE project_id = ?", (pid,))
    cats = {r["category"] for r in db.rows("SELECT category FROM documents WHERE project_id = ?", (pid,))}
    missing = [c for c, ok in domain.gate_checks(p, kpis, cats).get(to_stage, []) if not ok]
    ts = db.now()
    db.insert("stage_history", {"project_id": pid, "from_stage": p["stage"], "to_stage": to_stage, "note": note or None,
                                "missing_criteria": json.dumps(missing, ensure_ascii=False) if missing else None,
                                "user_id": user["id"], "at": ts})
    data = {"stage": to_stage, "updated_at": ts}
    if to_stage == "canli" and not p["golive_date"]:
        data["golive_date"] = date.today().isoformat()
    db.update("projects", pid, data)
    db.log(user["id"], "stage_changed", "project", pid, f"{domain.STAGE_LABELS[p['stage']]} → {domain.STAGE_LABELS[to_stage]}")
    if missing:
        flash(request, "Aşama değişti, ancak kapı kriterleri eksik: " + ", ".join(missing), "warn")
    else:
        flash(request, f"Proje '{domain.STAGE_LABELS[to_stage]}' aşamasına taşındı.")
    return RedirectResponse(f"/projeler/{pid}", status_code=303)


@app.post("/projeler/{pid}/durum")
def project_status_note(request: Request, pid: int, health: str = Form(...), note: str = Form(""), user=Depends(require_uploader)):
    """Hızlı durum güncellemesi — DT de kullanabilir; yorum olarak da kaydedilir."""
    p = get_project(pid, user)
    if health not in domain.HEALTH:
        raise HTTPException(400, "Geçersiz sağlık değeri")
    ts = db.now()
    db.update("projects", pid, {"health": health, "last_status_at": ts, "updated_at": ts})
    body = f"**Durum güncellemesi:** {domain.HEALTH[health][0]}" + (f"\n\n{note}" if note.strip() else "")
    db.insert("comments", {"target_type": "project", "target_id": pid, "user_id": user["id"], "body": body, "kind": "durum",
                           "created_at": ts})
    db.log(user["id"], "status_updated", "project", pid, f"{p['code']} → {domain.HEALTH[health][0]}")
    flash(request, "Durum güncellendi.")
    return RedirectResponse(f"/projeler/{pid}", status_code=303)


@app.post("/projeler/{pid}/kpi")
def kpi_add(request: Request, pid: int, name: str = Form(...), unit: str = Form(""), direction: str = Form("up"),
            baseline: str = Form(""), target: str = Form(""), actual: str = Form(""), method: str = Form(""),
            user=Depends(require_uploader)):
    get_project(pid, user)
    db.insert("kpis", {"project_id": pid, "name": name, "unit": unit or None, "direction": "down" if direction == "down" else "up",
                       "baseline": _f(baseline), "target": _f(target), "actual": _f(actual), "method": method or None,
                       "measured_at": date.today().isoformat() if _f(actual) is not None else None})
    _bump_measurement(pid)
    db.log(user["id"], "kpi_added", "project", pid, name)
    return RedirectResponse(f"/projeler/{pid}?tab=etki", status_code=303)


@app.post("/kpi/{kid}")
def kpi_update(request: Request, kid: int, baseline: str = Form(""), target: str = Form(""), actual: str = Form(""),
               method: str = Form(""), user=Depends(require_uploader)):
    k = db.row("SELECT * FROM kpis WHERE id = ?", (kid,))
    if not k:
        raise HTTPException(404, "KPI bulunamadı")
    get_project(k["project_id"], user)
    data = {"baseline": _f(baseline), "target": _f(target), "actual": _f(actual), "method": method or None}
    if data["actual"] != k["actual"]:
        data["measured_at"] = date.today().isoformat()
    db.update("kpis", kid, data)
    _bump_measurement(k["project_id"])
    db.log(user["id"], "kpi_updated", "project", k["project_id"], k["name"])
    return RedirectResponse(f"/projeler/{k['project_id']}?tab=etki", status_code=303)


@app.post("/kpi/{kid}/sil")
def kpi_delete(request: Request, kid: int, user=Depends(require_editor)):
    k = db.row("SELECT * FROM kpis WHERE id = ?", (kid,))
    if k:
        db.execute("DELETE FROM kpis WHERE id = ?", (kid,))
        return RedirectResponse(f"/projeler/{k['project_id']}?tab=etki", status_code=303)
    return back(request)


def _bump_measurement(pid: int) -> None:
    """KPI verisi girildikçe ölçümleme durumunu otomatik ilerletir (geri almaz; 'doğrulandı' insan onayıdır)."""
    p = db.row("SELECT measurement_status FROM projects WHERE id = ?", (pid,))
    kpis = db.rows("SELECT * FROM kpis WHERE project_id = ?", (pid,))
    level = "yok"
    if kpis:
        level = "planlandi"
    if any(k["baseline"] is not None for k in kpis):
        level = "baseline"
    if any(k["actual"] is not None for k in kpis):
        level = "olculuyor"
    if domain.MEASUREMENT_RANK[level] > domain.MEASUREMENT_RANK[p["measurement_status"]]:
        db.update("projects", pid, {"measurement_status": level})


@app.post("/projeler/{pid}/aksiyon")
def action_add(request: Request, pid: int, title: str = Form(...), owner: str = Form(""), due_date: str = Form(""),
               user=Depends(require_editor)):
    get_project(pid, user)
    db.insert("actions", {"project_id": pid, "title": title, "owner": owner or None, "due_date": due_date or None,
                          "status": "acik", "source": "Manuel", "created_by": user["id"], "created_at": db.now()})
    db.log(user["id"], "action_added", "project", pid, title)
    return RedirectResponse(f"/projeler/{pid}?tab=aksiyon", status_code=303)


@app.post("/aksiyon/{aid}/durum")
def action_toggle(request: Request, aid: int, user=Depends(require_uploader)):
    a = db.row("SELECT * FROM actions WHERE id = ?", (aid,))
    if not a:
        raise HTTPException(404, "Aksiyon bulunamadı")
    if a["project_id"]:
        get_project(a["project_id"], user)
    new = "kapali" if a["status"] == "acik" else "acik"
    db.update("actions", aid, {"status": new, "closed_at": db.now() if new == "kapali" else None})
    db.log(user["id"], "action_" + new, "project", a["project_id"], a["title"])
    return back(request)


@app.get("/aksiyonlar", response_class=HTMLResponse)
def action_list(request: Request, durum: str = "acik", user=Depends(require_internal)):
    acts = db.rows("SELECT a.*, p.code, p.name AS pname FROM actions a LEFT JOIN projects p ON p.id = a.project_id "
                   "WHERE (? = 'hepsi' OR a.status = ?) ORDER BY a.status, a.due_date", (durum, durum))
    return render(request, "actions.html", user, actions=acts, durum=durum,
                  projects=db.rows("SELECT id, code, name FROM projects WHERE stage != 'iptal' ORDER BY code"))


@app.post("/aksiyonlar")
def action_add_global(request: Request, title: str = Form(...), project_id: str = Form(""), owner: str = Form(""),
                      due_date: str = Form(""), user=Depends(require_editor)):
    db.insert("actions", {"project_id": int(project_id) if project_id.isdigit() else None, "title": title,
                          "owner": owner or None, "due_date": due_date or None, "status": "acik", "source": "Komite",
                          "created_by": user["id"], "created_at": db.now()})
    return RedirectResponse("/aksiyonlar", status_code=303)


@app.post("/projeler/{pid}/ai-degerlendirme")
def project_ai(request: Request, pid: int, user=Depends(require_internal)):
    p = get_project(pid, user)
    try:
        text = ai.project_assessment(pid)
    except ai.AIError as exc:
        flash(request, f"AI değerlendirmesi başarısız: {exc}", "error")
        return RedirectResponse(f"/projeler/{pid}", status_code=303)
    db.insert("comments", {"target_type": "project", "target_id": pid, "user_id": user["id"],
                           "body": text, "kind": "ai", "created_at": db.now()})
    db.log(user["id"], "ai_assessment", "project", pid, p["code"])
    return RedirectResponse(f"/projeler/{pid}?tab=yorumlar", status_code=303)


# ------------------------------------------------------------------ dokümanlar

async def _save_upload(file: UploadFile) -> tuple[str, int, str]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Bu dosya türü desteklenmiyor: {ext or '?'}")
    stored = f"{datetime.now():%Y%m%d%H%M%S}-{secrets.token_hex(6)}{ext}"
    path = config.UPLOAD_DIR / stored
    size = 0
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    with path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, f"Dosya {config.MAX_UPLOAD_MB} MB sınırını aşıyor")
            out.write(chunk)
    return stored, size, extract_text(path)


@app.post("/dokuman")
async def document_upload(request: Request, file: UploadFile = File(...), title: str = Form(""), category: str = Form("Diğer"),
                          project_id: str = Form(""), initiative_id: str = Form(""), user=Depends(require_uploader)):
    pid = int(project_id) if project_id.isdigit() else None
    iid = int(initiative_id) if initiative_id.isdigit() else None
    if pid:
        get_project(pid, user)
    if iid and user["role"] == "dt":
        raise HTTPException(403, "Bu alan yalnızca Doğuş Otomotiv kullanıcılarına açıktır.")
    stored, size, text = await _save_upload(file)
    db.insert("documents", {"project_id": pid, "initiative_id": iid, "title": title or file.filename, "category": category,
                                  "filename": file.filename, "stored_name": stored, "mime": file.content_type, "size": size,
                                  "text_content": text, "uploaded_by": user["id"], "uploaded_at": db.now()})
    db.log(user["id"], "document_uploaded", "project" if pid else "initiative", pid or iid, title or file.filename)
    flash(request, "Doküman yüklendi.")
    return back(request)


@app.get("/dokuman/{did}")
def document_download(did: int, user=Depends(require_user)):
    d = db.row("SELECT * FROM documents WHERE id = ?", (did,))
    if not d:
        raise HTTPException(404, "Doküman bulunamadı")
    if d["project_id"]:
        get_project(d["project_id"], user)
    elif user["role"] == "dt":
        raise HTTPException(404, "Doküman bulunamadı")
    path = config.UPLOAD_DIR / d["stored_name"]
    if not path.exists():
        raise HTTPException(404, "Dosya sunucuda bulunamadı")
    return FileResponse(path, filename=d["filename"], media_type=d["mime"] or "application/octet-stream")


@app.post("/dokuman/{did}/sil")
def document_delete(request: Request, did: int, user=Depends(require_editor)):
    d = db.row("SELECT * FROM documents WHERE id = ?", (did,))
    if d:
        (config.UPLOAD_DIR / d["stored_name"]).unlink(missing_ok=True)
        db.execute("DELETE FROM documents WHERE id = ?", (did,))
        db.log(user["id"], "document_deleted", "project", d["project_id"], d["title"])
    return back(request)


@app.get("/dokumanlar", response_class=HTMLResponse)
def document_library(request: Request, q: str = "", kategori: str = "", user=Depends(require_user)):
    where, params = ["1=1"], []
    if q:
        where.append("(d.title LIKE ? OR d.filename LIKE ? OR d.text_content LIKE ?)")
        params += [f"%{q}%"] * 3
    if kategori:
        where.append("d.category = ?")
        params.append(kategori)
    if user["role"] == "dt":
        where.append("p.visible_to_dt = 1")
    docs = db.rows(
        "SELECT d.id, d.title, d.category, d.filename, d.size, d.uploaded_at, d.project_id, d.initiative_id, "
        "p.code, p.name AS pname, i.name AS iname, i.slug, u.name AS uname "
        "FROM documents d LEFT JOIN projects p ON p.id = d.project_id LEFT JOIN initiatives i ON i.id = d.initiative_id "
        f"LEFT JOIN users u ON u.id = d.uploaded_by WHERE {' AND '.join(where)} ORDER BY d.uploaded_at DESC", tuple(params))
    reps = [] if kategori else db.rows("SELECT id, title, week_start, filename, uploaded_at FROM weekly_reports ORDER BY week_start DESC")
    return render(request, "documents.html", user, docs=docs, reports=reps, q=q, kategori=kategori,
                  projects=visible_projects(user))


# ------------------------------------------------------------------ yorumlar

def _comments(target_type: str, target_id: int, user: dict) -> list[dict]:
    kinds = "" if user["role"] != "dt" else " AND c.kind != 'ai'"
    return db.rows("SELECT c.*, u.name AS uname, u.organization, u.role AS urole FROM comments c JOIN users u ON u.id = c.user_id "
                   f"WHERE target_type = ? AND target_id = ?{kinds} ORDER BY c.created_at DESC, c.id DESC", (target_type, target_id))


@app.post("/yorum")
def comment_add(request: Request, target_type: str = Form(...), target_id: int = Form(...), body: str = Form(...),
                user=Depends(require_user)):
    body = body.strip()
    if not body:
        return back(request)
    if target_type == "project":
        get_project(target_id, user)
    elif target_type == "initiative":
        if user["role"] == "dt":
            raise HTTPException(403, "Bu alan yalnızca Doğuş Otomotiv kullanıcılarına açıktır.")
    else:
        raise HTTPException(400, "Geçersiz hedef")
    db.insert("comments", {"target_type": target_type, "target_id": target_id, "user_id": user["id"], "body": body[:10000],
                           "created_at": db.now()})
    db.log(user["id"], "comment_added", target_type, target_id, body[:80])
    return back(request)


@app.post("/yorum/{cid}/sil")
def comment_delete(request: Request, cid: int, user=Depends(require_user)):
    c = db.row("SELECT * FROM comments WHERE id = ?", (cid,))
    if c and (c["user_id"] == user["id"] or user["role"] == "admin"):
        db.execute("DELETE FROM comments WHERE id = ?", (cid,))
    return back(request)


# ------------------------------------------------------------------ haftalık raporlar

@app.get("/raporlar", response_class=HTMLResponse)
def report_list(request: Request, user=Depends(require_user)):
    reps = db.rows("SELECT r.*, u.name AS uname, (SELECT COUNT(*) FROM report_updates WHERE report_id = r.id) AS n, "
                   "(SELECT COUNT(*) FROM report_updates WHERE report_id = r.id AND suggested_health != 'yesil') AS risky "
                   "FROM weekly_reports r LEFT JOIN users u ON u.id = r.uploaded_by ORDER BY week_start DESC")
    monday = date.today() - timedelta(days=date.today().weekday())
    # Isı haritası: proje × hafta sağlık geçmişi
    weeks = db.rows("SELECT id, week_start FROM weekly_reports ORDER BY week_start DESC LIMIT 8")[::-1]
    grid = {}
    for u in db.rows("SELECT report_id, project_id, suggested_health, risk_score FROM report_updates WHERE project_id IS NOT NULL"):
        grid[(u["project_id"], u["report_id"])] = u
    heat_projects = visible_projects(user, "stage NOT IN ('fikir','iptal')")
    return render(request, "reports.html", user, reports=reps, monday=monday.isoformat(), weeks=weeks, grid=grid,
                  heat_projects=heat_projects)


@app.post("/raporlar")
async def report_upload(request: Request, background: BackgroundTasks, week_start: str = Form(...), title: str = Form(""),
                        file: UploadFile | None = File(None), text: str = Form(""), user=Depends(require_uploader)):
    stored, content, filename = None, text.strip(), None
    if file and file.filename:
        stored, _, extracted = await _save_upload(file)
        content = (extracted + ("\n\n" + content if content else "")).strip()
        filename = file.filename
    if not content:
        raise HTTPException(400, "Rapor dosyası ya da metni gerekli")
    rid = db.insert("weekly_reports", {"week_start": week_start, "title": title or f"DT Haftalık Durum Raporu — {_date(week_start)}",
                                       "filename": filename, "stored_name": stored, "text_content": content,
                                       "uploaded_by": user["id"], "uploaded_at": db.now()})
    db.log(user["id"], "report_uploaded", "report", rid, title or week_start)
    background.add_task(reports.run_analysis, rid, user["id"])
    flash(request, "Rapor yüklendi. AI analizi arka planda başladı; birkaç dakika içinde sonuçlar görünecek.")
    return RedirectResponse(f"/raporlar/{rid}", status_code=303)


@app.get("/raporlar/{rid}", response_class=HTMLResponse)
def report_detail(request: Request, rid: int, user=Depends(require_user)):
    r = db.row("SELECT r.*, u.name AS uname FROM weekly_reports r LEFT JOIN users u ON u.id = r.uploaded_by WHERE r.id = ?", (rid,))
    if not r:
        raise HTTPException(404, "Rapor bulunamadı")
    updates = db.rows("SELECT ru.*, p.code, p.name AS pname, p.health AS current_health, p.visible_to_dt FROM report_updates ru "
                      "LEFT JOIN projects p ON p.id = ru.project_id WHERE report_id = ? ORDER BY ru.risk_score DESC", (rid,))
    if user["role"] == "dt":
        updates = [u for u in updates if u["visible_to_dt"]]
    raw = json.loads(r["ai_raw"] or "{}")
    return render(request, "report_detail.html", user, r=r, updates=updates, raw=raw)


@app.get("/api/raporlar/{rid}/durum")
def report_status(rid: int, user=Depends(require_user)):
    return {"status": db.scalar("SELECT ai_status FROM weekly_reports WHERE id = ?", (rid,))}


@app.post("/raporlar/{rid}/analiz")
def report_reanalyze(request: Request, rid: int, background: BackgroundTasks, user=Depends(require_editor)):
    db.update("weekly_reports", rid, {"ai_status": "bekliyor", "applied": 0})
    background.add_task(reports.run_analysis, rid, user["id"])
    flash(request, "Analiz yeniden başlatıldı.")
    return RedirectResponse(f"/raporlar/{rid}", status_code=303)


@app.post("/raporlar/{rid}/uygula")
async def report_apply(request: Request, rid: int, user=Depends(require_editor)):
    form = await request.form()
    selected = {int(v) for v in form.getlist("update_id") if str(v).isdigit()}
    n = reports.apply_updates(rid, user["id"], only=selected)
    flash(request, f"{n} projenin durumu ve risk skoru güncellendi.")
    return RedirectResponse(f"/raporlar/{rid}", status_code=303)


@app.post("/raporlar/{rid}/sil")
def report_delete(request: Request, rid: int, user=Depends(require_admin)):
    r = db.row("SELECT * FROM weekly_reports WHERE id = ?", (rid,))
    if r and r["stored_name"]:
        (config.UPLOAD_DIR / r["stored_name"]).unlink(missing_ok=True)
    db.execute("DELETE FROM weekly_reports WHERE id = ?", (rid,))
    return RedirectResponse("/raporlar", status_code=303)


@app.get("/raporlar/{rid}/dosya")
def report_file(rid: int, user=Depends(require_user)):
    r = db.row("SELECT * FROM weekly_reports WHERE id = ?", (rid,))
    if not r or not r["stored_name"]:
        raise HTTPException(404, "Dosya yok")
    return FileResponse(config.UPLOAD_DIR / r["stored_name"], filename=r["filename"])


# ------------------------------------------------------------------ AI danışman

@app.get("/danisman", response_class=HTMLResponse)
def advisor(request: Request, user=Depends(require_internal)):
    messages = db.rows("SELECT * FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT 40", (user["id"],))[::-1]
    insights = db.rows("SELECT i.*, u.name AS uname FROM ai_insights i LEFT JOIN users u ON u.id = i.created_by "
                       "ORDER BY created_at DESC LIMIT 12")
    return render(request, "advisor.html", user, messages=messages, insights=insights, coverage=ai.coverage())


@app.post("/api/danisman")
async def advisor_ask(request: Request, user=Depends(require_internal)):
    payload = await request.json()
    question = (payload.get("question") or "").strip()[:4000]
    if not question:
        return JSONResponse({"error": "Soru boş"}, status_code=400)
    history = db.rows("SELECT role, content FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user["id"],))[::-1]
    try:
        answer = ai.advisor_answer(history, question)
    except Exception as exc:
        return JSONResponse({"error": f"AI yanıt veremedi: {exc}"}, status_code=502)
    ts = db.now()
    db.insert("chat_messages", {"user_id": user["id"], "role": "user", "content": question, "created_at": ts})
    db.insert("chat_messages", {"user_id": user["id"], "role": "assistant", "content": answer, "created_at": ts})
    return {"answer_html": str(_md(answer))}


@app.post("/danisman/temizle")
def advisor_clear(request: Request, user=Depends(require_internal)):
    db.execute("DELETE FROM chat_messages WHERE user_id = ?", (user["id"],))
    return RedirectResponse("/danisman", status_code=303)


@app.post("/danisman/bosluk-analizi")
def advisor_gap(request: Request, user=Depends(require_internal)):
    try:
        body = ai.gap_analysis()
    except Exception as exc:
        flash(request, f"Boşluk analizi başarısız: {exc}", "error")
        return RedirectResponse("/danisman", status_code=303)
    iid = db.insert("ai_insights", {"kind": "gap", "title": "AI Olgunluk ve Boşluk Analizi", "body": body,
                                    "created_by": user["id"], "created_at": db.now()})
    db.log(user["id"], "gap_analysis", "insight", iid)
    return RedirectResponse(f"/danisman/icgoru/{iid}", status_code=303)


@app.get("/danisman/icgoru/{iid}", response_class=HTMLResponse)
def insight_detail(request: Request, iid: int, user=Depends(require_internal)):
    i = db.row("SELECT i.*, u.name AS uname FROM ai_insights i LEFT JOIN users u ON u.id = i.created_by WHERE i.id = ?", (iid,))
    if not i:
        raise HTTPException(404, "İçgörü bulunamadı")
    return render(request, "insight.html", user, i=i)


# ------------------------------------------------------------------ kurumsal yapı

@app.get("/kurumsal-yapi", response_class=HTMLResponse)
def org(request: Request, user=Depends(require_internal)):
    units = db.rows("SELECT * FROM org_units ORDER BY name")
    children: dict = {}
    for u in units:
        children.setdefault(u["parent_id"], []).append(u)
    return render(request, "org.html", user, units=units, children=children, coverage=ai.coverage())


@app.post("/kurumsal-yapi")
def org_save(request: Request, name: str = Form(...), unit_id: str = Form(""), parent_id: str = Form(""), kind: str = Form("birim"),
             value_chain: str = Form(""), headcount: str = Form(""), description: str = Form(""), pain_points: str = Form(""),
             user=Depends(require_editor)):
    data = {"name": name, "parent_id": int(parent_id) if parent_id.isdigit() else None, "kind": kind,
            "value_chain": value_chain or None, "headcount": int(headcount) if headcount.isdigit() else None,
            "description": description or None, "pain_points": pain_points or None}
    if unit_id.isdigit():
        if data["parent_id"] == int(unit_id):
            data["parent_id"] = None
        db.update("org_units", int(unit_id), data)
    else:
        db.insert("org_units", data)
    flash(request, "Kurumsal yapı güncellendi.")
    return RedirectResponse("/kurumsal-yapi", status_code=303)


@app.post("/kurumsal-yapi/{uid}/sil")
def org_delete(request: Request, uid: int, user=Depends(require_editor)):
    db.execute("DELETE FROM org_units WHERE id = ?", (uid,))
    return RedirectResponse("/kurumsal-yapi", status_code=303)


@app.post("/kurumsal-yapi/dokuman")
async def org_doc(request: Request, file: UploadFile = File(...), user=Depends(require_editor)):
    """Organizasyon şeması / strateji dokümanını AI bağlamına ekler (kurumsal yapı kökü altında)."""
    _, _, text = await _save_upload(file)
    db.insert("org_units", {"name": f"Doküman: {file.filename}", "kind": "doküman", "description": text[:20000]})
    flash(request, "Doküman kurumsal bağlama eklendi; AI danışman bu içeriği boşluk analizinde kullanacak.")
    return RedirectResponse("/kurumsal-yapi", status_code=303)


# ------------------------------------------------------------------ AI güvenlik

@app.get("/guvenlik", response_class=HTMLResponse)
def security_page(request: Request, user=Depends(require_internal)):
    groups: dict[str, list] = {}
    for key, meta in security.METRICS.items():
        s = security.series(key)
        last = s[-1]["value"] if s else None
        prev = s[-2]["value"] if len(s) > 1 else None
        delta = None if last is None or prev in (None, 0) else (last - prev) / prev * 100
        good = None if delta is None or delta == 0 else (delta > 0) == (meta["direction"] == "up")
        chart = charts.line_chart([(_period(r["period"]), r["value"]) for r in s], meta["unit"], height=120,
                                  series_class="s1" if meta["direction"] == "up" else "s2")
        groups.setdefault(meta["group"], []).append({"key": key, **meta, "last": last, "delta": delta, "good": good,
                                                     "chart": Markup(chart)})
    initiatives = db.rows("SELECT i.*, (SELECT COUNT(*) FROM comments WHERE target_type = 'initiative' AND target_id = i.id) AS n "
                          "FROM initiatives i ORDER BY category DESC, name")
    project_sec = db.rows("SELECT code, name, id, stage, security_review, data_class FROM projects "
                          "WHERE stage IN ('gelistirme','pilot','canli','olcekleme') ORDER BY security_review, code")
    return render(request, "security.html", user, groups=groups, initiatives=initiatives, project_sec=project_sec,
                  periods=security.latest_periods(), metrics=security.METRICS)


@app.post("/guvenlik/metrik")
async def security_metric(request: Request, user=Depends(require_editor)):
    form = await request.form()
    period = str(form.get("period", ""))
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        raise HTTPException(400, "Dönem YYYY-AA formatında olmalı")
    n = 0
    for key in security.METRICS:
        v = _f(form.get(key))
        if v is not None:
            security.upsert(period, key, v)
            n += 1
    db.log(user["id"], "security_metrics", detail=f"{period}: {n} metrik")
    flash(request, f"{period} dönemi için {n} metrik kaydedildi.")
    return RedirectResponse("/guvenlik", status_code=303)


@app.post("/guvenlik/csv")
async def security_csv(request: Request, file: UploadFile = File(...), user=Depends(require_editor)):
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    n, errors = security.import_csv(raw)
    flash(request, f"{n} satır içe aktarıldı." + (" Hatalar: " + "; ".join(errors[:5]) if errors else ""), "warn" if errors else "ok")
    return RedirectResponse("/guvenlik", status_code=303)


@app.get("/guvenlik/sablon.csv")
def security_template(user=Depends(require_internal)):
    period = date.today().strftime("%Y-%m")
    lines = ["period,metric,value,note"] + [f"{period},{k},," for k in security.METRICS]
    return PlainTextResponse("\n".join(lines), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=ai-guvenlik-sablon.csv"})


@app.get("/guvenlik/{slug}", response_class=HTMLResponse)
def initiative_detail(request: Request, slug: str, user=Depends(require_internal)):
    i = db.row("SELECT * FROM initiatives WHERE slug = ?", (slug,))
    if not i:
        raise HTTPException(404, "Girişim bulunamadı")
    docs = db.rows("SELECT d.*, u.name AS uname FROM documents d LEFT JOIN users u ON u.id = d.uploaded_by "
                   "WHERE initiative_id = ? ORDER BY uploaded_at DESC", (i["id"],))
    related = {
        "ai-studio": ["ai_studio_active_users", "ai_studio_prompts", "ai_studio_use_cases"],
        "shadow-ai": ["shadow_ai_apps", "shadow_ai_users", "shadow_ai_blocked"],
        "ai-dlp": ["dlp_incidents", "sensitive_prompts_blocked"],
        "ai-egitim": ["training_completion", "policy_ack_rate"],
        "ai-politika": ["policy_ack_rate", "projects_security_reviewed"],
    }.get(slug, [])
    metric_charts = []
    for key in related:
        meta = security.METRICS[key]
        s = security.series(key)
        metric_charts.append({**meta, "last": s[-1]["value"] if s else None,
                              "chart": Markup(charts.line_chart([(_period(r["period"]), r["value"]) for r in s], meta["unit"],
                                                                series_class="s1" if meta["direction"] == "up" else "s2"))})
    return render(request, "initiative.html", user, i=i, docs=docs, comments=_comments("initiative", i["id"], user),
                  metric_charts=metric_charts)


@app.post("/guvenlik/{slug}")
def initiative_save(request: Request, slug: str, name: str = Form(...), description: str = Form(""), owner: str = Form(""),
                    status: str = Form(""), health: str = Form("yesil"), category: str = Form("guvenlik"),
                    user=Depends(require_editor)):
    data = {"name": name, "description": description or None, "owner": owner or None, "status": status or None,
            "health": health if health in domain.HEALTH else "yesil", "category": category}
    existing = db.row("SELECT id FROM initiatives WHERE slug = ?", (slug,))
    if existing:
        db.update("initiatives", existing["id"], data)
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower().translate(str.maketrans("çğıöşü", "cgiosu"))).strip("-") or secrets.token_hex(3)
        db.insert("initiatives", {**data, "slug": slug, "created_at": db.now()})
    return RedirectResponse(f"/guvenlik/{slug}", status_code=303)


# ------------------------------------------------------------------ süreç

@app.get("/surec", response_class=HTMLResponse)
def process(request: Request, user=Depends(require_user)):
    return render(request, "process.html", user)


# ------------------------------------------------------------------ yönetim

@app.get("/yonetim", response_class=HTMLResponse)
def admin_page(request: Request, user=Depends(require_admin)):
    users = db.rows("SELECT * FROM users ORDER BY active DESC, organization, name")
    log = db.rows("SELECT a.*, u.name AS uname FROM activity a LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT 60")
    return render(request, "admin.html", user, users=users, log=log, preview=None)


@app.post("/yonetim/kullanici")
def admin_user(request: Request, email: str = Form(...), name: str = Form(...), role: str = Form("viewer"), title: str = Form(""),
               organization: str = Form("Doğuş Otomotiv"), password: str = Form(""), user_id: str = Form(""),
               user=Depends(require_admin)):
    if role not in domain.ROLES:
        raise HTTPException(400, "Geçersiz rol")
    data = {"email": email.strip().lower(), "name": name, "role": role, "title": title or None, "organization": organization}
    if user_id.isdigit():
        if password:
            data["password_hash"] = hash_password(password)
        db.update("users", int(user_id), data)
        flash(request, "Kullanıcı güncellendi.")
    else:
        if db.scalar("SELECT 1 FROM users WHERE lower(email) = ?", (data["email"],)):
            flash(request, "Bu e-posta zaten kayıtlı.", "error")
            return RedirectResponse("/yonetim", status_code=303)
        temp = password or secrets.token_urlsafe(9)
        db.insert("users", {**data, "password_hash": hash_password(temp), "created_at": db.now()})
        flash(request, f"Kullanıcı oluşturuldu. Geçici parola: {temp}" if not password else "Kullanıcı oluşturuldu.")
    return RedirectResponse("/yonetim", status_code=303)


@app.post("/yonetim/kullanici/{uid}/durum")
def admin_user_toggle(request: Request, uid: int, user=Depends(require_admin)):
    if uid != user["id"]:
        db.execute("UPDATE users SET active = 1 - active WHERE id = ?", (uid,))
    return RedirectResponse("/yonetim", status_code=303)


@app.post("/yonetim/trello/onizle", response_class=HTMLResponse)
async def trello_preview(request: Request, file: UploadFile = File(...), user=Depends(require_admin)):
    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        pv = trello.preview(raw)
    except (json.JSONDecodeError, KeyError, TypeError):
        flash(request, "Geçerli bir Trello JSON dışa aktarımı değil.", "error")
        return RedirectResponse("/yonetim", status_code=303)
    request.session["trello_file"] = _stash(raw)
    users = db.rows("SELECT * FROM users ORDER BY active DESC, organization, name")
    return render(request, "admin.html", user, users=users, log=[], preview=pv)


@app.post("/yonetim/trello/aktar")
async def trello_import(request: Request, user=Depends(require_admin)):
    form = await request.form()
    token = request.session.pop("trello_file", None)
    raw = _unstash(token)
    if not raw:
        flash(request, "Önizleme süresi doldu, dosyayı tekrar yükleyin.", "error")
        return RedirectResponse("/yonetim", status_code=303)
    stage_map = {k[6:]: v for k, v in form.items() if k.startswith("stage_") and v in domain.STAGE_LABELS}
    n = trello.import_board(raw, stage_map, user["id"])
    flash(request, f"Trello'dan {n} kart proje olarak içe aktarıldı.")
    return RedirectResponse("/projeler", status_code=303)


def _stash(raw: str) -> str:
    token = secrets.token_hex(12)
    (config.DATA_DIR / f"trello-{token}.json").write_text(raw, encoding="utf-8")
    return token


def _unstash(token: str | None) -> str | None:
    if not token or not re.fullmatch(r"[0-9a-f]{24}", token):
        return None
    path = config.DATA_DIR / f"trello-{token}.json"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    path.unlink()
    return raw


@app.get("/disa-aktar/projeler.csv")
def export_projects(user=Depends(require_internal)):
    import csv
    import io
    buf = io.StringIO()
    cols = ["code", "name", "stage", "health", "priority", "value_chain", "business_unit", "brands", "ai_type", "sponsor", "owner",
            "dt_lead", "start_date", "target_date", "golive_date", "measurement_status", "estimated_value", "realized_value",
            "fte_saving", "security_review", "data_class", "ai_risk_score", "last_status_at"]
    w = csv.writer(buf, delimiter=";")
    w.writerow(cols)
    for p in db.rows("SELECT * FROM projects ORDER BY code"):
        w.writerow([p[c] for c in cols])
    return PlainTextResponse("﻿" + buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=ai-impact-projeler.csv"})

