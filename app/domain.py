"""Süreç tanımları: aşamalar, kapı kriterleri, roller, sağlık ve ölçümleme durumları.

Süreç tasarımının tamamı docs/SUREC_TASARIMI.md dosyasında anlatılır; buradaki sabitler
o tasarımın koddaki karşılığıdır.
"""

# Proje yaşam döngüsü (sıralı). "beklemede" ve "iptal" akış dışı durumlardır.
STAGES = [
    ("fikir", "Fikir / Talep", "İş biriminden gelen ihtiyaç ya da fırsat kayda alınır."),
    ("analiz", "Analiz & İş Değeri", "Problem, hedef KPI ve tahmini değer netleştirilir."),
    ("onay", "Onay & Planlama", "Yönlendirme komitesi onayı, DT ekibi ve takvim atanır."),
    ("gelistirme", "Geliştirme", "Doğuş Teknoloji geliştirmeyi yürütür."),
    ("pilot", "Pilot / POC", "Sınırlı kullanıcıyla denenir, baseline ölçülür."),
    ("canli", "Canlıda", "Üretimde kullanılıyor, etki ölçümü sürüyor."),
    ("olcekleme", "Ölçeklendirme", "Başka marka / birimlere yaygınlaştırılıyor."),
]
SIDE_STAGES = [
    ("beklemede", "Beklemede", "Karar, kaynak ya da bağımlılık bekleniyor."),
    ("iptal", "İptal / Kapatıldı", "Devam etmeme kararı alındı."),
]
STAGE_LABELS = {k: v for k, v, _ in STAGES + SIDE_STAGES}
STAGE_ORDER = [k for k, _, _ in STAGES]
ACTIVE_STAGES = {"analiz", "onay", "gelistirme", "pilot", "canli", "olcekleme"}

HEALTH = {
    "yesil": ("Yolunda", "good"),
    "sari": ("Dikkat", "warning"),
    "kirmizi": ("Riskli", "critical"),
}

MEASUREMENT = [
    ("yok", "Tanımlanmadı"),
    ("planlandi", "KPI tanımlı"),
    ("baseline", "Baseline alındı"),
    ("olculuyor", "Ölçülüyor"),
    ("dogrulandi", "Doğrulandı"),
]
MEASUREMENT_LABELS = dict(MEASUREMENT)
MEASUREMENT_RANK = {k: i for i, (k, _) in enumerate(MEASUREMENT)}

SECURITY_REVIEW = [
    ("yok", "Yapılmadı"),
    ("devam", "Değerlendirmede"),
    ("onaylandi", "Onaylandı"),
    ("sartli", "Şartlı onay"),
]
SECURITY_REVIEW_LABELS = dict(SECURITY_REVIEW)

DATA_CLASSES = ["Genel", "Dahili", "Gizli", "Kişisel Veri (KVKK)"]
AI_TYPES = ["Üretken AI (LLM)", "Makine Öğrenmesi", "Görüntü İşleme", "Doküman/OCR", "Ajan / Otomasyon", "Diğer"]
PRIORITIES = ["Yüksek", "Orta", "Düşük"]

# Organizasyon: 10 departman ve her departmanın markaları. İlk kurulumda yüklenir,
# sonra Ayarlar > Departmanlar ve markalar bölümünden yönetilir.
ORG = [
    ("VW Binek", ["VW Binek"]),
    ("VW Ticari Araç - Scania - Thermo King - Meiller - Wielton", ["VW Ticari Araç", "Scania", "Thermo King", "Meiller", "Wielton"]),
    ("Seat - Cupra - Porsche - DOD", ["Seat", "Cupra", "Porsche", "DOD"]),
    ("Audi - Bentley - Lamborghini", ["Audi", "Bentley", "Lamborghini"]),
    ("Yedek Parça ve Lojistik", []),
    ("Mali İşler", []),
    ("Dijital Dönüşüm ve Kurumsal İletişim", []),
    ("Hukuk", []),
    ("İnsan Kaynakları ve Süreç Yönetimi", []),
    ("İç Denetim", []),
]

# Metinde geçen marka yazımları → marka adı (normalize edilmiş anahtarlarla eşleşir)
BRAND_SYNONYMS = {
    "vw binek": "VW Binek", "volkswagen binek": "VW Binek", "vw binek arac": "VW Binek",
    "vw ticari": "VW Ticari Araç", "vw ticari arac": "VW Ticari Araç", "volkswagen ticari": "VW Ticari Araç", "vwta": "VW Ticari Araç",
    "scania": "Scania", "thermo king": "Thermo King", "thermoking": "Thermo King", "meiller": "Meiller", "wielton": "Wielton",
    "seat": "Seat", "cupra": "Cupra", "porsche": "Porsche", "dod": "DOD", "dogus oto": "DOD",
    "audi": "Audi", "bentley": "Bentley", "lamborghini": "Lamborghini",
}

# Eski sürümlerin departman adları → yeni departman (geçişte projeler buna göre taşınır)
LEGACY_DEPARTMENTS = {
    "Yedek Parça & Lojistik": "Yedek Parça ve Lojistik", "Finans": "Mali İşler", "Mali İşler": "Mali İşler",
    "Kurumsal İletişim": "Dijital Dönüşüm ve Kurumsal İletişim", "Dijital Dönüşüm": "Dijital Dönüşüm ve Kurumsal İletişim",
    "Hukuk & Uyum": "Hukuk", "Uyum": "Hukuk", "İnsan Kaynakları": "İnsan Kaynakları ve Süreç Yönetimi",
    "İç Denetim": "İç Denetim",
}


def match_brands(text: str | None) -> list[str]:
    """Serbest metindeki marka adlarını bulur: "Seat&CUPRA" → [Seat, Cupra], "DOD & Sensat.com" → [DOD]."""
    import re
    from .knowledge import norm
    if not text:
        return []
    low = " " + re.sub(r"[^a-z0-9]+", " ", norm(text)) + " "
    found = []
    for key in sorted(BRAND_SYNONYMS, key=len, reverse=True):
        if f" {key} " in low and BRAND_SYNONYMS[key] not in found:
            found.append(BRAND_SYNONYMS[key])
            low = low.replace(f" {key} ", " ")
    return found


# Doküman türleri: her tür için AI'a ne arayacağı söylenir (bkz. ai.EXTRACT_PROMPT).
DOC_TYPES = {
    "dt_durum": ("DT Durum Raporu", "Doğuş Teknoloji'nin dönemsel proje durum raporu (çok projeli)."),
    "ic_not": ("İç Notlar / Değerlendirme", "Dijital Dönüşüm ekibinin projeler hakkındaki notları, toplantı ve komite notları."),
    "pdd": ("PDD / Proje Tanım Dokümanı", "Problem, kapsam, çözüm, hedef KPI, takvim, sorumlular."),
    "kazanim": ("Kazanım / Fayda Dokümanı", "Gerçekleşen ve beklenen fayda: TL, FTE, KPI değerleri, ölçüm yöntemi."),
    "business_case": ("Business Case", "İş değeri, maliyet, yatırım geri dönüşü, tahmini değer."),
    "teknik": ("Teknik Tasarım / Gereksinim", "Mimari, gereksinim, entegrasyon, veri kaynakları."),
    "guvenlik": ("Güvenlik Değerlendirmesi", "AI risk ve güvenlik değerlendirmesi, veri sınıfı, onay durumu."),
    "pilot": ("Pilot Sonuç Raporu", "Pilot kapsamı, sonuçlar, baseline ve kararlar."),
    "toplanti": ("Toplantı / Komite Kararı", "Kararlar, aksiyonlar, sorumlular ve terminler."),
    "sunum": ("Sunum", "Yönetim veya proje sunumları."),
    "sozlesme": ("Sözleşme / Teklif", "Teklif, kapsam, bedel ve sözleşme şartları."),
    "yonetici_ozeti": ("Yönetici Özeti Raporu", "Yönetime sunulan dönemsel AI Impact özet raporu: öne çıkanlar, metrikler, kararlar, riskler."),
    "yonetisim": ("AI Yönetişim Dokümanı", "AI politikası, kullanım standardı, komite tüzüğü, risk çerçevesi, prosedür ve kontroller."),
    "copilot": ("Copilot Kullanım Raporu", "Microsoft 365 Copilot kullanım/lisans Excel'i (AI Security > Copilot Kullanımı'nda analiz edilir)."),
    "diger": ("Diğer", "Sınıflandırılamayan doküman."),
}
# Kendi sayfası ve kendi AI analizi olan doküman alanları
DOC_AREAS = {
    "yonetici-raporlari": {
        "title": "Yönetici Raporları", "types": ["yonetici_ozeti", "sunum"], "default": "yonetici_ozeti", "icon": "report",
        "intro": "Genel Müdür ve yönetime sunulan AI Impact özet raporları, sunumları. AI raporları dönemler arasında "
                 "karşılaştırır, raporlardaki mesajları sistemdeki proje verisiyle kontrol eder.",
        "prompt": """Aşağıda yönetime sunulmuş AI Impact yönetici özeti raporları (eskiden yeniye) ve güncel portföy verisi var.
Markdown, şu başlıklarla yaz:
## Raporların ana mesajları (dönem dönem, kısa)
## Dönemler arası değişim (ne iyileşti, ne kötüleşti, hangi taahhüt tekrar ediyor)
## Raporlar ile sistem verisi arasındaki tutarsızlıklar (rapordaki tarih/değer/durum vs. portföy kaydı; proje kodlarıyla)
## Raporlarda eksik kalanlar (ölçümlenmeyen projeler, riskler, sayısal etki)
## Bir sonraki yönetici raporu için öneri (başlıklar ve öne çıkarılması gereken 3 mesaj)
Kaynakları [D<no>] olarak göster.""",
    },
    "ai-yonetisimi": {
        "title": "AI Yönetişimi", "types": ["yonetisim", "guvenlik"], "default": "yonetisim", "icon": "gov",
        "intro": "AI politikası, kullanım standartları, risk çerçevesi, komite kararları ve güvenlik değerlendirmeleri. "
                 "AI dokümanları birbirleriyle ve projelerin durumuyla karşılaştırıp eksik kontrolleri raporlar.",
        "prompt": """Aşağıda şirketin AI yönetişim dokümanları (politika, standart, prosedür, komite, güvenlik değerlendirmesi),
AI proje portföyü, AI Security metrikleri ve Copilot kullanım özeti var. Markdown, şu başlıklarla değerlendir:
## Yönetişim çerçevesinin özeti (hangi dokümanlar neyi düzenliyor)
## Eksik ya da zayıf kontroller (veri sınıflandırma, KVKK, model riski, insan denetimi, üçüncü taraf/tedarikçi, kayıt ve izleme,
   Shadow AI, eğitim, olay yönetimi) — her biri için öneri
## Projelerin çerçeveye uyumu (güvenlik değerlendirmesi olmadan ilerleyenler, kişisel veri içerenler; proje kodlarıyla)
## Kullanım verisiyle tutarlılık (Copilot / AI Studio / Shadow AI metrikleri politikayla örtüşüyor mu)
## Öncelikli 5 aksiyon (sahip önerisiyle)
Kaynakları [D<no>] olarak göster.""",
    },
}

DOC_SOURCES = ["Doğuş Teknoloji", "Dijital Dönüşüm", "İş Birimi", "Yönetim", "Dış Kaynak"]

# Dokümanlardan çıkarılan bilgi türleri.
# apply: None = bilgi amaçlı (projenin bilgi akışına düşer), aksi hâlde onaylanınca neyi güncellediği.
FACT_TYPES = {
    "durum": ("Durum", None),
    "risk": ("Risk", None),
    "engel": ("Engel / Bağımlılık", None),
    "sonraki_adim": ("Sonraki adım", None),
    "karar": ("Karar", None),
    "olcum": ("Ölçüm notu", None),
    "not": ("Not", None),
    "saglik": ("Sağlık önerisi", "project.health"),
    "asama": ("Aşama önerisi", "project.stage"),
    "tarih": ("Tarih", "project.<field>"),
    "tanim": ("Proje tanımı", "project.<field>"),
    "kazanim": ("Kazanım / değer", "project.<field>"),
    "kpi": ("KPI değeri", "kpi"),
    "aksiyon": ("Aksiyon", "action"),
}
FACT_FIELDS = {
    "tarih": {"start_date": "Başlangıç", "target_date": "Hedef canlı tarihi", "golive_date": "Canlıya geçiş"},
    "tanim": {"summary": "Özet", "problem": "Problem", "solution": "Çözüm", "sponsor": "Sponsor", "owner": "DO sorumlusu",
              "dt_lead": "DT sorumlusu", "brands": "Markalar", "ai_type": "AI tipi", "data_class": "Veri sınıfı",
              "security_review": "Güvenlik değerlendirmesi"},
    "kazanim": {"estimated_value": "Tahmini yıllık değer (TL)", "realized_value": "Gerçekleşen yıllık değer (TL)",
                "fte_saving": "FTE kazanımı", "measurement_status": "Ölçümleme durumu"},
}
KPI_PARTS = {"baseline": "Baseline", "target": "Hedef", "actual": "Gerçekleşen"}

# Roller. "dt" Doğuş Teknoloji kullanıcılarıdır: yalnızca DT'ye açık projeleri görür,
# AI danışman, AI içgörüleri ve güvenlik metrikleri iç kullanıma ayrılmıştır.
ROLES = {
    "admin": "Yönetici (Admin)",
    "dde": "Dijital Dönüşüm Ekibi",
    "executive": "Üst Yönetim",
    "dt": "Doğuş Teknoloji",
    "viewer": "Görüntüleyici",
}
CAN_EDIT = {"admin", "dde"}
CAN_UPLOAD = {"admin", "dde", "dt"}
INTERNAL = {"admin", "dde", "executive", "viewer"}

ACTION_STATUS = {"acik": "Açık", "kapali": "Kapandı"}


def gate_checks(project: dict, kpis: list, doc_types: set) -> dict:
    """Bir sonraki aşamaya geçiş için kapı kriterlerini değerlendirir.

    doc_types: projeye bağlı dokümanların tür anahtarları (DOC_TYPES).
    Dönüş: {stage_key: [(kriter, sağlandı_mı), ...]} — her aşama için o aşamaya
    girmeden önce sağlanması beklenen kriterler.
    """
    has_kpi = len(kpis) > 0
    has_baseline = any(k.get("baseline") is not None for k in kpis)
    has_actual = any(k.get("actual") is not None for k in kpis)
    m_rank = MEASUREMENT_RANK.get(project.get("measurement_status") or "yok", 0)
    return {
        "analiz": [
            ("Problem tanımı yazıldı", bool(project.get("problem"))),
            ("İş birimi sponsoru belli", bool(project.get("sponsor"))),
        ],
        "onay": [
            ("Hedef KPI tanımlandı", has_kpi),
            ("Tahmini yıllık değer girildi", bool(project.get("estimated_value"))),
            ("Business case veya PDD yüklendi", bool({"business_case", "pdd"} & doc_types)),
        ],
        "gelistirme": [
            ("DT sorumlusu atandı", bool(project.get("dt_lead"))),
            ("Hedef canlı tarihi belirlendi", bool(project.get("target_date"))),
            ("Veri sınıflandırması yapıldı", bool(project.get("data_class"))),
        ],
        "pilot": [
            ("AI güvenlik değerlendirmesi başladı", project.get("security_review") in ("devam", "onaylandi", "sartli")),
            ("PDD veya teknik tasarım dokümanı var", bool({"pdd", "teknik"} & doc_types)),
        ],
        "canli": [
            ("Baseline ölçüm alındı", has_baseline),
            ("Güvenlik onayı var", project.get("security_review") in ("onaylandi", "sartli")),
            ("Pilot sonuç raporu yüklendi", "pilot" in doc_types),
        ],
        "olcekleme": [
            ("Gerçekleşen KPI değeri girildi", has_actual),
            ("Ölçüm doğrulandı", m_rank >= MEASUREMENT_RANK["dogrulandi"]),
        ],
    }
