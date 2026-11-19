@echo off
cd /d "%~dp0"
echo ==================================================
echo   PokeMarket Scanner - Avvio Server (porta 8765)
echo ==================================================
echo PC:        http://127.0.0.1:8765
echo Cellulare: http://192.168.2.160:8765
echo.
".\.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload
pause
