"""Doküman deposu.

Dosyalar STORAGE_DIR altında içerik özetine (SHA-256) göre saklanır:
    STORAGE_DIR/2026/10/ab/ab12…ef.docx
- Aynı dosya iki kez yüklenirse ikinci kopya diske yazılmaz (tekilleştirme).
- Dosya adları kullanıcı girdisinden türetilmez; yol enjeksiyonu riski yoktur.
- STORAGE_DIR bir NAS / SMB paylaşımına ya da ayrı bir diske bağlanabilir; veritabanı yalnızca göreli yolu tutar.
"""
import hashlib
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from . import config

ALLOWED_EXT = {
    ".pdf", ".docx", ".doc", ".docm", ".rtf", ".odt", ".pptx", ".ppt", ".odp", ".xlsx", ".xlsm", ".xls", ".ods",
    ".csv", ".txt", ".md", ".json", ".eml", ".msg", ".html", ".htm", ".png", ".jpg", ".jpeg", ".zip",
}
LEGACY_EXT = {".doc", ".rtf", ".odt", ".ppt", ".odp", ".xls", ".ods"}


class UploadError(Exception):
    pass


def save_stream(chunks, filename: str) -> dict:
    """Akışı geçici dosyaya yazar, özetini alır ve depoya taşır. chunks: bytes üreten yineleyici."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise UploadError(f"Bu dosya türü desteklenmiyor: {ext or '?'}")
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=config.STORAGE_DIR, suffix=".part")
    try:
        with tmp:
            for chunk in chunks:
                size += len(chunk)
                if size > limit:
                    raise UploadError(f"Dosya {config.MAX_UPLOAD_MB} MB sınırını aşıyor")
                digest.update(chunk)
                tmp.write(chunk)
        sha = digest.hexdigest()
        now = datetime.now()
        rel = Path(f"{now:%Y}") / f"{now:%m}" / sha[:2] / f"{sha}{ext}"
        existing = _find_existing(sha, ext)
        if existing:
            Path(tmp.name).unlink(missing_ok=True)
            rel = existing
        else:
            dest = config.STORAGE_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(tmp.name, dest)
        return {"storage_path": str(rel).replace("\\", "/"), "sha256": sha, "size": size, "ext": ext}
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def _find_existing(sha: str, ext: str) -> Path | None:
    from . import db
    r = db.row("SELECT storage_path FROM documents WHERE sha256 = ? AND storage_path IS NOT NULL LIMIT 1", (sha,))
    if r and (config.STORAGE_DIR / r["storage_path"]).exists():
        return Path(r["storage_path"])
    return None


def path_of(storage_path: str | None) -> Path | None:
    if not storage_path:
        return None
    p = (config.STORAGE_DIR / storage_path).resolve()
    if config.STORAGE_DIR.resolve() not in p.parents:
        return None
    return p


def soffice() -> str | None:
    return config.SOFFICE_PATH or shutil.which("soffice") or shutil.which("libreoffice")


def convert_legacy(src: Path) -> Path | None:
    """Eski Office formatlarını LibreOffice ile modern karşılığına çevirir (çıktı geçici klasörde)."""
    exe = soffice()
    if not exe:
        return None
    target = {".doc": "docx", ".rtf": "docx", ".odt": "docx", ".ppt": "pptx", ".odp": "pptx", ".xls": "xlsx", ".ods": "xlsx"}[src.suffix.lower()]
    out = Path(tempfile.mkdtemp(prefix="conv-"))
    try:
        subprocess.run([exe, "--headless", "--convert-to", target, "--outdir", str(out), str(src)],
                       check=True, timeout=180, capture_output=True)
    except (subprocess.SubprocessError, OSError):
        return None
    found = list(out.glob(f"*.{target}"))
    return found[0] if found else None


def usage() -> dict:
    total = sum(f.stat().st_size for f in config.STORAGE_DIR.rglob("*") if f.is_file())
    disk = shutil.disk_usage(config.STORAGE_DIR)
    return {"path": str(config.STORAGE_DIR.resolve()), "used": total, "free": disk.free, "total": disk.total}
