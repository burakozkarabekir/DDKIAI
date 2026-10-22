"""Doküman işleme hattı ve kalıcı iş kuyruğu.

Her doküman şu adımlardan geçer (documents.status):
    sirada → isleniyor → [metin çıkarma → parçalama + indeks → proje eşleştirme → AI çıkarımı → bilgiler] → islendi
Metin çıkarılamazsa "metin_yok", hata olursa "hata" (hata mesajı saklanır, yeniden işlenebilir).

İşler `jobs` tablosunda durur; arka plandaki işçi iş parçacığı sırayla çalıştırır. Sunucu yeniden başlarsa
yarım kalan işler kuyruğa geri alınır.
"""
import logging
import re
import threading
import time
import traceback

from . import ai, db, knowledge
from .domain import DOC_TYPES
from .extract import extract, full_text
from .storage import path_of

log = logging.getLogger("pipeline")
_wake = threading.Event()
_started = False


# ---------------------------------------------------------------- kuyruk

def enqueue(kind: str, ref_id: int | None = None, dedupe: bool = True) -> int:
    if dedupe:
        existing = db.scalar("SELECT id FROM jobs WHERE kind = ? AND COALESCE(ref_id, -1) = COALESCE(?, -1) AND status IN ('sirada')",
                             (kind, ref_id))
        if existing:
            return existing
    jid = db.insert("jobs", {"kind": kind, "ref_id": ref_id, "status": "sirada", "created_at": db.now()})
    _wake.set()
    return jid


def _claim() -> dict | None:
    with db.tx() as c:
        r = c.execute("SELECT * FROM jobs WHERE status = 'sirada' ORDER BY CASE kind WHEN 'document' THEN 0 ELSE 1 END, id LIMIT 1").fetchone()
        if not r:
            return None
        cur = c.execute("UPDATE jobs SET status = 'calisiyor', started_at = ?, attempts = attempts + 1 WHERE id = ? AND status = 'sirada'",
                        (db.now(), r["id"]))
        return dict(r) if cur.rowcount else None


def run_job(job: dict) -> None:
    try:
        HANDLERS[job["kind"]](job["ref_id"])
        db.update("jobs", job["id"], {"status": "tamam", "finished_at": db.now(), "error": None})
    except Exception as exc:
        log.exception("İş başarısız: %s", job)
        db.update("jobs", job["id"], {"status": "hata", "finished_at": db.now(), "error": f"{exc}"[:2000]})
        if job["kind"] == "document":
            db.update("documents", job["ref_id"], {"status": "hata", "error": f"{exc}\n{traceback.format_exc(limit=3)}"[:3000]})


def drain(max_jobs: int = 1000, timeout: float = 120) -> int:
    """Kuyruktaki işleri hemen çalıştırır ve arka plan işçisinin elindeki işlerin bitmesini bekler (testler, tohum veri)."""
    n = 0
    deadline = time.time() + timeout
    while n < max_jobs and time.time() < deadline:
        job = _claim()
        if job:
            run_job(job)
            n += 1
        elif db.scalar("SELECT COUNT(*) FROM jobs WHERE status IN ('sirada', 'calisiyor')"):
            time.sleep(0.1)
        else:
            break
    return n


def _loop() -> None:
    while True:
        try:
            job = _claim()
            if job:
                run_job(job)
                continue
        except Exception:
            log.exception("İşçi döngüsü hatası")
        _wake.wait(5)
        _wake.clear()


def start_worker() -> None:
    global _started
    if _started:
        return
    _started = True
    db.execute("UPDATE jobs SET status = 'sirada' WHERE status = 'calisiyor'")
    db.execute("UPDATE documents SET status = 'sirada' WHERE status = 'isleniyor'")
    threading.Thread(target=_loop, name="ai-impact-worker", daemon=True).start()


def queue_state() -> dict:
    r = db.row("SELECT SUM(status = 'sirada') AS waiting, SUM(status = 'calisiyor') AS running, SUM(status = 'hata') AS failed FROM jobs")
    return {k: (r[k] or 0) for k in ("waiting", "running", "failed")}


# ---------------------------------------------------------------- doküman işleme

def process_document(doc_id: int) -> None:
    doc = db.row("SELECT * FROM documents WHERE id = ?", (doc_id,))
    if not doc:
        return
    db.update("documents", doc_id, {"status": "isleniyor", "error": None})
    path = path_of(doc["storage_path"])
    if doc["storage_path"] and (not path or not path.exists()):
        raise FileNotFoundError(f"Dosya depoda bulunamadı: {doc['storage_path']}")
    if path:
        ex = extract(path)
        sections = ex["sections"]
        text = full_text(sections)
        db.update("documents", doc_id, {"text_content": text, "char_count": len(text), "page_count": ex["pages"]})
    else:  # yapıştırılmış metin
        text = doc["text_content"] or ""
        sections = [("", text)]
        ex = {"warning": None}
    if not text.strip():
        db.update("documents", doc_id, {"status": "metin_yok", "error": ex["warning"] or "Dokümandan metin çıkarılamadı.",
                                        "processed_at": db.now()})
        return
    if doc["type_source"] != "kullanici":
        db.update("documents", doc_id, {"doc_type": ai.guess_type(doc["filename"], text), "type_source": "kural"})
    knowledge.index_document(doc_id, sections)

    doc = db.row("SELECT * FROM documents WHERE id = ?", (doc_id,))
    result = ai.extract_document(doc, text)
    store_extraction(doc, result)

    data = {"status": "islendi", "processed_at": db.now(), "error": ex["warning"], "ai_mode": "live" if ai.is_live() else "mock"}
    db.update("documents", doc_id, data)
    doc = db.row("SELECT * FROM documents WHERE id = ?", (doc_id,))
    if doc["doc_type"] in ("dt_durum", "ic_not", "toplanti"):
        enqueue("weekly", None)
    db.log(doc["uploaded_by"], "document_processed", "document", doc_id, doc["title"])


def store_extraction(doc: dict, result: dict) -> None:
    doc_id = doc["id"]
    data = {}
    if doc["type_source"] != "kullanici" and result.get("doc_type") in DOC_TYPES:
        data.update(doc_type=result["doc_type"], type_source="ai" if ai.is_live() else "kural")
    if not doc["doc_date"] and knowledge._iso(result.get("doc_date")):
        data["doc_date"] = knowledge._iso(result.get("doc_date"))
    if result.get("summary"):
        data["summary"] = str(result["summary"])[:3000]
    if data:
        db.update("documents", doc_id, data)
    doc = {**doc, **data}

    codes = {r["code"].upper(): r["id"] for r in db.rows("SELECT id, code FROM projects")}
    for p in result.get("projects") or []:
        pid = codes.get(str(p.get("code") or "").upper())
        if pid:
            knowledge.link(doc_id, pid, "ai", _num(p.get("confidence")) or 0.7)

    # Yeniden işlemede incelenmiş (onaylı/reddedilmiş) bilgiler korunur, diğerleri yeniden üretilir.
    db.execute("DELETE FROM facts WHERE document_id = ? AND status IN ('bilgi', 'oneri')", (doc_id,))
    default_as_of = doc.get("doc_date") or doc["uploaded_at"][:10]
    touched = set()
    for f in result.get("facts") or []:
        pid = codes.get(str(f.get("project_code") or "").upper())
        ftype = f.get("type")
        if not pid or ftype not in knowledge.FACT_TYPES:
            continue
        value = f.get("value")
        num = _num(f.get("value_num"))
        if num is None and ftype in ("kpi", "kazanim") and value is not None:
            num = ai.parse_number(str(value))
        fid = knowledge.add_fact(doc_id, pid, ftype, field=f.get("field"), subfield=f.get("subfield"),
                                 value_text=None if value is None else str(value), value_num=num, unit=f.get("unit"),
                                 as_of=f.get("as_of") or default_as_of, confidence=_num(f.get("confidence")),
                                 evidence=f.get("evidence"))
        if fid:
            touched.add(pid)
            knowledge.link(doc_id, pid, "ai", _num(f.get("confidence")) or 0.7)
    for np in result.get("new_projects") or []:
        if np.get("name"):
            knowledge.add_fact(doc_id, None, "not", field="yeni_proje", value_text=str(np["name"])[:200],
                               evidence=str(np.get("description") or "")[:600], as_of=default_as_of)
    if doc["doc_type"] == "dt_durum":
        for pid in touched:
            db.execute("UPDATE projects SET last_status_at = ? WHERE id = ? AND (last_status_at IS NULL OR last_status_at < ?)",
                       (default_as_of + "T12:00:00", pid, default_as_of + "T12:00:00"))


def _num(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- diğer işler

def weekly_insight(_ref=None) -> None:
    body = ai.portfolio_weekly()
    latest = db.row("SELECT id, doc_date FROM documents WHERE doc_type = 'dt_durum' AND status = 'islendi' "
                    "ORDER BY COALESCE(doc_date, uploaded_at) DESC LIMIT 1")
    title = f"Haftalık portföy yorumu — {(latest or {}).get('doc_date') or db.now()[:10]}"
    db.insert("ai_insights", {"kind": "weekly", "title": title, "body": body, "source_document_id": latest["id"] if latest else None,
                              "created_at": db.now()})


def project_synthesis(pid: int) -> None:
    body = ai.project_synthesis(pid)
    db.execute("DELETE FROM ai_insights WHERE kind = 'project' AND project_id = ?", (pid,))
    db.insert("ai_insights", {"kind": "project", "title": "Proje sentezi", "body": body, "project_id": pid, "created_at": db.now()})
    m = re.search(r"(?:skor|risk)[^0-9]{0,20}(\d{1,3})", body, re.I)
    if m and ai.is_live() and 0 <= int(m.group(1)) <= 100:
        db.update("projects", pid, {"ai_risk_score": int(m.group(1))})


def gap_insight(_ref=None) -> None:
    db.insert("ai_insights", {"kind": "gap", "title": "AI Olgunluk ve Boşluk Analizi", "body": ai.gap_analysis(), "created_at": db.now()})


HANDLERS = {"document": process_document, "weekly": weekly_insight, "synthesis": project_synthesis, "gap": gap_insight}


def reprocess_all(only_mock: bool = False) -> int:
    where = "WHERE ai_mode = 'mock' OR ai_mode IS NULL" if only_mock else ""
    ids = [r["id"] for r in db.rows(f"SELECT id FROM documents {where}")]
    for i in ids:
        db.update("documents", i, {"status": "sirada"})
        enqueue("document", i)
    return len(ids)

