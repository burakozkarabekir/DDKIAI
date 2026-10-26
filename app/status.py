"""Elle girilen proje durum güncellemeleri.

Bir güncelleme; sağlık, aşama, ilerleme %, özet, engel, sonraki adım ve (değiştiyse) hedef tarihi içerir.
Kaydedildiğinde projenin ilgili alanları güncellenir, aşama değiştiyse tarihçeye işlenir ve güncelleme
projenin bilgi akışında ve AI bağlamında (sentez, haftalık yorum, danışman) dokümanlardan gelen bilgilerle
birlikte yer alır.
"""
from . import db
from .domain import HEALTH, STAGE_LABELS


def record(pid: int, user_id: int | None, *, health=None, stage=None, progress=None, summary=None, blockers=None,
           next_steps=None, target_date=None) -> int | None:
    p = db.row("SELECT * FROM projects WHERE id = ?", (pid,))
    if not p:
        return None
    health = health if health in HEALTH else None
    stage = stage if stage in STAGE_LABELS else None
    try:
        progress = max(0, min(100, int(progress))) if progress not in (None, "") else None
    except (TypeError, ValueError):
        progress = None
    clean = lambda v: (str(v).strip()[:4000] or None) if v is not None else None  # noqa: E731
    summary, blockers, next_steps = clean(summary), clean(blockers), clean(next_steps)
    target_date = (str(target_date).strip() or None) if target_date else None
    changed = any([summary, blockers, next_steps, progress is not None,
                   health and health != p["health"], stage and stage != p["stage"],
                   target_date and target_date != p["target_date"]])
    if not changed:
        return None
    ts = db.now()
    sid = db.insert("status_updates", {"project_id": pid, "stage": stage or p["stage"], "health": health or p["health"],
                                       "progress": progress, "summary": summary, "blockers": blockers, "next_steps": next_steps,
                                       "target_date": target_date, "user_id": user_id, "created_at": ts})
    data = {"last_status_at": ts, "updated_at": ts}
    if health:
        data["health"] = health
    if target_date:
        data["target_date"] = target_date
    if stage and stage != p["stage"]:
        data["stage"] = stage
        db.insert("stage_history", {"project_id": pid, "from_stage": p["stage"], "to_stage": stage, "note": "Durum güncellemesi",
                                    "user_id": user_id, "at": ts})
        if stage in ("canli", "olcekleme") and not p["golive_date"]:
            data["golive_date"] = ts[:10]
        if stage in ("gelistirme", "pilot") and not p["start_date"]:
            data["start_date"] = ts[:10]
    db.update("projects", pid, data)
    db.log(user_id, "status_updated", "project", pid, summary[:80] if summary else HEALTH.get(health or p["health"], ("",))[0])
    return sid


def latest(pid: int) -> dict | None:
    return db.row("SELECT s.*, u.name AS uname FROM status_updates s LEFT JOIN users u ON u.id = s.user_id "
                  "WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (pid,))


def history(pid: int, limit: int = 50) -> list[dict]:
    return db.rows("SELECT s.*, u.name AS uname FROM status_updates s LEFT JOIN users u ON u.id = s.user_id "
                   "WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT ?", (pid, limit))


def latest_by_project() -> dict[int, dict]:
    rows = db.rows("SELECT s.* FROM status_updates s JOIN (SELECT project_id, MAX(id) AS mid FROM status_updates GROUP BY project_id) m "
                   "ON m.mid = s.id")
    return {r["project_id"]: r for r in rows}


def as_text(s: dict) -> str:
    parts = [f"sağlık {HEALTH.get(s['health'], ('?',))[0]}", f"aşama {STAGE_LABELS.get(s['stage'], s['stage'])}"]
    if s.get("progress") is not None:
        parts.append(f"ilerleme %{s['progress']}")
    text = f"[Manuel durum {s['created_at'][:10]}] " + ", ".join(parts)
    for label, key in (("Özet", "summary"), ("Engel", "blockers"), ("Sonraki", "next_steps"), ("Yeni hedef", "target_date")):
        if s.get(key):
            text += f" · {label}: {s[key]}"
    return text
