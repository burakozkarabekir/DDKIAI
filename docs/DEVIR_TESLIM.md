# Devir teslim: AI Impact Merkezi

Dijital Dönüşüm ekibinin AI Impact projelerini takip ettiği uygulama. Trello'nun yerini alır. Projeler, DT haftalık raporları
ve yönetici özetleri, AI analizleri, AI Security ve Copilot metrikleri burada tutulur.

## Nerede, nasıl?

| | |
|---|---|
| **Adres** | http://192.168.75.30:8000 |
| **Sunucu** | DOASDMZAIWEBT01 · 192.168.75.30 · Ubuntu (DMZ, internete kapalı) |
| **Sunucu erişimi** | CyberArk → `dtpamcxaiteam` (kasa: DOASPamAIWEB). Terminal: **Connect**. Dosya: **Connect ▼ → WinSCP**. Bağlanırken **Drives** ve **Clipboard** işaretlenir |
| **Uygulama klasörü** | `/home/dtpamcxaiteam/ai-impact` |
| **Veriler** | `ai-impact/data` (veritabanı `app.db` + `files/` dokümanlar) |
| **Yedekler** | Her gece 02:30 `ai-impact/backups/` klasörüne alınır, son 14 yedek tutulur. İstenirse tarayıcıdan: **Ayarlar → Yedeği indir** |
| **AI** | Azure AI Foundry · `customercommunication-aifoundry` · deployment `gpt-5.6-sol`. Ayar ve anahtar: **Ayarlar → AI bağlantısı** |
| **Kullanıcılar** | **Yönetim** sayfası (rol: Dijital Dönüşüm Ekibi / Üst Yönetim / Görüntüleyici / Doğuş Teknoloji) |

## Belgeler

- [Sunucuya kurulum, güncelleme, sorun giderme](SUNUCU_KURULUMU.md)
- [Süreç tasarımı: kim ne zaman ne yapar](SUREC_TASARIMI.md)
- [Veri mimarisi: dokümanlardan bilgi çıkarma](VERI_MIMARISI.md)
- Genel bakış: README

## Rutin işler

| Ne zaman | İş | Nasıl |
|---|---|---|
| Her hafta | DT durum raporlarını yükle, inceleme kuyruğunu onayla | **Dokümanlar → Yükle**, **İnceleme Kuyruğu** |
| Her hafta | Proje durumlarını güncelle | **Durum Girişi** |
| Her ay | Copilot kullanım Excel'ini yükle | **AI Security → Copilot Kullanımı** |
| Arada bir | Uygulama ayakta mı, yedek alınıyor mu | PuTTY: `cd ~/ai-impact && bash deploy/servis.sh durum && ls -lt backups | head -3` |
| Anahtar yenilenince | Yeni Azure anahtarını gir | **Ayarlar → AI bağlantısı** |
| Yeni sürüm gelince | Güncelle | SUNUCU_KURULUMU.md → "Yeni sürüme geçiş" |

## Bilinmesi gerekenler

- **Dosya aktarımı:** CyberArk yalnızca P: sürücüsünü (`\\ddimfps1\PUBLIC`) geçirir ve dosya kopyala-yapıştırı engeller. Sunucuya dosya (yeni sürüm) yalnızca P: altındaki bir klasör üzerinden gider. Dokümanlar ve veriler ise tarayıcıdan yüklenir.
- **İnternet:** Sunucu internete çıkamaz. Python paketleri güncellemelerde bilgisayarda indirilip pakete eklenir.
- **Giriş ekranı:** `AUTH_ENABLED=1` (sunucuda `.env`) iken herkes kendi hesabıyla girer. Kapalıyken adrese ulaşan herkes tam yetkilidir.
- **AI'sız çalışma:** AI bağlantısı koparsa uygulama "demo modunda" çalışmaya devam eder: dokümanlar kural tabanlı işlenir, analizler basit olur. Bağlantı gelince **Ayarlar → Bu dokümanları yeniden işle** ile AI'la yeniden işlenir.

## Ayrılmadan önce kontrol listesi (Burak)

- [ ] Uygulama sunucuda çalışıyor, ekipten biri adresi açabildi
- [ ] Veriler taşındı (**Ayarlar → Geri yükle**), AI bağlantı testi başarılı
- [ ] Ekip kullanıcıları eklendi, giriş açıldı, `admin@demo.local` parolası değişti ve yeni parola sorumluya verildi
- [ ] Bir ekip arkadaşı CyberArk ile sunucuya bağlanıp `bash deploy/servis.sh durum` çalıştırabildi
- [ ] Kod deposu (GitHub `burakozkarabekir/DDKIAI`, kişisel hesap) ekibe ya da şirket hesabına devredildi, ya da kodun son hâli (zip) ekibe verildi
- [ ] Azure AI anahtarının sahibi ve yenileme sorumlusu belli
- [ ] Sorumlu kişi: ______________________
