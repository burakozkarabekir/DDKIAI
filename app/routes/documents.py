"""Doküman yükleme ve kütüphane, doküman detayı, inceleme kuyruğu, DT durum raporları görünümü."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .. import db, domain, knowledge, pipeline
from ..auth import require_editor, require_internal
from ..storage import UploadError, path_of, save_stream
from ..web import back, departments, flash, parse_float, redirect, render

router = APIRouter()

STATUS = {"sirada": "Sırada", "isleniyor": "İşleniyor", "islendi": "İşlendi", "metin_yok": "Metin yok", "hata": "Hata"}


def _file_chunks(f: UploadFile):
    while chunk := f.file.read(1024 * 1024):
        yield chunk


@router.get("/dokumanlar", response_class=HTMLResponse)
def library(request: Request, q: str = "", tur: str = "", proje: str = "", durum: str = "", user=Depends(require_internal)):
    where, params = ["1=1"], []
    if tur:
        where.append("d.doc_type = ?")
        params.append(tur)
    if durum:
        where.append("d.status = ?")
        params.append(durum)
    if proje.isdigit():
        where.append("d.id IN (SELECT document_id FROM document_links WHERE project_id = ?)")
        params.append(int(proje))
    hits = []
    if q:
        hits = knowledge.search(q, limit=30)
        ids = sorted({h["document_id"] for h in hits}) or [0]
        where.append(f"(d.title LIKE ? OR d.filename LIKE ? OR d.id IN ({','.join('?' * len(ids))}))")
        params += [f"%{q}%", f"%{q}%", *ids]
    docs = db.rows(
        "SELECT d.id, d.title, d.doc_type, d.type_source, d.source, d.doc_date, d.filename, d.size, d.status, d.uploaded_at, "
        "d.initiative_id, d.char_count, (SELECT GROUP_CONCAT(p.code, ', ') FROM document_links l JOIN projects p ON p.id = l.project_id "
        " WHERE l.document_id = d.id) AS codes, (SELECT COUNT(*) FROM facts f WHERE f.document_id = d.id) AS nfacts, "
        "(SELECT COUNT(*) FROM facts f WHERE f.document_id = d.id AND f.status = 'oneri') AS npending "
        f"FROM documents d WHERE {' AND '.join(where)} ORDER BY COALESCE(d.doc_date, substr(d.uploaded_at, 1, 10)) DESC, d.id DESC",
        tuple(params))
    type_counts = {r["doc_type"]: r["n"] for r in db.rows("SELECT doc_type, COUNT(*) AS n FROM documents GROUP BY doc_type")}
    return render(request, "documents.html", user, docs=docs, hits=hits[:8], q=q, tur=tur, proje=proje, durum=durum,
                  type_counts=type_counts, projects=db.rows("SELECT id, code, name FROM projects ORDER BY code"),
                  status_labels=STATUS, processing=any(d["status"] in ("sirada", "isleniyor") for d in docs))


@router.post("/dokumanlar")
def upload(request: Request, files: list[UploadFile] = File(...), doc_type: str = Form("otomatik"), source: str = Form(""),
           doc_date: str = Form(""), project_ids: list[str] = Form([]), initiative_id: str = Form(""), user=Depends(require_internal)):
    created, dupes, errors = [], [], []
    for f in files:
        if not f.filename:
            continue
        try:
            stored = save_stream(_file_chunks(f), f.filename)
        except UploadError as exc:
            errors.append(f"{f.filename}: {exc}")
            continue
        dup = db.row("SELECT id, title FROM documents WHERE sha256 = ?", (stored["sha256"],))
        if dup:
            dupes.append(f"{f.filename} (zaten var: #{dup['id']} {dup['title']})")
            continue
        did = db.insert("documents", {
            "title": f.filename.rsplit(".", 1)[0][:200], "filename": f.filename, "storage_path": stored["storage_path"],
            "sha256": stored["sha256"], "size": stored["size"], "mime": f.content_type,
            "doc_type": doc_type if doc_type in domain.DOC_TYPES else "diger",
            "type_source": "kullanici" if doc_type in domain.DOC_TYPES else "otomatik",
            "source": source or None, "doc_date": doc_date or None,
            "initiative_id": int(initiative_id) if initiative_id.isdigit() else None,
            "status": "sirada", "uploaded_by": user["id"], "uploaded_at": db.now()})
        for pid in project_ids:
            if str(pid).isdigit():
                knowledge.link(did, int(pid), "manuel")
        pipeline.enqueue("document", did)
        created.append(did)
        db.log(user["id"], "document_uploaded", "document", did, f.filename)
    msg = [f"{len(created)} doküman yüklendi ve işleme kuyruğuna alındı."] if created else []
    if dupes:
        msg.append("Aynı içerik zaten yüklü olduğu için atlananlar: " + "; ".join(dupes))
    if errors:
        msg.append("Yüklenemeyenler: " + "; ".join(errors))
    flash(request, " ".join(msg) or "Dosya seçilmedi.", "warn" if (dupes or errors) else "ok")
    if len(created) == 1:
        return redirect(f"/dokumanlar/{created[0]}")
    return back(request, "/dokumanlar")


@router.post("/dokumanlar/metin")
def upload_text(request: Request, title: str = Form(...), text: str = Form(...), doc_type: str = Form("otomatik"),
                source: str = Form(""), doc_date: str = Form(""), user=Depends(require_internal)):
    """E-posta gövdesi gibi metni doküman olarak kaydeder (dosya olmadan)."""
    did = db.insert("documents", {
        "title": title[:200], "filename": f"{title[:80]}.txt", "text_content": text, "char_count": len(text), "size": len(text.encode()),
        "doc_type": doc_type if doc_type in domain.DOC_TYPES else "diger",
        "type_source": "kullanici" if doc_type in domain.DOC_TYPES else "otomatik",
        "source": source or None, "doc_date": doc_date or None, "status": "sirada", "uploaded_by": user["id"], "uploaded_at": db.now()})
    pipeline.enqueue("document", did)
    flash(request, "Metin kaydedildi ve işleme alındı.")
    return redirect(f"/dokumanlar/{did}")


def _doc(did: int) -> dict:
    d = db.row("SELECT d.*, u.name AS uname, i.name AS iname, i.slug FROM documents d LEFT JOIN users u ON u.id = d.uploaded_by "
               "LEFT JOIN initiatives i ON i.id = d.initiative_id WHERE d.id = ?", (did,))
    if not d:
        raise HTTPException(404, "Doküman bulunamadı")
    return d


@router.get("/dokumanlar/{did}", response_class=HTMLResponse)
def detail(request: Request, did: int, user=Depends(require_internal)):
    d = _doc(did)
    links = db.rows("SELECT l.*, p.code, p.name FROM document_links l JOIN projects p ON p.id = l.project_id WHERE l.document_id = ? "
                    "ORDER BY l.mentions DESC, p.code", (did,))
    facts = db.rows("SELECT f.*, p.code, p.name AS pname FROM facts f LEFT JOIN projects p ON p.id = f.project_id "
                    "WHERE f.document_id = ? ORDER BY p.code, CASE WHEN f.status = 'oneri' THEN 0 ELSE 1 END, f.fact_type", (did,))
    for f in facts:
        f["label"], f["display"] = knowledge.field_label(f), knowledge.display_value(f)
        f["current"] = knowledge.current_value(f) if f["status"] == "oneri" else None
    grouped: dict = {}
    for f in facts:
        grouped.setdefault((f["code"] or "", f["pname"] or ""), []).append(f)
    chunks = db.rows("SELECT c.*, p.code FROM chunks c LEFT JOIN projects p ON p.id = c.project_id WHERE document_id = ? ORDER BY seq", (did,))
    candidates = [f for f in facts if f["field"] == "yeni_proje" and f["status"] == "bilgi"]
    return render(request, "document_detail.html", user, d=d, links=links, grouped=grouped, chunks=chunks, candidates=candidates,
                  projects=db.rows("SELECT id, code, name FROM projects ORDER BY code"), status_labels=STATUS,
                  job=db.row("SELECT * FROM jobs WHERE kind = 'document' AND ref_id = ? ORDER BY id DESC LIMIT 1", (did,)))


@router.post("/dokumanlar/{did}")
def update_meta(request: Request, did: int, title: str = Form(...), doc_type: str = Form(...), source: str = Form(""),
                doc_date: str = Form(""), reprocess: str = Form(""), user=Depends(require_internal)):
    d = _doc(did)
    data = {"title": title[:200], "source": source or None, "doc_date": doc_date or None}
    if doc_type in domain.DOC_TYPES and doc_type != d["doc_type"]:
        data.update(doc_type=doc_type, type_source="kullanici")
    db.update("documents", did, data)
    if reprocess:
        db.update("documents", did, {"status": "sirada"})
        pipeline.enqueue("document", did)
        flash(request, "Bilgiler kaydedildi, doküman yeniden işleniyor.")
    else:
        flash(request, "Bilgiler kaydedildi.")
    return redirect(f"/dokumanlar/{did}")


@router.post("/dokumanlar/{did}/yeniden-isle")
def reprocess(request: Request, did: int, user=Depends(require_internal)):
    _doc(did)
    db.update("documents", did, {"status": "sirada", "error": None})
    pipeline.enqueue("document", did)
    flash(request, "Doküman yeniden işleniyor. Onayladığınız/reddettiğiniz bilgiler korunur.")
    return redirect(f"/dokumanlar/{did}")


@router.post("/dokumanlar/{did}/bagla")
def add_link(request: Request, did: int, project_id: int = Form(...), user=Depends(require_internal)):
    _doc(did)
    knowledge.link(did, project_id, "manuel")
    flash(request, "Proje bağlandı. Bu proje için bilgi çıkarmak üzere dokümanı yeniden işleyebilirsiniz.")
    return redirect(f"/dokumanlar/{did}")


@router.post("/dokumanlar/{did}/bag-kaldir/{pid}")
def remove_link(request: Request, did: int, pid: int, user=Depends(require_internal)):
    db.execute("DELETE FROM document_links WHERE document_id = ? AND project_id = ?", (did, pid))
    db.execute("DELETE FROM facts WHERE document_id = ? AND project_id = ? AND status IN ('bilgi', 'oneri')", (did, pid))
    db.execute("UPDATE chunks SET project_id = NULL WHERE document_id = ? AND project_id = ?", (did, pid))
    return redirect(f"/dokumanlar/{did}")


@router.get("/dokumanlar/{did}/indir")
def download(did: int, user=Depends(require_internal)):
    d = _doc(did)
    path = path_of(d["storage_path"])
    if not path or not path.exists():
        raise HTTPException(404, "Dosya depoda bulunamadı")
    return FileResponse(path, filename=d["filename"], media_type=d["mime"] or "application/octet-stream")


@router.post("/dokumanlar/{did}/sil")
def delete(request: Request, did: int, user=Depends(require_editor)):
    d = _doc(did)
    db.execute("DELETE FROM documents WHERE id = ?", (did,))
    still_used = d["sha256"] and db.scalar("SELECT 1 FROM documents WHERE sha256 = ?", (d["sha256"],))
    path = path_of(d["storage_path"])
    if path and not still_used:
        path.unlink(missing_ok=True)
    db.log(user["id"], "document_deleted", "document", did, d["title"])
    flash(request, f"'{d['title']}' ve ondan çıkarılan bilgiler silindi.")
    return redirect("/dokumanlar")


@router.get("/api/dokumanlar/durum")
def status_api(ids: str = "", user=Depends(require_internal)):
    id_list = [int(i) for i in ids.split(",") if i.isdigit()][:200]
    if not id_list:
        return {"pending": 0}
    n = db.scalar(f"SELECT COUNT(*) FROM documents WHERE id IN ({','.join('?' * len(id_list))}) AND status IN ('sirada','isleniyor')",
                  tuple(id_list))
    return {"pending": n}


@router.get("/api/is/{kind}/{ref_id}")
def job_status(kind: str, ref_id: int, user=Depends(require_internal)):
    j = db.row("SELECT status FROM jobs WHERE kind = ? AND ref_id = ? ORDER BY id DESC LIMIT 1", (kind, ref_id))
    return {"status": j["status"] if j else None}


# ------------------------------------------------------------------ inceleme kuyruğu

@router.get("/inceleme", response_class=HTMLResponse)
def review(request: Request, proje: str = "", tur: str = "", user=Depends(require_internal)):
    items = knowledge.pending(int(proje) if proje.isdigit() else None)
    if tur:
        items = [f for f in items if f["fact_type"] == tur]
    grouped: dict = {}
    for f in items:
        grouped.setdefault((f["project_id"], f["code"], f["pname"]), []).append(f)
    return render(request, "review.html", user, grouped=grouped, total=len(items), conflicts=knowledge.conflicts(),
                  projects=db.rows("SELECT DISTINCT p.id, p.code, p.name FROM facts f JOIN projects p ON p.id = f.project_id "
                                   "WHERE f.status = 'oneri' ORDER BY p.code"), proje=proje, tur=tur)


@router.post("/inceleme")
async def review_bulk(request: Request, user=Depends(require_internal)):
    form = await request.form()
    ids = [int(v) for v in form.getlist("fact_id") if str(v).isdigit()]
    action = form.get("action")
    n = 0
    for fid in ids:
        if action == "onayla":
            n += 1 if knowledge.apply_fact(fid, user["id"]) else 0
        elif action == "reddet":
            knowledge.reject_fact(fid, user["id"])
            n += 1
    flash(request, f"{n} öneri {'onaylandı ve projelere işlendi' if action == 'onayla' else 'reddedildi'}.")
    return back(request, "/inceleme")


@router.post("/bilgi/{fid}/deger")
def review_edit(request: Request, fid: int, value: str = Form(""), as_of: str = Form(""), user=Depends(require_internal)):
    """Öneriyi onaylamadan önce değerini düzeltme."""
    f = db.row("SELECT * FROM facts WHERE id = ?", (fid,))
    if not f or f["status"] not in ("oneri", "bilgi"):
        raise HTTPException(404, "Bilgi bulunamadı")
    data = {"as_of": knowledge._iso(as_of) or f["as_of"], "confidence": 1.0}
    v = value.strip()
    if f["fact_type"] in ("kpi", "kazanim") and f["field"] != "measurement_status":
        num = parse_float(v)
        if num is None:
            flash(request, "Sayısal bir değer girin.", "error")
            return back(request, "/inceleme")
        data["value_num"] = num
    elif f["fact_type"] == "tarih":
        if not knowledge._iso(v):
            flash(request, "Tarihi GG.AA.YYYY ya da YYYY-AA-GG biçiminde girin.", "error")
            return back(request, "/inceleme")
        data["value_text"] = knowledge._iso(v)
    else:
        data["value_text"] = v[:4000]
    db.update("facts", fid, data)
    flash(request, "Değer güncellendi. Onaylarsanız bu değer projeye işlenir.")
    return back(request, "/inceleme")


@router.post("/bilgi/{fid}/{action}")
def review_one(request: Request, fid: int, action: str, user=Depends(require_internal)):
    if action == "onayla":
        knowledge.apply_fact(fid, user["id"])
    elif action == "reddet":
        knowledge.reject_fact(fid, user["id"])
    return back(request, "/inceleme")


# ------------------------------------------------------------------ DT durum raporları

@router.get("/raporlar", response_class=HTMLResponse)
def reports(request: Request, user=Depends(require_internal)):
    reps = db.rows("SELECT d.*, (SELECT COUNT(DISTINCT project_id) FROM facts WHERE document_id = d.id AND project_id IS NOT NULL) AS n, "
                   "(SELECT COUNT(*) FROM facts WHERE document_id = d.id AND fact_type = 'saglik' AND value_text != 'yesil') AS risky "
                   "FROM documents d WHERE doc_type = 'dt_durum' ORDER BY COALESCE(doc_date, substr(uploaded_at, 1, 10)) DESC")
    cols = reps[:10][::-1]
    grid = {}
    for f in db.rows("SELECT document_id, project_id, value_text, value_num FROM facts WHERE fact_type = 'saglik' AND project_id IS NOT NULL"):
        grid[(f["project_id"], f["document_id"])] = f
    heat_projects = db.rows("SELECT * FROM projects WHERE stage NOT IN ('fikir','iptal') ORDER BY code")
    notes = db.rows("SELECT d.* FROM documents d WHERE doc_type IN ('ic_not', 'toplanti') ORDER BY COALESCE(doc_date, uploaded_at) DESC LIMIT 8")
    weekly = db.rows("SELECT * FROM ai_insights WHERE kind = 'weekly' ORDER BY id DESC LIMIT 6")
    return render(request, "reports.html", user, reports=reps, cols=cols, grid=grid, heat_projects=heat_projects, notes=notes,
                  weekly=weekly, status_labels=STATUS, departments=departments())
