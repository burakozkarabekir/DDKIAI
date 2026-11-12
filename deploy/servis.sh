#!/usr/bin/env bash
# AI Impact Merkezi'ni yönet:  bash deploy/servis.sh baslat | durdur | yeniden | durum | log
# systemd servisi kuruluysa onu kullanır; değilse (sudo yetkisi yoksa) uygulamayı kullanıcı olarak arka planda çalıştırır.
set -uo pipefail
cd "$(dirname "$0")/.."
SERVICE=ai-impact
PORT="$(grep -E '^PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '\r')"
PORT="${PORT:-8000}"
PIDF=data/ai-impact.pid
LOG=data/ai-impact.log
VPY=.venv/bin/python
QUIET=0; [ "${2:-}" = "--sessiz" ] && QUIET=1

systemd_mode() { [ -d /run/systemd/system ] && [ -f /etc/systemd/system/$SERVICE.service ]; }
running() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }
healthy() { "$VPY" -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:$PORT/saglik', timeout=5).read().decode())" 2>/dev/null; }

start() {
  if systemd_mode; then sudo -n systemctl start $SERVICE; return; fi
  if running; then [ $QUIET = 1 ] || echo "Zaten çalışıyor (PID $(cat $PIDF))."; return 0; fi
  [ -x "$VPY" ] || { echo "Önce kurulum: bash deploy/kur.sh"; return 1; }
  mkdir -p data
  [ -f "$LOG" ] && [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt 20000000 ] && mv -f "$LOG" "$LOG.1"
  nohup "$VPY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --no-access-log >> "$LOG" 2>&1 < /dev/null &
  echo $! > "$PIDF"
  [ $QUIET = 1 ] || echo "Başlatıldı (PID $!, port $PORT). Kayıtlar: $LOG"
}

stop() {
  if systemd_mode; then sudo -n systemctl stop $SERVICE; return; fi
  if running; then
    kill "$(cat "$PIDF")"
    for _ in $(seq 1 15); do running || break; sleep 1; done
    running && kill -9 "$(cat "$PIDF")" 2>/dev/null
    echo "Durduruldu."
  else
    echo "Çalışmıyordu."
  fi
  rm -f "$PIDF"
}

case "${1:-durum}" in
  baslat)  start ;;
  durdur)  stop ;;
  yeniden) stop; sleep 1; start ;;
  durum)
    if systemd_mode; then systemctl status $SERVICE --no-pager -n 0 | head -5; elif running; then echo "Çalışıyor (PID $(cat $PIDF), port $PORT)"; else echo "Çalışmıyor."; fi
    if out="$(healthy)"; then echo "Yanıt veriyor: $out"; else echo "http://127.0.0.1:$PORT yanıt vermiyor."; fi ;;
  log)
    if systemd_mode; then sudo -n journalctl -u $SERVICE -n 150 --no-pager 2>/dev/null || journalctl -u $SERVICE -n 150 --no-pager
    else tail -n 150 "$LOG"; fi ;;
  *) echo "Kullanım: bash deploy/servis.sh baslat | durdur | yeniden | durum | log"; exit 1 ;;
esac
