#!/bin/sh
# Registra el servidor de alertas como servicio de launchd (macOS): arranca al iniciar
# sesión, se reinicia solo si se cae y escribe su registro en server.log.
#
# Uso (desde la carpeta del proyecto):
#   sh mac/instalar_servicio.sh              instalar o actualizar
#   sh mac/instalar_servicio.sh --quitar     detener y quitar el servicio
set -e
LABEL="co.sismoalert.servidor"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

# Quitar la versión anterior si existe (no falla si no estaba)
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true

if [ "$1" = "--quitar" ]; then
  rm -f "$PLIST"
  echo "Servicio quitado."
  exit 0
fi

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "Falta el entorno de Python en $DIR/.venv. Créalo primero (ver README)."
  exit 1
fi
chmod +x "$DIR/iniciar.sh"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>$DIR/iniciar.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$DIR/server.log</string>
  <key>StandardErrorPath</key><string>$DIR/server.log</string>
</dict>
</plist>
EOF

launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Servicio instalado: $LABEL"
echo "Página:   http://127.0.0.1:8765"
echo "Registro: tail -f \"$DIR/server.log\""
echo "Estado:   launchctl print $DOMAIN/$LABEL | grep -E 'state|pid'"
