#!/usr/bin/env bash
# AI Impact Merkezi — Linux sunucuya kurulum (Docker gerekmez).
#
#   Proje klasöründe:   bash deploy/kur.sh
#   Farklı port:        PORT=8080 bash deploy/kur.sh
#   Belirli Python:     PYTHON=python3.11 bash deploy/kur.sh
#
# Tekrar çalıştırmak güvenlidir: mevcut .env, veriler ve dokümanlar korunur.
set -euo pipefail
cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"
SERVICE=ai-impact

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ -f app/main.py ] && [ -f requirements.txt ] || die "Bu komutu proje klasöründe çalıştırın (içinde app/ ve requirements.txt olan klasör)."
# Windows'ta düzenlenen dosyalardaki CRLF satır sonlarını düzelt
sed -i 's/\r$//' deploy/*.sh requirements.txt 2>/dev/null || true
[ -f .env ] && sed -i 's/\r$//' .env

# ---------------------------------------------------------------- 1) Python
say "1/6 Python kontrolü (3.10 veya üzeri gerekir)"
PY=""
for c in ${PYTHON:-} python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  echo "    Uygun Python bulunamadı. Mevcut: $(python3 --version 2>&1 || echo 'python3 yok')"
  if command -v dnf >/dev/null 2>&1; then echo "    Kurulum (RHEL/Rocky/Alma 8-9):  sudo dnf install -y python3.11 python3.11-pip"
  elif command -v yum >/dev/null 2>&1; then echo "    Kurulum:  sudo yum install -y python3.11"
  elif command -v apt-get >/dev/null 2>&1; then echo "    Kurulum (Ubuntu/Debian):  sudo apt-get install -y python3 python3-venv"
  fi
  die "Python kurulduktan sonra bu komutu tekrar çalıştırın (sudo yetkiniz yoksa sunucu ekibinden isteyin)."
fi
ok "$("$PY" --version) → $PY"

# ---------------------------------------------------------------- 2) paketler
say "2/6 Sanal ortam (.venv) ve paketler"
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv || { rm -rf .venv; die "Sanal ortam kurulamadı. Ubuntu/Debian'da: sudo apt-get install -y python3-venv"; }
fi
VPY="$APP_DIR/.venv/bin/python"
if [ -d wheels ]; then
  "$VPY" -m pip install --quiet --no-index --find-links wheels -r requirements.txt \
    || die "wheels klasöründeki paketler bu Python sürümüne uymuyor. docs/SUNUCU_KURULUMU.md → 'İnternetsiz kurulum'."
else
  "$VPY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  "$VPY" -m pip install --quiet -r requirements.txt \
    || die "Paketler indirilemedi. Sunucu pypi.org'a çıkamıyorsa docs/SUNUCU_KURULUMU.md → 'İnternetsiz kurulum'. Proxy gerekiyorsa önce: export HTTPS_PROXY=http://proxy-adresi:port"
fi
ok "Paketler kuruldu"

# ---------------------------------------------------------------- 3) .env
say "3/6 Ayar dosyası (.env)"
if [ ! -f .env ]; then
  cp .env.example .env
  warn ".env oluşturuldu. AI bağlantısı için AI_BASE_URL, AI_API_KEY, AI_MODEL satırlarını doldurun:  nano .env"
fi
if ! grep -qE '^SECRET_KEY=.{24,}$' .env || grep -qE '^SECRET_KEY=degistir-beni' .env; then
  KEY="$("$VPY" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  if grep -q '^SECRET_KEY=' .env; then sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$KEY|" .env; else echo "SECRET_KEY=$KEY" >> .env; fi
  ok "SECRET_KEY rastgele bir değerle değiştirildi"
fi
if grep -qE '^PORT=' .env; then
  [ -n "${PORT:-}" ] && sed -i "s|^PORT=.*|PORT=$PORT|" .env
else
  echo "PORT=${PORT:-8000}" >> .env
fi
PORT="$(grep -E '^PORT=' .env | tail -1 | cut -d= -f2)"
chmod 600 .env
mkdir -p data
ok ".env hazır (port $PORT)"
grep -qE '^AUTH_ENABLED=1' .env || warn "Giriş ekranı kapalı (AUTH_ENABLED=0): sunucuya ağdan ulaşan herkes uygulamayı tam yetkiyle kullanır. Ekip için önerilen: AUTH_ENABLED=1 (docs/SUNUCU_KURULUMU.md, adım 5)."

# ---------------------------------------------------------------- 4) servis
say "4/6 Servis (sunucu açılınca otomatik başlasın)"
install_unit() {
  # python -m uvicorn: SELinux, ev klasöründeki betiklerin servis olarak çalıştırılmasını engelleyebilir
  sudo -n tee /etc/systemd/system/$SERVICE.service >/dev/null <<EOF
[Unit]
Description=AI Impact Merkezi
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$APP_DIR
ExecStart=$VPY -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
  sudo -n systemctl daemon-reload && sudo -n systemctl enable $SERVICE >/dev/null 2>&1 && sudo -n systemctl restart $SERVICE
}
# systemd gerçekten çalışıyorsa (/run/systemd/system) ve sudo parola istemiyorsa servis olarak kur
if [ -d /run/systemd/system ] && sudo -n true 2>/dev/null; then
  bash deploy/servis.sh durdur >/dev/null 2>&1 || true   # önceki kullanıcı modu kurulumundan kalan süreç
  if install_unit; then
    ok "systemd servisi kuruldu ve başlatıldı ($SERVICE)"
  else
    sudo -n rm -f /etc/systemd/system/$SERVICE.service
    sudo -n systemctl daemon-reload 2>/dev/null || true
    warn "systemd servisi kurulamadı: uygulama kullanıcı modunda çalıştırılıyor."
    bash deploy/servis.sh yeniden
  fi
else
  if [ -d /run/systemd/system ]; then warn "sudo yetkisi yok (ya da parola istiyor): uygulama kullanıcı modunda çalıştırılıyor."
  else warn "systemd çalışmıyor: uygulama kullanıcı modunda çalıştırılıyor."; fi
  bash deploy/servis.sh yeniden
fi
# günlük yedek; kullanıcı modunda ayrıca açılışta ve 5 dakikada bir "çalışıyor mu" kontrolü
if command -v crontab >/dev/null 2>&1; then
  {
    crontab -l 2>/dev/null | grep -v "$APP_DIR/deploy/" || true
    echo "30 2 * * * bash '$APP_DIR/deploy/yedekle.sh' >/dev/null 2>&1"
    if ! [ -f /etc/systemd/system/$SERVICE.service ]; then
      echo "@reboot bash '$APP_DIR/deploy/servis.sh' baslat --sessiz >/dev/null 2>&1"
      echo "*/5 * * * * bash '$APP_DIR/deploy/servis.sh' baslat --sessiz >/dev/null 2>&1"
    fi
  } | crontab - 2>/dev/null && ok "Zamanlanmış görevler: her gece 02:30 yedek$([ -f /etc/systemd/system/$SERVICE.service ] || echo '; açılışta ve 5 dakikada bir otomatik başlatma')" \
    || warn "crontab kullanılamıyor: yedek ve otomatik başlatma elle yapılmalı (bash deploy/yedekle.sh, bash deploy/servis.sh baslat)."
else
  warn "crontab yok: sunucu yeniden başlarsa 'bash deploy/servis.sh baslat' ile başlatın."
fi

# ---------------------------------------------------------------- 5) güvenlik duvarı
say "5/6 Sunucunun güvenlik duvarı"
if command -v firewall-cmd >/dev/null 2>&1 && sudo -n firewall-cmd --state >/dev/null 2>&1; then
  if sudo -n firewall-cmd --query-port="$PORT/tcp" >/dev/null 2>&1; then ok "firewalld: $PORT/tcp zaten açık"
  else sudo -n firewall-cmd --permanent --add-port="$PORT/tcp" >/dev/null && sudo -n firewall-cmd --reload >/dev/null && ok "firewalld: $PORT/tcp açıldı"; fi
elif command -v ufw >/dev/null 2>&1 && sudo -n ufw status 2>/dev/null | grep -q "Status: active"; then
  sudo -n ufw allow "$PORT/tcp" >/dev/null && ok "ufw: $PORT/tcp açıldı"
else
  warn "Sunucudaki güvenlik duvarı kontrol edilemedi (kapalı ya da sudo yok)."
fi
warn "Ofis ağından DMZ'ye erişim için kurumsal güvenlik duvarında da TCP $PORT izni gerekir (docs/SUNUCU_KURULUMU.md, adım 4)."

# ---------------------------------------------------------------- 6) kontrol
say "6/6 Kontrol"
up=0
for _ in $(seq 1 30); do
  if "$VPY" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/saglik', timeout=3)" 2>/dev/null; then up=1; break; fi
  sleep 1
done
[ "$up" = 1 ] || die "Uygulama yanıt vermiyor. Kayıtlara bakın:  bash deploy/servis.sh log"
ok "Uygulama çalışıyor: http://127.0.0.1:$PORT"
echo "    AI bağlantısı deneniyor (en fazla ~1 dk)…"
"$VPY" - <<'EOF' || true
from app import ai
r = ai.diagnose()
for s in r["steps"]:
    print(f"      {'✓' if s['ok'] else '✗'} {s['name']}: {str(s['detail'])[:150]}")
    if s.get("fix") and not s["ok"]:
        print(f"        → {s['fix'][:400]}")
print("    " + ("AI bağlantısı çalışıyor." if r["ok"] else "AI bağlantısı kurulamadı; uygulama demo modunda çalışır. Ayarlar → Derin tanılama."))
EOF

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
printf '\n\033[1;32mKurulum tamam.\033[0m Ekip arkadaşlarınız tarayıcıda şu adresi açsın:\n\n    http://%s:%s\n\n' "${IP:-<sunucu-ip>}" "$PORT"
echo "Yönetim:  bash deploy/servis.sh durum | yeniden | durdur | log    ·    Güncelleme: bash deploy/guncelle.sh"
