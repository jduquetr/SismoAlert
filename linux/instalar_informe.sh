#!/bin/sh
# Programa el informe diario (informe_diario.py) con un timer de systemd: todos los días a
# las 6 p. m. de Bogotá lo envía por Telegram. Si la máquina estaba apagada a esa hora, sale
# al encenderla. Necesita TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en el archivo .env.
#
# Uso (desde la carpeta del proyecto):
#   sh linux/instalar_informe.sh              instalar o actualizar
#   sh linux/instalar_informe.sh --quitar     quitar el timer
#
# Después:
#   systemctl list-timers sismoalert-informe       próxima ejecución
#   sudo systemctl start sismoalert-informe        enviarlo ya
#   journalctl -u sismoalert-informe               registro de envíos
set -e
NAME="sismoalert-informe"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"

if [ "$1" = "--quitar" ]; then
  sudo systemctl disable --now "$NAME.timer" 2>/dev/null || true
  sudo rm -f "/etc/systemd/system/$NAME.service" "/etc/systemd/system/$NAME.timer"
  sudo systemctl daemon-reload
  echo "Informe diario quitado."
  exit 0
fi

# Leer el registro del servicio (journalctl) sin sudo
sudo usermod -aG systemd-journal "$USER_NAME"

sudo tee "/etc/systemd/system/$NAME.service" >/dev/null <<EOF
[Unit]
Description=Informe diario de SismoAlert por Telegram
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python $DIR/informe_diario.py
Environment=PYTHONIOENCODING=utf-8
EOF

sudo tee "/etc/systemd/system/$NAME.timer" >/dev/null <<EOF
[Unit]
Description=Informe diario de SismoAlert a las 6 p. m. (Bogotá)

[Timer]
OnCalendar=*-*-* 18:00:00 America/Bogota
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "$NAME.timer"
[ -f "$DIR/.env" ] || echo "Falta $DIR/.env con TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID"
systemctl list-timers "$NAME.timer" --no-pager
