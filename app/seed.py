"""Kurulum: ortak kullanıcılar, eski demo verisinin temizlenmesi ve tam sıfırlama.

Uygulama hiçbir örnek (demo) veri yüklemez: ekranda yalnızca sizin yüklediğiniz dokümanlardan, Trello
aktarımından ve elle girdiğiniz kayıtlardan gelen veriler görünür. Eski sürümlerin yüklediği demo kayıtları
ilk açılışta otomatik silinir (purge_legacy_demo).
"""
import os

from . import db
from .auth import TEAM_EMAIL, hash_password
from .legacy_demo import (DEMO_COMMENTS, DEMO_DEPARTMENTS, DEMO_FILES, DEMO_INITIATIVES, DEMO_PAIN_POINTS, DEMO_PROJECTS,
                          DEMO_TRENDS)


def ensure_users() -> None:
    """Ortak ekip kullanıcısı (giriş kapalıyken kullanılır) ve ilk yönetici."""
    if not db.scalar("SELECT 1 FROM users WHERE email = ?", (TEAM_EMAIL,)):
        db.insert("users", {"email": TEAM_EMAIL, "name": "Dijital Dönüşüm Ekibi", "role": "admin", "title": "Ortak hesap",
                            "password_hash": hash_password(os.urandom(16).hex()), "created_at": db.now()})
    if not db.scalar("SELECT 1 FROM users WHERE role = 'admin' AND email != ?", (TEAM_EMAIL,)):
        db.insert("users", {"email": os.getenv("ADMIN_EMAIL", "admin@demo.local"), "name": "Sistem Yöneticisi", "role": "admin",
                            "title": "Admin", "password_hash": hash_password(os.getenv("ADMIN_PASSWORD", "Admin123!")),
                            "created_at": db.now()})


def demo_present() -> bool:
    return bool(db.scalar("SELECT 1 FROM projects WHERE trello_id IS NULL AND code = ? AND name = ?", tuple(DEMO_PROJECTS[0])))


def purge_legacy_demo(user_id: int | None = None) -> dict | None:
    """Eski sürümlerin demo kayıtlarını bir kez siler. Kullanıcının eklediği her şey korunur."""
    if db.setting("demo_purged_v3") == "1":
        return None
    stats = clear_demo(user_id)
    db.execute("DELETE FROM users WHERE email LIKE '%@demo.local' AND role != 'admin' "
               "AND id NOT IN (SELECT user_id FROM comments)")
    db.set_setting("demo_purged_v3", "1")
    return stats


def clear_demo(user_id: int | None = None) -> dict:
    """Yalnızca demo kayıtlarını siler; kullanıcının eklediği proje, doküman ve metrikler korunur."""
    from .storage import path_of
    stats = {}
    codes = [p[0] for p in DEMO_PROJECTS]
    names = [p[1] for p in DEMO_PROJECTS]
    demo_pids = [r["id"] for r in db.rows(
        f"SELECT id FROM projects WHERE trello_id IS NULL AND code IN ({','.join('?' * len(codes))}) AND name IN ({','.join('?' * len(names))})",
        tuple(codes) + tuple(names))]
    docs = db.rows("SELECT id, storage_path, sha256 FROM documents WHERE filename IN ({}) OR filename LIKE 'DT Haftalık Durum Raporu 20__-__-__.%'"
                   .format(",".join("?" * len(DEMO_FILES))), tuple(DEMO_FILES))
    for d in docs:
        db.execute("DELETE FROM documents WHERE id = ?", (d["id"],))
        p = path_of(d["storage_path"])
        if p and not db.scalar("SELECT 1 FROM documents WHERE sha256 = ?", (d["sha256"],)):
            p.unlink(missing_ok=True)
    stats["doküman"] = len(docs)
    if demo_pids:
        marks = ",".join("?" * len(demo_pids))
        db.execute(f"DELETE FROM comments WHERE target_type = 'project' AND target_id IN ({marks})", tuple(demo_pids))
        db.execute(f"DELETE FROM projects WHERE id IN ({marks})", tuple(demo_pids))
    stats["proje"] = len(demo_pids)
    for body in DEMO_COMMENTS:
        db.execute("DELETE FROM comments WHERE body = ?", (body,))
    keep = {r["target_id"] for r in db.rows("SELECT DISTINCT target_id FROM comments WHERE target_type = 'initiative'")}
    keep |= {r["initiative_id"] for r in db.rows("SELECT DISTINCT initiative_id FROM documents WHERE initiative_id IS NOT NULL")}
    removed = 0
    for r in db.rows(f"SELECT id FROM initiatives WHERE slug IN ({','.join('?' * len(DEMO_INITIATIVES))})", tuple(DEMO_INITIATIVES)):
        if r["id"] not in keep:
            db.execute("DELETE FROM initiatives WHERE id = ?", (r["id"],))
            removed += 1
    stats["girişim"] = removed
    for metric, vals in DEMO_TRENDS.items():  # değeri demo serisiyle aynı ve elle girilmemiş metrikler
        for v in vals:
            db.execute("DELETE FROM security_metrics WHERE metric = ? AND value = ? AND note IS NULL", (metric, v))
    db.execute("DELETE FROM ai_insights WHERE project_id IS NULL OR project_id NOT IN (SELECT id FROM projects)")
    db.execute("DELETE FROM jobs WHERE status IN ('tamam', 'hata')")
    for uid in [r["id"] for r in db.rows("SELECT id FROM users WHERE email LIKE '%@demo.local' AND role != 'admin'")]:
        if db.scalar("SELECT 1 FROM comments WHERE user_id = ?", (uid,)):
            db.execute("UPDATE users SET active = 0 WHERE id = ?", (uid,))
        else:
            db.execute("DELETE FROM users WHERE id = ?", (uid,))
    for name, pain in DEMO_PAIN_POINTS.items():
        db.execute("UPDATE departments SET pain_points = NULL WHERE name = ? AND pain_points = ?", (name, pain))
    # demo sürümünün varsayılan departmanlarından boş kalanlar
    for name in DEMO_DEPARTMENTS:
        db.execute("DELETE FROM departments WHERE name = ? AND id NOT IN (SELECT department_id FROM projects WHERE department_id IS NOT NULL)",
                   (name,))
    db.set_setting("demo_cleared", "1")
    db.log(user_id, "demo_cleared", detail=str(stats))
    return stats


def reset_all(user_id: int | None = None) -> None:
    """Kullanıcılar, departmanlar ve markalar dışındaki tüm verileri siler (dosyalar dahil)."""
    from .config import STORAGE_DIR
    for table in ("facts", "chunks", "document_links", "copilot_rows", "copilot_datasets", "documents", "kpis", "stage_history",
                  "status_updates", "project_brands", "actions", "comments", "ai_insights", "chat_messages", "jobs",
                  "security_metrics", "initiatives", "projects", "activity"):
        db.execute(f"DELETE FROM {table}")
    db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    for f in STORAGE_DIR.rglob("*"):
        if f.is_file():
            f.unlink(missing_ok=True)
    db.log(user_id, "reset_all")
