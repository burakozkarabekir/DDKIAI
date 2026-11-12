#!/usr/bin/env bash
# Veritabanı + yüklenen dokümanlar + .env yedeği:  bash deploy/yedekle.sh
# backups/ai-impact-YYYYAAGG-SSDD.tar.gz oluşturur, son 14 yedeği tutar. Kurulum her gece 02:30 için cron'a ekler.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f data/app.db ] || { echo "data/app.db yok; yedeklenecek veri bulunamadı."; exit 0; }
umask 077
mkdir -p backups
TS="$(date +%Y%m%d-%H%M)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# çalışan uygulamayı durdurmadan tutarlı kopya (SQLite online backup)
.venv/bin/python - "$TMP/app.db" <<'EOF'
import sqlite3, sys
src = sqlite3.connect("data/app.db")
dst = sqlite3.connect(sys.argv[1])
src.backup(dst)
dst.close(); src.close()
EOF
mkdir -p "$TMP/ai-impact/data"
mv "$TMP/app.db" "$TMP/ai-impact/data/app.db"
[ -d data/files ] && cp -a data/files "$TMP/ai-impact/data/files"
[ -f .env ] && cp -a .env "$TMP/ai-impact/.env"
tar -czf "backups/ai-impact-$TS.tar.gz" -C "$TMP" ai-impact
ls -1t backups/ai-impact-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "Yedek alındı: backups/ai-impact-$TS.tar.gz ($(du -h "backups/ai-impact-$TS.tar.gz" | cut -f1))"
