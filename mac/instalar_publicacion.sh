#!/bin/sh
# Registra en launchd (macOS) la publicación automática en Vercel: corre publicar.sh cada
# 10 minutos, y este solo sube algo si cambió el registro de sismos (o una vez al día).
#
# Antes, una sola vez en este Mac (ver README):
#   brew install gh && gh auth login && gh auth setup-git
#   git config user.name "Tu nombre" && git config user.email tu@correo
#
# Uso (desde la carpeta del proyecto):
#   sh mac/instalar_publicacion.sh              instalar o actualizar
#   sh mac/instalar_publicacion.sh --quitar     quitar
set -e
LABEL="co.sismoalert.publicar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"
INTERVALO=600  # segundos

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true

if [ "$1" = "--quitar" ]; then
  rm -f "$PLIST"
  echo "Publicación automática quitada."
  exit 0
fi

chmod +x "$DIR/publicar.sh"
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
    <string>$DIR/publicar.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>$INTERVALO</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <!-- launchd arranca con un PATH mínimo: aquí están git y gh de Homebrew -->
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StandardOutPath</key><string>$DIR/publicar.log</string>
  <key>StandardErrorPath</key><string>$DIR/publicar.log</string>
</dict>
</plist>
EOF

launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Publicación automática instalada: revisa cada $((INTERVALO / 60)) minutos."
echo "Registro: tail -f \"$DIR/publicar.log\""
echo "Probar ya: \"$DIR/publicar.sh\" --forzar"
