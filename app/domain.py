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

VALUE_CHAIN = [
    "Satış & Bayi Yönetimi",
    "Satış Sonrası & Servis",
    "Yedek Parça & Lojistik",
    "Müşteri Deneyimi & CRM",
    "Pazarlama",
    "Finans & Muhasebe",
    "İnsan Kaynakları",
    "Tedarik Zinciri & Satın Alma",
    "Filo & Kiralama",
    "Kurumsal Hizmetler & Hukuk",
    "BT & Siber Güvenlik",
]

DOC_CATEGORIES = [
    "İş Analizi / Business Case",
    "Gereksinim",
    "Teknik Tasarım",
    "Güvenlik Değerlendirmesi",
    "Pilot Sonuç Raporu",
    "Ölçüm Raporu",
    "Sunum",
    "Sözleşme / Teklif",
    "Diğer",
]

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


def gate_checks(project: dict, kpis: list, doc_categories: set) -> dict:
    """Bir sonraki aşamaya geçiş için kapı kriterlerini değerlendirir.

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
            ("Business case dokümanı yüklendi", "İş Analizi / Business Case" in doc_categories),
        ],
        "gelistirme": [
            ("DT sorumlusu atandı", bool(project.get("dt_lead"))),
            ("Hedef canlı tarihi belirlendi", bool(project.get("target_date"))),
            ("Veri sınıflandırması yapıldı", bool(project.get("data_class"))),
        ],
        "pilot": [
            ("AI güvenlik değerlendirmesi başladı", project.get("security_review") in ("devam", "onaylandi", "sartli")),
            ("Gereksinim / teknik tasarım dokümanı var", bool({"Gereksinim", "Teknik Tasarım"} & doc_categories)),
        ],
        "canli": [
            ("Baseline ölçüm alındı", has_baseline),
            ("Güvenlik onayı var", project.get("security_review") in ("onaylandi", "sartli")),
            ("Pilot sonuç raporu yüklendi", "Pilot Sonuç Raporu" in doc_categories),
        ],
        "olcekleme": [
            ("Gerçekleşen KPI değeri girildi", has_actual),
            ("Ölçüm doğrulandı", m_rank >= MEASUREMENT_RANK["dogrulandi"]),
        ],
    }
