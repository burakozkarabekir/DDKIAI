# Sunucuya kurulum (DMZ — DOASDMZAIWEBT01)

Bu rehber uygulamayı DMZ'deki Linux sunucuya kurup ekibin tarayıcıdan kullanmasını sağlar.
Sunucu: **DOASDMZAIWEBT01 · 192.168.75.30** · Bağlantı: CyberArk → *Accounts View* → `dtpamcxaiteam` → **Connect**.
Süre: ~20 dakika (ağ izinleri hariç). Docker gerekmez.

Sonuçta ekip arkadaşlarınız şu adresi açar: **http://192.168.75.30:8000**

---

> **Terminale yapıştırma:** CyberArk'ın açtığı PuTTY penceresinde Ctrl+V çalışmaz; **farenin sağ tuşuna** tıklayın (ya da
> Shift+Insert). Hiçbiri yapıştırmıyorsa CyberArk panoyu kapatmıştır: komutları elle yazın. Rehberdeki zorunlu komutlar kısadır
> (adım 2c ve 3); uzun komutlar yalnızca kendi bilgisayarınızda (PowerShell) çalıştırılır.

## 1. Sunucuyu tanıyın (2 dk, isteğe bağlı)

`deploy/kur.sh` bu kontrolleri zaten yapar. Önceden bakmak isterseniz CyberArk'ta **Connect** ile bağlanıp şunları çalıştırın
(elle yazacaksanız yalnızca ilk iki satır yeterli: `python3 -V` ve `sudo -n true && echo VAR`):

```bash
grep PRETTY /etc/os-release; python3 --version; ls /usr/bin/python3.1* 2>/dev/null
sudo -n true 2>/dev/null && echo "sudo: VAR" || echo "sudo: YOK"
curl -s -o /dev/null -w "pypi: %{http_code}\n" --max-time 10 https://pypi.org/simple/ || echo "pypi: ERİŞİM YOK"
curl -s -o /dev/null -w "azure: %{http_code}\n" --max-time 10 https://customercommunication-aifoundry.services.ai.azure.com || echo "azure: ERİŞİM YOK"
```

| Çıktı | Anlamı |
|---|---|
| Python **3.10 veya üzeri** var (ör. `python3.11`) | Hazır. Yoksa sunucu ekibinden isteyin: RHEL/Rocky `sudo dnf install -y python3.11`, Ubuntu `sudo apt-get install -y python3 python3-venv` |
| `sudo: VAR` | Uygulama **sistem servisi** olarak kurulur (sunucu açılınca kendiliğinden başlar). `YOK` ise kullanıcı modunda çalışır; otomatik başlatma cron ile yapılır. İkisi de olur. |
| `pypi: 200` | Paketler internetten iner. `ERİŞİM YOK` ise **İnternetsiz kurulum** (aşağıda). |
| `azure: 200/401/404` (herhangi bir sayı) | AI uç noktasına çıkış var. `ERİŞİM YOK` ise adım 4'teki talebe AI çıkışını ekleyin. |

## 2. Dosyaları sunucuya taşıyın

**a) Bilgisayarınızda paketleyin.** DMZ sunucusu internete çıkamadığı için Python paketleri de bilgisayarınızda indirilip
pakete eklenir.

1. GitHub'dan dalın son hâlini indirip açın. İçindeki `app`, `deploy`, `docs` klasörlerini ve `requirements.txt`,
   `.env.example` dosyalarını kendi proje klasörünüze kopyalayın (üzerine yazın). Klasördeki `data` ve `.env` yerinde kalsın.
2. Bilgisayarınızdaki uygulamayı durdurun (terminalde Ctrl+C).
3. Proje klasöründe PowerShell'de çalıştırın:

```powershell
foreach ($v in "3.10","3.11","3.12") { py -3.15 -m pip download pip -r requirements.txt -d wheels --only-binary=:all: --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --python-version $v }
tar -czf ai-impact.tgz app deploy docs requirements.txt .env.example .env data wheels
```

- `wheels` klasörü, sunucudaki Python 3.10/3.11/3.12 için paketleri içerir (~26 MB). Ubuntu 22.04'te 3.10, 24.04'te 3.12 gelir.
- `data` mevcut verilerinizi (projeler, dokümanlar, yorumlar) taşır.
- `.env` AI ayarlarınızı taşır.

Taşıdıktan sonra herkes sunucudaki adresi kullanmalı; bilgisayarınızdaki kopya eski kalır.

**b) Sunucuya gönderin.** CyberArk'ta **Connect** düğmesinin yanındaki oka tıklayın. Listede **WinSCP / SFTP** varsa onunla
bağlanıp `ai-impact.tgz` dosyasını ev klasörünüze (`/home/dtpamcxaiteam`) sürükleyin. Listede yoksa PAM ekibinden bu sunucu için
dosya aktarım (PSM-WinSCP / SFTP) bağlantısı isteyin.

> Alternatif: sunucu GitHub'a çıkabiliyorsa `git clone -b claude/dogus-ai-impact-tracking-lmxuqo https://github.com/burakozkarabekir/DDKIAI.git ~/ai-impact`
> (özel depo için GitHub'dan salt okunur bir erişim anahtarı gerekir). Bu yolda `.env` dosyasını sunucuda `nano ~/ai-impact/.env` ile
> oluşturup değerleri yapıştırırsınız; veriler boş başlar (Trello'yu yeniden aktarabilirsiniz).

**c) Sunucuda açın** (kısa komutlar, elle yazılabilir):

```bash
mkdir ai-impact
tar -xzf ai-impact.tgz -C ai-impact
cd ai-impact
```

## 3. Kurun (tek komut)

```bash
bash deploy/kur.sh
```

Betik sırasıyla şunları yapar ve her adımı ✓ / ! ile raporlar:

1. Uygun Python'u bulur
2. `.venv` sanal ortamını kurar, paketleri yükler
3. `.env`'i hazırlar: varsayılan `SECRET_KEY`'i rastgele değerle değiştirir, dosyayı yalnızca size okunur yapar
4. Uygulamayı başlatır: sudo varsa `ai-impact` systemd servisi, yoksa kullanıcı modu
5. Her gece 02:30 yedek, sudo yoksa açılışta ve 5 dakikada bir otomatik başlatma (cron)
6. Sunucunun kendi güvenlik duvarında portu açar (sudo varsa)
7. Uygulamanın yanıt verdiğini ve AI bağlantısını dener, ekibin açacağı adresi yazar

Port 8000 doluysa: `PORT=8080 bash deploy/kur.sh`. Betiği tekrar çalıştırmak güvenlidir; veriler ve `.env` korunur.

## 4. Ağ erişimi (ağ / güvenlik ekibine talep)

Uygulama sunucuda çalışsa da DMZ'deki kurumsal güvenlik duvarı ofis ağından erişimi engelliyor olabilir. Bir ekip arkadaşınız
tarayıcıda `http://192.168.75.30:8000` adresini açamıyorsa şu talebi iletin:

```
Konu: DMZ'deki AI Impact Merkezi uygulaması için erişim izni

1) İç ağdan sunucuya (gelen):
   Kaynak : Doğuş Otomotiv iç ağ / VPN kullanıcıları (ya da Dijital Dönüşüm ekibinin ağ segmenti)
   Hedef  : 192.168.75.30 (DOASDMZAIWEBT01)
   Port   : TCP 8000 (HTTP)  — ileride HTTPS için TCP 443
   Amaç   : Dijital Dönüşüm ekibinin AI proje takip uygulaması (iç kullanım)

2) Sunucudan dışarı (giden):
   Kaynak : 192.168.75.30
   Hedef  : customercommunication-aifoundry.services.ai.azure.com, TCP 443
   Amaç   : Uygulamanın AI analizleri için şirketin Azure AI Foundry kaynağı

3) (Yalnızca kurulum sırasında, geçici) pypi.org ve files.pythonhosted.org, TCP 443
   — gerek yoksa "İnternetsiz kurulum" kullanılacak.

İsteğe bağlı: aiimpact.<şirket-alan-adı> gibi bir DNS kaydı → 192.168.75.30
```

## 5. Giriş ekranını açın (önerilir)

Giriş kapalıyken (`AUTH_ENABLED=0`) sunucuya ağdan ulaşan herkes uygulamayı tam yetkiyle kullanır ve tüm işlemler
"Dijital Dönüşüm Ekibi" ortak hesabına yazılır. Ekip kullanacağı için girişi açmanızı öneririm:

1. Giriş açılmadan önce uygulamada sol alttaki **Yönetim** sayfasından ekip arkadaşlarınızı ekleyin:
   - **Dijital Dönüşüm Ekibi:** düzenler ve yükler
   - **Üst Yönetim / Görüntüleyici:** yalnızca okur
   - **Doğuş Teknoloji:** yalnızca kendisine açılan projeleri görür ve rapor yükler
   
   Parola alanını boş bırakırsanız geçici bir parola üretilir; kişiye iletin.
2. Sunucuda girişi açın:
   ```bash
   cd ~/ai-impact && sed -i 's/^AUTH_ENABLED=.*/AUTH_ENABLED=1/' .env && bash deploy/servis.sh yeniden
   ```
3. Yönetici hesabıyla girin. Verileri bilgisayarınızdan taşıdıysanız hesap `admin@demo.local`, parola `Admin123!` olur.
   **Yönetim** sayfasından bu parolayı hemen değiştirin.

## 6. Günlük yönetim

Tüm komutlar `~/ai-impact` klasöründe çalıştırılır:

| Komut | Ne yapar |
|---|---|
| `bash deploy/servis.sh durum` | Çalışıyor mu, yanıt veriyor mu |
| `bash deploy/servis.sh yeniden` | Yeniden başlatır (`.env` değişikliğinden sonra gerekir) |
| `bash deploy/servis.sh durdur` / `baslat` | Durdurur / başlatır |
| `bash deploy/servis.sh log` | Son kayıtlar (hata ararken) |
| `bash deploy/yedekle.sh` | Elle yedek → `backups/` klasörü (otomatik yedek her gece 02:30, son 14 yedek tutulur) |
| `nano .env` | AI ve diğer ayarlar; kaydettikten sonra `bash deploy/servis.sh yeniden` |

## 7. Yeni sürüme geçiş

1. Bilgisayarınızda yeni sürümü GitHub'dan indirip klasöründe paketleyin. **`data` ve `.env` eklemeyin**, yoksa sunucudaki
   verilerin üzerine yazılır:
   ```powershell
   foreach ($v in "3.10","3.11","3.12") { py -3.15 -m pip download pip -r requirements.txt -d wheels --only-binary=:all: --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --python-version $v }
   tar -czf guncelleme.tgz app deploy docs requirements.txt wheels
   ```
2. Dosyayı aynı yolla sunucuya gönderin ve sunucuda çalıştırın:
   ```bash
   tar -xzf ~/guncelleme.tgz -C ~/ai-impact && bash ~/ai-impact/deploy/guncelle.sh
   ```
   Betik önce yedek alır, paketleri günceller ve uygulamayı yeniden başlatır. Veritabanı değişiklikleri açılışta kendiliğinden yapılır.
   (git ile kurduysanız yalnızca 2. adımdaki `guncelle.sh` yeterli; kodu kendisi çeker.)

## 8. Yedekten geri dönüş

```bash
cd ~/ai-impact && bash deploy/servis.sh durdur
tar -xzf backups/ai-impact-YYYYAAGG-SSDD.tar.gz -C /tmp
cp -a /tmp/ai-impact/data/. data/ && bash deploy/servis.sh baslat
```

## İnternetsiz kurulum

Adım 2a'daki paket bunu zaten yapar: `deploy/kur.sh` `wheels` klasörünü görünce internete çıkmadan kurar. Ubuntu'da
`python3-venv` paketi kurulu değilse (internetsiz sunucuda kurulamaz) betik pip'siz sanal ortam açar ve pip'i `wheels`
içindeki paketten çalıştırır; ek bir şey yapmanız gerekmez.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `$'\r': command not found` | Dosyalar Windows'ta düzenlenmiş: `sed -i 's/\r$//' deploy/*.sh` ve tekrar çalıştırın |
| "Uygun Python bulunamadı" (ör. Ubuntu 20.04'te Python 3.8) | Taşınabilir Python kullanın: github.com/astral-sh/python-build-standalone/releases sayfasından `cpython-3.12.…-x86_64-unknown-linux-gnu-install_only.tar.gz` dosyasını indirip pakete ekleyin. Sunucuda proje klasöründe `tar -xzf cpython-3.12*.tar.gz` (bir `python` klasörü açılır), sonra tekrar `bash deploy/kur.sh`. Betik bu Python'u kendiliğinden kullanır |
| "wheels klasöründe bu Python sürümüne uygun paket yok" | Sunucudaki sürümü öğrenin (`python3 -V`) ve 2a'daki `foreach` listesine ekleyip paketi yeniden oluşturun |
| `address already in use` | Port dolu: `PORT=8080 bash deploy/kur.sh` (adres de `:8080` olur) |
| Sunucuda `servis.sh durum` "yanıt veriyor" diyor ama ekip açamıyor | Ağ izni eksik: adım 4 |
| AI analizleri çalışmıyor | Uygulamada **Ayarlar → Bağlantıyı test et / Derin tanılama**. Sunucudan Azure'a çıkış yoksa adım 4, madde 2 |
| Paketler inmiyor | Proxy gerekiyorsa `export HTTPS_PROXY=http://proxy-adresi:port` ve tekrar kurun, ya da İnternetsiz kurulum |
| Başka bir hata | `bash deploy/servis.sh log` çıktısının ekran görüntüsünü paylaşın |

## HTTPS (sonraki adım)

Kurumsal sertifika alındığında önüne Nginx konur: uygulama 8000'de kalır, Nginx 443'te sertifikayla yayınlar
(örnek ayar: README → "DMZ sunucusuna kurulum"). HTTPS'e geçince `.env`'de `COOKIE_SECURE=1` yapıp yeniden başlatın.
