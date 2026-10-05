#!/bin/sh
# Programa la actualización diaria (linux/actualizar.sh) con un timer de systemd: todos los
# días a las 7 a. m. de Bogotá baja lo nuevo de main, lo instala, reinicia y comprueba que
# funcione; si no, vuelve a la versión anterior. Avisa por Telegram si hay .env.
#
# Uso (desde la carpeta del proyecto):
#   sh linux/instalar_actualizacion.sh              instalar o actualizar
#   sh linux/instalar_actualizacion.sh --quitar     quitar el timer
#
# Después:
#   systemctl list-timers sismoalert-actualizar     próxima ejecución
#   sudo systemctl start sismoalert-actualizar      actualizar ya
#   tail actualizar.log                             qué hizo cada día
set -e
NAME="sismoalert-actualizar"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"

if [ "$1" = "--quitar" ]; then
  sudo systemctl disable --now "$NAME.timer" 2>/dev/null || true
  sudo rm -f "/etc/systemd/system/$NAME.service" "/etc/systemd/system/$NAME.timer"
  sudo systemctl daemon-reload
  echo "Actualización diaria quitada."
  exit 0
fi

# El actualizador reinicia el servicio con sudo: debe poder hacerlo sin contraseña
if ! sudo -n systemctl status sismoalert >/dev/null 2>&1; then
  echo "El usuario $USER_NAME necesita sudo sin contraseña para reiniciar el servicio sismoalert."
  exit 1
fi

sudo tee "/etc/systemd/system/$NAME.service" >/dev/null <<EOF
[Unit]
Description=Actualización diaria de SismoAlert desde GitHub
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=/bin/sh $DIR/linux/actualizar.sh
EOF

sudo tee "/etc/systemd/system/$NAME.timer" >/dev/null <<EOF
[Unit]
Description=Actualización diaria de SismoAlert a las 7 a. m. (Bogotá)

[Timer]
OnCalendar=*-*-* 07:00:00 America/Bogota
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "$NAME.timer"
[ -f "$DIR/.env" ] || echo "Sin $DIR/.env: no habrá avisos por Telegram (TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID)"
systemctl list-timers "$NAME.timer" --no-pager
