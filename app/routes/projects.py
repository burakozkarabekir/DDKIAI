"""Yönetici özeti, projeler, KPI, aksiyonlar, yorumlar ve zaman çizelgesi."""
import csv
import io
import json
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from markupsafe import Markup

from .. import ai, db, domain, knowledge, pipeline, timeline
from ..auth import require_editor, require_internal, require_uploader, require_user
from ..web import (back, departments, flash, get_project, parse_float, redirect, render, visible_projects)

router = APIRouter()


# ------------------------------------------------------------------ yönetici özeti

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(require_user)):
    if user["role"] == "dt":
        return redirect("/projeler")
    projects = db.rows("SELECT * FROM projects ORDER BY code")
    active = [p for p in projects if p["stage"] in domain.ACTIVE_STAGES]
    live = [p for p in projects if p["stage"] in ("canli", "olcekleme")]
    measured = [p for p in live if domain.MEASUREMENT_RANK[p["measurement_status"]] >= domain.MEASUREMENT_RANK["olculuyor"]]
    stage_counts = [(k, label, sum(1 for p in projects if p["stage"] == k)) for k, label, _ in domain.STAGES]
    side_counts = [(k, label, sum(1 for p in projects if p["stage"] == k)) for k, label, _ in domain.SIDE_STAGES]
    health_counts = {h: sum(1 for p in active if p["health"] == h) for h in domain.HEALTH}
    risky = sorted([p for p in projects if p["stage"] != "iptal" and (p["health"] != "yesil" or (p["ai_risk_score"] or 0) >= 50)],
                   key=lambda p: -(p["ai_risk_score"] or 0))
    actions = db.rows("SELECT a.*, p.code FROM actions a LEFT JOIN projects p ON p.id = a.project_id "
                      "WHERE a.status = 'acik' ORDER BY a.due_date")
    latest_insight = db.row("SELECT * FROM ai_insights WHERE kind = 'weekly' ORDER BY id DESC LIMIT 1")
    latest_docs = db.rows("SELECT id, title, doc_type, doc_date, status, uploaded_at FROM documents ORDER BY id DESC LIMIT 6")
    recent_comments = db.rows(
        "SELECT c.*, u.name AS uname, COALESCE(p.code || ' ' || p.name, i.name) AS target_name, "
        "CASE c.target_type WHEN 'project' THEN '/projeler/' || c.target_id ELSE '/guvenlik/' || i.slug END AS link "
        "FROM comments c JOIN users u ON u.id = c.user_id "
        "LEFT JOIN projects p ON c.target_type = 'project' AND p.id = c.target_id "
        "LEFT JOIN initiatives i ON c.target_type = 'initiative' AND i.id = c.target_id "
        "WHERE c.kind NOT IN ('trello', 'ai') ORDER BY c.id DESC LIMIT 5")
    value = {"live_estimated": sum(p["estimated_value"] or 0 for p in live), "realized": sum(p["realized_value"] or 0 for p in projects)}
    tl = timeline.load()
    q = timeline.quarterly(tl)
    return render(request, "dashboard.html", user, projects=projects, active=active, live=live, measured=measured,
                  stage_counts=stage_counts, side_counts=side_counts, health_counts=health_counts, risky=risky[:7],
                  unmeasured_live=[p for p in live if p not in measured], actions=actions, latest_insight=latest_insight,
                  stale=ai.stale_projects(), value=value, coverage=ai.coverage(), recent_comments=recent_comments,
                  latest_docs=latest_docs, tl_summary=timeline.summary(tl), conflicts=knowledge.conflicts(),
                  tl_bars=Markup(timeline.quarterly_bars(q[-6:])))


# ------------------------------------------------------------------ zaman çizelgesi

@router.get("/zaman-cizelgesi", response_class=HTMLResponse)
def timeline_page(request: Request, departman: str = "", stage: str = "", yil: str = "", grup: str = "dept",
                  user=Depends(require_user)):
    projects = timeline.load(int(departman) if departman.isdigit() else None, stage or None, int(yil) if yil.isdigit() else None)
    q = timeline.quarterly(projects)
    years = sorted({d.year for p in timeline.load() for d in (p["start"], p["target"], p["golive"]) if d})
    return render(request, "timeline.html", user, projects=projects, s=timeline.summary(projects), quarters=q,
                  gantt=Markup(timeline.gantt(projects, "stage" if grup == "asama" else "dept")),
                  bars=Markup(timeline.quarterly_bars(q)), cumulative=Markup(timeline.cumulative_chart(q)),
                  departments=departments(), years=years, f={"departman": departman, "stage": stage, "yil": yil, "grup": grup})


# ------------------------------------------------------------------ projeler

PROJECT_FIELDS = ["name", "aliases", "summary", "problem", "solution", "business_unit", "brands", "ai_type", "health", "priority",
                  "sponsor", "owner", "dt_lead", "start_date", "target_date", "golive_date", "measurement_status", "estimated_value",
                  "realized_value", "fte_saving", "security_review", "data_class"]
NUMERIC = {"estimated_value", "realized_value", "fte_saving"}


@router.get("/projeler", response_class=HTMLResponse)
def project_list(request: Request, view: str = "pano", q: str = "", stage: str = "", health: str = "", departman: str = "",
                 olcum: str = "", user=Depends(require_user)):
    where, params = ["1=1"], []
    if q:
        where.append("(p.name LIKE ? OR p.code LIKE ? OR p.summary LIKE ? OR p.brands LIKE ? OR p.aliases LIKE ?)")
        params += [f"%{q}%"] * 5
    for col, val in (("p.stage", stage), ("p.health", health), ("p.measurement_status", olcum)):
        if val:
            where.append(f"{col} = ?")
            params.append(val)
    if departman.isdigit():
        where.append("p.department_id = ?")
        params.append(int(departman))
    projects = visible_projects(user, " AND ".join(where), tuple(params))
    counts = {r["target_id"]: r["n"] for r in db.rows(
        "SELECT target_id, COUNT(*) AS n FROM comments WHERE target_type = 'project' GROUP BY target_id")}
    docs = {r["project_id"]: r["n"] for r in db.rows("SELECT project_id, COUNT(*) AS n FROM document_links GROUP BY project_id")}
    pend = {r["project_id"]: r["n"] for r in db.rows("SELECT project_id, COUNT(*) AS n FROM facts WHERE status = 'oneri' GROUP BY project_id")}
    return render(request, "projects.html", user, projects=projects, view=view, counts=counts, docs=docs, pend=pend,
                  departments=departments(), filters={"q": q, "stage": stage, "health": health, "departman": departman, "olcum": olcum})


@router.get("/projeler/yeni", response_class=HTMLResponse)
def project_new(request: Request, ad: str = "", user=Depends(require_editor)):
    return render(request, "project_form.html", user, departments=departments(),
                  project={"name": ad, "stage": "fikir", "health": "yesil", "priority": "Orta", "measurement_status": "yok",
                           "security_review": "yok", "visible_to_dt": 1})


def _project_data(form) -> dict:
    data = {}
    for f in PROJECT_FIELDS:
        v = form.get(f)
        if v is None:
            continue
        v = v.strip()
        data[f] = parse_float(v) if f in NUMERIC else (v or None)
    dep = str(form.get("department_id") or "")
    data["department_id"] = int(dep) if dep.isdigit() else None
    return data


@router.post("/projeler")
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
    src = str(form.get("from_fact") or "")
    if src.isdigit():  # dokümanda bulunan "portföyde olmayan proje" adayından oluşturuldu
        f = db.row("SELECT * FROM facts WHERE id = ?", (int(src),))
        if f:
            knowledge.link(f["document_id"], pid, "manuel")
            db.update("facts", f["id"], {"status": "onaylandi", "project_id": pid, "reviewed_by": user["id"], "reviewed_at": ts})
    db.log(user["id"], "project_created", "project", pid, data["name"])
    flash(request, "Proje oluşturuldu. İlgili dokümanları yeniden işlerseniz yeni proje de eşleştirilir.")
    return redirect(f"/projeler/{pid}")


@router.get("/projeler/{pid}", response_class=HTMLResponse)
def project_detail(request: Request, pid: int, tab: str = "genel", user=Depends(require_user)):
    p = get_project(pid, user)
    kpis = db.rows("SELECT * FROM kpis WHERE project_id = ? ORDER BY id", (pid,))
    documents = db.rows("SELECT d.*, l.method, l.confidence, l.mentions FROM document_links l JOIN documents d ON d.id = l.document_id "
                        "WHERE l.project_id = ? ORDER BY COALESCE(d.doc_date, d.uploaded_at) DESC", (pid,))
    gates = domain.gate_checks(p, kpis, {d["doc_type"] for d in documents})
    history = db.rows("SELECT h.*, u.name AS uname FROM stage_history h LEFT JOIN users u ON u.id = h.user_id "
                      "WHERE project_id = ? ORDER BY at DESC", (pid,))
    comments = comments_for("project", pid, user)
    actions = db.rows("SELECT * FROM actions WHERE project_id = ? ORDER BY status, due_date", (pid,))
    facts = knowledge.project_facts(pid) if user["role"] != "dt" else []
    synthesis = db.row("SELECT * FROM ai_insights WHERE kind = 'project' AND project_id = ? ORDER BY id DESC LIMIT 1", (pid,))
    synth_job = db.row("SELECT * FROM jobs WHERE kind = 'synthesis' AND ref_id = ? AND status IN ('sirada','calisiyor') LIMIT 1", (pid,))
    next_stage = None
    if p["stage"] in domain.STAGE_ORDER and p["stage"] != domain.STAGE_ORDER[-1]:
        next_stage = domain.STAGE_ORDER[domain.STAGE_ORDER.index(p["stage"]) + 1]
    return render(request, "project_detail.html", user, p=p, kpis=kpis, documents=documents, gates=gates, history=history,
                  comments=comments, actions=actions, tab=tab, next_stage=next_stage, facts=facts, synthesis=synthesis,
                  synth_job=synth_job, pending=knowledge.pending(pid), conflicts=knowledge.conflicts(pid),
                  status_timeline=[f for f in facts if f["fact_type"] in ("durum", "saglik", "risk", "engel", "sonraki_adim", "karar", "not", "olcum")])


@router.get("/projeler/{pid}/duzenle", response_class=HTMLResponse)
def project_edit(request: Request, pid: int, user=Depends(require_editor)):
    return render(request, "project_form.html", user, project=get_project(pid, user), departments=departments())


@router.post("/projeler/{pid}")
async def project_update(request: Request, pid: int, user=Depends(require_editor)):
    get_project(pid, user)
    data = _project_data(await request.form())
    data["updated_at"] = db.now()
    db.update("projects", pid, data)
    db.log(user["id"], "project_updated", "project", pid)
    flash(request, "Proje güncellendi.")
    return redirect(f"/projeler/{pid}")


@router.post("/projeler/{pid}/sil")
def project_delete(request: Request, pid: int, user=Depends(require_editor)):
    p = get_project(pid, user)
    db.execute("DELETE FROM comments WHERE target_type = 'project' AND target_id = ?", (pid,))
    db.execute("DELETE FROM projects WHERE id = ?", (pid,))
    db.log(user["id"], "project_deleted", "project", pid, p["code"])
    flash(request, f"{p['code']} silindi.")
    return redirect("/projeler")


@router.post("/projeler/{pid}/asama")
def project_stage(request: Request, pid: int, to_stage: str = Form(...), note: str = Form(""), user=Depends(require_editor)):
    p = get_project(pid, user)
    if to_stage not in domain.STAGE_LABELS or to_stage == p["stage"]:
        return back(request)
    kpis = db.rows("SELECT * FROM kpis WHERE project_id = ?", (pid,))
    types = {r["doc_type"] for r in db.rows("SELECT d.doc_type FROM document_links l JOIN documents d ON d.id = l.document_id "
                                            "WHERE l.project_id = ?", (pid,))}
    missing = [c for c, ok in domain.gate_checks(p, kpis, types).get(to_stage, []) if not ok]
    ts = db.now()
    db.insert("stage_history", {"project_id": pid, "from_stage": p["stage"], "to_stage": to_stage, "note": note or None,
                                "missing_criteria": json.dumps(missing, ensure_ascii=False) if missing else None,
                                "user_id": user["id"], "at": ts})
    data = {"stage": to_stage, "updated_at": ts}
    if to_stage == "canli" and not p["golive_date"]:
        data["golive_date"] = date.today().isoformat()
    if to_stage in ("gelistirme", "pilot") and not p["start_date"]:
        data["start_date"] = date.today().isoformat()
    db.update("projects", pid, data)
    db.log(user["id"], "stage_changed", "project", pid, f"{domain.STAGE_LABELS[p['stage']]} → {domain.STAGE_LABELS[to_stage]}")
    if missing:
        flash(request, "Aşama değişti, ancak kapı kriterleri eksik: " + ", ".join(missing), "warn")
    else:
        flash(request, f"Proje '{domain.STAGE_LABELS[to_stage]}' aşamasına taşındı.")
    return redirect(f"/projeler/{pid}")


@router.post("/projeler/{pid}/durum")
def project_status_note(request: Request, pid: int, health: str = Form(...), note: str = Form(""), user=Depends(require_uploader)):
    p = get_project(pid, user)
    if health not in domain.HEALTH:
        raise HTTPException(400, "Geçersiz sağlık değeri")
    ts = db.now()
    db.update("projects", pid, {"health": health, "last_status_at": ts, "updated_at": ts})
    body = f"**Durum güncellemesi:** {domain.HEALTH[health][0]}" + (f"\n\n{note}" if note.strip() else "")
    db.insert("comments", {"target_type": "project", "target_id": pid, "user_id": user["id"], "body": body, "kind": "durum", "created_at": ts})
    db.log(user["id"], "status_updated", "project", pid, f"{p['code']} → {domain.HEALTH[health][0]}")
    flash(request, "Durum güncellendi.")
    return redirect(f"/projeler/{pid}")


@router.post("/projeler/{pid}/sentez")
def project_synthesis(request: Request, pid: int, user=Depends(require_internal)):
    get_project(pid, user)
    pipeline.enqueue("synthesis", pid)
    flash(request, "Proje sentezi hazırlanıyor. Tüm kaynaklar birlikte değerlendiriliyor; sayfa birazdan güncellenecek.")
    return redirect(f"/projeler/{pid}?tab=bilgi")


# ------------------------------------------------------------------ KPI

@router.post("/projeler/{pid}/kpi")
def kpi_add(request: Request, pid: int, name: str = Form(...), unit: str = Form(""), direction: str = Form("up"),
            baseline: str = Form(""), target: str = Form(""), actual: str = Form(""), method: str = Form(""),
            user=Depends(require_uploader)):
    get_project(pid, user)
    db.insert("kpis", {"project_id": pid, "name": name, "unit": unit or None, "direction": "down" if direction == "down" else "up",
                       "baseline": parse_float(baseline), "target": parse_float(target), "actual": parse_float(actual),
                       "method": method or None, "measured_at": date.today().isoformat() if parse_float(actual) is not None else None})
    knowledge.bump_measurement(pid)
    db.log(user["id"], "kpi_added", "project", pid, name)
    return redirect(f"/projeler/{pid}?tab=etki")


@router.post("/kpi/{kid}")
def kpi_update(request: Request, kid: int, baseline: str = Form(""), target: str = Form(""), actual: str = Form(""),
               method: str = Form(""), user=Depends(require_uploader)):
    k = db.row("SELECT * FROM kpis WHERE id = ?", (kid,))
    if not k:
        raise HTTPException(404, "KPI bulunamadı")
    get_project(k["project_id"], user)
    data = {"baseline": parse_float(baseline), "target": parse_float(target), "actual": parse_float(actual), "method": method or None}
    if data["actual"] != k["actual"]:
        data["measured_at"] = date.today().isoformat()
    db.update("kpis", kid, data)
    knowledge.bump_measurement(k["project_id"])
    return redirect(f"/projeler/{k['project_id']}?tab=etki")


@router.post("/kpi/{kid}/sil")
def kpi_delete(request: Request, kid: int, user=Depends(require_editor)):
    k = db.row("SELECT * FROM kpis WHERE id = ?", (kid,))
    if k:
        db.execute("DELETE FROM kpis WHERE id = ?", (kid,))
        return redirect(f"/projeler/{k['project_id']}?tab=etki")
    return back(request)


# ------------------------------------------------------------------ aksiyonlar

@router.post("/projeler/{pid}/aksiyon")
def action_add(request: Request, pid: int, title: str = Form(...), owner: str = Form(""), due_date: str = Form(""),
               user=Depends(require_editor)):
    get_project(pid, user)
    db.insert("actions", {"project_id": pid, "title": title, "owner": owner or None, "due_date": due_date or None,
                          "status": "acik", "source": "Manuel", "created_by": user["id"], "created_at": db.now()})
    return redirect(f"/projeler/{pid}?tab=aksiyon")


@router.post("/aksiyon/{aid}/durum")
def action_toggle(request: Request, aid: int, user=Depends(require_uploader)):
    a = db.row("SELECT * FROM actions WHERE id = ?", (aid,))
    if not a:
        raise HTTPException(404, "Aksiyon bulunamadı")
    new = "kapali" if a["status"] == "acik" else "acik"
    db.update("actions", aid, {"status": new, "closed_at": db.now() if new == "kapali" else None})
    db.log(user["id"], "action_" + new, "project", a["project_id"], a["title"])
    return back(request)


@router.get("/aksiyonlar", response_class=HTMLResponse)
def action_list(request: Request, durum: str = "acik", user=Depends(require_internal)):
    acts = db.rows("SELECT a.*, p.code, p.name AS pname, d.title AS dtitle FROM actions a LEFT JOIN projects p ON p.id = a.project_id "
                   "LEFT JOIN documents d ON d.id = a.source_document_id "
                   "WHERE (? = 'hepsi' OR a.status = ?) ORDER BY a.status, a.due_date", (durum, durum))
    return render(request, "actions.html", user, actions=acts, durum=durum,
                  projects=db.rows("SELECT id, code, name FROM projects WHERE stage != 'iptal' ORDER BY code"))


@router.post("/aksiyonlar")
def action_add_global(request: Request, title: str = Form(...), project_id: str = Form(""), owner: str = Form(""),
                      due_date: str = Form(""), user=Depends(require_editor)):
    db.insert("actions", {"project_id": int(project_id) if project_id.isdigit() else None, "title": title, "owner": owner or None,
                          "due_date": due_date or None, "status": "acik", "source": "Komite", "created_by": user["id"],
                          "created_at": db.now()})
    return redirect("/aksiyonlar")


# ------------------------------------------------------------------ yorumlar

def comments_for(target_type: str, target_id: int, user: dict) -> list[dict]:
    kinds = "" if user["role"] != "dt" else " AND c.kind != 'ai'"
    return db.rows("SELECT c.*, u.name AS uname, u.organization, u.role AS urole FROM comments c JOIN users u ON u.id = c.user_id "
                   f"WHERE target_type = ? AND target_id = ?{kinds} ORDER BY c.created_at DESC, c.id DESC", (target_type, target_id))


@router.post("/yorum")
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


@router.post("/yorum/{cid}/sil")
def comment_delete(request: Request, cid: int, user=Depends(require_user)):
    c = db.row("SELECT * FROM comments WHERE id = ?", (cid,))
    if c and (c["user_id"] == user["id"] or user["role"] == "admin"):
        db.execute("DELETE FROM comments WHERE id = ?", (cid,))
    return back(request)


# ------------------------------------------------------------------ dışa aktarım

@router.get("/disa-aktar/projeler.csv")
def export_projects(user=Depends(require_internal)):
    buf = io.StringIO()
    cols = ["code", "name", "dept", "stage", "health", "priority", "brands", "ai_type", "sponsor", "owner", "dt_lead", "start_date",
            "target_date", "golive_date", "measurement_status", "estimated_value", "realized_value", "fte_saving", "security_review",
            "data_class", "ai_risk_score", "last_status_at"]
    w = csv.writer(buf, delimiter=";")
    w.writerow(cols)
    for p in db.rows("SELECT p.*, d.name AS dept FROM projects p LEFT JOIN departments d ON d.id = p.department_id ORDER BY code"):
        w.writerow([p[c] for c in cols])
    return PlainTextResponse("﻿" + buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=ai-impact-projeler.csv"})
