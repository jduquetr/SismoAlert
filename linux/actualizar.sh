#!/bin/sh
# Trae los cambios de GitHub de la rama actual y, si hubo, reinicia el servicio.
# Lo corre cron cada 5 minutos (linux/instalar_servicio.sh). No toca docs/, que es de
# publicar.sh, ni datos/, que no está en git.
cd "$(dirname "$0")/.." || exit 1
git fetch -q || exit 0
[ "$(git rev-parse HEAD)" = "$(git rev-parse '@{u}')" ] && exit 0

antes=$(git rev-parse HEAD)
git checkout -q -- docs/ 2>/dev/null
if ! git pull -q --ff-only; then
  echo "$(date '+%F %T') ERROR: git pull falló; revisa con git status"
  exit 1
fi
if ! git diff --quiet "$antes" HEAD -- requirements.txt; then
  .venv/bin/python -m pip install -q -r requirements.txt
fi
# Solo reiniciar si cambió algo más que la copia publicada
if git diff --quiet "$antes" HEAD -- . ':(exclude)docs'; then
  exit 0
fi
sudo systemctl restart sismoalert
echo "$(date '+%F %T') actualizado a $(git rev-parse --short HEAD) y reiniciado"
