#!/bin/sh
# Actualización automática de código, siempre desde origin/azure-telegram.
# Dependencias nuevas requieren una intervención con entorno preparado previamente.
set -eu
# El shell analiza el cuerpo completo antes de que Git pueda reemplazar este archivo.
actualizar() {
PATH=/usr/local/bin:/usr/bin:/bin
export PATH GIT_TERMINAL_PROMPT=0
cd "$(dirname "$0")/.."
fail() { echo "$(date '+%F %T') ERROR: $*" >&2; exit 1; }
[ "$(id -u)" -ne 0 ] || fail "Ejecuta como el usuario del servicio, nunca root"
command -v flock >/dev/null || fail "Falta flock (util-linux)"
exec 9>.actualizar.lock
flock -n 9 || exit 0
[ "$(git symbolic-ref --short HEAD)" = azure-telegram ] || fail "La rama no es azure-telegram"
case "$(git remote get-url origin)" in
  https://github.com/jduquetr/SismoAlert.git|git@github.com:jduquetr/SismoAlert.git) ;;
  *) fail "origin no es jduquetr/SismoAlert" ;;
esac
git diff --quiet && git diff --cached --quiet || fail "Hay cambios locales; no se descartan (incluido docs/)"
git fetch -q origin refs/heads/azure-telegram:refs/remotes/origin/azure-telegram || fail "git fetch falló; se conserva el servicio"
antes=$(git rev-parse HEAD)
objetivo=$(git rev-parse refs/remotes/origin/azure-telegram)
[ "$antes" != "$objetivo" ] || exit 0
git merge-base --is-ancestor "$antes" "$objetivo" || fail "La rama diverge; no se hará reset ni merge automático"
git diff --quiet "$antes" "$objetivo" -- requirements.txt || fail "Cambiaron dependencias: preparar y validar un entorno antes de actualizar manualmente"
# Compilar el contenido candidato sin importarlo, sin tocar el checkout ni el servicio.
.venv/bin/python - "$objetivo" <<'PY' || exit 1
import subprocess, sys
ref = sys.argv[1]
paths = subprocess.check_output(['git', 'ls-tree', '-rz', '--name-only', ref]).split(b'\0')
for raw in paths:
    if raw.endswith(b'.py'):
        path = raw.decode()
        compile(subprocess.check_output(['git', 'show', f'{ref}:{path}']), path, 'exec')
PY
# Comprobar el permiso antes de cambiar HEAD, sin esperar una contraseña en cron.
sudo -n -l /usr/bin/systemctl restart sismoalert.service >/dev/null 2>&1 || fail "Falta permiso sudo no interactivo para reiniciar sismoalert.service"
git merge -q --ff-only "$objetivo" || fail "Fast-forward falló; revisa git status"
if git diff --quiet "$antes" HEAD -- . ':(exclude)docs'; then
  echo "$(date '+%F %T') actualizado solo docs/; sin reinicio"
  exit 0
fi
if sudo -n /usr/bin/systemctl restart sismoalert.service; then
  sleep 3
  if /usr/bin/systemctl is-active --quiet sismoalert.service && .venv/bin/python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8765/state', timeout=10) as r:
    assert r.status == 200
PY
  then
    echo "$(date '+%F %T') actualizado a $(git rev-parse --short HEAD); servicio activo"
    exit 0
  fi
fi
echo "ERROR: falló el arranque; intentando volver a $antes" >&2
# --keep aborta si aparecieron cambios locales incompatibles; nunca --hard.
git reset --keep "$antes" || fail "Rollback bloqueado por cambios locales; intervención requerida"
sudo -n /usr/bin/systemctl restart sismoalert.service || fail "No pudo reiniciarse la versión anterior"
fail "Actualización revertida; revisar journalctl -u sismoalert"

}
actualizar
