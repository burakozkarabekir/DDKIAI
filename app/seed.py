"""Demo verisi. SEED_DEMO=1 ve veritabanı boşsa ilk açılışta yüklenir.

Demo dokümanları gerçek dosya formatlarında (Word, Excel, metin) üretilip uygulamanın doküman işleme
hattından geçirilir; böylece bilgi çıkarımı, proje eşleştirme, çelişki tespiti ve inceleme kuyruğu
demo verisinde de gerçek akışla çalışır.

Gerçek verilere geçmeden önce `data/` klasörü silinip SEED_DEMO=0 ile başlatılmalıdır.
"""
import io
import os
from datetime import date, datetime, timedelta

from . import db, knowledge, pipeline, security
from .auth import TEAM_EMAIL, hash_password
from .domain import DEFAULT_DEPARTMENTS
from .storage import save_stream


def _d(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _ts(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")


def ensure_users() -> None:
    """Ortak ekip kullanıcısı (giriş kapalıyken kullanılır) ve ilk yönetici."""
    if not db.scalar("SELECT 1 FROM users WHERE email = ?", (TEAM_EMAIL,)):
        db.insert("users", {"email": TEAM_EMAIL, "name": "Dijital Dönüşüm Ekibi", "role": "admin", "title": "Ortak hesap",
                            "password_hash": hash_password(os.urandom(16).hex()), "created_at": db.now()})
    if not db.scalar("SELECT 1 FROM users WHERE role = 'admin' AND email != ?", (TEAM_EMAIL,)):
        db.insert("users", {"email": os.getenv("ADMIN_EMAIL", "admin@demo.local"), "name": "Sistem Yöneticisi", "role": "admin",
                            "title": "Admin", "password_hash": hash_password(os.getenv("ADMIN_PASSWORD", "Admin123!")),
                            "created_at": db.now()})


def ensure_departments() -> None:
    if db.scalar("SELECT COUNT(*) FROM departments"):
        return
    for i, (name, desc) in enumerate(DEFAULT_DEPARTMENTS):
        db.insert("departments", {"name": name, "description": desc, "sort": i, "active": 1})


VC_TO_DEPT = {
    "Satış & Bayi Yönetimi": "Satış", "Satış Sonrası & Servis": "Satış Sonrası Hizmetler",
    "Yedek Parça & Lojistik": "Yedek Parça & Lojistik", "Müşteri Deneyimi & CRM": "Müşteri Deneyimi & CRM",
    "Pazarlama": "Pazarlama", "Finans & Muhasebe": "Finans", "İnsan Kaynakları": "İnsan Kaynakları",
    "Tedarik Zinciri & Satın Alma": "Satın Alma", "Filo & Kiralama": "Filo Kiralama",
    "Kurumsal Hizmetler & Hukuk": "Hukuk & Uyum", "BT & Siber Güvenlik": "Bilgi Teknolojileri & Güvenlik",
}
PAIN_POINTS = {
    "Satış": "Lead takibi dağınık, bayi performans raporları manuel hazırlanıyor.",
    "Satış Sonrası Hizmetler": "Garanti reddi kayıpları, teknik bilgiye erişim süresi.",
    "Yedek Parça & Lojistik": "Acil sipariş maliyeti, stok fazlası, bayi bazlı talep oynaklığı.",
    "Müşteri Deneyimi & CRM": "Yüksek çağrı hacmi, şikâyet kök neden analizi yapılamıyor.",
    "Finans": "Manuel mutabakat, ay sonu kapanış süresi.",
    "Filo Kiralama": "Araç iade hasar süreçleri, kalan değer tahmini.",
}

USERS = [
    ("gm@demo.local", "Genel Müdür", "executive", "Genel Müdür", "Doğuş Otomotiv"),
    ("dde@demo.local", "Dijital Dönüşüm Uzmanı", "dde", "AI Portföy Yöneticisi", "Doğuş Otomotiv"),
    ("dt@demo.local", "DT Proje Yöneticisi", "dt", "Proje Yöneticisi", "Doğuş Teknoloji"),
    ("izleyici@demo.local", "Satış Sonrası Direktörü", "viewer", "Direktör", "Doğuş Otomotiv"),
]

# code, name, value_chain, unit, brands, ai_type, stage, health, priority, sponsor, owner, dt_lead,
# start, target, golive, measurement, est_value, realized, fte, security, data_class, risk, summary
PROJECTS = [
    ("AI-001", "Servis Danışmanı Asistanı", "Satış Sonrası & Servis", "Satış Sonrası Hizmetler", "Volkswagen, Audi, Škoda",
     "Üretken AI (LLM)", "canli", "yesil", "Yüksek", "Satış Sonrası Direktörü", "Servis Süreçleri Yöneticisi", "DT · Ece K.",
     -300, -120, -110, "dogrulandi", 18_000_000, 14_500_000, 22, "onaylandi", "Dahili", 15,
     "Servis danışmanlarının teknik bülten, garanti kuralları ve iş emri geçmişine doğal dille erişmesini sağlayan asistan."),
    ("AI-002", "Garanti Talebi Ön Kontrol", "Satış Sonrası & Servis", "Garanti", "Tüm markalar",
     "Doküman/OCR", "pilot", "sari", "Yüksek", "Satış Sonrası Direktörü", "Garanti Müdürü", "DT · Mert A.",
     -200, 20, None, "baseline", 9_500_000, None, 8, "devam", "Gizli", 48,
     "Bayilerden gelen garanti taleplerini üretici kurallarına göre ön kontrol eden ve ret riskini işaretleyen model."),
    ("AI-003", "Yedek Parça Talep Tahmini", "Yedek Parça & Lojistik", "Yedek Parça", "Volkswagen, Audi, SEAT, Cupra",
     "Makine Öğrenmesi", "gelistirme", "kirmizi", "Yüksek", "Yedek Parça Genel Müdür Yrd.", "Parça Planlama Müdürü", "DT · Selin T.",
     -150, -10, None, "planlandi", 32_000_000, None, None, "yok", "Dahili", 78,
     "Bayi ve depo bazında yedek parça talebini tahminleyip stok seviyesini ve acil sipariş maliyetini düşürmek."),
    ("AI-004", "Bayi Performans Kopilotu", "Satış & Bayi Yönetimi", "Bayi Geliştirme", "Volkswagen, Audi, Porsche",
     "Üretken AI (LLM)", "pilot", "yesil", "Orta", "Satış Direktörü", "Bayi Geliştirme Müdürü", "DT · Can B.",
     -120, 45, None, "baseline", 6_000_000, None, 4, "sartli", "Dahili", 22,
     "Bölge müdürlerine bayi KPI'larını yorumlayan, ziyaret öncesi brifing hazırlayan asistan."),
    ("AI-005", "Çağrı Merkezi Konuşma Analitiği", "Müşteri Deneyimi & CRM", "Müşteri İlişkileri", "Tüm markalar",
     "Üretken AI (LLM)", "canli", "sari", "Yüksek", "Müşteri Deneyimi Direktörü", "CRM Müdürü", "DT · Ece K.",
     -260, -60, -45, "yok", 7_500_000, None, 6, "onaylandi", "Kişisel Veri (KVKK)", 40,
     "Çağrıların özetlenmesi, şikâyet kategorizasyonu ve duygu analizi. Canlıda fakat etki ölçümü henüz yok."),
    ("AI-006", "Kampanya İçerik Üretici", "Pazarlama", "Pazarlama İletişimi", "SEAT, Cupra, Škoda",
     "Üretken AI (LLM)", "analiz", "yesil", "Orta", "Pazarlama Direktörü", "Dijital Pazarlama Müdürü", None,
     -30, 120, None, "yok", 3_000_000, None, None, "yok", "Genel", 20,
     "Marka kılavuzuna uygun kampanya metni ve görsel taslağı üretimi."),
    ("AI-007", "Fatura & İrsaliye Eşleştirme", "Finans & Muhasebe", "Muhasebe", "—",
     "Doküman/OCR", "gelistirme", "sari", "Orta", "CFO", "Muhasebe Müdürü", "DT · Mert A.",
     -90, 30, None, "planlandi", 5_200_000, None, 7, "devam", "Gizli", 55,
     "Tedarikçi faturaları ile irsaliye ve siparişleri otomatik eşleştirip uyuşmazlıkları işaretleme."),
    ("AI-008", "Kiralık Araç Hasar Tespiti", "Filo & Kiralama", "Filo Kiralama", "Volkswagen, Škoda",
     "Görüntü İşleme", "onay", "yesil", "Orta", "Filo Kiralama GM Yrd.", "Operasyon Müdürü", None,
     -45, 180, None, "planlandi", 8_000_000, None, None, "yok", "Dahili", 25,
     "İade edilen kiralık araçların fotoğraflarından hasar tespiti ve onarım maliyet tahmini."),
    ("AI-009", "İK Politika Asistanı", "İnsan Kaynakları", "İnsan Kaynakları", "—",
     "Üretken AI (LLM)", "canli", "yesil", "Düşük", "İK Direktörü", "İK İş Ortağı", "DT · Can B.",
     -220, -90, -80, "olculuyor", 1_200_000, 900_000, 1.5, "onaylandi", "Dahili", 10,
     "Çalışanların yan haklar, izin ve iç yönetmelik sorularını yanıtlayan asistan."),
    ("AI-010", "Sözleşme Risk Tarayıcı", "Kurumsal Hizmetler & Hukuk", "Hukuk", "—",
     "Üretken AI (LLM)", "beklemede", "sari", "Düşük", "Hukuk Müşaviri", "Hukuk Müdürü", "DT · Selin T.",
     -160, 60, None, "yok", 2_000_000, None, None, "devam", "Gizli", 50,
     "Sözleşmelerde standart dışı ve riskli maddeleri işaretleyen tarayıcı. Lisans kararı bekleniyor."),
    ("AI-011", "Satış Fırsatı Skorlama", "Satış & Bayi Yönetimi", "Satış Operasyon", "Volkswagen, Audi",
     "Makine Öğrenmesi", "fikir", "yesil", "Orta", "Satış Direktörü", None, None,
     None, None, None, "yok", None, None, None, "yok", None, None,
     "Showroom ve web lead'lerini satışa dönüşme olasılığına göre skorlama."),
    ("AI-012", "AI Studio Kurumsal Platform", "BT & Siber Güvenlik", "Dijital Dönüşüm", "—",
     "Ajan / Otomasyon", "olcekleme", "yesil", "Yüksek", "Genel Müdür", "Dijital Dönüşüm Lideri", "DT · Platform Ekibi",
     -360, -200, -190, "olculuyor", 12_000_000, 6_500_000, 15, "onaylandi", "Gizli", 18,
     "Çalışanların güvenli kurumsal LLM erişimi ve kendi asistanlarını oluşturabildiği iç platform."),
    ("AI-013", "Tedarikçi Teklif Karşılaştırma", "Tedarik Zinciri & Satın Alma", "Satın Alma", "—",
     "Üretken AI (LLM)", "analiz", "yesil", "Düşük", "Satın Alma Müdürü", "Satın Alma Uzmanı", None,
     -20, 150, None, "yok", 1_500_000, None, None, "yok", None, 15,
     "Teklif dokümanlarını standart kriterlere göre karşılaştırıp özet tablo çıkarma."),
]

KPIS = {
    "AI-001": [("Ortalama bilgi arama süresi", "dk", "down", 12, 4, 3.5, "Servis danışmanı zaman etüdü"),
               ("İlk seferde doğru teşhis oranı", "%", "up", 71, 80, 78, "DMS iş emri tekrar oranı")],
    "AI-002": [("Garanti ret oranı", "%", "down", 9.5, 5, None, "Üretici ret raporları"),
               ("Talep başına kontrol süresi", "dk", "down", 18, 6, None, "Garanti ekibi zaman etüdü")],
    "AI-003": [("Acil sipariş maliyeti", "TL/ay", "down", 4_200_000, 2_800_000, None, "ERP sipariş tipi analizi")],
    "AI-004": [("Ziyaret hazırlık süresi", "dk", "down", 90, 20, None, "Bölge müdürü anketi")],
    "AI-005": [("Çağrı sonrası iş süresi (ACW)", "sn", "down", None, 30, None, "Çağrı merkezi sistemi")],
    "AI-007": [("Manuel eşleştirme oranı", "%", "down", 100, 25, None, "Muhasebe iş listesi")],
    "AI-008": [("Hasar tespit süresi", "dk", "down", 40, 10, None, "Operasyon kayıtları")],
    "AI-009": [("İK'ya gelen tekrar eden soru", "adet/ay", "down", 1400, 600, 820, "İK talep sistemi")],
    "AI-012": [("Aylık aktif kullanıcı", "kişi", "up", 0, 1500, 1120, "AI Studio logları"),
               ("Kayıtlı kullanım senaryosu", "adet", "up", 0, 60, 41, "AI Studio yönetim paneli")],
}

INITIATIVES = [
    ("ai-studio", "AI Studio", "platform", "Kurumsal LLM erişim platformu. Çalışanlar onaylı modellere güvenli şekilde erişir, kendi asistanlarını oluşturur.",
     "Dijital Dönüşüm Lideri", "Ölçeklendirme — 1.120 aktif kullanıcı", "yesil"),
    ("shadow-ai", "Shadow AI Programı", "guvenlik", "Onaysız AI araçlarının (ChatGPT kişisel hesap, ücretsiz çeviri/özet siteleri vb.) tespiti, "
     "risk sınıflandırması ve çalışanların AI Studio'ya yönlendirilmesi.", "Bilgi Güvenliği Müdürü", "Tespit + yönlendirme fazı", "sari"),
    ("ai-politika", "AI Kullanım Politikası & Yönetişim", "guvenlik", "Kabul edilebilir kullanım politikası, AI risk sınıflandırması, "
     "proje güvenlik değerlendirme kapısı ve AI komitesi.", "Uyum Müdürü", "Politika yayında, komite aylık", "yesil"),
    ("ai-dlp", "AI Veri Koruma (DLP)", "guvenlik", "Promptlarda kişisel veri / gizli bilgi tespiti ve engelleme kuralları.",
     "Bilgi Güvenliği Müdürü", "Kural seti genişletiliyor", "sari"),
    ("ai-egitim", "AI Okuryazarlığı & Güvenlik Eğitimi", "guvenlik", "Tüm çalışanlar için temel AI ve güvenli kullanım eğitimi.",
     "İK Gelişim Müdürü", "Dalga 2 devam ediyor", "yesil"),
]

REPORT_1 = """DOĞUŞ TEKNOLOJİ — AI IMPACT HAFTALIK DURUM RAPORU

AI-001 Servis Danışmanı Asistanı: Canlıda stabil çalışıyor. Bu hafta Škoda teknik bültenleri eklendi. Kullanıcı sayısı 310'a ulaştı.

AI-002 Garanti Talebi Ön Kontrol: Pilot 3 bayide devam ediyor. Üretici kural setinin son versiyonu bekleniyor. Model doğruluğu %86.

AI-003 Yedek Parça Talep Tahmini: ERP veri erişimi için yetki talebi hâlâ onay bekleniyor. Feature engineering çalışması devam ediyor. Hedef tarih revize edilebilir.

AI-004 Bayi Performans Kopilotu: 5 bölge müdürü ile pilot başladı. İlk geri bildirimler olumlu. Sonraki hafta brifing şablonu güncellenecek.

AI-007 Fatura & İrsaliye Eşleştirme: OCR doğruluğu el yazılı irsaliyelerde düşük. Alternatif model test ediliyor.

AI-012 AI Studio: 3 yeni kullanım senaryosu yayınlandı. Finans ekibi onboarding planlandı.
"""

REPORT_2 = """DOĞUŞ TEKNOLOJİ — AI IMPACT HAFTALIK DURUM RAPORU

AI-001 Servis Danışmanı Asistanı: Canlıda. Audi bülten entegrasyonu tamamlandı. Aylık ölçüm raporu paylaşıldı.

AI-002 Garanti Talebi Ön Kontrol: Üretici kural seti hâlâ bekleniyor; pilot genişletmesi ertelendi. UAT tarihi iki hafta kaydı.

AI-003 Yedek Parça Talep Tahmini: ERP veri erişimi onayı ikinci haftadır bekleniyor, geliştirme fiilen durdu. Ekipten bir veri bilimci başka projeye kaydırıldı. Yeni hedef tarih: {hedef_dt}.

AI-004 Bayi Performans Kopilotu: Pilot sürüyor, 12 brifing üretildi. Sonraki hafta Audi bölgeleri eklenecek.

AI-005 Çağrı Merkezi Konuşma Analitiği: Canlıda. Ölçüm için çağrı merkezi sisteminden ACW verisi talebi netleşmedi.

AI-007 Fatura & İrsaliye Eşleştirme: Alternatif OCR modeli ile doğruluk %91'e çıktı. Muhasebe ekibi ile UAT planlanıyor.

AI-012 AI Studio: Finans ekibi onboarding tamamlandı, aktif kullanıcı 1.120.
"""



INTERNAL_NOTES = """Dijital Dönüşüm — AI Impact İç Değerlendirme Notları

AI-003 Yedek Parça Talep Tahmini: DT gecikmeyi 1 hafta olarak raporluyor ancak ERP yetkisi gelmeden model eğitimi başlayamaz; bizim tahminimiz en az 6 hafta. Hedef canlı tarihi {hedef_ic} olarak revize edilmeli. Karar: BT Güvenlik ile eskalasyon toplantısı yapılacak.
Aksiyon: ERP erişim onayı için BT Güvenlik direktörüyle görüşme.

AI-005 Çağrı Merkezi Konuşma Analitiği: Canlıda fakat ACW baseline verisi hâlâ yok. Etki raporlanamıyor; ölçüm planı olmadan ölçeklendirmeye geçilmemeli.

AI-002 Garanti Talebi Ön Kontrol: Üretici kural seti gecikmesi bizim kontrolümüz dışında. Pilot sonuçları umut verici; bayiler memnun. Riskli değil dikkat seviyesinde izlenmeli.

AI-004 Bayi Performans Kopilotu: Bölge müdürlerinden olumlu geri bildirim. Audi bölgelerine genişleme için sponsor onayı alındı.
"""

PDD_AI002 = [
    ("title", "AI-002 Garanti Talebi Ön Kontrol — Proje Tanım Dokümanı (PDD)"),
    ("h", "Genel Bilgiler"),
    ("p", "Sponsor: Satış Sonrası Direktörü"),
    ("p", "Başlangıç: 01.04.2026"),
    ("p", "Hedef canlı tarihi: 30.11.2026"),
    ("h", "Problem ve Çözüm"),
    ("p", "Problem: Bayilerden gelen garanti taleplerinin yaklaşık %9,5'i üretici tarafından reddediliyor; ret sonrası maliyet distribütörde kalıyor."),
    ("p", "Çözüm: Talepler üreticiye gönderilmeden önce kural seti ve geçmiş ret verisiyle eğitilmiş model tarafından ön kontrolden geçirilir; riskli talepler işaretlenir."),
    ("h", "Hedef KPI'lar"),
    ("p", "KPI: Garanti ret oranı | baseline 9,5 | hedef 5 | %"),
    ("p", "KPI: Talep başına kontrol süresi | baseline 18 | hedef 6 | dk"),
    ("p", "Tahmini yıllık kazanım: 9.500.000 TL"),
]

BENEFIT_AI001 = [
    ("Proje", "AI-001 Servis Danışmanı Asistanı"),
    ("Dönem", "2026 Q3"),
    ("Gerçekleşen yıllık kazanım", "15.200.000 TL"),
    ("FTE", "22"),
    ("KPI", "Ortalama bilgi arama süresi | baseline 12 | hedef 4 | gerçekleşen 3,2 | dk"),
    ("KPI", "İlk seferde doğru teşhis oranı | baseline 71 | hedef 80 | gerçekleşen 79 | %"),
    ("Ölçüm yöntemi", "DMS iş emri verisi ve 40 servis danışmanıyla zaman etüdü; Finans ile mutabık kalındı."),
]


def _docx_bytes(blocks) -> bytes:
    import docx
    d = docx.Document()
    for kind, text in blocks:
        if kind == "title":
            d.add_heading(text, level=0)
        elif kind == "h":
            d.add_heading(text, level=1)
        else:
            d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _report_docx(text: str) -> bytes:
    lines = [l for l in text.splitlines()]
    blocks = [("title", lines[0])] + [("p", l) for l in lines[1:] if l.strip()]
    return _docx_bytes(blocks)


def _xlsx_bytes(rows) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Kazanım"
    ws.append(["Kalem", "Değer"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _add_doc(filename: str, data: bytes, doc_type: str | None, source: str, doc_date: str, user_id: int) -> int:
    stored = save_stream([data], filename)
    did = db.insert("documents", {
        "title": filename.rsplit(".", 1)[0], "filename": filename, "storage_path": stored["storage_path"], "sha256": stored["sha256"],
        "size": stored["size"], "doc_type": doc_type or "diger", "type_source": "kullanici" if doc_type else "otomatik",
        "source": source, "doc_date": doc_date, "status": "sirada", "uploaded_by": user_id, "uploaded_at": doc_date + "T10:00:00"})
    pipeline.process_document(did)
    return did


DEMO_COMMENTS = [
    ("project", "AI-003", "executive", "ERP erişimi neden 2 haftadır bekliyor? Bu hafta sonuna kadar çözülsün, gerekirse bana eskale edin."),
    ("project", "AI-005", None, "Canlıya çıktı ama baseline yok. Ölçüm planını önümüzdeki komitede netleştirelim."),
    ("project", "AI-001", "viewer", "Servis ekiplerinden çok olumlu geri bildirim var. Porsche servislerine de genişletebilir miyiz?"),
    ("initiative", 2, "executive", "Shadow AI kullanıcı sayısı düşüyor, güzel. Hangi birimler hâlâ en çok kullanıyor?"),
    ("initiative", 1, None, "Finans onboarding tamamlandı. Sırada İK ve Hukuk var."),
]
DEMO_FILES = ["DDE İç Değerlendirme Notları.docx", "AI-002 PDD.docx", "AI-001 Kazanım Raporu Q3.xlsx"]


def demo_present() -> bool:
    if db.setting("demo_loaded") == "1":
        return True
    return bool(db.scalar("SELECT 1 FROM projects WHERE trello_id IS NULL AND code = 'AI-001' AND name = ?", (PROJECTS[0][1],)))


def clear_demo(user_id: int | None = None) -> dict:
    """Yalnızca demo kayıtlarını siler; kullanıcının eklediği proje, doküman ve metrikler korunur."""
    from .storage import path_of
    stats = {}
    codes = [p[0] for p in PROJECTS]
    demo_pids = [r["id"] for r in db.rows(
        f"SELECT id FROM projects WHERE trello_id IS NULL AND code IN ({','.join('?' * len(codes))}) AND name IN ({','.join('?' * len(codes))})",
        tuple(codes) + tuple(p[1] for p in PROJECTS))]
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
    for _t, _ref, _role, body in DEMO_COMMENTS:
        db.execute("DELETE FROM comments WHERE body = ?", (body,))
    slugs = [i[0] for i in INITIATIVES]
    demo_inits = [r["id"] for r in db.rows(f"SELECT id FROM initiatives WHERE slug IN ({','.join('?' * len(slugs))})", tuple(slugs))]
    # Demo girişimlerine kullanıcı yorum/doküman eklediyse girişimi koru
    keep = {r["target_id"] for r in db.rows("SELECT DISTINCT target_id FROM comments WHERE target_type = 'initiative'")}
    keep |= {r["initiative_id"] for r in db.rows("SELECT DISTINCT initiative_id FROM documents WHERE initiative_id IS NOT NULL")}
    for iid in demo_inits:
        if iid not in keep:
            db.execute("DELETE FROM initiatives WHERE id = ?", (iid,))
    stats["girişim"] = len([i for i in demo_inits if i not in keep])
    # Demo metrikleri: değeri demo serisiyle birebir aynı olan kayıtlar (kullanıcının girdiği değerler korunur)
    for metric, vals in DEMO_TRENDS.items():
        for v in vals:
            db.execute("DELETE FROM security_metrics WHERE metric = ? AND value = ? AND note IS NULL", (metric, v))
    db.execute("DELETE FROM ai_insights WHERE project_id IS NULL OR project_id NOT IN (SELECT id FROM projects)")
    db.execute("DELETE FROM chat_messages")
    db.execute("DELETE FROM jobs WHERE status IN ('tamam', 'hata')")
    demo_users = [r["id"] for r in db.rows("SELECT id FROM users WHERE email LIKE '%@demo.local' AND role != 'admin'")]
    for uid in demo_users:
        if not db.scalar("SELECT 1 FROM comments WHERE user_id = ?", (uid,)):
            db.execute("DELETE FROM users WHERE id = ?", (uid,))
        else:
            db.execute("UPDATE users SET active = 0 WHERE id = ?", (uid,))
    for name, pain in PAIN_POINTS.items():
        db.execute("UPDATE departments SET pain_points = NULL WHERE name = ? AND pain_points = ?", (name, pain))
    db.set_setting("demo_loaded", "0")
    db.set_setting("demo_cleared", "1")
    db.log(user_id, "demo_cleared", detail=str(stats))
    return stats


def reset_all(user_id: int | None = None) -> None:
    """Kullanıcılar ve departmanlar dışındaki tüm verileri siler (dosyalar dahil)."""
    from .config import STORAGE_DIR
    for table in ("facts", "chunks", "document_links", "documents", "kpis", "stage_history", "actions", "comments", "ai_insights",
                  "chat_messages", "jobs", "security_metrics", "initiatives", "projects", "activity"):
        db.execute(f"DELETE FROM {table}")
    db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    for f in STORAGE_DIR.rglob("*"):
        if f.is_file():
            f.unlink(missing_ok=True)
    db.set_setting("demo_loaded", "0")
    db.set_setting("demo_cleared", "1")
    db.log(user_id, "reset_all")


def seed_demo() -> None:
    if db.scalar("SELECT COUNT(*) FROM projects") or db.setting("demo_cleared") == "1":
        return
    db.set_setting("demo_loaded", "1")
    team_id = db.scalar("SELECT id FROM users WHERE email = ?", (TEAM_EMAIL,))
    ids = {}
    for email, name, role, title, org in USERS:
        if not db.scalar("SELECT 1 FROM users WHERE email = ?", (email,)):
            ids[role] = db.insert("users", {"email": email, "name": name, "role": role, "title": title, "organization": org,
                                            "password_hash": hash_password("Demo123!"), "created_at": db.now()})
    deps = {r["name"]: r["id"] for r in db.rows("SELECT id, name FROM departments")}
    for name, pain in PAIN_POINTS.items():
        if name in deps:
            db.update("departments", deps[name], {"pain_points": pain})
    pids = {}
    for (code, name, vc, unit, brands, ai_type, stage, health, prio, sponsor, owner, dt, start, target, golive,
         meas, est, real, fte, sec, dclass, risk, summary) in PROJECTS:
        pids[code] = db.insert("projects", {
            "code": code, "name": name, "department_id": deps.get(VC_TO_DEPT.get(vc)), "business_unit": unit, "brands": brands,
            "ai_type": ai_type, "stage": stage, "health": health, "priority": prio, "sponsor": sponsor, "owner": owner, "dt_lead": dt,
            "start_date": _d(start) if start is not None else None, "target_date": _d(target) if target is not None else None,
            "golive_date": _d(golive) if golive is not None else None, "measurement_status": meas,
            "estimated_value": est, "realized_value": real, "fte_saving": fte, "security_review": sec, "data_class": dclass,
            "ai_risk_score": risk, "summary": summary, "problem": summary if stage != "fikir" else None,
            "aliases": "Talep tahmini, Parça tahminleme" if code == "AI-003" else None,
            "created_at": _ts(start or -5), "updated_at": _ts(-2),
        })
        db.insert("stage_history", {"project_id": pids[code], "from_stage": None, "to_stage": "fikir", "note": "Kayıt açıldı",
                                    "user_id": team_id, "at": _ts(start or -5)})
        if stage != "fikir":
            db.insert("stage_history", {"project_id": pids[code], "from_stage": "fikir", "to_stage": stage, "note": "Demo verisi",
                                        "user_id": team_id, "at": _ts(-20)})
    for code, ks in KPIS.items():
        for name, unit, direction, base, target, actual, method in ks:
            db.insert("kpis", {"project_id": pids[code], "name": name, "unit": unit, "direction": direction, "baseline": base,
                               "target": target, "actual": actual, "method": method, "measured_at": _d(-7) if actual else None})
    actions = [("AI-002", "Üretici garanti kural setinin DT'ye iletilmesi", "Garanti Müdürü", _d(4)),
               ("AI-005", "ACW baseline verisinin çağrı merkezinden alınması", "CRM Müdürü", _d(7)),
               ("AI-010", "Lisans kararı için hukuk-satın alma toplantısı", "Hukuk Müdürü", _d(-10)),
               ("AI-008", "Güvenlik değerlendirmesinin başlatılması", "Bilgi Güvenliği", _d(14))]
    for code, title, owner, due in actions:
        db.insert("actions", {"project_id": pids[code], "title": title, "owner": owner, "due_date": due, "status": "acik",
                              "source": "Haftalık değerlendirme", "created_by": team_id, "created_at": _ts(-8)})
    for slug, name, cat, desc, owner, status, health in INITIATIVES:
        db.insert("initiatives", {"slug": slug, "name": name, "category": cat, "description": desc, "owner": owner,
                                  "status": status, "health": health, "created_at": _ts(-200)})
    _seed_security()

    # --- Dokümanlar: gerçek işleme hattından geçer ---
    monday = date.today() - timedelta(days=date.today().weekday())
    w2, w1 = (monday - timedelta(days=14)).isoformat(), (monday - timedelta(days=7)).isoformat()
    r1 = _add_doc(f"DT Haftalık Durum Raporu {w2}.txt", REPORT_1.encode(), "dt_durum", "Doğuş Teknoloji", w2, team_id)
    for f in knowledge.pending():  # eski raporun önerileri onaylanmış olsun
        if f["document_id"] == r1:
            knowledge.apply_fact(f["id"], team_id)
    fmt = lambda days: (date.today() + timedelta(days=days)).strftime("%d.%m.%Y")  # noqa: E731
    report2 = REPORT_2.replace("{hedef_dt}", fmt(25))
    notes = INTERNAL_NOTES.replace("{hedef_ic}", fmt(55))
    _add_doc(f"DT Haftalık Durum Raporu {w1}.docx", _report_docx(report2), "dt_durum", "Doğuş Teknoloji", w1, team_id)
    _add_doc("DDE İç Değerlendirme Notları.docx", _docx_bytes([("title", notes.splitlines()[0])] +
             [("p", l) for l in notes.splitlines()[1:] if l.strip()]), None, "Dijital Dönüşüm", _d(-3), team_id)
    _add_doc("AI-002 PDD.docx", _docx_bytes(PDD_AI002), "pdd", "Dijital Dönüşüm", _d(-180), team_id)
    _add_doc("AI-001 Kazanım Raporu Q3.xlsx", _xlsx_bytes(BENEFIT_AI001), "kazanim", "İş Birimi", _d(-10), team_id)
    pipeline.drain()

    comments = [(t, {"AI-003": pids["AI-003"], "AI-005": pids["AI-005"], "AI-001": pids["AI-001"]}.get(ref, ref), ids.get(role) if role else team_id, body)
                for t, ref, role, body in DEMO_COMMENTS]
    for t, tid, uid, body in comments:
        db.insert("comments", {"target_type": t, "target_id": tid, "user_id": uid or team_id, "body": body, "created_at": _ts(-3)})
    pipeline.enqueue("gap")
    pipeline.drain()
    db.log(team_id, "seed", detail="Demo verisi yüklendi")


def _demo_months() -> list[str]:
    base = date.today().replace(day=1)
    months = []
    for i in range(8, -1, -1):
        y, m = base.year, base.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")
    return months


DEMO_TRENDS = {
    "ai_studio_active_users": [120, 260, 410, 560, 690, 810, 930, 1040, 1120],
    "ai_studio_prompts": [3_100, 8_400, 15_200, 22_800, 29_500, 36_100, 44_700, 51_900, 58_300],
    "ai_studio_use_cases": [3, 7, 12, 17, 22, 27, 32, 37, 41],
    "shadow_ai_apps": [64, 61, 55, 49, 47, 41, 38, 36, 33],
    "shadow_ai_users": [890, 850, 760, 690, 640, 560, 520, 470, 430],
    "shadow_ai_blocked": [0, 0, 1_200, 2_600, 2_350, 2_100, 1_850, 1_600, 1_420],
    "dlp_incidents": [14, 19, 22, 17, 15, 18, 12, 10, 9],
    "sensitive_prompts_blocked": [40, 85, 130, 150, 160, 145, 150, 138, 126],
    "policy_ack_rate": [12, 35, 58, 70, 78, 83, 87, 90, 92],
    "training_completion": [0, 8, 21, 34, 45, 52, 60, 66, 71],
    "projects_security_reviewed": [30, 33, 40, 45, 50, 55, 58, 60, 62],
}


def _seed_security() -> None:
    for metric, vals in DEMO_TRENDS.items():
        for per, v in zip(_demo_months(), vals):
            security.upsert(per, metric, v)
