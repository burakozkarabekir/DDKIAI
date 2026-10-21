"""Yüklenen dokümanlardan düz metin çıkarma (AI analizi ve arama için)."""
import csv
import io
from pathlib import Path

ALLOWED_EXT = {".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".txt", ".md", ".csv", ".json", ".png", ".jpg", ".jpeg", ".zip", ".msg", ".eml"}
TEXT_LIMIT = 400_000


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        elif ext == ".docx":
            import docx
            d = docx.Document(str(path))
            parts = [p.text for p in d.paragraphs]
            for table in d.tables:
                for r in table.rows:
                    parts.append(" | ".join(c.text.strip() for c in r.cells))
            text = "\n".join(parts)
        elif ext in (".xlsx", ".xlsm"):
            from openpyxl import load_workbook
            wb = load_workbook(str(path), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets:
                parts.append(f"## Sayfa: {ws.title}")
                for r in ws.iter_rows(values_only=True):
                    if any(v is not None for v in r):
                        parts.append(" | ".join("" if v is None else str(v) for v in r))
            text = "\n".join(parts)
        elif ext == ".pptx":
            text = _pptx_text(path)
        elif ext == ".csv":
            raw = path.read_text(encoding="utf-8", errors="replace")
            text = "\n".join(" | ".join(r) for r in csv.reader(io.StringIO(raw)))
        elif ext in (".txt", ".md", ".json", ".eml"):
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            text = ""
    except Exception as exc:  # bozuk / şifreli dosyalar analizi durdurmasın
        text = f"[Metin çıkarılamadı: {exc}]"
    return text[:TEXT_LIMIT]


def _pptx_text(path: Path) -> str:
    import re
    import zipfile
    parts = []
    with zipfile.ZipFile(path) as z:
        slides = sorted(
            (n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
            key=lambda n: int(re.findall(r"\d+", n)[-1]),
        )
        for i, name in enumerate(slides, 1):
            xml = z.read(name).decode("utf-8", errors="replace")
            texts = re.findall(r"<a:t>([^<]*)</a:t>", xml)
            parts.append(f"## Slayt {i}\n" + " ".join(texts))
    return "\n".join(parts)
