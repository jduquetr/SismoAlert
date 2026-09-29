#!/bin/sh
# Registra el servidor de alertas como servicio de systemd (Linux: máquina virtual en la
# nube, Raspberry Pi): arranca al encender, se reinicia solo si se cae y su registro se ve
# con journalctl. Corre con el usuario que ejecuta este script.
#
# Uso (desde la carpeta del proyecto):
#   sh linux/instalar_servicio.sh              instalar o actualizar
#   sh linux/instalar_servicio.sh --quitar     detener y quitar el servicio
#
# Después:
#   systemctl status sismoalert          ¿está corriendo? ¿desde cuándo?
#   journalctl -u sismoalert -f          registro en vivo
#   sudo systemctl restart sismoalert    reiniciar (p. ej. tras git pull)
set -e
NAME="sismoalert"
UNIT="/etc/systemd/system/$NAME.service"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"

if [ "$1" = "--quitar" ]; then
  sudo systemctl disable --now "$NAME" 2>/dev/null || true
  sudo rm -f "$UNIT"
  sudo systemctl daemon-reload
  echo "Servicio quitado."
  exit 0
fi

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "Falta el entorno de Python en $DIR/.venv. Créalo primero:"
  echo "  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi
chmod +x "$DIR/iniciar.sh"

sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Alertas de sismos Medellín (SismoAlert)
Wants=network-online.target
After=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=/bin/sh $DIR/iniciar.sh
Restart=always
RestartSec=10
Environment=PYTHONIOENCODING=utf-8

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "$NAME"
echo "Servicio instalado: $NAME"
echo "Estado:   systemctl status $NAME"
echo "Registro: journalctl -u $NAME -f"
