"""Tüm verilerin yedeği ve geri yüklenmesi (veritabanı + yüklenen dokümanlar).

Ayarlar sayfasından indirilen yedek, başka bir kurulumda (ör. bilgisayardaki uygulamadan sunucuya taşırken) yine
Ayarlar sayfasından geri yüklenir. deploy/yedekle.sh ile alınan sunucu yedekleri de kabul edilir.
Yedekte AI anahtarı bulunmaz; .env dosyası geri yüklenmez.
"""
import json
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import config, db

AI_SETTINGS_KEY = "ai_settings"


def make_backup() -> Path:
    """Çalışan uygulamayı durdurmadan tutarlı yedek üretir; geçici .tar.gz dosyasının yolunu döner (çağıran siler)."""
    tmp = Path(tempfile.mkdtemp(prefix="aiimpact-yedek-"))
    snap = tmp / "app.db"
    src, dst = sqlite3.connect(config.DB_PATH), sqlite3.connect(snap)
    try:
        src.backup(dst)
        row = dst.execute("SELECT value FROM settings WHERE key = ?", (AI_SETTINGS_KEY,)).fetchone()
        if row:  # anahtar yedeğe girmez
            ai = json.loads(row[0] or "{}")
            ai.pop("AI_API_KEY", None)
            dst.execute("UPDATE settings SET value = ? WHERE key = ?", (json.dumps(ai), AI_SETTINGS_KEY))
            dst.commit()
    finally:
        dst.close()
        src.close()
    out = tmp / f"ai-impact-yedek-{datetime.now():%Y%m%d-%H%M}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(snap, arcname="data/app.db")
        if config.STORAGE_DIR.exists():
            tar.add(config.STORAGE_DIR, arcname="data/files")
    snap.unlink()
    return out


def _safe_members(tar: tarfile.TarFile) -> tuple[tarfile.TarInfo, str, list[tuple[tarfile.TarInfo, str]]]:
    """Yedekteki app.db'yi ve doküman dosyalarını bulur; güvenli olmayan girdileri reddeder."""
    members = tar.getmembers()
    dbs = [m for m in members if m.isfile() and PurePosixPath(m.name).as_posix().endswith("data/app.db")]
    if not dbs:
        raise ValueError("Dosyada data/app.db bulunamadı. Ayarlar sayfasından indirilen ya da deploy/yedekle.sh ile alınan bir yedek seçin.")
    prefix = dbs[0].name[: -len("data/app.db")]
    files = []
    for m in members:
        name = PurePosixPath(m.name)
        if name.is_absolute() or ".." in name.parts:
            raise ValueError(f"Güvenli olmayan dosya yolu: {m.name}")
        if not m.name.startswith(prefix + "data/files/") or not m.isfile():
            continue  # klasörler, .env ve diğerleri atlanır; bağlantı/cihaz girdileri hiç açılmaz
        rel = m.name[len(prefix + "data/files/"):]
        if rel:
            files.append((m, rel))
    return dbs[0], prefix, files


def restore(upload: Path) -> dict:
    """Yedeği mevcut verilerin yerine yükler. AI ayarları (Ayarlar sayfasından girilenler) korunur."""
    tmp = Path(tempfile.mkdtemp(prefix="aiimpact-geri-"))
    try:
        try:
            tar = tarfile.open(upload, "r:*")
        except tarfile.TarError as exc:
            raise ValueError("Dosya okunamadı; .tar.gz biçiminde bir yedek seçin.") from exc
        with tar:
            db_member, _prefix, files = _safe_members(tar)
            new_db = tmp / "app.db"
            with tar.extractfile(db_member) as f, open(new_db, "wb") as out:
                shutil.copyfileobj(f, out)
            check = sqlite3.connect(new_db)
            try:
                if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Yedekteki veritabanı bozuk.")
                if not check.execute("SELECT 1 FROM sqlite_master WHERE name = 'projects'").fetchone():
                    raise ValueError("Bu dosya AI Impact Merkezi yedeği değil.")
                stats = {"proje": check.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                         "doküman": (check.execute("SELECT COUNT(*) FROM documents").fetchone() or [0])[0]
                         if check.execute("SELECT 1 FROM sqlite_master WHERE name = 'documents'").fetchone() else 0}
            finally:
                check.close()
            keep_ai = db.setting(AI_SETTINGS_KEY)
            # canlı veritabanının yerine (uygulama çalışırken, SQLite yedekleme API'siyle)
            src, dst = sqlite3.connect(new_db), sqlite3.connect(config.DB_PATH, timeout=30)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            root = config.STORAGE_DIR.resolve()
            for m, rel in files:
                target = (root / rel).resolve()
                if root not in target.parents:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as f, open(target, "wb") as out:
                    shutil.copyfileobj(f, out)
            stats["dosya"] = len(files)
        if keep_ai is not None:
            db.set_setting(AI_SETTINGS_KEY, keep_ai)
        else:
            db.execute("DELETE FROM settings WHERE key = ?", (AI_SETTINGS_KEY,))
        return stats
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
