"""Demo verisi. SEED_DEMO=1 ve veritabanı boşsa ilk açılışta yüklenir.

Gerçek verilere geçmeden önce `data/app.db` silinip SEED_DEMO=0 ile başlatılmalıdır
(yalnızca admin kullanıcısı oluşturulur).
"""
import os
from datetime import date, datetime, timedelta

from . import ai, db, security
from .config import UPLOAD_DIR
from .reports import store_report_analysis
from .auth import hash_password


def _d(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _ts(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")


def ensure_admin() -> None:
    if db.scalar("SELECT COUNT(*) FROM users"):
        return
    email = os.getenv("ADMIN_EMAIL", "admin@demo.local")
    password = os.getenv("ADMIN_PASSWORD", "Admin123!")
    db.insert("users", {"email": email, "name": "Sistem Yöneticisi", "role": "admin", "title": "Admin",
                        "password_hash": hash_password(password), "created_at": db.now()})


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

ORG = [
    ("Doğuş Otomotiv", None, "şirket", None, 2400, "Çok markalı otomotiv distribütörü ve perakendecisi.", None),
    ("Satış & Pazarlama", "Doğuş Otomotiv", "fonksiyon", "Satış & Bayi Yönetimi", 380, "Marka satış organizasyonları ve bayi ağı yönetimi.",
     "Lead takibi dağınık, bayi performans raporları manuel hazırlanıyor."),
    ("Pazarlama İletişimi", "Satış & Pazarlama", "birim", "Pazarlama", 60, "Kampanya ve marka iletişimi.", "İçerik üretim hızı, marka uyum kontrolü."),
    ("Satış Sonrası Hizmetler", "Doğuş Otomotiv", "fonksiyon", "Satış Sonrası & Servis", 420, "Servis ağı, garanti ve teknik destek.",
     "Garanti reddi kayıpları, teknik bilgiye erişim süresi."),
    ("Yedek Parça", "Satış Sonrası Hizmetler", "birim", "Yedek Parça & Lojistik", 310, "Parça planlama, depo ve dağıtım.",
     "Acil sipariş maliyeti, stok fazlası, bayi bazlı talep oynaklığı."),
    ("Müşteri İlişkileri", "Doğuş Otomotiv", "birim", "Müşteri Deneyimi & CRM", 140, "Çağrı merkezi ve şikâyet yönetimi.",
     "Yüksek çağrı hacmi, şikâyet kök neden analizi yapılamıyor."),
    ("Finans", "Doğuş Otomotiv", "fonksiyon", "Finans & Muhasebe", 160, "Muhasebe, hazine, bütçe ve raporlama.", "Manuel mutabakat, ay sonu kapanış süresi."),
    ("İnsan Kaynakları", "Doğuş Otomotiv", "fonksiyon", "İnsan Kaynakları", 45, "İşe alım, yetenek ve çalışan deneyimi.", None),
    ("Satın Alma", "Doğuş Otomotiv", "birim", "Tedarik Zinciri & Satın Alma", 35, "Dolaylı satın alma ve tedarikçi yönetimi.", None),
    ("Filo Kiralama", "Doğuş Otomotiv", "iştirak", "Filo & Kiralama", 120, "Kurumsal filo kiralama operasyonu.", "Araç iade hasar süreçleri, kalan değer tahmini."),
    ("Hukuk", "Doğuş Otomotiv", "birim", "Kurumsal Hizmetler & Hukuk", 18, "Sözleşmeler ve uyum.", None),
    ("Dijital Dönüşüm", "Doğuş Otomotiv", "birim", "BT & Siber Güvenlik", 25, "AI Impact programının sahibi.", None),
]

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

AI-003 Yedek Parça Talep Tahmini: ERP veri erişimi onayı ikinci haftadır bekleniyor, geliştirme fiilen durdu. Ekipten bir veri bilimci başka projeye kaydırıldı. Hedef tarih gecikme riski yüksek.

AI-004 Bayi Performans Kopilotu: Pilot sürüyor, 12 brifing üretildi. Sonraki hafta Audi bölgeleri eklenecek.

AI-005 Çağrı Merkezi Konuşma Analitiği: Canlıda. Ölçüm için çağrı merkezi sisteminden ACW verisi talebi netleşmedi.

AI-007 Fatura & İrsaliye Eşleştirme: Alternatif OCR modeli ile doğruluk %91'e çıktı. Muhasebe ekibi ile UAT planlanıyor.

AI-012 AI Studio: Finans ekibi onboarding tamamlandı, aktif kullanıcı 1.120.
"""


def seed_demo() -> None:
    if db.scalar("SELECT COUNT(*) FROM projects"):
        return
    admin_id = db.scalar("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")
    ids = {}
    for email, name, role, title, org in USERS:
        if not db.scalar("SELECT 1 FROM users WHERE email = ?", (email,)):
            ids[role] = db.insert("users", {"email": email, "name": name, "role": role, "title": title, "organization": org,
                                            "password_hash": hash_password("Demo123!"), "created_at": db.now()})
    pids = {}
    for (code, name, vc, unit, brands, ai_type, stage, health, prio, sponsor, owner, dt, start, target, golive,
         meas, est, real, fte, sec, dclass, risk, summary) in PROJECTS:
        pids[code] = db.insert("projects", {
            "code": code, "name": name, "value_chain": vc, "business_unit": unit, "brands": brands, "ai_type": ai_type,
            "stage": stage, "health": health, "priority": prio, "sponsor": sponsor, "owner": owner, "dt_lead": dt,
            "start_date": _d(start) if start is not None else None, "target_date": _d(target) if target is not None else None,
            "golive_date": _d(golive) if golive is not None else None, "measurement_status": meas,
            "estimated_value": est, "realized_value": real, "fte_saving": fte, "security_review": sec, "data_class": dclass,
            "ai_risk_score": risk, "summary": summary,
            "problem": summary if stage != "fikir" else None,
            "visible_to_dt": 0 if code == "AI-011" else 1,
            "created_at": _ts(start or -5), "updated_at": _ts(-2),
        })
        db.insert("stage_history", {"project_id": pids[code], "from_stage": None, "to_stage": "fikir",
                                    "note": "Kayıt açıldı", "user_id": admin_id, "at": _ts(start or -5)})
        if stage != "fikir":
            db.insert("stage_history", {"project_id": pids[code], "from_stage": "fikir", "to_stage": stage,
                                        "note": "Demo verisi", "user_id": admin_id, "at": _ts(-20)})
    for code, ks in KPIS.items():
        for name, unit, direction, base, target, actual, method in ks:
            db.insert("kpis", {"project_id": pids[code], "name": name, "unit": unit, "direction": direction, "baseline": base,
                               "target": target, "actual": actual, "method": method, "measured_at": _d(-7) if actual else None})
    for code, cat, title in [("AI-001", "İş Analizi / Business Case", "Servis Asistanı Business Case"),
                             ("AI-001", "Pilot Sonuç Raporu", "Pilot Sonuç Raporu"),
                             ("AI-001", "Güvenlik Değerlendirmesi", "AI Güvenlik Değerlendirmesi"),
                             ("AI-002", "İş Analizi / Business Case", "Garanti Ön Kontrol İş Değeri"),
                             ("AI-002", "Gereksinim", "Gereksinim Dokümanı v2"),
                             ("AI-003", "İş Analizi / Business Case", "Talep Tahmini Business Case"),
                             ("AI-012", "Teknik Tasarım", "AI Studio Mimari")]:
        stored = f"demo-{pids[code]}-{len(title)}.txt"
        content = f"{title}\n\nDemo dokümanı — gerçek doküman yüklendiğinde içerik AI analizinde kullanılır."
        (UPLOAD_DIR / stored).write_text(content, encoding="utf-8")
        db.insert("documents", {"project_id": pids[code], "title": title, "category": cat, "filename": f"{title}.txt",
                                "stored_name": stored, "mime": "text/plain", "size": len(content), "text_content": content,
                                "uploaded_by": ids.get("dde", admin_id), "uploaded_at": _ts(-30)})
    actions = [("AI-003", "ERP veri erişim onayının BT Güvenlik'ten çıkarılması", "BT Güvenlik Müdürü", _d(-3)),
               ("AI-002", "Üretici garanti kural setinin DT'ye iletilmesi", "Garanti Müdürü", _d(4)),
               ("AI-005", "ACW baseline verisinin çağrı merkezinden alınması", "CRM Müdürü", _d(7)),
               ("AI-010", "Lisans kararı için hukuk-satın alma toplantısı", "Hukuk Müdürü", _d(-10)),
               ("AI-008", "Güvenlik değerlendirmesinin başlatılması", "Bilgi Güvenliği", _d(14))]
    for code, title, owner, due in actions:
        db.insert("actions", {"project_id": pids[code], "title": title, "owner": owner, "due_date": due, "status": "acik",
                              "source": "Haftalık değerlendirme", "created_by": ids.get("dde", admin_id), "created_at": _ts(-8)})
    org_ids = {}
    for name, parent, kind, vc, hc, desc, pain in ORG:
        org_ids[name] = db.insert("org_units", {"name": name, "parent_id": org_ids.get(parent), "kind": kind, "value_chain": vc,
                                                "headcount": hc, "description": desc, "pain_points": pain})
    for slug, name, cat, desc, owner, status, health in INITIATIVES:
        db.insert("initiatives", {"slug": slug, "name": name, "category": cat, "description": desc, "owner": owner,
                                  "status": status, "health": health, "created_at": _ts(-200)})
    # Güvenlik metrikleri: son 9 ay
    base = date.today().replace(day=1)
    months = []
    for i in range(8, -1, -1):
        y, m = base.year, base.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")
    trends = {
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
    for metric, vals in trends.items():
        for period, v in zip(months, vals):
            security.upsert(period, metric, v)
    # Haftalık raporlar + analiz
    for weeks_ago, text in ((2, REPORT_1), (1, REPORT_2)):
        week = date.today() - timedelta(days=date.today().weekday() + 7 * weeks_ago)
        rid = db.insert("weekly_reports", {"week_start": week.isoformat(), "title": f"DT Haftalık Durum Raporu — {week.strftime('%d.%m.%Y')}",
                                           "filename": "rapor.txt", "text_content": text, "uploaded_by": ids.get("dt", admin_id),
                                           "uploaded_at": _ts(-7 * weeks_ago + 1)})
        store_report_analysis(rid, ai._mock_report_analysis(text), apply=True, user_id=admin_id,
                              at=(week + timedelta(days=1)).isoformat() + "T10:00:00")
    comments = [("project", pids["AI-003"], ids.get("executive"), "ERP erişimi neden 2 haftadır bekliyor? Bu hafta sonuna kadar çözülsün, gerekirse bana eskale edin."),
                ("project", pids["AI-003"], ids.get("dt"), "BT Güvenlik ile toplantı Perşembe günü planlandı. Onay gelirse 1 haftalık gecikmeyle hedefe yetişebiliriz."),
                ("project", pids["AI-005"], ids.get("dde"), "Canlıya çıktı ama baseline yok. Ölçüm planını önümüzdeki komitede netleştirelim."),
                ("project", pids["AI-001"], ids.get("viewer"), "Servis ekiplerinden çok olumlu geri bildirim var. Porsche servislerine de genişletebilir miyiz?"),
                ("initiative", 2, ids.get("executive"), "Shadow AI kullanıcı sayısı düşüyor, güzel. Hangi birimler hâlâ en çok kullanıyor?"),
                ("initiative", 1, ids.get("dde"), "Finans onboarding tamamlandı. Sırada İK ve Hukuk var.")]
    for t, tid, uid, body in comments:
        db.insert("comments", {"target_type": t, "target_id": tid, "user_id": uid or admin_id, "body": body, "created_at": _ts(-3)})
    db.insert("ai_insights", {"kind": "gap", "title": "AI Olgunluk ve Boşluk Analizi", "body": ai._mock_gap_analysis(),
                              "created_by": admin_id, "created_at": _ts(-1)})
    db.log(admin_id, "seed", detail="Demo verisi yüklendi")
