@echo off
REM Starts the Awareness & Remediation Portal (a SEPARATE service) on port 8100.
REM It reuses the backend's Python 3.12 venv and talks to PhishAwareness over
REM REST at http://127.0.0.1:8000. Running under the venv python EXPLICITLY is
REM what prevents the "ModuleNotFoundError" that happens under system Python.
cd /d "%~dp0portal"
set "PYEXE=%~dp0backend\.venv\Scripts\python.exe"
if not exist "%PYEXE%" (
  echo [ERROR] Backend venv missing. Run Start-PhishAwareness.bat first.
  pause & exit /b 1
)

REM ensure the portal's deps are in the shared venv (idempotent + quick)
echo [i] Checking portal dependencies...
"%PYEXE%" -m pip install --disable-pip-version-check -q -r requirements.txt

REM connection + automation defaults (all overridable in the app Settings screen)
if "%PA_BASE_URL%"=="" set "PA_BASE_URL=http://127.0.0.1:8000"
if "%PORTAL_AUTO_SYNC_SECONDS%"=="" set "PORTAL_AUTO_SYNC_SECONDS=300"

echo [i] Portal running on http://localhost:8100  (auto-sync every %PORTAL_AUTO_SYNC_SECONDS%s)
"%PYEXE%" -m uvicorn app.main:app --port 8100
pause
