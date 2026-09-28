@echo off
rem Inicia el servidor de alertas y abre la página en el navegador
cd /d "%~dp0"
start "" http://127.0.0.1:8765
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -u server.py
