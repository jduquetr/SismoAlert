#!/bin/sh
# Inicia el servidor de alertas en macOS, Linux o Raspberry Pi.
# Uso: ./iniciar.sh            (solo el servidor; así lo usa el servicio)
#      ./iniciar.sh --abrir    (además abre la página en el navegador)
cd "$(dirname "$0")" || exit 1
export PYTHONIOENCODING=utf-8

if [ ! -x .venv/bin/python ]; then
  echo "Falta el entorno de Python. Créalo con:"
  echo "  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi

if [ "$1" = "--abrir" ]; then
  # Abrir la página unos segundos después, cuando el servidor ya escucha
  (sleep 3; if command -v open >/dev/null; then open http://127.0.0.1:8765; \
   elif command -v xdg-open >/dev/null; then xdg-open http://127.0.0.1:8765; fi) &
fi

exec .venv/bin/python -u server.py
