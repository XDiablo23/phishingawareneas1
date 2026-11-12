@echo off
REM Starts the PhishAwareness backend API using the project's Python 3.12 venv
REM EXPLICITLY, so it works even when no venv is "activated". This is what
REM permanently prevents the recurring "ModuleNotFoundError: jwt" (that error
REM only happens when uvicorn runs under system Python 3.14 instead of the venv).
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Backend venv missing. Run Start-PhishAwareness.bat first.
  pause & exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000
pause
