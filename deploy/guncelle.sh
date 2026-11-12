#!/usr/bin/env bash
# Yeni sürüme geçiş:  bash deploy/guncelle.sh
# Önce yeni sürümün app/ klasörünü ve requirements.txt dosyasını bu klasörün üzerine kopyalayın
# (git ile kurulduysa gerek yok: betik git pull yapar). Veriler (data/) ve .env'e dokunulmaz.
set -euo pipefail
cd "$(dirname "$0")/.."
sed -i 's/\r$//' deploy/*.sh requirements.txt 2>/dev/null || true
echo "==> Yedek"
bash deploy/yedekle.sh
if [ -d .git ]; then
  echo "==> Kod güncelleniyor (git pull)"
  git pull --ff-only
fi
echo "==> Paketler"
if [ -d wheels ]; then .venv/bin/python -m pip install --quiet --no-index --find-links wheels -r requirements.txt
else .venv/bin/python -m pip install --quiet -r requirements.txt; fi
echo "==> Yeniden başlatılıyor"
bash deploy/servis.sh yeniden
sleep 3
bash deploy/servis.sh durum
echo "Tamam. Tarayıcıda sayfayı bir kez Ctrl+F5 ile yenileyin."
