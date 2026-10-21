# AI Impact Merkezi

Doğuş Otomotiv Dijital Dönüşüm ekibi için AI Impact projelerinin takip, ölçümleme ve danışmanlık platformu.
Trello panosunun yerini alır; Genel Müdür ve ekibinin portföyü tek ekrandan izlemesi için tasarlanmıştır.

> Süreç tasarımı: [`docs/SUREC_TASARIMI.md`](docs/SUREC_TASARIMI.md)

## Modüller

| Modül | Ne işe yarar |
|---|---|
| **Yönetici Özeti** | Aktif/canlı proje, gerçekleşen etki, riskli projeler, portföy hunisi, ölçümleme olgunluğu, haftalık AI yorumu, güncel olmayan projeler, geciken aksiyonlar, değer zinciri kapsaması |
| **Projeler** | Kanban pano + liste. Proje kartı: künye, aşama kapıları, KPI (baseline/hedef/gerçekleşen), haftalık durum geçmişi, dokümanlar, aksiyonlar, yorumlar, tarihçe |
| **Haftalık Raporlar** | DT raporu yüklenir (PDF/Word/Excel/PPT/metin) → AI proje bazında durum, risk skoru, engel ve öneri çıkarır → DDE onaylayınca portföye işlenir. Proje × hafta sağlık ısı haritası |
| **AI Danışman** | Portföy + raporlar + kurumsal yapı + güvenlik metriklerini bilen sohbet; boşluk ve odak analizi; içgörü arşivi |
| **Kurumsal Yapı** | Birimler, değer zinciri eşleşmesi, ağrı noktaları, strateji dokümanları (AI bağlamı) |
| **AI Security** | AI Studio, Shadow AI, AI DLP, eğitim ve politika girişimleri (yorum + doküman) ve aylık metrik trendleri; projelerde güvenlik kapısı |
| **Doküman Kütüphanesi** | Tüm dokümanlar, içerikte arama |
| **Süreç & Kurallar** | Yaşam döngüsü, kapılar, RACI, ritim, eskalasyon |
| **Yönetim** | Kullanıcılar ve roller (DT dahil), Trello JSON aktarımı, işlem kaydı |

## Hızlı başlangıç (yerel)

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
# http://localhost:8000  ·  gm@demo.local / Demo123!  ·  admin@demo.local / Admin123!
```

Demo hesapları: `gm@` (üst yönetim), `dde@` (dijital dönüşüm), `dt@` (Doğuş Teknoloji), `izleyici@` — hepsi `@demo.local`, parola `Demo123!`.

## DMZ sunucusuna kurulum (Docker)

```bash
cp .env.example .env      # SECRET_KEY, ADMIN_PASSWORD, SEED_DEMO=0, AI_* değerlerini doldurun
docker compose up -d --build
```

- Uygulama `127.0.0.1:8000`'de dinler; önüne kurumsal sertifikalı **Nginx / IIS reverse proxy** konmalı ve `COOKIE_SECURE=1` yapılmalı.
- `./data` klasörü veritabanını (`app.db`) ve yüklenen dosyaları içerir — **düzenli yedeklenmeli**.
- Docker yoksa: Python 3.11+ ile `uvicorn app.main:app --host 127.0.0.1 --port 8000` ve systemd servisi.

Örnek Nginx:

```nginx
server {
  listen 443 ssl;
  server_name aiimpact.sirket.local;
  client_max_body_size 60m;
  location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto https; proxy_read_timeout 180s; }
}
```

## Şirket içi AI bağlantısı

`.env` içinde:

```ini
AI_PROVIDER=openai                       # openai | azure | anthropic | mock
AI_BASE_URL=https://ai-gateway.sirket.local/v1
AI_API_KEY=...
AI_MODEL=model-adi
```

`mock` modunda (varsayılan) AI çağrısı yapılmaz; kural tabanlı demo çıktıları üretilir. Sol menünün altındaki
gösterge hangi modda çalışıldığını gösterir. İstemler `app/ai.py` içindedir.

## Güvenlik notları
- Parolalar PBKDF2-SHA256 ile saklanır; başarısız giriş denemeleri sınırlanır.
- Oturum çerezi `SameSite=Lax`, POST isteklerinde Origin kontrolü, sıkı Content-Security-Policy.
- AI çıktıları ve yorumlar Markdown olarak render edilir; ham HTML ve `javascript:` linkleri temizlenir.
- DT kullanıcıları yalnızca "DT'ye açık" işaretli projeleri görür; AI içgörüleri ve AI Security iç kullanıma ayrılmıştır.

## Geliştirme

```bash
pip install pytest && python -m pytest -q
```

Yapı: `app/main.py` (rotalar) · `app/domain.py` (süreç tanımları, kapı kriterleri) · `app/ai.py` (AI istemleri ve sağlayıcılar) ·
`app/reports.py` (rapor analizi akışı) · `app/security.py` (metrik tanımları) · `app/trello.py` · `app/templates/` · `app/static/`.
