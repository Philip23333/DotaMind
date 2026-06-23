@echo off
setlocal

set "API_PORT=8001"

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %API_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  echo Port %API_PORT% is already in use. Stop the existing process before starting MetaMind API.
  exit /b 1
)

cd /d "%~dp0apps\api"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port %API_PORT% --log-level info
