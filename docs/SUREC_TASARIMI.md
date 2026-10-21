# AI Impact Takip Süreci — Tasarım Dokümanı (v1)

**Sahibi:** Doğuş Otomotiv Dijital Dönüşüm Ekibi
**Kullanıcılar:** Genel Müdür ve yönetim ekibi, Dijital Dönüşüm (DDE), iş birimi sponsorları, Doğuş Teknoloji (DT), Bilgi Güvenliği

Bu doküman, Trello panosunun yerini alan **AI Impact Merkezi**'nin arkasındaki süreci tanımlar. Uygulama bu sürecin
aracıdır: kuralların çoğunu (aşama kapıları, "durum gelmedi" uyarısı, ölçümleme olgunluğu, geciken aksiyonlar)
otomatik kontrol eder. Uygulama içindeki **Süreç & Kurallar** sayfası bu dokümanın kısa hâlidir.

---

## 1. Neden yeni bir süreç?

| Bugün (Trello) | Hedef |
|---|---|
| Kart var ama "ne durumda" sorusunun cevabı yorumlarda kayboluyor | Her projenin sağlığı, aşaması ve son durum tarihi tek bakışta |
| Canlıya çıkan projenin etki yaratıp yaratmadığı bilinmiyor | Baseline + hedef + gerçekleşen KPI; ölçümleme olgunluk seviyesi |
| DT raporu e-postada; okuyan kendi yorumunu yapıyor | Rapor sisteme yükleniyor, AI proje bazında çıkarım ve risk puanı üretiyor |
| "Hangi alanda AI yok?" sorusu cevapsız | Kurumsal yapı × değer zinciri × portföy kapsama haritası ve boşluk analizi |
| AI güvenliği ayrı yerde, projelerden kopuk | Güvenlik değerlendirmesi aşama kapısı; AI Studio / Shadow AI metrikleri aynı yerde |

**İlkeler**
1. **Tek gerçek kaynak.** Proje durumu, dokümanı, kararı ve tartışması burada.
2. **Ölçülmeyen etki, etki değildir.** Canlıya çıkan her projenin baseline'ı ve ölçüm sahibi olur.
3. **Kapıdan geçmeden ilerleme yok.** Eksik kriterle geçiş mümkün ama kayda geçer ve görünür olur.
4. **AI önerir, insan karar verir.** AI raporları okur ve puanlar; portföye işleme kararı DDE'dedir.
5. **Yönetici 5 dakikada durumu anlar.** Yönetici Özeti sadece istisnaları öne çıkarır.

---

## 2. Proje yaşam döngüsü

| # | Aşama | Sahibi | Bu aşamaya giriş kapısı (sistem kontrol eder) | Çıktı |
|---|---|---|---|---|
| 1 | Fikir / Talep | İş birimi + DDE | — | Talep kaydı |
| 2 | Analiz & İş Değeri | DDE + Sponsor | Problem tanımı · Sponsor belli | Business case, hedef KPI |
| 3 | Onay & Planlama | AI Yönlendirme Komitesi | Hedef KPI · Tahmini yıllık değer · Business case dokümanı | Komite kararı, DT ekibi, takvim |
| 4 | Geliştirme | Doğuş Teknoloji | DT sorumlusu · Hedef canlı tarihi · Veri sınıflandırması | Gereksinim/tasarım, haftalık rapor |
| 5 | Pilot / POC | DT + İş birimi | Güvenlik değerlendirmesi başladı · Gereksinim/teknik tasarım dokümanı | Baseline, pilot sonuç raporu |
| 6 | Canlıda | İş birimi + DDE | Baseline ölçümü · Güvenlik onayı · Pilot sonuç raporu | Aylık KPI ölçümü |
| 7 | Ölçeklendirme | DDE + Komite | Gerçekleşen KPI · Ölçüm doğrulandı | Yaygınlaştırma planı |

Akış dışı: **Beklemede** (en fazla 6 hafta, sonra komite kararı) ve **İptal** (öğrenimler yorum olarak yazılır).

### Ölçümleme olgunluğu
`Tanımlanmadı → KPI tanımlı → Baseline alındı → Ölçülüyor → Doğrulandı`
İlk dört seviye KPI verisi girildikçe sistem tarafından otomatik ilerletilir. **Doğrulandı** bir insan kararıdır
(çeyreklik etki doğrulamasında Finans ile birlikte).

### Sağlık tanımları
- **Yolunda:** Takvim ve kapsam planda; engel yok ya da sahibi belli ve bu hafta çözülecek.
- **Dikkat:** ≤ 2 hafta kayma riski; karar / veri / erişim bekleniyor; aynı engel ikinci kez raporlandı.
- **Riskli:** Hedef tarih kaçtı ya da > 2 hafta kayacak; geliştirme durdu; ekip kaybı; güvenlik onayı yok.

---

## 3. Ritim

**Haftalık**
| Gün | Ne olur | Kim |
|---|---|---|
| Pazartesi 12:00 | DT haftalık raporu yükler (dosya ya da yapıştırılmış metin) | DT |
| Pazartesi öğleden sonra | AI analizi → DDE önerileri inceler, seçtiklerini portföye işler, aksiyon açar | DDE |
| Salı | DDE–DT senkronu (30 dk): sadece sarı/kırmızı projeler ve açık aksiyonlar | DDE + DT |
| Çarşamba | GM Yönetici Özeti'ni inceler, talimatlarını proje kartına yorum olarak yazar | GM |
| Cuma | Aksiyon sahipleri kapanışları işler | Herkes |

**Aylık:** AI Yönlendirme Komitesi (aşama kararları, yeni talepler) · KPI gerçekleşen değer girişi · AI Security metrikleri.
**Çeyreklik:** Etki doğrulama (Finans) · AI boşluk analizi ve odak alanı seçimi.

---

## 4. Eskalasyon kuralları
- 2 hafta üst üste **Riskli** → GM gündemi + DT yöneticisiyle karar toplantısı.
- AI risk skoru **≥ 60** → DDE 48 saat içinde engel sahibiyle görüşür, aksiyon açar.
- Terminini **7 gün** geçen aksiyon → aylık komitede.
- Aktif proje **14 gün** raporda geçmezse → DT'den yazılı durum (Yönetici Özeti'nde otomatik listelenir).
- Canlıda olup **60 gün** içinde baseline'ı olmayan proje → ölçüm planı zorunlu aksiyon.
- KVKK kapsamında kişisel veri içeren projede güvenlik onayı yoksa pilota geçilmez.

---

## 5. RACI

| Faaliyet | GM / Komite | DDE | İş Birimi | DT | Bilgi Güvenliği |
|---|---|---|---|---|---|
| Talep / fikir girişi | I | A | R | C | I |
| Business case ve KPI | I | A | R | C | — |
| Onay & önceliklendirme | A | R | C | C | C |
| Geliştirme + haftalık rapor | I | A | C | R | — |
| AI güvenlik değerlendirmesi | I | C | I | R | A |
| Pilot ve baseline | I | A | R | R | C |
| Canlıya geçiş kararı | A | R | C | C | C |
| KPI ölçümü ve etki raporu | I | A | R | C | — |
| Haftalık AI analizinin onayı | I | A/R | — | I | — |
| AI Security metrikleri | I | C | — | C | A/R |

---

## 6. Erişim modeli

| Rol | Görebildikleri | Yapabildikleri |
|---|---|---|
| Üst Yönetim | Her şey | Yorum, AI danışman, boşluk analizi |
| Dijital Dönüşüm Ekibi | Her şey | Proje/aşama/KPI/aksiyon/metrik yönetimi, AI önerilerini onaylama |
| Doğuş Teknoloji | Yalnızca "DT'ye açık" projeler, haftalık raporlar, dokümanlar | Rapor/doküman yükleme, durum ve KPI güncelleme, yorum |
| Görüntüleyici | Her şey (iç alanlar dahil) | Yorum |
| Admin | Her şey | Kullanıcı yönetimi, Trello aktarımı, silme |

DT kullanıcıları **AI risk skorlarını, AI danışman yorumlarını, AI Security ve Kurumsal Yapı** sayfalarını görmez.
Bunun nedeni: AI'ın tedarikçi performansı hakkındaki yorumları iç değerlendirmedir. (Karar sizin — açılabilir.)

---

## 7. AI'ın süreçteki rolü

| Kullanım | Girdi | Çıktı | İnsan kontrolü |
|---|---|---|---|
| Haftalık rapor analizi | DT raporu + portföy + geçen haftanın raporu | Proje bazında durum, önerilen sağlık, risk skoru (0-100), engel, sonraki adım, danışman yorumu; raporda geçmeyen projeler | DDE seçip onaylar |
| Proje değerlendirmesi | Proje künyesi, KPI, haftalık geçmiş, yorumlar, doküman içerikleri | Takılma riski, ölçümleme değerlendirmesi, aksiyon önerisi (yorum olarak eklenir) | Okuyan karar verir |
| Boşluk & odak analizi | Kurumsal yapı + ağrı noktaları + portföy + güvenlik metrikleri | Kapsama haritası, eksik alanlar, odaklanılacak 3 alan | Komite seçer |
| Danışman sohbeti | Tüm bağlam + son içgörüler | Soru-cevap | — |

Tüm AI çağrıları **şirket içi uç noktaya** gider; uygulama dışarıya veri göndermez.

---

## 8. Açık sorular (birlikte netleştirelim)
1. **Giriş:** Active Directory / Entra ID ile tek oturum (SSO) mu, yoksa uygulama içi kullanıcı mı? DT kullanıcıları AD'de var mı?
2. **AI uç noktası:** API formatı (OpenAI uyumlu / Azure OpenAI / diğer), model adı, bağlam uzunluğu ve DMZ'den erişim.
3. **DT rapor formatı:** Rapor Excel mi, PowerPoint mi, e-posta mı? Örnek bir rapor paylaşılırsa analiz istemi ona göre ayarlanır.
4. **Etki para birimi:** Değer TL/yıl mı tutulmalı, yoksa FTE + süre + maliyet ayrı ayrı mı raporlanmalı?
5. **AI Security veri kaynakları:** AI Studio logları, proxy/CASB, DLP — otomatik çekilebilir mi, yoksa aylık CSV mi?
6. **DT görünürlüğü:** DT AI risk skorlarını görmeli mi?
7. **Bildirimler:** Haftalık özetin GM'ye e-posta ile gitmesi isteniyor mu (SMTP bilgisi)?

## 9. Yol haritası önerisi
- **Faz 1 (bu sürüm):** Portföy, aşama kapıları, KPI, doküman, yorum, haftalık rapor + AI analizi, danışman, kurumsal yapı, AI Security, Trello aktarımı.
- **Faz 2:** AD/SSO, e-posta bildirimleri (Pazartesi hatırlatma, Çarşamba GM özeti), haftalık özetin PDF'i.
- **Faz 3:** AI Studio / DLP metriklerinin otomatik entegrasyonu, doküman içinde semantik arama (RAG), PostgreSQL.
