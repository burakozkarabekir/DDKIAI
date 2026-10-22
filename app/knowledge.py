"""Bilgi katmanı: proje eşleştirme, parçalama, tam metin arama, çıkarılan bilgiler ve çelişkiler.

Veri akışı
    doküman ─► bölümler ─► proje sınırlarına göre segment ─► parçalar (chunks + FTS5)
                                   │
                                   └► proje eşleştirme (kod / ad / takma ad / AI) ─► document_links
    AI çıkarımı ─► facts (her biri: proje, tür, alan, değer, tarih, güven, alıntı, kaynak doküman)
    facts ─► bilgi akışı (salt bilgi) | inceleme kuyruğu (proje alanını değiştiren öneriler) ─► onay ─► proje
"""
import json
import re
from datetime import date

from . import db
from .domain import FACT_FIELDS, FACT_TYPES, HEALTH, KPI_PARTS, MEASUREMENT_LABELS, MEASUREMENT_RANK, STAGE_LABELS

CHUNK_SIZE = 1800
CHUNK_OVERLAP = 200

_TR = str.maketrans({"İ": "i", "I": "i", "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "ö": "o", "Ö": "o",
                     "ş": "s", "Ş": "s", "ü": "u", "Ü": "u", "â": "a", "î": "i", "û": "u"})


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").translate(_TR).lower()).strip()


# ---------------------------------------------------------------- proje eşleştirme

def catalog() -> list[dict]:
    """Eşleştirme için proje kataloğu: kod, ad ve takma adlar (normalize edilmiş)."""
    out = []
    for p in db.rows("SELECT id, code, name, aliases FROM projects"):
        names = [p["name"]] + [a.strip() for a in (p["aliases"] or "").split(",") if a.strip()]
        num = re.sub(r"\D", "", p["code"])
        out.append({"id": p["id"], "code": p["code"], "name": p["name"],
                    "code_re": re.compile(rf"\b{re.escape(p['code'].split('-')[0])}[\s\-_]?0*{int(num) if num else ''}\b", re.I) if num else None,
                    "names": [norm(n) for n in names if len(norm(n)) >= 6]})
    return out


def mentions(text: str, cat: list[dict] | None = None) -> dict[int, dict]:
    """Metinde geçen projeler: {project_id: {"count": n, "method": "kod"|"isim", "first": konum}}"""
    cat = cat if cat is not None else catalog()
    low = norm(text)
    found: dict[int, dict] = {}
    for p in cat:
        hits = list(p["code_re"].finditer(text)) if p["code_re"] else []
        if hits:
            found[p["id"]] = {"count": len(hits), "method": "kod", "first": hits[0].start()}
            continue
        for n in p["names"]:
            i = low.find(n)
            if i != -1:
                found[p["id"]] = {"count": low.count(n), "method": "isim", "first": i}
                break
    return found


def _line_project(line: str, cat: list[dict]) -> int | None:
    """Satır bir proje başlığı gibi mi başlıyor? (DT raporlarında her proje bölümü kod/ad ile başlar)"""
    head = line.strip()[:120]
    if not head:
        return None
    m = mentions(head, cat)
    if not m:
        return None
    pid, info = min(m.items(), key=lambda kv: kv[1]["first"])
    return pid if info["first"] <= 12 else None


def segment(sections: list[tuple[str, str]], cat: list[dict]) -> list[tuple[str, str, int | None]]:
    """Bölümleri proje sınırlarında böler. Dönüş: [(başlık, metin, proje_id|None)]"""
    out = []
    for heading, text in sections:
        heading_pid = _line_project(heading, cat) if heading else None
        cur_pid, buf = heading_pid, []
        for line in text.splitlines():
            pid = _line_project(line, cat)
            if pid and pid != cur_pid and buf:
                out.append((heading, "\n".join(buf).strip(), cur_pid))
                buf = []
            if pid:
                cur_pid = pid
            buf.append(line)
        if buf and "\n".join(buf).strip():
            out.append((heading, "\n".join(buf).strip(), cur_pid))
    return out


def chunk(segments: list[tuple[str, str, int | None]]) -> list[tuple[str, str, int | None]]:
    out = []
    for heading, text, pid in segments:
        if len(text) <= CHUNK_SIZE:
            out.append((heading, text, pid))
            continue
        paras = re.split(r"\n{2,}|\n(?=[-•*\d])", text)
        buf = ""
        for para in paras:
            if len(buf) + len(para) > CHUNK_SIZE and buf:
                out.append((heading, buf.strip(), pid))
                buf = buf[-CHUNK_OVERLAP:]
            while len(para) > CHUNK_SIZE:
                out.append((heading, (buf + para[:CHUNK_SIZE]).strip(), pid))
                para, buf = para[CHUNK_SIZE - CHUNK_OVERLAP:], ""
            buf += "\n" + para
        if buf.strip():
            out.append((heading, buf.strip(), pid))
    return out


def index_document(doc_id: int, sections: list[tuple[str, str]]) -> dict[int, dict]:
    """Parçaları yeniden oluşturur, proje bağlarını (kod/isim) günceller. Dönüş: bulunan projeler."""
    cat = catalog()
    pieces = chunk(segment(sections, cat))
    found = mentions("\n".join(f"{h}\n{t}" for h, t in sections), cat)
    manual = [r["project_id"] for r in db.rows("SELECT project_id FROM document_links WHERE document_id = ? AND method = 'manuel'", (doc_id,))]
    # Tek projelik dokümanlarda (PDD, kazanım dokümanı…) proje adı geçmeyen bölümler de o projeye aittir.
    total = sum(v["count"] for v in found.values())
    dominant = None
    if len(manual) == 1:
        dominant = manual[0]
    elif found:
        top, info = max(found.items(), key=lambda kv: kv[1]["count"])
        if len(found) == 1 or info["count"] >= 0.7 * total:
            dominant = top
    with db.tx() as c:
        c.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        for i, (heading, text, pid) in enumerate(pieces):
            if pid is None:
                m = mentions(text, cat)
                pid = next(iter(m)) if len(m) == 1 else dominant
            c.execute("INSERT INTO chunks (document_id, seq, heading, project_id, text) VALUES (?, ?, ?, ?, ?)",
                      (doc_id, i, heading or None, pid, text))
    for pid, info in found.items():
        link(doc_id, pid, info["method"], 1.0 if info["method"] == "kod" else 0.8, info["count"])
    return found


def link(doc_id: int, project_id: int, method: str, confidence: float = 1.0, mentions_: int = 0) -> None:
    """Doküman–proje bağı. Manuel bağ otomatik olanla ezilmez."""
    db.execute(
        "INSERT INTO document_links (document_id, project_id, method, confidence, mentions) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(document_id, project_id) DO UPDATE SET "
        "method = CASE WHEN document_links.method = 'manuel' THEN 'manuel' ELSE excluded.method END, "
        "confidence = MAX(document_links.confidence, excluded.confidence), mentions = MAX(document_links.mentions, excluded.mentions)",
        (doc_id, project_id, method, confidence, mentions_))


# ---------------------------------------------------------------- arama

def _fts_query(q: str) -> str | None:
    words = [w for w in re.findall(r"[\wçğıöşüÇĞİÖŞÜ]{3,}", q) if norm(w) not in _STOP]
    if not words:
        return None
    return " OR ".join(f'"{w}"*' if len(w) >= 5 else f'"{w}"' for w in words[:16])


_STOP = {norm(w) for w in "ve veya ile icin için bir bu şu ne nasıl neden hangi mi mı mu mü olan olarak gibi daha çok en de da ki proje projeler projesi".split()}


def search(q: str, limit: int = 12, project_ids: list[int] | None = None, doc_types: list[str] | None = None) -> list[dict]:
    fq = _fts_query(q)
    if not fq:
        return []
    where, params = ["chunks_fts MATCH ?"], [fq]
    if project_ids:
        where.append(f"(c.project_id IN ({','.join('?' * len(project_ids))}) OR c.document_id IN "
                     f"(SELECT document_id FROM document_links WHERE project_id IN ({','.join('?' * len(project_ids))})))")
        params += project_ids + project_ids
    if doc_types:
        where.append(f"d.doc_type IN ({','.join('?' * len(doc_types))})")
        params += doc_types
    try:
        return db.rows(
            "SELECT c.id, c.document_id, c.heading, c.project_id, c.text, d.title, d.doc_type, d.doc_date, d.source, "
            "snippet(chunks_fts, 0, '[[', ']]', ' … ', 24) AS snip, bm25(chunks_fts) AS score "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid JOIN documents d ON d.id = c.document_id "
            f"WHERE {' AND '.join(where)} ORDER BY score LIMIT ?", (*params, limit))
    except Exception:
        return []


def project_chunks(project_id: int, limit: int = 30) -> list[dict]:
    """Bir projeye ait parçalar: önce açıkça projeye etiketli olanlar, yeni dokümandan eskiye."""
    return db.rows(
        "SELECT c.*, d.title, d.doc_type, d.doc_date, d.source FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE c.project_id = ? OR (c.project_id IS NULL AND c.document_id IN "
        "  (SELECT document_id FROM document_links WHERE project_id = ?)) "
        "ORDER BY (c.project_id = ?) DESC, COALESCE(d.doc_date, d.uploaded_at) DESC, c.seq LIMIT ?",
        (project_id, project_id, project_id, limit))


# ---------------------------------------------------------------- bilgiler (facts)

def needs_review(fact_type: str) -> bool:
    return FACT_TYPES.get(fact_type, ("", None))[1] is not None


def add_fact(document_id: int, project_id: int | None, fact_type: str, *, field=None, subfield=None, value_text=None,
             value_num=None, unit=None, as_of=None, confidence=None, evidence=None) -> int | None:
    if fact_type not in FACT_TYPES:
        return None
    if fact_type in FACT_FIELDS and field not in FACT_FIELDS[fact_type]:
        return None
    if fact_type == "kpi" and (not field or subfield not in KPI_PARTS or value_num is None):
        return None
    if fact_type == "saglik" and value_text not in HEALTH:
        return None
    if fact_type == "asama" and value_text not in STAGE_LABELS:
        return None
    if fact_type == "tarih" and not _iso(value_text):
        return None
    if fact_type == "kazanim" and field == "measurement_status":
        if value_text not in MEASUREMENT_LABELS:
            return None
    elif fact_type == "kazanim" and value_num is None:
        return None
    if fact_type == "tarih":
        value_text = _iso(value_text)
    status = "oneri" if needs_review(fact_type) and project_id else "bilgi"
    if status == "oneri" and _already_applied(project_id, fact_type, field, subfield, value_text, value_num):
        status = "bilgi"
    return db.insert("facts", {
        "project_id": project_id, "document_id": document_id, "fact_type": fact_type, "field": field, "subfield": subfield,
        "value_text": (str(value_text)[:4000] if value_text is not None else None), "value_num": value_num, "unit": unit,
        "as_of": _iso(as_of), "confidence": confidence, "evidence": (evidence or "")[:1200] or None,
        "status": status, "created_at": db.now(),
    })


def _iso(v) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
    else:
        m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _already_applied(pid, fact_type, field, subfield, value_text, value_num) -> bool:
    p = db.row("SELECT * FROM projects WHERE id = ?", (pid,))
    if not p:
        return False
    if fact_type == "saglik":
        return p["health"] == value_text
    if fact_type == "asama":
        return p["stage"] == value_text
    if fact_type in ("tarih", "tanim"):
        return str(p.get(field) or "") == str(value_text or "")
    if fact_type == "kazanim":
        return (p.get(field) == value_text) if field == "measurement_status" else (p.get(field) == value_num)
    if fact_type == "kpi":
        k = db.row("SELECT * FROM kpis WHERE project_id = ? AND lower(name) = lower(?)", (pid, field))
        return bool(k) and k.get(subfield) == value_num
    return False


def _tr_date(v) -> str:
    iso = _iso(v)
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso else (v or "—")


def current_value(f: dict) -> str:
    p = db.row("SELECT * FROM projects WHERE id = ?", (f["project_id"],)) if f["project_id"] else None
    if not p:
        return "—"
    t = f["fact_type"]
    if t == "saglik":
        return HEALTH[p["health"]][0]
    if t == "asama":
        return STAGE_LABELS[p["stage"]]
    if t == "kpi":
        k = db.row("SELECT * FROM kpis WHERE project_id = ? AND lower(name) = lower(?)", (p["id"], f["field"]))
        return "KPI tanımlı değil" if not k else ("—" if k[f["subfield"]] is None else f"{k[f['subfield']]:g}")
    if t == "aksiyon":
        return "—"
    v = p.get(f["field"])
    if t == "tarih":
        return _tr_date(v) if v else "—"
    if f["field"] == "measurement_status":
        return MEASUREMENT_LABELS.get(v, "—")
    return "—" if v in (None, "") else (f"{v:,.0f}".replace(",", ".") if isinstance(v, float) and v > 1000 else str(v))


def display_value(f: dict) -> str:
    t = f["fact_type"]
    if t == "saglik":
        return HEALTH.get(f["value_text"], ("?",))[0] + (f" (risk {f['value_num']:.0f})" if f["value_num"] is not None else "")
    if t == "asama":
        return STAGE_LABELS.get(f["value_text"], f["value_text"])
    if t == "kazanim" and f["field"] == "measurement_status":
        return MEASUREMENT_LABELS.get(f["value_text"], f["value_text"])
    if t == "tarih":
        return _tr_date(f["value_text"])
    if f["value_num"] is not None and t in ("kpi", "kazanim"):
        v = f["value_num"]
        s = f"{v:,.0f}".replace(",", ".") if abs(v) >= 1000 else f"{v:g}"
        return f"{s} {f['unit'] or ''}".strip()
    return f["value_text"] or "—"


def field_label(f: dict) -> str:
    t = f["fact_type"]
    if t == "kpi":
        return f"KPI · {f['field']} · {KPI_PARTS.get(f['subfield'], '')}"
    if t in FACT_FIELDS:
        return FACT_FIELDS[t].get(f["field"], f["field"])
    return FACT_TYPES[t][0]


def apply_fact(fact_id: int, user_id: int | None) -> bool:
    f = db.row("SELECT * FROM facts WHERE id = ?", (fact_id,))
    if not f or f["status"] != "oneri" or not f["project_id"]:
        return False
    pid, t, ts = f["project_id"], f["fact_type"], db.now()
    if t == "saglik":
        data = {"health": f["value_text"]}
        if f["value_num"] is not None:
            data["ai_risk_score"] = int(f["value_num"])
        if f["evidence"]:
            data["ai_risk_note"] = f["evidence"]
        db.update("projects", pid, {**data, "updated_at": ts})
    elif t == "asama":
        old = db.scalar("SELECT stage FROM projects WHERE id = ?", (pid,))
        db.update("projects", pid, {"stage": f["value_text"], "updated_at": ts})
        db.insert("stage_history", {"project_id": pid, "from_stage": old, "to_stage": f["value_text"],
                                    "note": f"Dokümandan (#{f['document_id']}) onaylandı", "user_id": user_id, "at": ts})
    elif t in ("tarih", "tanim"):
        db.update("projects", pid, {f["field"]: f["value_text"], "updated_at": ts})
    elif t == "kazanim":
        val = f["value_text"] if f["field"] == "measurement_status" else f["value_num"]
        db.update("projects", pid, {f["field"]: val, "updated_at": ts})
    elif t == "kpi":
        k = db.row("SELECT * FROM kpis WHERE project_id = ? AND lower(name) = lower(?)", (pid, f["field"]))
        data = {f["subfield"]: f["value_num"]}
        if f["subfield"] == "actual":
            data["measured_at"] = f["as_of"] or date.today().isoformat()
        if k:
            db.update("kpis", k["id"], data)
        else:
            db.insert("kpis", {"project_id": pid, "name": f["field"], "unit": f["unit"], **data})
        bump_measurement(pid)
    elif t == "aksiyon":
        db.insert("actions", {"project_id": pid, "title": f["value_text"][:300], "owner": f["unit"], "due_date": f["as_of"],
                              "status": "acik", "source": "Doküman", "source_document_id": f["document_id"],
                              "created_by": user_id, "created_at": ts})
    db.update("facts", fact_id, {"status": "onaylandi", "reviewed_by": user_id, "reviewed_at": ts})
    if t != "aksiyon":  # aynı alana dair bekleyen diğer önerileri kapat
        db.execute("UPDATE facts SET status = 'atlandi', reviewed_by = ?, reviewed_at = ? WHERE status = 'oneri' AND id != ? "
                   "AND project_id = ? AND fact_type = ? AND COALESCE(field, '') = COALESCE(?, '') AND COALESCE(subfield, '') = COALESCE(?, '')",
                   (user_id, ts, fact_id, pid, t, f["field"], f["subfield"]))
    db.log(user_id, "fact_applied", "project", pid, f"{field_label(f)} → {display_value(f)}")
    return True


def reject_fact(fact_id: int, user_id: int | None) -> None:
    db.execute("UPDATE facts SET status = 'reddedildi', reviewed_by = ?, reviewed_at = ? WHERE id = ? AND status = 'oneri'",
               (user_id, db.now(), fact_id))


def bump_measurement(pid: int) -> None:
    """KPI verisi girildikçe ölçümleme durumunu ilerletir (geri almaz; 'doğrulandı' insan kararıdır)."""
    p = db.row("SELECT measurement_status FROM projects WHERE id = ?", (pid,))
    kpis = db.rows("SELECT * FROM kpis WHERE project_id = ?", (pid,))
    level = "yok"
    if kpis:
        level = "planlandi"
    if any(k["baseline"] is not None for k in kpis):
        level = "baseline"
    if any(k["actual"] is not None for k in kpis):
        level = "olculuyor"
    if p and MEASUREMENT_RANK[level] > MEASUREMENT_RANK[p["measurement_status"]]:
        db.update("projects", pid, {"measurement_status": level})


def pending(project_id: int | None = None) -> list[dict]:
    where, params = "f.status = 'oneri'", []
    if project_id:
        where += " AND f.project_id = ?"
        params.append(project_id)
    out = db.rows("SELECT f.*, p.code, p.name AS pname, d.title AS dtitle, d.doc_type, d.doc_date, d.source "
                  f"FROM facts f JOIN projects p ON p.id = f.project_id JOIN documents d ON d.id = f.document_id WHERE {where} "
                  "ORDER BY p.code, f.fact_type, f.field, COALESCE(f.as_of, d.doc_date) DESC", tuple(params))
    for f in out:
        f["label"], f["display"], f["current"] = field_label(f), display_value(f), current_value(f)
    return out


def conflicts(project_id: int | None = None) -> list[dict]:
    """Aynı proje alanı için farklı dokümanların farklı değer verdiği durumlar (onaylı + bekleyen)."""
    where = ("f.status IN ('oneri', 'onaylandi', 'bilgi') AND (f.fact_type IN ('tarih', 'kazanim', 'kpi', 'asama') "
             "OR (f.fact_type = 'tanim' AND f.field IN ('sponsor', 'owner', 'dt_lead', 'data_class', 'security_review')))")
    params = []
    if project_id:
        where += " AND f.project_id = ?"
        params.append(project_id)
    facts = db.rows("SELECT f.*, p.code, p.name AS pname, d.title AS dtitle, d.doc_type, d.doc_date, d.source FROM facts f "
                    "JOIN projects p ON p.id = f.project_id JOIN documents d ON d.id = f.document_id "
                    f"WHERE {where}", tuple(params))
    groups: dict[tuple, list] = {}
    for f in facts:
        groups.setdefault((f["project_id"], f["fact_type"], f["field"], f["subfield"]), []).append(f)
    out = []
    for key, fs in groups.items():
        values = {}
        for f in fs:
            v = f["value_num"] if f["value_num"] is not None else norm(f["value_text"] or "")
            values.setdefault(v, []).append(f)
        docs = {f["document_id"] for f in fs}
        if len(values) > 1 and len(docs) > 1:
            for f in fs:
                f["display"] = display_value(f)
            out.append({"project_id": key[0], "code": fs[0]["code"], "pname": fs[0]["pname"], "label": field_label(fs[0]),
                        "facts": sorted(fs, key=lambda f: f["doc_date"] or "", reverse=True)})
    return out


def project_facts(project_id: int, limit: int = 200) -> list[dict]:
    out = db.rows("SELECT f.*, d.title AS dtitle, d.doc_type, d.doc_date, d.source FROM facts f JOIN documents d ON d.id = f.document_id "
                  "WHERE f.project_id = ? AND f.status != 'reddedildi' ORDER BY COALESCE(f.as_of, d.doc_date, d.uploaded_at) DESC, f.id DESC LIMIT ?",
                  (project_id, limit))
    for f in out:
        f["label"], f["display"] = field_label(f), display_value(f)
    return out


def facts_json(project_id: int, limit: int = 120) -> str:
    """AI sentezine verilecek, kaynak etiketli bilgi listesi."""
    rows = project_facts(project_id, limit)
    return json.dumps([{"kaynak": f"D{f['document_id']}", "doküman_türü": f["doc_type"], "tarih": f["as_of"] or f["doc_date"],
                        "tür": f["fact_type"], "alan": f["label"], "değer": f["display"], "durum": f["status"],
                        "alıntı": (f["evidence"] or "")[:300]} for f in rows], ensure_ascii=False)
