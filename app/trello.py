"""Trello panosu JSON dışa aktarımından proje içe aktarma.

Trello'da: Pano menüsü → Yazdır, dışa aktar ve paylaş → JSON olarak dışa aktar.

Aktarılanlar
- Kart adı: "UC88-YP Lojistik-Spare Parts Demand Forecasting" → kod UC88, birim "YP Lojistik", ad "Spare Parts…"
  "UC32 & UC43-…" → kod UC32, diğer adlara UC43 · "… Faz2" → kod UC57-F2 · kodsuz kartlar → PRJ-001…
- Birim: departmana eşlenir (önizlemede seçilir) ya da marka ise (VW Binek, Audi, Scania…) marka alanına yazılır
- Liste → aşama (önizlemede seçilir; "Aktarma" seçilen listeler atlanır)
- Liste değişiklikleri → aşama tarihçesi; ilk "devam eden" listeye giriş → başlangıç, "tamamlandı" listesine giriş → canlıya geçiş
  (Trello'da hareket kaydı olmayan kartların başlangıç tarihi boş kalır; uydurulmaz.)
- Bitiş tarihi (due) → hedef tarih · etiketler → etiketler · üyeler → DO sorumlusu · açıklama → özet/çözüm
- Yorumlar → yorum · checklist maddeleri → aksiyon · ekler → yorum (link)
Yeniden aktarımda Trello kart kimliğiyle eşleşen projeler güncellenir, yorum ve aksiyonlar tekrar eklenmez.
"""
import json
import re
from datetime import datetime, timezone

from . import db
from .knowledge import norm

SKIP = "atla"

_STAGE_HINTS = [
    (SKIP, ("champion", "platformu listesi", "platform listesi", "şablon", "template", "bilgilendirme")),
    ("analiz", ("fayda", "maliyet", "ölçümlen", "ön değerlendirme", "on degerlendirme", "değerlendir")),
    ("beklemede", ("hold", "bekle", "askı", "tekrar değerlendir", "tekrar degerlendir")),
    ("iptal", ("iptal", "cancel", "kapatıl", "reddedil")),
    ("olcekleme", ("ölçek", "olcek", "yaygın", "scale")),
    ("canli", ("done", "maintenance", "canlı", "canli", "live", "prod", "tamamlan")),
    ("pilot", ("pilot", "poc", "uat", "test")),
    ("gelistirme", ("inprogress", "in progress", "geliştir", "gelistir", "devam", "doing", "development")),
    ("onay", ("refinement", "backlog", "onay", "plan", "approved")),
    ("fikir", ("iş listesi", "is listesi", "fikir", "talep", "idea", "todo", "yapılacak")),
]

# Birim adı → varsayılan departman (Ayarlar'daki adlarla). Bulunamayan birim için yeni departman önerilir.
_DEPT_SYNONYMS = {
    "yp lojistik": "Yedek Parça & Lojistik", "yedek parca": "Yedek Parça & Lojistik", "lojistik": "Yedek Parça & Lojistik",
    "ik": "İnsan Kaynakları", "insan kaynaklari": "İnsan Kaynakları",
    "hukuk": "Hukuk & Uyum", "uyum": "Hukuk & Uyum",
    "ssh": "Satış Sonrası Hizmetler", "satis sonrasi": "Satış Sonrası Hizmetler",
    "dim": "Müşteri Deneyimi & CRM", "crm": "Müşteri Deneyimi & CRM",
    "mali isler": "Finans", "finans": "Finans", "muhasebe": "Finans",
    "pazarlama": "Pazarlama", "satin alma": "Satın Alma", "satis": "Satış",
    "filo": "Filo Kiralama", "bt": "Bilgi Teknolojileri & Güvenlik",
}
_BRANDS = {"vw binek", "vw ticari", "volkswagen", "seat&cupra", "seat & cupra", "seat", "cupra", "audi", "porsche", "scania",
           "skoda", "bentley", "lamborghini", "man", "dod", "dogus oto", "vw"}

_CODE_RE = re.compile(r"^\s*(UC)\s*0*(\d+)((?:\s*&\s*UC\s*\d+)*)\s*[-–:]?\s*(.*)$", re.I | re.S)


def guess_stage(list_name: str) -> str:
    low = norm(list_name)
    for stage, words in _STAGE_HINTS:
        if any(norm(w) in low for w in words):
            return stage
    return "fikir"


def _ts(card_id: str) -> str | None:
    """Trello kimliğinin ilk 8 hanesi oluşturulma zamanıdır."""
    try:
        return datetime.fromtimestamp(int(card_id[:8], 16), tz=timezone.utc).date().isoformat()
    except (ValueError, TypeError):
        return None


def parse_name(name: str) -> dict:
    """Kart adını kod, ek kodlar, birim ve başlığa ayırır."""
    name = re.sub(r"\s+", " ", name).strip()
    code, extra, rest = None, [], name
    m = _CODE_RE.match(name)
    if m:
        code = f"UC{int(m.group(2)):02d}"
        extra = [f"UC{int(x):02d}" for x in re.findall(r"UC\s*(\d+)", m.group(3) or "", re.I)]
        rest = m.group(4).strip()
    unit, title = None, rest
    m2 = re.match(r"^([^-–]{2,30}?)\s*([-–]{1,2})\s*(.+)$", rest)
    if m2 and m2.group(2) != "--":
        cand, tail = m2.group(1).strip(), m2.group(3).strip(" -–")
        if len(tail) >= 6 and not cand.startswith("(") and _looks_like_unit(cand):
            unit, title = cand, tail
    phase = re.search(r"\bfaz\s*(\d)\b", name, re.I)
    return {"code": code, "extra": extra, "unit": unit, "title": title or name, "phase": phase.group(1) if phase else None}


def _looks_like_unit(cand: str) -> bool:
    """"VW Binek", "İK", "Bayi Geliştirme" birimdir; "Micro-Segment" gibi tireli kelimeler değildir."""
    words = cand.split()
    if not 1 <= len(words) <= 3:
        return False
    if classify_unit(cand, {})[0] in ("brand", "dept"):
        return True
    if len(words) == 1:
        return cand.isupper() and len(cand) <= 6  # DİM, DMS, SSH gibi kısaltmalar
    return len(words) == 2 and all(w[:1].isupper() for w in words)


def classify_unit(unit: str | None, departments: dict[str, int]) -> tuple[str, str | None]:
    """Dönüş: ("brand", None) | ("dept", departman_adı) | ("new", None)"""
    if not unit:
        return "none", None
    n = norm(unit)
    if n in _BRANDS or any(n.startswith(b + " ") for b in _BRANDS):
        return "brand", None
    for key, dept in _DEPT_SYNONYMS.items():
        if n == key or n.startswith(key + " "):
            return "dept", dept
    for dname in departments:
        if norm(dname) == n:
            return "dept", dname
    return "new", None


def _load(raw: str) -> dict:
    data = json.loads(raw)
    if not isinstance(data, dict) or "cards" not in data or "lists" not in data:
        raise KeyError("cards")
    return data


def preview(raw: str) -> dict:
    data = _load(raw)
    lists = {l["id"]: l for l in data["lists"] if not l.get("closed")}
    cards = [c for c in data["cards"] if not c.get("closed") and c.get("idList") in lists]
    deps = {d["name"]: d["id"] for d in db.rows("SELECT id, name FROM departments")}
    units: dict[str, dict] = {}
    codes: dict[str, list] = {}
    for c in cards:
        p = parse_name(c["name"])
        if p["unit"]:
            u = units.setdefault(p["unit"], {"name": p["unit"], "count": 0})
            u["count"] += 1
        if p["code"]:
            codes.setdefault(p["code"], []).append(f"{c['name'][:60]} ({lists[c['idList']]['name']})")
    for u in units.values():
        kind, dept = classify_unit(u["name"], deps)
        u["kind"], u["dept"] = kind, dept
    existing = {r["trello_id"] for r in db.rows("SELECT trello_id FROM projects WHERE trello_id IS NOT NULL")}
    return {
        "board": data.get("name", "Trello"),
        "lists": [{"id": l["id"], "name": l["name"], "stage": guess_stage(l["name"]),
                   "count": sum(1 for c in cards if c["idList"] == l["id"])} for l in lists.values()],
        "card_count": len(cards),
        "existing": sum(1 for c in cards if c["id"] in existing),
        "units": sorted(units.values(), key=lambda u: -u["count"]),
        "duplicates": {k: v for k, v in codes.items() if len(v) > 1},
        "departments": sorted(deps),
        "comments": sum(1 for a in data.get("actions", []) if a.get("type") == "commentCard"),
        "moves": sum(1 for a in data.get("actions", []) if a.get("type") == "updateCard" and "listAfter" in a.get("data", {})),
    }


def _unique_code(base: str, phase: str | None, taken: set[str]) -> str:
    code = f"{base}-F{phase}" if phase else base
    n = 2
    candidate = code
    while candidate in taken:
        candidate = f"{code}-{n}"
        n += 1
    taken.add(candidate)
    return candidate


def import_board(raw: str, stage_map: dict[str, str], unit_map: dict[str, str], user_id: int, update_existing: bool = True) -> dict:
    """unit_map: {birim: departman_id | "yeni" | "marka" | ""}"""
    data = _load(raw)
    lists = {l["id"]: l for l in data["lists"]}
    members = {m["id"]: m.get("fullName") for m in data.get("members", [])}
    labels = {l["id"]: l.get("name") for l in data.get("labels", [])}
    checklists = {c["id"]: c for c in data.get("checklists", [])}
    comments: dict[str, list] = {}
    moves: dict[str, list] = {}
    for a in data.get("actions", []):
        cid = a.get("data", {}).get("card", {}).get("id")
        if a.get("type") == "commentCard":
            comments.setdefault(cid, []).append(a)
        elif a.get("type") == "updateCard" and "listAfter" in a.get("data", {}):
            moves.setdefault(cid, []).append(a)
    for v in moves.values():
        v.sort(key=lambda a: a["date"])

    dept_ids = {d["name"]: d["id"] for d in db.rows("SELECT id, name FROM departments")}

    def department_for(unit: str | None) -> tuple[int | None, bool]:
        """Dönüş: (departman_id, birim_marka_mı)"""
        if not unit:
            return None, False
        choice = unit_map.get(unit, "")
        if choice == "marka":
            return None, True
        if choice == "yeni":
            if unit not in dept_ids:
                dept_ids[unit] = db.insert("departments", {"name": unit[:120], "description": "Trello'dan oluşturuldu",
                                                           "sort": len(dept_ids), "active": 1})
            return dept_ids[unit], False
        if str(choice).isdigit():
            return int(choice), False
        return None, False

    by_trello = {r["trello_id"]: r for r in db.rows("SELECT * FROM projects WHERE trello_id IS NOT NULL")}
    taken = {r["code"] for r in db.rows("SELECT code FROM projects")}
    seq = 1 + max([int(m.group(1)) for c in taken if (m := re.match(r"PRJ-(\d+)$", c))] or [0])
    stats = {"created": 0, "updated": 0, "skipped": 0, "comments": 0, "actions": 0, "history": 0}
    today = datetime.now().date().isoformat()
    ts_now = db.now()

    rank = {k: i for i, k in enumerate(["iptal", "fikir", "beklemede", "analiz", "onay", "gelistirme", "pilot", "canli", "olcekleme"])}

    def card_rank(c):
        lst_ = lists.get(c.get("idList"))
        st = stage_map.get(c.get("idList"), guess_stage(lst_["name"]) if lst_ else SKIP)
        return -rank.get(st, -1)

    for card in sorted(data["cards"], key=card_rank):
        lst = lists.get(card.get("idList"))
        stage = stage_map.get(card.get("idList"), guess_stage(lst["name"]) if lst else SKIP)
        if card.get("closed") or not lst or lst.get("closed") or stage == SKIP:
            stats["skipped"] += 1
            continue
        p = parse_name(card["name"])
        unit_dept, is_brand = department_for(p["unit"])
        tags = [labels.get(i) for i in card.get("idLabels", []) if labels.get(i)]
        owner = ", ".join(filter(None, (members.get(m) for m in card.get("idMembers", []))))
        desc = (card.get("desc") or "").strip()
        card_moves = moves.get(card["id"], [])
        stage_of = lambda lid: stage_map.get(lid, guess_stage(lists[lid]["name"]) if lid in lists else SKIP)  # noqa: E731
        start = (card.get("start") or "")[:10] or next(
            (a["date"][:10] for a in card_moves if stage_of(a["data"]["listAfter"]["id"]) in ("gelistirme", "pilot")), None)
        due = (card.get("due") or "")[:10] or None
        golive = None
        if stage in ("canli", "olcekleme"):
            golive = (card.get("dateCompleted") or "")[:10] or next(
                (a["date"][:10] for a in reversed(card_moves) if stage_of(a["data"]["listAfter"]["id"]) in ("canli", "olcekleme")), None) \
                or (due if due and due <= today else None)
        aliases = list(p["extra"])
        if p["code"] and p["title"] != card["name"]:
            aliases.append(p["title"][:120])
        fields = {
            "name": (p["title"] if p["code"] else card["name"])[:200],
            "aliases": ", ".join(dict.fromkeys(a for a in aliases if a)) or None,
            "summary": (re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0][:400] if desc else None),
            "solution": desc[:8000] or None,
            "business_unit": p["unit"], "brands": p["unit"] if is_brand else None,
            "department_id": unit_dept, "stage": stage, "owner": owner or None,
            "start_date": start, "target_date": due, "golive_date": golive,
            "tags": ", ".join(tags) or None,
            "health": "sari" if any(norm(t) == "dependent" for t in tags) else "yesil",
        }
        existing = by_trello.get(card["id"])
        if existing:
            if not update_existing:
                stats["skipped"] += 1
                continue
            # Elle girilmiş alanları ezme: yalnızca Trello'nun sahibi olduğu alanları güncelle
            upd = {k: v for k, v in fields.items() if k in ("name", "stage", "target_date", "tags", "owner") and v is not None}
            for k in ("start_date", "golive_date", "department_id", "brands", "business_unit", "solution", "summary", "aliases"):
                if fields[k] and not existing.get(k):
                    upd[k] = fields[k]
            if upd.get("stage") and upd["stage"] != existing["stage"]:
                db.insert("stage_history", {"project_id": existing["id"], "from_stage": existing["stage"], "to_stage": upd["stage"],
                                            "note": "Trello aktarımı", "user_id": user_id, "at": ts_now})
            db.update("projects", existing["id"], {**upd, "updated_at": ts_now})
            pid = existing["id"]
            stats["updated"] += 1
        else:
            if p["code"]:
                code = _unique_code(p["code"], p["phase"], taken)
            else:
                code = f"PRJ-{seq:03d}"
                seq += 1
                taken.add(code)
            created = _ts(card["id"]) or today
            pid = db.insert("projects", {**fields, "code": code, "trello_id": card["id"], "created_at": created + "T09:00:00",
                                         "updated_at": ts_now})
            stats["created"] += 1
            db.insert("stage_history", {"project_id": pid, "from_stage": None, "to_stage": "fikir", "note": "Trello kartı oluşturuldu",
                                        "user_id": user_id, "at": created + "T09:00:00"})
            prev = None
            for a in card_moves:
                to = stage_of(a["data"]["listAfter"]["id"])
                if to == SKIP or to == prev:
                    continue
                frm = stage_of(a["data"]["listBefore"]["id"]) if a["data"].get("listBefore") else None
                db.insert("stage_history", {"project_id": pid, "from_stage": None if frm == SKIP else frm, "to_stage": to,
                                            "note": f"Trello: {a['data']['listBefore']['name']} → {a['data']['listAfter']['name']}",
                                            "user_id": user_id, "at": a["date"][:19]})
                prev = to
                stats["history"] += 1
            if not card_moves and stage != "fikir":
                db.insert("stage_history", {"project_id": pid, "from_stage": "fikir", "to_stage": stage,
                                            "note": f"Trello listesi: {lst['name']}", "user_id": user_id, "at": ts_now})
        stats["comments"] += _import_comments(pid, card, comments.get(card["id"], []), user_id)
        stats["actions"] += _import_checklists(pid, card, checklists, user_id)
    db.log(user_id, "trello_import", detail=json.dumps(stats, ensure_ascii=False))
    return stats


def _import_comments(pid: int, card: dict, acts: list, user_id: int) -> int:
    have = {r["body"] for r in db.rows("SELECT body FROM comments WHERE target_type = 'project' AND target_id = ?", (pid,))}
    n = 0
    for a in sorted(acts, key=lambda a: a["date"]):
        author = a.get("memberCreator", {}).get("fullName", "Trello")
        body = f"**{author}** (Trello, {a['date'][:10]}): {a['data'].get('text', '').strip()}"
        if body not in have:
            db.insert("comments", {"target_type": "project", "target_id": pid, "user_id": user_id, "body": body, "kind": "trello",
                                   "created_at": a["date"][:19]})
            n += 1
    for att in card.get("attachments") or []:
        if att.get("url"):
            body = f"Trello eki: [{att.get('name') or 'dosya'}]({att['url']})"
            if body not in have:
                db.insert("comments", {"target_type": "project", "target_id": pid, "user_id": user_id, "body": body, "kind": "trello",
                                       "created_at": (att.get("date") or db.now())[:19]})
                n += 1
    return n


def _import_checklists(pid: int, card: dict, checklists: dict, user_id: int) -> int:
    have = {r["title"] for r in db.rows("SELECT title FROM actions WHERE project_id = ?", (pid,))}
    n = 0
    for cid in card.get("idChecklists", []):
        ch = checklists.get(cid)
        for item in (ch or {}).get("checkItems", []):
            title = f"{item['name'].strip()}" + (f" ({ch['name']})" if ch.get("name") and ch["name"] != "Checklist" else "")
            if not item["name"].strip() or title in have:
                continue
            done = item.get("state") == "complete"
            db.insert("actions", {"project_id": pid, "title": title[:300], "due_date": (item.get("due") or "")[:10] or None,
                                  "status": "kapali" if done else "acik", "source": "Trello checklist", "created_by": user_id,
                                  "created_at": db.now(), "closed_at": db.now() if done else None})
            n += 1
    return n
