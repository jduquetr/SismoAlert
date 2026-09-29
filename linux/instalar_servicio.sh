#!/bin/sh
# Ejecutar como usuario dedicado del servicio con sudo, nunca como root.
# Uso: sh linux/instalar_servicio.sh [--quitar]
set -eu
PATH=/usr/local/bin:/usr/bin:/bin
export PATH
NAME=sismoalert
UNIT="/etc/systemd/system/$NAME.service"
DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
USER_NAME="$(id -un)"
[ "$(id -u)" -ne 0 ] || { echo "Ejecuta como usuario del servicio, no root" >&2; exit 1; }
# Rutas y usuarios se insertan en systemd, cron y sudoers: rechazar sus metacaracteres.
case "$DIR" in *[!a-zA-Z0-9_./-]*) echo "Ruta no compatible con cron/systemd: $DIR" >&2; exit 1;; esac
case "$USER_NAME" in ''|*[!a-zA-Z0-9_-]*) echo "Usuario no compatible" >&2; exit 1;; esac
case "${1:-}" in
  --quitar)
    sudo systemctl disable --now "$NAME"
    sudo rm -f "$UNIT" "/etc/cron.d/$NAME" "/etc/sudoers.d/$NAME"
    sudo systemctl daemon-reload
    echo "Servicio y actualización automática quitados. /etc/sismoalert.env se conserva."
    exit 0 ;;
  '') ;;
  *) echo "Uso: $0 [--quitar]" >&2; exit 1 ;;
esac
[ "$(git -C "$DIR" symbolic-ref --short HEAD)" = azure-telegram ] || {
  echo "Instalar únicamente desde azure-telegram" >&2; exit 1;
}
[ -x "$DIR/.venv/bin/python" ] || { echo "Falta $DIR/.venv/bin/python" >&2; exit 1; }
command -v flock >/dev/null
sudo -v
# Los secretos los lee systemd como root; no convertir el archivo en código shell.
if sudo test -e /etc/sismoalert.env; then
  sudo test ! -L /etc/sismoalert.env || { echo "El archivo de entorno no puede ser un enlace" >&2; exit 1; }
  sudo chown root:root /etc/sismoalert.env
  sudo chmod 600 /etc/sismoalert.env
fi
mkdir -p "$DIR/datos"
umask 077
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
cat > "$tmp/unit" <<EOF
[Unit]
Description=SismoAlert - alertas de sismos Medellin
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
EnvironmentFile=-/etc/sismoalert.env
Environment=PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
ExecStart=$DIR/.venv/bin/python -u $DIR/server.py
Restart=always
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$DIR/datos

[Install]
WantedBy=multi-user.target
EOF
cat > "$tmp/cron" <<EOF
SHELL=/bin/sh
PATH=/usr/local/bin:/usr/bin:/bin
*/5 * * * * $USER_NAME /bin/sh $DIR/linux/actualizar.sh >> $DIR/actualizar.log 2>&1
EOF
# Permiso limitado a reiniciar esta unidad; no otorga sudo al script ni al intérprete.
cat > "$tmp/sudoers" <<EOF
$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl restart sismoalert.service
EOF
sudo visudo -cf "$tmp/sudoers"
sudo install -o root -g root -m 0440 "$tmp/sudoers" "/etc/sudoers.d/$NAME"
sudo install -o root -g root -m 0644 "$tmp/unit" "$UNIT"
sudo install -o root -g root -m 0644 "$tmp/cron" "/etc/cron.d/$NAME"
sudo systemctl daemon-reload
sudo systemctl enable "$NAME" >/dev/null
sudo systemctl restart "$NAME"
echo "Servicio $NAME instalado. Registro: journalctl -u $NAME -f"
