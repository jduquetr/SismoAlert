#!/bin/sh
# Registra el servidor de alertas como servicio de systemd (Linux: máquina virtual en la
# nube o Raspberry Pi): arranca con el equipo, se reinicia solo si se cae y deja su
# registro en journalctl. Además programa la actualización automática desde GitHub.
#
# Uso (desde la carpeta del proyecto, con un usuario que tenga sudo):
#   sh linux/instalar_servicio.sh              instalar o actualizar
#   sh linux/instalar_servicio.sh --quitar     detener y quitar el servicio
#
# Los avisos por Telegram leen /etc/sismoalert.env (ver README).
set -e
NAME=sismoalert
UNIT="/etc/systemd/system/$NAME.service"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"

if [ "$1" = "--quitar" ]; then
  sudo systemctl disable --now "$NAME" 2>/dev/null || true
  sudo rm -f "$UNIT" "/etc/cron.d/$NAME"
  sudo systemctl daemon-reload
  echo "Servicio quitado."
  exit 0
fi

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "Falta el entorno de Python en $DIR/.venv. Créalo primero (ver README)."
  exit 1
fi
chmod +x "$DIR/iniciar.sh" "$DIR/linux/actualizar.sh"

sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=SismoAlert - alertas de sismos Medellin
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
EnvironmentFile=-/etc/sismoalert.env
ExecStart=$DIR/iniciar.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Cada 5 minutos: si hay cambios en GitHub, traerlos y reiniciar el servicio
sudo tee "/etc/cron.d/$NAME" >/dev/null <<EOF
*/5 * * * * $USER_NAME $DIR/linux/actualizar.sh >> $DIR/actualizar.log 2>&1
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$NAME" >/dev/null
sudo systemctl restart "$NAME"
echo "Servicio $NAME instalado. Registro: journalctl -u $NAME -f"
