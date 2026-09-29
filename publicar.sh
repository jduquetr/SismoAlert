#!/bin/sh
# Publica en Vercel la copia estática con los datos de este computador (el vigilante).
#
# Hace commit y push de docs/ solo si cambió el registro de sismos o si la última
# publicación tiene más de REFRESCO_HORAS horas; si no, no deja rastro. Pensado para
# correr cada hora con launchd (mac/instalar_publicacion.sh). Escribe en publicar.log.
#
# Uso: ./publicar.sh            publicar si hay cambios
#      ./publicar.sh --forzar   publicar aunque no haya cambios
cd "$(dirname "$0")" || exit 1
REFRESCO_HORAS=24
LOG=publicar.log
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# Una sola ejecución a la vez
LOCK=.publicar.lock
if ! mkdir "$LOCK" 2>/dev/null; then
  log "otra publicación sigue en curso; se omite esta vuelta"
  exit 0
fi
trap 'rmdir "$LOCK"' EXIT

if [ -z "$(git config user.email)" ]; then
  log "ERROR: falta la identidad de git. Corre: git config user.name \"Tu nombre\"; git config user.email tu@correo"
  exit 1
fi

# Descartar la copia generada en una vuelta anterior y traer lo último de GitHub
git checkout -q -- docs/ 2>/dev/null
if ! git pull -q --rebase; then
  git rebase --abort 2>/dev/null
  log "ERROR: git pull falló (¿conflicto o sin conexión?). Revisa con: git status"
  exit 1
fi

if ! .venv/bin/python copia_estatica.py >> "$LOG" 2>&1; then
  log "ERROR: copia_estatica.py falló; ¿está corriendo el servidor?"
  git checkout -q -- docs/ 2>/dev/null
  exit 1
fi

# ¿Cambió el registro? ¿Hace cuánto fue la última publicación?
registro_cambio=0
git diff --quiet -- docs/sismos-detectados.geojson || registro_cambio=1
ultima=$(git log -1 --format=%ct -- docs/index.html 2>/dev/null)
edad=$(( $(date +%s) - ${ultima:-0} ))

if [ "$1" = "--forzar" ]; then
  motivo="publicación manual"
elif [ "$registro_cambio" -eq 1 ]; then
  motivo="registro de sismos actualizado"
elif [ "$edad" -ge $((REFRESCO_HORAS * 3600)) ]; then
  motivo="refresco diario"
else
  git checkout -q -- docs/
  exit 0
fi

git add docs/index.html docs/sismos-detectados.geojson
if git diff --cached --quiet; then
  log "sin cambios que publicar"
  exit 0
fi
git commit -q -m "Publicar datos del computador vigilante ($motivo)"
if git push -q; then
  log "publicado en Vercel: $motivo"
else
  log "ERROR: git push falló; se reintenta en la próxima vuelta"
  exit 1
fi
