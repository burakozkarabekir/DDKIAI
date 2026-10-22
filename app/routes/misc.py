"""Oturum, AI danışman, AI Security, süreç, ayarlar (departmanlar, AI bağlantısı, depolama) ve yönetim."""
import json
import re
import secrets
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from markupsafe import Markup

from .. import ai, charts, config, db, domain, pipeline, security, storage, trello
from ..auth import authenticate, hash_password, require_admin, require_editor, require_internal, require_user
from ..web import flash, md, parse_float, period, redirect, render, templates
from .projects import comments_for

router = APIRouter()


# ------------------------------------------------------------------ oturum

@router.get("/giris", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if not config.AUTH_ENABLED:
        return redirect("/")
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None, "demo": config.SEED_DEMO})


@router.post("/giris")
def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/")):
    user = authenticate(email, password)
    if not user:
        return templates.TemplateResponse(request, "login.html", {"next": next, "demo": config.SEED_DEMO,
                                                                  "error": "E-posta veya parola hatalı (ya da çok fazla deneme)."},
                                          status_code=401)
    request.session.clear()
    request.session["uid"] = user["id"]
    db.log(user["id"], "login")
    return redirect(next if next.startswith("/") and not next.startswith("//") else "/")


@router.get("/cikis")
def logout(request: Request):
    request.session.clear()
    return redirect("/giris" if config.AUTH_ENABLED else "/")


@router.get("/saglik")
def health():
    return {"ok": True, "ai": ai.provider_label(), "queue": pipeline.queue_state()}


# ------------------------------------------------------------------ AI danışman

@router.get("/danisman", response_class=HTMLResponse)
def advisor(request: Request, user=Depends(require_internal)):
    messages = db.rows("SELECT * FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT 40", (user["id"],))[::-1]
    insights = db.rows("SELECT i.*, p.code FROM ai_insights i LEFT JOIN projects p ON p.id = i.project_id "
                       "ORDER BY i.id DESC LIMIT 15")
    gap_running = db.scalar("SELECT 1 FROM jobs WHERE kind IN ('gap', 'weekly') AND status IN ('sirada', 'calisiyor')")
    return render(request, "advisor.html", user, messages=messages, insights=insights, gap_running=gap_running)


@router.post("/api/danisman")
async def advisor_ask(request: Request, user=Depends(require_internal)):
    payload = await request.json()
    question = (payload.get("question") or "").strip()[:4000]
    if not question:
        return JSONResponse({"error": "Soru boş"}, status_code=400)
    history = db.rows("SELECT role, content FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user["id"],))[::-1]
    try:
        answer, _hits = ai.advisor_answer(history, question)
    except Exception as exc:
        return JSONResponse({"error": f"AI yanıt veremedi: {exc}"}, status_code=502)
    ts = db.now()
    db.insert("chat_messages", {"user_id": user["id"], "role": "user", "content": question, "created_at": ts})
    db.insert("chat_messages", {"user_id": user["id"], "role": "assistant", "content": answer, "created_at": ts})
    return {"answer_html": str(md(answer))}


@router.post("/danisman/temizle")
def advisor_clear(request: Request, user=Depends(require_internal)):
    db.execute("DELETE FROM chat_messages WHERE user_id = ?", (user["id"],))
    return redirect("/danisman")


@router.post("/danisman/analiz/{kind}")
def advisor_run(request: Request, kind: str, user=Depends(require_internal)):
    if kind not in ("gap", "weekly"):
        raise HTTPException(404, "Bilinmeyen analiz")
    pipeline.enqueue(kind)
    flash(request, "Analiz kuyruğa alındı; birkaç dakika içinde içgörü arşivinde görünecek.")
    return redirect("/danisman")


@router.get("/danisman/icgoru/{iid}", response_class=HTMLResponse)
def insight_detail(request: Request, iid: int, user=Depends(require_internal)):
    i = db.row("SELECT i.*, p.code, p.name AS pname FROM ai_insights i LEFT JOIN projects p ON p.id = i.project_id WHERE i.id = ?", (iid,))
    if not i:
        raise HTTPException(404, "İçgörü bulunamadı")
    return render(request, "insight.html", user, i=i)


# ------------------------------------------------------------------ AI Security

@router.get("/guvenlik", response_class=HTMLResponse)
def security_page(request: Request, user=Depends(require_internal)):
    groups: dict[str, list] = {}
    for key, meta in security.METRICS.items():
        s = security.series(key)
        last = s[-1]["value"] if s else None
        prev = s[-2]["value"] if len(s) > 1 else None
        delta = None if last is None or prev in (None, 0) else (last - prev) / prev * 100
        good = None if delta is None or delta == 0 else (delta > 0) == (meta["direction"] == "up")
        chart = charts.line_chart([(period(r["period"]), r["value"]) for r in s], meta["unit"], height=120,
                                  series_class="s1" if meta["direction"] == "up" else "s2")
        groups.setdefault(meta["group"], []).append({"key": key, **meta, "last": last, "delta": delta, "good": good, "chart": Markup(chart)})
    initiatives = db.rows("SELECT i.*, (SELECT COUNT(*) FROM comments WHERE target_type = 'initiative' AND target_id = i.id) AS n "
                          "FROM initiatives i ORDER BY category DESC, name")
    project_sec = db.rows("SELECT code, name, id, stage, security_review, data_class FROM projects "
                          "WHERE stage IN ('gelistirme','pilot','canli','olcekleme') ORDER BY security_review, code")
    return render(request, "security.html", user, groups=groups, initiatives=initiatives, project_sec=project_sec,
                  periods=security.latest_periods(), metrics=security.METRICS)


@router.post("/guvenlik/metrik")
async def security_metric(request: Request, user=Depends(require_editor)):
    form = await request.form()
    per = str(form.get("period", ""))
    if not re.fullmatch(r"\d{4}-\d{2}", per):
        raise HTTPException(400, "Dönem YYYY-AA formatında olmalı")
    n = 0
    for key in security.METRICS:
        v = parse_float(form.get(key))
        if v is not None:
            security.upsert(per, key, v)
            n += 1
    flash(request, f"{per} dönemi için {n} metrik kaydedildi.")
    return redirect("/guvenlik")


@router.post("/guvenlik/csv")
async def security_csv(request: Request, file: UploadFile = File(...), user=Depends(require_editor)):
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    n, errors = security.import_csv(raw)
    flash(request, f"{n} satır içe aktarıldı." + (" Hatalar: " + "; ".join(errors[:5]) if errors else ""), "warn" if errors else "ok")
    return redirect("/guvenlik")


@router.get("/guvenlik/sablon.csv")
def security_template(user=Depends(require_internal)):
    per = date.today().strftime("%Y-%m")
    lines = ["period,metric,value,note"] + [f"{per},{k},," for k in security.METRICS]
    return PlainTextResponse("\n".join(lines), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=ai-guvenlik-sablon.csv"})


RELATED = {
    "ai-studio": ["ai_studio_active_users", "ai_studio_prompts", "ai_studio_use_cases"],
    "shadow-ai": ["shadow_ai_apps", "shadow_ai_users", "shadow_ai_blocked"],
    "ai-dlp": ["dlp_incidents", "sensitive_prompts_blocked"],
    "ai-egitim": ["training_completion", "policy_ack_rate"],
    "ai-politika": ["policy_ack_rate", "projects_security_reviewed"],
}


@router.get("/guvenlik/{slug}", response_class=HTMLResponse)
def initiative_detail(request: Request, slug: str, user=Depends(require_internal)):
    i = db.row("SELECT * FROM initiatives WHERE slug = ?", (slug,))
    if not i:
        raise HTTPException(404, "Girişim bulunamadı")
    docs = db.rows("SELECT * FROM documents WHERE initiative_id = ? ORDER BY uploaded_at DESC", (i["id"],))
    metric_charts = []
    for key in RELATED.get(slug, []):
        meta = security.METRICS[key]
        s = security.series(key)
        metric_charts.append({**meta, "last": s[-1]["value"] if s else None,
                              "chart": Markup(charts.line_chart([(period(r["period"]), r["value"]) for r in s], meta["unit"],
                                                                series_class="s1" if meta["direction"] == "up" else "s2"))})
    return render(request, "initiative.html", user, i=i, docs=docs, comments=comments_for("initiative", i["id"], user),
                  metric_charts=metric_charts)


@router.post("/guvenlik/{slug}")
def initiative_save(request: Request, slug: str, name: str = Form(...), description: str = Form(""), owner: str = Form(""),
                    status: str = Form(""), health: str = Form("yesil"), category: str = Form("guvenlik"), user=Depends(require_editor)):
    data = {"name": name, "description": description or None, "owner": owner or None, "status": status or None,
            "health": health if health in domain.HEALTH else "yesil", "category": category}
    existing = db.row("SELECT id FROM initiatives WHERE slug = ?", (slug,))
    if existing:
        db.update("initiatives", existing["id"], data)
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower().translate(str.maketrans("çğıöşü", "cgiosu"))).strip("-") or secrets.token_hex(3)
        db.insert("initiatives", {**data, "slug": slug, "created_at": db.now()})
    return redirect(f"/guvenlik/{slug}")


# ------------------------------------------------------------------ süreç

@router.get("/surec", response_class=HTMLResponse)
def process(request: Request, user=Depends(require_user)):
    return render(request, "process.html", user)


# ------------------------------------------------------------------ ayarlar

@router.get("/ayarlar", response_class=HTMLResponse)
def settings(request: Request, user=Depends(require_editor)):
    deps = db.rows("SELECT d.*, (SELECT COUNT(*) FROM projects p WHERE p.department_id = d.id) AS n FROM departments d ORDER BY sort, name")
    ai_cfg = {"provider": config.AI_PROVIDER, "base_url": config.AI_BASE_URL or "—", "model": config.AI_MODEL or "—",
              "key": ("•" * 8 + config.AI_API_KEY[-4:]) if len(config.AI_API_KEY) > 8 else ("tanımlı" if config.AI_API_KEY else "yok"),
              "auth_header": config.AI_AUTH_HEADER or "varsayılan", "context": config.AI_MAX_CONTEXT_CHARS, "timeout": config.AI_TIMEOUT}
    docs = db.row("SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS size, SUM(status = 'hata') AS failed, "
                  "SUM(status = 'metin_yok') AS notext FROM documents")
    return render(request, "settings.html", user, deps=deps, ai_cfg=ai_cfg, usage=storage.usage(), docs=docs,
                  queue=pipeline.queue_state(), soffice=storage.soffice(), test=request.session.pop("ai_test", None),
                  failed_jobs=db.rows("SELECT * FROM jobs WHERE status = 'hata' ORDER BY id DESC LIMIT 10"))


@router.post("/ayarlar/departman")
def department_save(request: Request, name: str = Form(...), dep_id: str = Form(""), description: str = Form(""),
                    pain_points: str = Form(""), sort: str = Form("0"), active: str = Form(""), user=Depends(require_editor)):
    data = {"name": name.strip()[:120], "description": description or None, "pain_points": pain_points or None,
            "sort": int(sort) if sort.lstrip("-").isdigit() else 0, "active": 1 if active else 0}
    try:
        if dep_id.isdigit():
            db.update("departments", int(dep_id), data)
        else:
            db.insert("departments", {**data, "active": 1})
    except Exception:
        flash(request, "Bu adla bir departman zaten var.", "error")
        return redirect("/ayarlar#departmanlar")
    flash(request, "Departman kaydedildi.")
    return redirect("/ayarlar#departmanlar")


@router.post("/ayarlar/departman/{dep_id}/sil")
def department_delete(request: Request, dep_id: int, user=Depends(require_editor)):
    n = db.scalar("SELECT COUNT(*) FROM projects WHERE department_id = ?", (dep_id,))
    db.execute("DELETE FROM departments WHERE id = ?", (dep_id,))
    flash(request, f"Departman silindi. {n} projenin departmanı boşaltıldı." if n else "Departman silindi.")
    return redirect("/ayarlar#departmanlar")


@router.post("/ayarlar/ai-test")
def ai_test(request: Request, user=Depends(require_editor)):
    request.session["ai_test"] = ai.test_connection()
    return redirect("/ayarlar#ai")


@router.post("/ayarlar/yeniden-isle")
def reprocess_all(request: Request, user=Depends(require_admin)):
    n = pipeline.reprocess_all()
    flash(request, f"{n} doküman yeniden işleme kuyruğuna alındı. Onaylanmış/reddedilmiş bilgiler korunur.")
    return redirect("/ayarlar")


@router.post("/ayarlar/is/{jid}/tekrar")
def retry_job(request: Request, jid: int, user=Depends(require_editor)):
    db.execute("UPDATE jobs SET status = 'sirada', error = NULL WHERE id = ? AND status = 'hata'", (jid,))
    j = db.row("SELECT * FROM jobs WHERE id = ?", (jid,))
    if j and j["kind"] == "document":
        db.update("documents", j["ref_id"], {"status": "sirada"})
    pipeline._wake.set()
    return redirect("/ayarlar#kuyruk")


# ------------------------------------------------------------------ yönetim

@router.get("/yonetim", response_class=HTMLResponse)
def admin_page(request: Request, user=Depends(require_admin)):
    users = db.rows("SELECT * FROM users ORDER BY active DESC, organization, name")
    log = db.rows("SELECT a.*, u.name AS uname FROM activity a LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT 60")
    return render(request, "admin.html", user, users=users, log=log, preview=None)


@router.post("/yonetim/kullanici")
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
            return redirect("/yonetim")
        temp = password or secrets.token_urlsafe(9)
        db.insert("users", {**data, "password_hash": hash_password(temp), "created_at": db.now()})
        flash(request, f"Kullanıcı oluşturuldu. Geçici parola: {temp}" if not password else "Kullanıcı oluşturuldu.")
    return redirect("/yonetim")


@router.post("/yonetim/kullanici/{uid}/durum")
def admin_user_toggle(request: Request, uid: int, user=Depends(require_admin)):
    if uid != user["id"]:
        db.execute("UPDATE users SET active = 1 - active WHERE id = ?", (uid,))
    return redirect("/yonetim")


@router.post("/yonetim/trello/onizle", response_class=HTMLResponse)
async def trello_preview(request: Request, file: UploadFile = File(...), user=Depends(require_admin)):
    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        pv = trello.preview(raw)
    except (json.JSONDecodeError, KeyError, TypeError):
        flash(request, "Geçerli bir Trello JSON dışa aktarımı değil.", "error")
        return redirect("/yonetim")
    token = secrets.token_hex(12)
    (config.DATA_DIR / f"trello-{token}.json").write_text(raw, encoding="utf-8")
    request.session["trello_file"] = token
    users = db.rows("SELECT * FROM users ORDER BY active DESC, organization, name")
    return render(request, "admin.html", user, users=users, log=[], preview=pv)


@router.post("/yonetim/trello/aktar")
async def trello_import(request: Request, user=Depends(require_admin)):
    form = await request.form()
    token = request.session.pop("trello_file", None)
    path = config.DATA_DIR / f"trello-{token}.json" if token and re.fullmatch(r"[0-9a-f]{24}", token) else None
    if not path or not path.exists():
        flash(request, "Önizleme süresi doldu, dosyayı tekrar yükleyin.", "error")
        return redirect("/yonetim")
    raw = path.read_text(encoding="utf-8")
    path.unlink()
    stage_map = {k[6:]: v for k, v in form.items() if k.startswith("stage_") and v in domain.STAGE_LABELS}
    n = trello.import_board(raw, stage_map, user["id"])
    flash(request, f"Trello'dan {n} kart proje olarak içe aktarıldı.")
    return redirect("/projeler")
