"""Trello panosu JSON dışa aktarımından (Menü → Yazdır ve dışa aktar → JSON) proje içe aktarma."""
import json
import re

from . import db

_STAGE_HINTS = [
    ("olcekleme", ("ölçek", "olcek", "yaygın", "scale")),
    ("canli", ("canlı", "canli", "live", "prod", "tamamlan", "done")),
    ("pilot", ("pilot", "poc", "test", "uat")),
    ("gelistirme", ("geliştir", "gelistir", "devam", "doing", "progress", "development")),
    ("onay", ("onay", "plan", "approved")),
    ("analiz", ("analiz", "değerlendir", "backlog", "review")),
    ("beklemede", ("bekle", "hold", "askı")),
    ("iptal", ("iptal", "cancel", "kapat")),
    ("fikir", ("fikir", "talep", "idea", "todo", "yapılacak")),
]


def guess_stage(list_name: str) -> str:
    low = list_name.lower()
    for stage, words in _STAGE_HINTS:
        if any(w in low for w in words):
            return stage
    return "fikir"


def preview(raw: str) -> dict:
    data = json.loads(raw)
    lists = {l["id"]: l for l in data.get("lists", []) if not l.get("closed")}
    cards = [c for c in data.get("cards", []) if not c.get("closed") and c.get("idList") in lists]
    return {
        "board": data.get("name", "Trello"),
        "lists": [{"id": l["id"], "name": l["name"], "stage": guess_stage(l["name"]),
                   "count": sum(1 for c in cards if c["idList"] == l["id"])} for l in lists.values()],
        "card_count": len(cards),
    }


def import_board(raw: str, stage_map: dict[str, str], user_id: int) -> int:
    data = json.loads(raw)
    lists = {l["id"]: l for l in data.get("lists", []) if not l.get("closed")}
    members = {m["id"]: m.get("fullName") for m in data.get("members", [])}
    comments: dict[str, list] = {}
    for a in data.get("actions", []):
        if a.get("type") == "commentCard":
            cid = a.get("data", {}).get("card", {}).get("id")
            comments.setdefault(cid, []).append(a)
    existing = {r["trello_id"] for r in db.rows("SELECT trello_id FROM projects WHERE trello_id IS NOT NULL")}
    n_codes = db.scalar("SELECT COUNT(*) FROM projects") or 0
    imported = 0
    for card in data.get("cards", []):
        if card.get("closed") or card.get("idList") not in lists or card["id"] in existing:
            continue
        n_codes += 1
        code = f"AI-{n_codes:03d}"
        while db.scalar("SELECT 1 FROM projects WHERE code = ?", (code,)):
            n_codes += 1
            code = f"AI-{n_codes:03d}"
        labels = [l.get("name") for l in card.get("labels", []) if l.get("name")]
        health = "kirmizi" if any(re.search(r"risk|kırmızı|acil", l, re.I) for l in labels) else "yesil"
        owner = ", ".join(filter(None, (members.get(m) for m in card.get("idMembers", []))))
        ts = db.now()
        pid = db.insert("projects", {
            "code": code, "name": card["name"][:200], "summary": card.get("desc") or "",
            "stage": stage_map.get(card["idList"], guess_stage(lists[card["idList"]]["name"])),
            "health": health, "owner": owner or None,
            "target_date": (card.get("due") or "")[:10] or None,
            "brands": ", ".join(labels) or None, "trello_id": card["id"],
            "created_at": ts, "updated_at": ts,
        })
        for a in reversed(comments.get(card["id"], [])):
            author = a.get("memberCreator", {}).get("fullName", "Trello")
            db.insert("comments", {
                "target_type": "project", "target_id": pid, "user_id": user_id,
                "body": f"**{author}** (Trello, {a.get('date', '')[:10]}): {a['data'].get('text', '')}",
                "kind": "trello", "created_at": a.get("date", ts)[:19],
            })
        for url in (att.get("url") for att in card.get("attachments", []) if att.get("url")):
            db.insert("comments", {"target_type": "project", "target_id": pid, "user_id": user_id,
                                   "body": f"Trello eki: {url}", "kind": "trello", "created_at": ts})
        imported += 1
    db.log(user_id, "trello_import", detail=f"{imported} kart içe aktarıldı")
    return imported
