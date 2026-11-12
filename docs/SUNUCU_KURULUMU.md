# Sunucuya kurulum: baştan sona

**Sunucu:** DOASDMZAIWEBT01 · 192.168.75.30 (Ubuntu, DMZ)
**Bağlantı:** CyberArk → *Accounts View* → `dtpamcxaiteam` (kasa: DOASPamAIWEB)
**Ekibin adresi:** http://192.168.75.30:8000

Bu ortamda denenip doğrulananlar (Kasım 2026):

| Konu | Durum | Sonucu |
|---|---|---|
| Sunucunun internete çıkışı | Yok | Python paketleri bilgisayarda indirilip pakete eklenir |
| CyberArk'ta dosya kopyala-yapıştır | Kapalı (yazı yapıştırma açık) | Dosya yalnızca **P: sürücüsü** üzerinden gider |
| CyberArk'ta paylaşılan sürücü | Yalnızca P: (`\\ddimfps1\PUBLIC`) | Kök klasöre yazılamaz; P: altında yazabildiğiniz bir klasör gerekir |
| Ofisten `http://192.168.75.30:8000` | Erişilebiliyor | Ağ izni gerekmez |

Kurulum dört aşamadan oluşur. Sunucuya **yalnızca kod** gider. AI anahtarı ve veriler sonra **tarayıcıdan** girilir, böylece paylaşım klasörüne gizli bilgi konmaz.

---

## A. Bilgisayarınızda (≈10 dk)

**A1. Güncel kodu alın.** GitHub'dan dalın son hâlini (zip) indirip açın. İçindeki `app`, `deploy`, `docs` klasörlerini ve
`requirements.txt`, `.env.example` dosyalarını kendi proje klasörünüze kopyalayın, sorarsa üzerine yazın. `data` klasörü ve
`.env` dosyası yerinde kalsın.

**A2. Verilerinizin yedeğini indirin.** Proje klasöründe VS Code terminalinde uygulamayı başlatın:

```powershell
py -3.15 -m uvicorn app.main:app
```

Tarayıcıda http://127.0.0.1:8000/ayarlar adresini açın → **Yedek ve veri taşıma** → **⬇ Yedeği indir**.
`ai-impact-yedek-….tar.gz` dosyası İndirilenler klasörüne iner. Bu dosya D3'te tarayıcıdan yüklenecek, sunucuya gönderilmez.
Sonra terminalde **Ctrl+C** ile uygulamayı durdurun.

**A3. Kod paketini oluşturun.** Aynı terminalde çalıştırın:

```powershell
foreach ($v in "3.10","3.11","3.12") { py -3.15 -m pip download pip -r requirements.txt -d wheels --only-binary=:all: --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --python-version $v }
tar -czf ai-impact-kod.tgz app deploy docs requirements.txt .env.example wheels
```

`ai-impact-kod.tgz` (~35 MB) yalnızca kodu ve Python paketlerini içerir: **AI anahtarı ve proje verisi yoktur.**

## B. Paketi sunucuya taşıyın

**B1. P: sürücüsüne koyun.** P: sürücüsü `\\ddimfps1\PUBLIC` paylaşımıdır. Kök klasörüne yazılamaz; yazabildiğiniz bir alt
klasör gerekir. Klasör adını ekipten öğrenin; yoksa BT'den isteyin (talep metni: Ek A). Klasör adı `KlasörAdı` ise:

```powershell
Copy-Item .\ai-impact-kod.tgz "P:\KlasörAdı\"
```

**B2. WinSCP ile bağlanın.**
1. CyberArk'ta `dtpamcxaiteam` satırında **Connect** yanındaki oka basıp **WinSCP**'yi seçin.
2. Açılan güvenlik penceresinde (*RemoteApp security warning*) **Drives** ve **Clipboard** kutularını işaretleyip **Connect**'e basın.

**B3. Dosyayı sürükleyin.**
1. WinSCP'de sol panele tıklayın, **Ctrl+O** yapın ve **Browse…** düğmesine basın.
2. **This PC** altında **"P on <bilgisayar adınız>"** öğesini açın (ör. `P on DGNL1254`). B1'deki klasörü seçip **OK** ve tekrar **OK**'a basın.
3. Sol paneldeki `ai-impact-kod.tgz` dosyasını sağ panele (`/home/dtpamcxaiteam/`) sürükleyin.
4. Aktarımdan sonra dosyayı P: sürücüsünden silin.

Not: Soldaki "Desktop / My documents" CyberArk aracı sunucusunun klasörleridir, sizin bilgisayarınızın değil. Ctrl+C / Ctrl+V
ile dosya kopyalamayı CyberArk engeller; bu normaldir.

## C. Sunucuda kurulum (4 komut)

**C1. Terminali açın.** CyberArk'ta **Connect** (varsayılan, SSH) → güvenlik penceresinde **Clipboard** işaretli → **Connect**.
Açılan PuTTY penceresinde yapıştırma **farenin sağ tuşuyla** yapılır (Ctrl+V çalışmaz).

**C2. Kurun:**

```bash
mkdir ai-impact
tar -xzf ai-impact-kod.tgz -C ai-impact
cd ai-impact
bash deploy/kur.sh
```

Betik her adımı ✓ / ! ile raporlar ve sonunda ekibin adresini yazar. Şunları yapar:
- Python sanal ortamını kurar ve paketleri internetsiz yükler
- `.env` dosyasını rastgele bir `SECRET_KEY` ile hazırlar
- Uygulamayı başlatır: sudo yetkisi varsa sistem servisi olarak, yoksa kullanıcı modunda (açılışta ve 5 dakikada bir kendiliğinden başlar)
- Her gece yedek almayı ayarlar

"AI bağlantısı henüz yok" uyarısı bu aşamada normaldir; AI'ı D2'de bağlayacaksınız.

## D. Tarayıcıda (kendi bilgisayarınızdan)

**D1.** http://192.168.75.30:8000 adresini açın.

**D2. AI'ı bağlayın.** **Ayarlar → AI bağlantısı → ⚙ AI ayarlarını buradan girin**. Değerleri bilgisayarınızdaki `.env`
dosyasından (VS Code'da açıp) kopyalayın:

| Alan | `.env` satırı | Örnek |
|---|---|---|
| Adres | `AI_BASE_URL` | `https://customercommunication-aifoundry.services.ai.azure.com/openai/v1/responses` |
| Model / deployment adı | `AI_MODEL` | `gpt-5.6-sol` |
| API anahtarı | `AI_API_KEY` | (anahtarınız) |

**Kaydet**'e, ardından **Bağlantıyı test et**'e basın. Ayarlar hemen geçerli olur; yeniden başlatma gerekmez. Anahtar sayfada açık
gösterilmez ve yedeklere girmez. Test başarısız olursa çıkan "Ne yapmalı" notuna bakın. Sunucudan Azure'a çıkış kapalıysa BT'den
`customercommunication-aifoundry.services.ai.azure.com`, TCP 443 için izin istemek gerekir.

**D3. Verilerinizi taşıyın.** **Ayarlar → Yedek ve veri taşıma → Yedekten geri yükle** bölümünde A2'deki dosyayı seçin, onay
kutusunu işaretleyip **Geri yükle**'ye basın. Projeler, durum güncellemeleri, yorumlar ve dokümanlar sunucuya geçer.

**D4. Ekibi ekleyin ve girişi açın (önerilir).** Giriş kapalıyken adrese ulaşan herkes tam yetkilidir.
1. Sol alttaki **Yönetim** sayfasından ekip arkadaşlarınızı ekleyin:
   - **Dijital Dönüşüm Ekibi:** düzenler ve yükler
   - **Üst Yönetim / Görüntüleyici:** yalnızca okur
   - **Doğuş Teknoloji:** yalnızca kendisine açılan projeleri görür ve rapor yükler
   
   Parola alanını boş bırakırsanız geçici bir parola üretilir.
2. PuTTY'de girişi açın:
   ```bash
   cd ~/ai-impact && sed -i 's/^AUTH_ENABLED=.*/AUTH_ENABLED=1/' .env && bash deploy/servis.sh yeniden
   ```
3. Yönetici hesabıyla girin. D3'te verileri bilgisayarınızdan taşıdıysanız hesap `admin@demo.local`, parola `Admin123!` olur.
   **Yönetim** sayfasından bu parolayı hemen değiştirin.

---

## Günlük yönetim (PuTTY, `~/ai-impact` klasöründe)

| Komut | Ne yapar |
|---|---|
| `bash deploy/servis.sh durum` | Çalışıyor mu, yanıt veriyor mu |
| `bash deploy/servis.sh yeniden` | Yeniden başlatır (`.env` değişince gerekir; Ayarlar sayfasındaki AI değişikliğinde gerekmez) |
| `bash deploy/servis.sh log` | Son kayıtlar (hata ararken) |
| `bash deploy/yedekle.sh` | Elle yedek → `backups/`. Otomatik yedek her gece 02:30 alınır, son 14 yedek tutulur |

Yedek almanın kolay yolu: tarayıcıda **Ayarlar → Yedeği indir**.

## Yeni sürüme geçiş

1. Bilgisayarda A1 ve A3 adımlarını uygulayın. A2'ye gerek yok.
2. Paketi B1–B3 adımlarındaki gibi sunucuya taşıyın.
3. PuTTY'de çalıştırın:
   ```bash
   tar -xzf ~/ai-impact-kod.tgz -C ~/ai-impact && bash ~/ai-impact/deploy/guncelle.sh
   ```

Betik önce yedek alır, sonra paketleri günceller ve uygulamayı yeniden başlatır. Veriler, `.env` ve Ayarlar sayfasındaki AI
ayarları korunur.

## Yedekten geri dönüş

En kolayı tarayıcıdan: **Ayarlar → Yedekten geri yükle**. Hem indirilen yedekler hem `backups/` klasöründekiler kabul edilir;
`backups/` içindeki dosyayı almak için WinSCP'de sağ panelden P: klasörüne sürükleyin.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| Sunucu terminaline yapıştırılamıyor | Bağlanırken **Clipboard** işaretli olmalı; yapıştırma sağ tıkla yapılır |
| WinSCP'de P: görünmüyor | Bağlanırken **Drives** işaretli olmalı; **Ctrl+O → Browse → This PC** |
| `$'\r': command not found` | `sed -i 's/\r$//' deploy/*.sh` ve tekrar çalıştırın |
| "Uygun Python bulunamadı" | Ubuntu 20.04 gibi eski sürümde olur. github.com/astral-sh/python-build-standalone/releases sayfasından `cpython-3.12.…-x86_64-unknown-linux-gnu-install_only.tar.gz` dosyasını indirip pakete ekleyin. Sunucuda proje klasöründe `tar -xzf cpython-3.12*.tar.gz` çalıştırıp `bash deploy/kur.sh`'i tekrarlayın |
| "wheels klasöründe … uygun paket yok" | Sunucuda `python3 -V` ile sürümü öğrenin, A3'teki listeye ekleyip paketi yeniden oluşturun |
| `address already in use` | Port dolu: `PORT=8080 bash deploy/kur.sh` (adres de `:8080` olur) |
| AI çalışmıyor | **Ayarlar → Bağlantıyı test et / Derin tanılama** |
| Başka bir hata | `bash deploy/servis.sh log` çıktısının ekran görüntüsünü alın |

## Ek A: P: sürücüsünde aktarım klasörü talebi (BT Servis Masası)

> **Konu:** CyberArk üzerinden DMZ sunucusuna dosya aktarımı için P: (\\ddimfps1\PUBLIC) altında klasör
>
> Dijital Dönüşüm ekibi olarak DMZ'deki DOASDMZAIWEBT01 (192.168.75.30) sunucusuna iç kullanım için bir web uygulaması kuruyoruz.
> CyberArk'ta `DOASPamAIWEB` kasasındaki `dtpamcxaiteam` hesabıyla WinSCP üzerinden bağlanıyoruz. Bağlantıda yalnızca P: sürücüsü
> (\\ddimfps1\PUBLIC) yönlendiriliyor, ancak bu paylaşımda yazabileceğimiz bir klasör yok. `\\ddimfps1\PUBLIC` altında yalnızca
> Dijital Dönüşüm ekibinin okuyup yazabileceği bir aktarım klasörü açılabilir mi? CyberArk aktarımları için tanımlı standart bir
> klasör varsa yolunu iletebilir misiniz?

## HTTPS (sonraki adım)

Kurumsal sertifika alındığında uygulamanın önüne Nginx konur. Uygulama 8000 portunda kalır, Nginx 443 portunda sertifikayla
yayınlar (örnek ayar: README → "DMZ sunucusuna kurulum"). HTTPS'e geçince `.env`'de `COOKIE_SECURE=1` yapıp yeniden başlatın.
