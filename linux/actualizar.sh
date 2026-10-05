#!/bin/sh
# Actualización diaria desde GitHub (rama main), pensada para la máquina que vigila.
#
# 1. Si main no cambió, no hace nada.
# 2. Solo actualiza si la revisión automática de GitHub (Actions) pasó para ese commit.
# 3. Instala dependencias si cambió requirements.txt y comprueba que el código cargue.
# 4. Reinicia el servidor y verifica que vuelvan a llegar datos de las estaciones.
# 5. Si algo falla, vuelve sola a la versión anterior.
# Avisa por Telegram (TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env) y escribe en
# actualizar.log. Los ajustes propios de esta máquina van en config_local.py, que git no
# toca, así que nunca chocan con lo que suben los demás.
#
# Uso: sh linux/actualizar.sh            actualizar si hay cambios
#      sh linux/actualizar.sh --forzar   aunque la revisión de GitHub no haya pasado
cd "$(dirname "$0")/.." || exit 1
REPO="jduquetr/SismoAlert"
SERVICE="sismoalert"
LOG="actualizar.log"
HOST="$(hostname)"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; echo "$*"; }

notify() {
  [ -f .env ] || return 0
  token=$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' .env | tr -d '"\r')
  chat=$(sed -n 's/^TELEGRAM_CHAT_ID=//p' .env | tr -d '"\r')
  [ -n "$token" ] && [ -n "$chat" ] || return 0
  curl -s -m 30 -o /dev/null "https://api.telegram.org/bot$token/sendMessage" \
    --data-urlencode "chat_id=$chat" --data-urlencode "text=SismoAlert ($HOST): $*" || true
}

fail() { log "ERROR: $*"; notify "⚠️ actualización fallida: $*"; exit 1; }

# Datos de estaciones llegando de nuevo (al menos 6) en menos de 3 minutos
healthy() {
  i=0
  while [ $i -lt 36 ]; do
    n=$(curl -s -m 5 http://127.0.0.1:8765/state | .venv/bin/python -c \
      "import json,sys; d=json.load(sys.stdin); print(sum(1 for s in d['stations'] if s['last_packet_age_s'] is not None and s['last_packet_age_s'] < 120))" 2>/dev/null)
    [ "${n:-0}" -ge 6 ] && return 0
    i=$((i + 1)); sleep 5
  done
  return 1
}

restart_and_check() {
  sudo systemctl restart "$SERVICE" && healthy
}

git fetch -q origin main || fail "no se pudo consultar GitHub"
OLD=$(git rev-parse HEAD)
NEW=$(git rev-parse origin/main)
if [ "$OLD" = "$NEW" ]; then
  log "sin cambios ($(git log -1 --format=%h))"
  exit 0
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  fail "hay cambios locales sin commit en $(pwd); los ajustes de esta máquina van en config_local.py"
fi

# Revisión automática de GitHub para el commit nuevo
if [ "$1" != "--forzar" ]; then
  checks=$(curl -s -m 30 "https://api.github.com/repos/$REPO/commits/$NEW/check-runs" | .venv/bin/python -c "
import json, sys
runs = json.load(sys.stdin).get('check_runs', [])
if not runs: print('sin-revision')
elif any(r['status'] != 'completed' for r in runs): print('en-curso')
elif all(r['conclusion'] in ('success', 'skipped', 'neutral') for r in runs): print('ok')
else: print('fallo')" 2>/dev/null)
  case "$checks" in
    ok) ;;
    sin-revision) log "aviso: $(git rev-parse --short "$NEW") no tiene revisión de GitHub; se actualiza igual" ;;
    en-curso) log "la revisión de GitHub de $(git rev-parse --short "$NEW") sigue en curso; se intenta en la próxima vuelta"; exit 0 ;;
    *) fail "la revisión de GitHub falló para $(git rev-parse --short "$NEW"); no se instala. Ver https://github.com/$REPO/actions" ;;
  esac
fi

CHANGES=$(git log --format='• %h %an: %s' "$OLD..$NEW" | head -15)
git merge -q --ff-only "$NEW" || fail "no se pudo avanzar a $(git rev-parse --short "$NEW") (¿historia reescrita?)"

if ! git diff --quiet "$OLD" "$NEW" -- requirements.txt; then
  .venv/bin/python -m pip install -q -r requirements.txt >> "$LOG" 2>&1 || {
    git reset -q --hard "$OLD"; fail "pip install falló; se volvió a $(git rev-parse --short "$OLD")"; }
fi

# Que el código cargue antes de reiniciar el servicio
if ! .venv/bin/python -c "import config, detector, sources, store, traveltime, server" >> "$LOG" 2>&1; then
  git reset -q --hard "$OLD"
  fail "el código nuevo no carga (ver $LOG); se volvió a $(git rev-parse --short "$OLD")"
fi

if restart_and_check; then
  log "actualizado $(git rev-parse --short "$OLD") → $(git rev-parse --short "$NEW")"
  notify "✅ actualizado a $(git rev-parse --short "$NEW") y funcionando.
$CHANGES"
else
  git reset -q --hard "$OLD"
  if ! git diff --quiet "$OLD" "$NEW" -- requirements.txt; then
    .venv/bin/python -m pip install -q -r requirements.txt >> "$LOG" 2>&1
  fi
  if restart_and_check; then
    fail "con $(git rev-parse --short "$NEW") no llegaron datos de las estaciones; se volvió a $(git rev-parse --short "$OLD"), que funciona"
  else
    fail "no llegan datos de las estaciones ni con la versión nueva ni con la anterior; revisar la máquina (journalctl -u $SERVICE)"
  fi
fi
