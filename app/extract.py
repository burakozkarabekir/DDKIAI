"""Dokümanlardan yapıyı koruyarak metin çıkarma.

Çıktı bölümlerden oluşur: [(başlık, metin)]. Başlık; Word başlık stilleri, slayt numarası, Excel sayfası
ya da PDF sayfasıdır. Bölümler daha sonra parçalara (chunk) ayrılıp indekslenir.
"""
import csv
import email
import io
import re
import zipfile
from html import unescape
from pathlib import Path

from .storage import LEGACY_EXT, convert_legacy

TEXT_LIMIT = 1_500_000


def extract(path: Path) -> dict:
    """Dönüş: {"sections": [(heading, text)], "pages": int|None, "warning": str|None}"""
    ext = path.suffix.lower()
    warning = None
    if ext in LEGACY_EXT:
        converted = convert_legacy(path)
        if not converted:
            return {"sections": [], "pages": None,
                    "warning": f"{ext} formatı için sunucuda LibreOffice yok; dosyayı modern formatta (docx/pptx/xlsx) yükleyin."}
        path, ext = converted, converted.suffix.lower()
    try:
        if ext == ".pdf":
            sections, pages = _pdf(path)
            if sum(len(t) for _, t in sections) < 40 * max(1, pages):
                warning = "PDF'ten neredeyse hiç metin çıkmadı; taranmış (görüntü) bir doküman olabilir. OCR gerekir."
            return {"sections": sections, "pages": pages, "warning": warning}
        if ext in (".docx", ".docm"):
            return {"sections": _docx(path), "pages": None, "warning": None}
        if ext in (".xlsx", ".xlsm"):
            return {"sections": _xlsx(path), "pages": None, "warning": None}
        if ext == ".pptx":
            secs = _pptx(path)
            return {"sections": secs, "pages": len(secs), "warning": None}
        if ext == ".csv":
            raw = path.read_text(encoding="utf-8-sig", errors="replace")
            return {"sections": [("Tablo", "\n".join(" | ".join(r) for r in csv.reader(io.StringIO(raw))))], "pages": None, "warning": None}
        if ext in (".html", ".htm"):
            return {"sections": [("", _strip_html(path.read_text(encoding="utf-8", errors="replace")))], "pages": None, "warning": None}
        if ext == ".eml":
            return {"sections": _eml(path), "pages": None, "warning": None}
        if ext in (".txt", ".md", ".json"):
            return {"sections": _plain_sections(path.read_text(encoding="utf-8", errors="replace")), "pages": None, "warning": None}
        if ext == ".zip":
            return {"sections": [("Arşiv içeriği", "\n".join(zipfile.ZipFile(path).namelist()))], "pages": None,
                    "warning": "ZIP içindeki dosyalar ayrı ayrı yüklenmelidir; yalnızca dosya listesi okundu."}
        return {"sections": [], "pages": None, "warning": "Bu dosya türünden metin çıkarılamaz (görsel vb.). Doküman saklandı."}
    except Exception as exc:  # bozuk / şifreli dosyalar akışı durdurmasın
        return {"sections": [], "pages": None, "warning": f"Metin çıkarılamadı: {exc}"}


def full_text(sections: list[tuple[str, str]]) -> str:
    out = []
    for h, t in sections:
        out.append((f"## {h}\n" if h else "") + t)
    return "\n\n".join(out)[:TEXT_LIMIT]


# ---------------------------------------------------------------- biçimler

def _pdf(path: Path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    sections = [(f"Sayfa {i}", (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages, 1)]
    return [s for s in sections if s[1]], len(reader.pages)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _wtext(el) -> str:
    """Bir öğenin altındaki tüm metin (hiperlink, alan, metin kutusu dahil); sekme/satır sonu korunur."""
    out = []
    for node in el.iter():
        if node.tag == _W + "t":
            out.append(node.text or "")
        elif node.tag == _W + "tab":
            out.append(" ")
        elif node.tag in (_W + "br", _W + "cr"):
            out.append("\n")
    return "".join(out).strip()


def _docx(path: Path):
    import docx
    d = docx.Document(str(path))
    styles = {s.style_id: (s.name or "").lower() for s in d.styles}
    sections, heading, buf = [], "", []

    def flush():
        if buf:
            sections.append((heading, "\n".join(buf).strip()))
            buf.clear()
        elif heading:  # içeriksiz başlık (ör. doküman başlığı) kaybolmasın: proje eşleştirmede gerekli
            sections.append((heading, heading))

    def table_rows(tbl):
        rows = []
        for tr in tbl.findall(_W + "tr"):
            cells = []
            for tc in tr.findall(_W + "tc"):
                cells.append(" ".join(t for t in (_wtext(p) for p in tc.iter(_W + "p")) if t))
            if any(cells):
                rows.append(cells)
        if not rows:
            return
        header = rows[0]
        # İlk satır başlık gibi görünüyorsa (kısa, sayı olmayan hücreler) her satıra sütun adlarını ekle
        use_header = len(rows) > 1 and len(header) > 1 and all(0 < len(h) <= 40 and not re.search(r"\d{3,}", h) for h in header)
        for cells in rows[1:] if use_header else rows:
            if use_header and len(cells) == len(header):
                parts = [f"{h}: {v}" for h, v in zip(header, cells) if v]
            else:
                parts = []
                for v in cells:
                    if v and (not parts or parts[-1] != v):  # birleştirilmiş hücre tekrarlarını at
                        parts.append(v)
            if parts:
                yield " | ".join(parts)

    def walk(container):
        nonlocal heading
        for block in container.iterchildren():
            tag = block.tag
            if tag == _W + "p":
                text = _wtext(block)
                ps = block.find(f"{_W}pPr/{_W}pStyle")
                style = styles.get(ps.get(_W + "val"), "") if ps is not None else ""
                is_heading = style.startswith(("heading", "başlık", "title")) or style == "title"
                if text and is_heading and len(text) <= 200:
                    flush()
                    heading = text
                elif text:
                    buf.append(text)
            elif tag == _W + "tbl":
                buf.extend(table_rows(block))
            elif tag in (_W + "sdt", _W + "customXml", _W + "smartTag"):
                content = block.find(_W + "sdtContent")
                walk(content if content is not None else block)

    walk(d.element.body)
    flush()
    return sections


def _xlsx(path: Path):
    from openpyxl import load_workbook
    wb = load_workbook(str(path), read_only=True, data_only=True)
    sections = []
    for ws in wb.worksheets:
        lines = []
        for r in ws.iter_rows(values_only=True):
            if any(v is not None and str(v).strip() for v in r):
                lines.append(" | ".join("" if v is None else str(v).strip() for v in r).rstrip(" |"))
        if lines:
            sections.append((f"Sayfa: {ws.title}", "\n".join(lines)))
    return sections


def _pptx(path: Path):
    sections = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
        for name in slides:
            num = re.findall(r"\d+", name)[-1]
            xml = z.read(name).decode("utf-8", errors="replace")
            paras = [unescape(" ".join(re.findall(r"<a:t>([^<]*)</a:t>", p))) for p in re.findall(r"<a:p>(.*?)</a:p>", xml, re.S)]
            text = "\n".join(p for p in paras if p.strip())
            note_name = f"ppt/notesSlides/notesSlide{num}.xml"
            if note_name in names:
                notes = " ".join(re.findall(r"<a:t>([^<]*)</a:t>", z.read(note_name).decode("utf-8", errors="replace")))
                if notes.strip():
                    text += f"\n[Konuşmacı notu] {unescape(notes)}"
            title = text.split("\n", 1)[0][:80] if text else ""
            sections.append((f"Slayt {num}" + (f" · {title}" if title else ""), text))
    return [s for s in sections if s[1].strip()]


def _eml(path: Path):
    msg = email.message_from_bytes(path.read_bytes())
    head = f"Konu: {msg.get('Subject', '')}\nKimden: {msg.get('From', '')}\nTarih: {msg.get('Date', '')}"
    parts = []
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            parts.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace"))
        elif part.get_content_type() == "text/html" and not parts:
            parts.append(_strip_html(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")))
    return [("E-posta", head + "\n\n" + "\n".join(parts))]


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", html)
    return re.sub(r"[ \t]+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def _plain_sections(text: str):
    """Markdown/düz metinde '#' başlıklarına ya da BÜYÜK HARF satırlarına göre böl."""
    sections, heading, buf = [], "", []
    for line in text.splitlines():
        m = re.match(r"^#{1,4}\s+(.+)", line)
        if m:
            if buf:
                sections.append((heading, "\n".join(buf).strip()))
                buf = []
            heading = m.group(1).strip()
        else:
            buf.append(line)
    if buf:
        sections.append((heading, "\n".join(buf).strip()))
    return [s for s in sections if s[1]]
