# AI Impact Merkezi

Doğuş Otomotiv Dijital Dönüşüm ekibinin AI Impact projelerini takip, ölçümleme ve danışmanlık platformu.
Trello panosunun yerini alır; dokümanlardan otomatik bilgi çıkarır, kaynakları birleştirir ve yönetime tek ekrandan sunar.

- Süreç tasarımı: [`docs/SUREC_TASARIMI.md`](docs/SUREC_TASARIMI.md)
- Veri mimarisi (doküman bilgi katmanı): [`docs/VERI_MIMARISI.md`](docs/VERI_MIMARISI.md)

## Modüller

| Modül | Ne işe yarar |
|---|---|
| **Genel Bakış** | Vitrin ekranı: canlı sayaçlar, ölçüm halkası, aşama akışı, departman × aşama matrisi, marka kırılımı, Copilot benimseme, riskli projeler, haftalık AI yorumu, aksiyonlar, çelişkiler |
| **Projeler** | Pano + liste, departman ve **marka** filtresi. Proje ekleme/düzenleme (kod, departman, çoklu marka). Proje: künye, aşama kapıları, **Bilgi & Kaynaklar** (AI sentezi, bilgi akışı, öneriler, çelişkiler), KPI, dokümanlar, aksiyonlar, yorumlar, tarihçe |
| **Durum Girişi** | Dokümanlardan bağımsız, elle durum güncelleme: proje sayfasında **● Durum güncelle** ya da tüm aktif projeler için tek ekranlık haftalık tablo. Güncellemeler bilgi akışına ve AI analizlerine girer |
| **Yönetici Raporları** | Yönetici özeti / sunum dokümanları için ayrı alan ve alan bazında AI analizi |
| **Zaman Çizelgesi** | Gantt (başlangıç → canlı, planlanan, gecikme), çeyrek bazında başlayan/tamamlanan, kümülatif tamamlanan, departman/aşama/yıl filtresi |
| **Dokümanlar** | Çoklu yükleme, otomatik tür tespiti, proje eşleştirme, içerikte arama, doküman detayında çıkarılan bilgiler |
| **DT Raporları** | DT durum raporları, rapor × proje sağlık ısı haritası, iç notlar, haftalık AI yorumları |
| **İnceleme Kuyruğu** | Proje alanını değiştirecek önerilerin onayı (kaynak + alıntıyla) |
| **AI Danışman** | Kaynak göstererek soru-cevap, boşluk analizi, haftalık yorum, içgörü arşivi. Her sayfanın sağ alt köşesindeki **AI'a sor** balonu açık sayfanın bağlamıyla (proje, Copilot, doküman alanı) yanıt verir |
| **AI Security** | Üç ayrı sayfa: **Genel & Girişimler** (AI Studio, Shadow AI, DLP metrikleri), **Copilot Kullanımı** (M365 Copilot Excel/CSV: benimseme, departman/uygulama kırılımı, kullanılmayan lisanslar, dönemsel eğilim, AI analizi — kişisel veri AI'a gönderilmez), **AI Yönetişimi** (politika/standart dokümanları ve AI analizi) |
| **Ayarlar** | 10 departman ve bağlı markalar, AI bağlantı testi ve derin tanılama, Trello aktarımı, depolama durumu, işleme kuyruğu |

### Departman ve marka kırılımı

Departmanlar ve markalar iki ayrı kırılımdır. 10 departman:
1 VW Binek · 2 VW Ticari Araç - Scania - Thermo King - Meiller - Wielton · 3 Seat - Cupra - Porsche - DOD ·
4 Audi - Bentley - Lamborghini · 5 Yedek Parça ve Lojistik · 6 Mali İşler · 7 Dijital Dönüşüm ve Kurumsal İletişim · 8 Hukuk ·
9 İnsan Kaynakları ve Süreç Yönetimi · 10 İç Denetim.
Departman adındaki her marka (Scania, Cupra, Bentley…) ayrı bir marka kaydıdır; bir proje birden çok markaya ait olabilir.
Departmanı boş bırakılan projenin departmanı seçilen markadan gelir. Liste **Ayarlar → Departmanlar ve markalar** bölümünden düzenlenir.

## Hızlı başlangıç (yerel)

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload       # http://localhost:8000
```

Giriş ekranı kapalıdır (`AUTH_ENABLED=0`); uygulama doğrudan açılır. Uygulamada örnek (demo) veri yoktur: ekranlar yalnızca
yüklediğiniz dokümanlar, Trello aktarımı ve elle girdiğiniz verilerle dolar.

## DMZ sunucusuna kurulum (Docker)

```bash
cp .env.example .env                # aşağıdaki "AI bağlantısı" adımlarını uygulayın, SECRET_KEY verin
docker compose up -d --build
```

- Uygulama `127.0.0.1:8000`'de dinler; önüne kurumsal sertifikalı **Nginx / IIS reverse proxy** konur.
- Tek süreç (tek uvicorn worker) çalıştırın: doküman işleme kuyruğu uygulama içinde çalışır.

```nginx
server {
  listen 443 ssl;
  server_name aiimpact.sirket.local;
  client_max_body_size 110m;              # MAX_UPLOAD_MB'den biraz büyük
  location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host;
               proxy_set_header X-Forwarded-Proto https; proxy_read_timeout 300s; }
}
```

## AI bağlantısı — nereleri düzenlemelisiniz?

Yalnızca sunucudaki **`.env`** dosyası. Kod değişikliği gerekmez.

1. `.env.example` dosyasını `.env` olarak kopyalayın (zaten yaptıysanız açın).
2. Şu satırları doldurun:

| Değişken | Ne yazılır | Örnek |
|---|---|---|
| `AI_PROVIDER` | Uç noktanın tipi — `auto` bırakırsanız adresten algılanır | `auto` · `openai` (OpenAI uyumlu gateway / vLLM / LiteLLM) · `azure` · `anthropic` |
| `AI_BASE_URL` | Uç noktanın kök adresi | `https://ai-gateway.dogus.local/v1` — **`/chat/completions` yazmayın**, uygulama ekler |
| `AI_API_KEY` | API anahtarı | `sk-...` |
| `AI_MODEL` | Model adı (Azure'da *deployment* adı) | `gpt-4o`, `claude-…`, `llama-3.1-70b` |
| `AI_AUTH_HEADER` | *(gerekirse)* anahtar farklı başlıkta gidecekse | `Ocp-Apim-Subscription-Key`, `api-key` |
| `AI_CA_BUNDLE` | *(gerekirse)* kurum içi sertifika | `/etc/ssl/certs/dogus-ca.pem` |
| `AI_MAX_CONTEXT_CHARS` | Tek çağrıdaki en fazla metin | 128K token model: `200000` · 32K: `60000` |

3. Uygulamayı yeniden başlatın: `docker compose up -d` (Docker'sızsa servisi yeniden başlatın).
4. **Ayarlar → AI bağlantısı → Bağlantıyı test et**. Sayfanın üstünde "AI bağlı değil" uyarısı görüyorsanız `.env` okunmamıştır
   (dosya adı tam olarak `.env` mi, proje kök klasöründe mi, uygulamayı yeniden başlattınız mı?). Yeşil mesaj görürseniz hazırsınız. Sol menünün altındaki gösterge
   "Demo modu" yerine sağlayıcı ve model adını gösterir.
5. AI bağlanmadan önce yüklenmiş dokümanlar Ayarlar'da listelenir: **Bu dokümanları yeniden işle** ile gerçek modelden geçirin (onaylı bilgiler korunur).

**Azure OpenAI / AI Foundry kullanıyorsanız** en kolayı: portalda modelin sayfasındaki **Target URI** adresini olduğu gibi
`AI_BASE_URL`'e yapıştırmak. Uygulama deployment adını ve `api-version`'ı adresten alır. `AI_MODEL` alanına *model adı* değil
**deployment adı** yazılır (AI Foundry → Deployments → *Name*). `Resource not found (404)` hatası neredeyse her zaman yanlış deployment adı
ya da yanlış adres demektir.

**Bağlantı çalışmıyorsa** Ayarlar → **Bağlantıyı test et** adım adım sonuç verir: `.env` okundu mu, ayarlar dolu mu, adres çözümleniyor mu,
porta ulaşılıyor mu, model ne cevap verdi — ve her hatalı adımda ne yapılması gerektiğini yazar. Şirket ağının SSL sertifikası
Windows sertifika deposundan otomatik tanınır (`truststore`); proxy gerekiyorsa `AI_PROXY`, şirket içi adres için `NO_PROXY` kullanın.

Uygulama standart istekleri gönderir:
- `openai`: `POST {AI_BASE_URL}/chat/completions`, `Authorization: Bearer <anahtar>`, JSON modu (`response_format`) — desteklenmezse otomatik olarak düz moda düşer.
- `azure`: `POST {AI_BASE_URL}/openai/deployments/{AI_MODEL}/chat/completions?api-version=…`, `api-key: <anahtar>`
  (adres `/openai/v1` ile bitiyorsa `POST …/openai/v1/chat/completions`, model gövdede). Yeni modellerin reddettiği
  `max_tokens` / `temperature` parametreleri otomatik ayıklanır.
- `anthropic`: `POST {AI_BASE_URL}/v1/messages`, `x-api-key: <anahtar>`.

Sunucunun çıkışında kurumsal proxy varsa `HTTPS_PROXY` / `NO_PROXY` ortam değişkenleri de kullanılır.

## Dokümanlar nerede saklanır?

| Ne | Nerede | Boyut |
|---|---|---|
| Dosyaların kendisi | `STORAGE_DIR` → Docker'da `./files` klasörü (`/files`) | Büyür — ayrı disk ya da NAS bağlayın |
| Veritabanı (proje, bilgi, metin, arama indeksi) | `DATA_DIR/app.db` → Docker'da `./data` | Doküman metni dahil, genelde dosyaların %5-15'i |

- Dosyalar `files/2026/10/ab/ab12…ef.docx` biçiminde, içerik özetine (SHA-256) göre saklanır. Aynı dosya ikinci kez yüklenirse yeniden kaydedilmez.
- NAS kullanmak için `docker-compose.yml`'de `./files:/files` satırını örn. `/mnt/nas/ai-impact:/files` yapın.
- **Yedekleme:** `data/` (günlük) ve `files/` (günlük artımlı) klasörlerini yedekleyin. Yedeği almadan önce `sqlite3 data/app.db ".backup data/yedek.db"` ile tutarlı kopya alın.
- Doluluk ve boş alan: **Ayarlar → Doküman deposu**.
- Desteklenen türler: docx, doc*, pdf, pptx, ppt*, xlsx, xls*, csv, txt, md, eml, html, rtf*, odt*. (*LibreOffice ile dönüştürülür; Docker imajında hazır gelir.)
  Taranmış (görüntü) PDF'lerde metin çıkmaz; doküman "metin yok" olarak işaretlenir.

## İlk kurulum: Trello'yu aktarmak

Eski sürümlerden kalan demo kayıtları ilk açılışta kendiliğinden silinir (sizin eklediğiniz proje, doküman ve yorumlar korunur);
eski departmanlar yeni 10 departmana taşınır.

1. **Ayarlar → Trello'dan aktar.** Trello'da *Menü → Yazdır, dışa aktar ve paylaş → JSON olarak dışa aktar* ile indirdiğiniz dosyayı seçin, **Önizle**.
2. Önizlemede listelerin aşamalarını (ör. *AI Champion* → Aktarma) ve kart adındaki birimlerin departmanlarını (ör. *YP Lojistik* → Yedek Parça ve Lojistik,
   *VW Binek* → marka) kontrol edin, **Aktar**. UC kodları proje kodu olur; liste geçmişi tarihçeye, yorumlar ve checklist'ler projelere taşınır.
   Aynı dosyayı sonra tekrar yüklerseniz projeler güncellenir, kopya oluşmaz.
3. Dokümanları yükleyin. Dokümanda UC kodu ya da proje adı geçtiğinde otomatik eşleşir; geçmiyorsa proje sayfasında **Diğer adlar** alanına
   dokümanlarda kullanılan adı ekleyip dokümanı yeniden işleyin.
4. Copilot kullanım Excel'ini **AI Security → Copilot Kullanımı** sayfasından yükleyin. Sütunlar otomatik tanınır; tanınmayanları
   aynı sayfadaki sütun eşlemesinden düzeltebilirsiniz. M365 yönetim merkezindeki kişi bazlı rapor da, departman bazlı özet tablo da olur.

Her şeyi silip baştan başlamak için: **Ayarlar → Tüm verileri sıfırla** (kullanıcılar ve departmanlar korunur).

## Giriş ekranı

Şu an kapalı (`AUTH_ENABLED=0`): herkes "Dijital Dönüşüm Ekibi" ortak hesabıyla çalışır. Kullanıcı, rol ve parola altyapısı
yerinde; `AUTH_ENABLED=1` yapıp yeniden başlatınca giriş ekranı ve roller (Üst Yönetim, Doğuş Teknoloji, Görüntüleyici) devreye girer.
Kullanıcılar **Yönetim** sayfasından eklenir.

## v1'den geçiş

İlk sürümü denediyseniz `data/` klasörünü silip yeniden başlatın (v1 yalnızca demo verisi içeriyordu). Silmezseniz uygulama
eski doküman tablosunu `documents_v1` olarak saklar ve yeni yapıyı yanına kurar.

## Geliştirme

```bash
pip install pytest && python -m pytest -q
```

| Dosya | Görev |
|---|---|
| `app/main.py` | Uygulama, ara katmanlar, rotaların bağlanması |
| `app/routes/` | `projects.py` (özet, projeler, zaman çizelgesi) · `documents.py` (doküman, inceleme, DT raporları) · `misc.py` (danışman, güvenlik, ayarlar, yönetim) |
| `app/pipeline.py` | Doküman işleme hattı ve kalıcı iş kuyruğu |
| `app/knowledge.py` | Proje eşleştirme, parçalama, FTS arama, bilgiler, öneri uygulama, çelişki tespiti |
| `app/ai.py` | AI sağlayıcıları, istemler (çıkarım, sentez, haftalık yorum, boşluk analizi, danışman), demo modu |
| `app/extract.py` · `app/storage.py` | Metin çıkarma (yapı korunarak) · dosya deposu |
| `app/timeline.py` | Gantt ve çeyreklik istatistikler |
| `app/domain.py` | Aşamalar, kapı kriterleri, doküman ve bilgi türleri, doküman alanları, departman ve marka listesi |
| `app/org.py` · `app/status.py` · `app/copilot.py` | Departman/marka yapısı · manuel durum güncellemeleri · Copilot kullanım analitiği |
