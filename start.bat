@echo off
rem Keiba EV: start Django (API :8001) and Vite (UI :5174) in separate windows, then open the browser
cd /d "%~dp0"
start "keiba-ev api" cmd /k ".venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8001"
start "keiba-ev ui" cmd /k "cd frontend && npm run dev"
timeout /t 4 /nobreak >nul
start "" http://localhost:5174/
