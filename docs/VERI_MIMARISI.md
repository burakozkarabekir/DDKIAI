# Veri Mimarisi — Doküman Bilgi Katmanı

AI Impact Merkezi'ne çok farklı türde dokümanlar gelir: DT'nin çok projeli durum raporları, Dijital Dönüşüm
ekibinin iç notları, her projenin PDD'si, kazanım/fayda dokümanları, toplantı kararları, sunumlar… Bu dokümanlar
**aynı projeden farklı açılardan** bahseder ve çoğu zaman birbiriyle **çelişir** (DT "1 hafta gecikme" der,
iç notlar "en az 6 hafta" der). Bu yüzden dokümanlar dosya olarak saklanmakla kalmaz; yapılandırılmış bilgiye
dönüştürülür, projelerle ilişkilendirilir ve kaynağı korunarak birleştirilir.

## Akış

```mermaid
flowchart LR
  U[Yükleme<br/>çok dosya, tür: otomatik/elle] --> S[(Depo<br/>STORAGE_DIR<br/>SHA-256 ile tekil)]
  S --> X[Metin çıkarma<br/>Word başlıkları, slaytlar,<br/>Excel sayfaları, PDF sayfaları<br/>.doc/.ppt → LibreOffice]
  X --> G[Proje sınırlarında segment<br/>+ parçalama ~1800 karakter]
  G --> I[(chunks + FTS5<br/>tam metin arama)]
  G --> M[Proje eşleştirme<br/>kod · ad · diğer adlar · AI]
  M --> L[(document_links<br/>doküman ↔ proje, çoka çok)]
  X --> A[AI çıkarımı<br/>türüne göre istem,<br/>büyük doküman = pencereler]
  A --> F[(facts<br/>tür · alan · değer · tarih ·<br/>güven · alıntı · kaynak)]
  F -->|salt bilgi| B[Proje bilgi akışı]
  F -->|alan değiştiren| R[İnceleme kuyruğu<br/>insan onayı]
  R -->|onay| P[(projects / kpis / actions)]
  F --> C[Çelişki tespiti<br/>aynı alan, farklı kaynak, farklı değer]
  F & I & P --> Y[Proje sentezi · Haftalık yorum ·<br/>Boşluk analizi · Danışman (kaynaklı yanıt)]
```

## Tablolar

| Tablo | Ne tutar | Not |
|---|---|---|
| `documents` | Dosya üst verisi, tür, kaynak, doküman tarihi, çıkarılan metin, özet, işleme durumu | Dosyanın kendisi `STORAGE_DIR/YYYY/AA/ab/<sha256>.<uzantı>` |
| `document_links` | Doküman ↔ proje (çoka çok), eşleşme yöntemi (manuel/kod/isim/ai), güven, geçiş sayısı | Elle eklenen bağ otomatik süreçle ezilmez |
| `chunks` + `chunks_fts` | Arama ve AI bağlamı için parçalar; parçanın ait olduğu proje | SQLite FTS5, Türkçe karakterleri normalize eder |
| `facts` | Dokümandan çıkarılmış tek bir bilgi: `durum, risk, engel, sonraki_adim, karar, olcum, not, saglik, asama, tarih, tanim, kazanim, kpi, aksiyon` | Her bilgi kaynak doküman + alıntı + tarih + güven taşır |
| `jobs` | Kalıcı iş kuyruğu (doküman işleme, sentez, haftalık yorum, boşluk analizi) | Sunucu yeniden başlarsa yarım işler kuyruğa döner |
| `ai_insights` | AI metinleri: haftalık portföy yorumu, boşluk analizi, proje sentezi | |
| `departments` | Ayarlanabilir departman listesi + ağrı noktaları | Kapsama haritası ve boşluk analizinin temeli |

## Bilgi (fact) yaşam döngüsü

```
bilgi      → salt bilgi; projenin bilgi akışında görünür (durum, risk, engel, karar, not…)
oneri      → proje alanını değiştirecek (sağlık, tarih, KPI, kazanım, tanım, aşama, aksiyon); onay bekler
onaylandi  → projeye uygulandı (kim, ne zaman kayıtlı)
reddedildi → uygulanmadı
atlandi    → aynı alan için başka bir öneri onaylandı
```

- Projedeki mevcut değerle aynı olan öneri otomatik olarak "bilgi"ye düşer (gereksiz onay yükü olmaz).
- Doküman yeniden işlenirse yalnızca `bilgi` ve `oneri` durumundakiler yeniden üretilir; insan kararları korunur.
- Çelişki: aynı proje + alan için **farklı dokümanların farklı değer** verdiği durumlar. Yönetici özetinde, proje
  sayfasında ve inceleme kuyruğunda listelenir.

## Neden bu tasarım?

1. **İzlenebilirlik:** Ekrandaki her değerin hangi dokümandan, hangi cümleden geldiği bilinir (`[D12]` atıfları).
2. **Birleştirme:** Aynı proje hakkında DT raporu, iç not, PDD ve kazanım dokümanı tek bir zaman akışında birleşir;
   AI sentezi bu birleşik veriye bakarak yorum yapar.
3. **Güvenli otomasyon:** AI proje kaydını doğrudan değiştirmez; öneri üretir, ekip onaylar.
4. **Ölçeklenebilirlik:** Büyük dokümanlar pencerelere bölünerek işlenir; arama FTS5 ile milisaniyeler içinde
   çalışır. Doküman sayısı on binlere çıktığında PostgreSQL + pgvector (anlamsal arama) geçişi şemaya dokunmadan yapılabilir.
5. **Dayanıklılık:** İşleme kuyruğu veritabanında durur; hata alan işler Ayarlar sayfasından tekrar denenir.

## Bilinen sınırlar / sonraki adımlar
- **Taranmış PDF / görsel:** Metin katmanı olmayan dosyalar "metin yok" olarak işaretlenir. OCR (Tesseract) eklenebilir.
- **Anlamsal arama:** Şu an anahtar kelime tabanlı (FTS5). Şirket içi bir embedding modeli varsa vektör arama eklenebilir.
- **Tablo yoğun Excel'ler:** Satırlar metne çevrilir; çok büyük tablolarda özel içe aktarım (ör. KPI şablonu) daha doğru sonuç verir.
