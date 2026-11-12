@echo off
setlocal
title PhishAwareness - Run Everything
cd /d "%~dp0"

echo ============================================================
echo   PhishAwareness - one-click launcher (runs everything)
echo ============================================================

REM --- 1. require Python 3.12 (deps do NOT build on 3.14) ---
py -3.12 --version >nul 2>&1
if errorlevel 1 goto NOPY

REM --- 2. backend venv must be Python 3.12 (rebuild if wrong/absent) ---
cd backend
if not exist ".venv\Scripts\python.exe" goto MAKEVENV
".venv\Scripts\python.exe" -c "import sys;exit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>&1
if errorlevel 1 ( echo [i] Rebuilding venv on Python 3.12... & rmdir /s /q .venv & goto MAKEVENV )
goto DEPS

:MAKEVENV
echo [i] Creating Python 3.12 virtual environment...
py -3.12 -m venv .venv
if errorlevel 1 goto VENVFAIL

:DEPS
echo [i] Installing/refreshing backend dependencies...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto PIPFAIL
cd ..

REM --- 3. start GoPhish (delivery tool) if it sits beside the project ---
echo [i] Starting GoPhish (optional - only needed for live campaigns)...
start "GoPhish" cmd /k "%~dp0run_gophish.bat"

REM --- 4. start the API and the Web app, each in its own window ---
start "PhishAwareness API" cmd /k "%~dp0run_api.bat"
start "PhishAwareness Web" cmd /k "%~dp0run_web.bat"

REM --- 4b. start the Awareness & Remediation Portal (separate service) ---
start "Remediation Portal" cmd /k "%~dp0run_portal.bat"

REM --- 5. open the apps in the browser once the servers are up ---
echo [i] Waiting for the web servers to come up...
timeout /t 10 >nul
start "" http://localhost:5173
start "" http://localhost:8100

echo.
echo ============================================================
echo  Running. Four windows opened:
echo    - PhishAwareness API      http://localhost:8000
echo    - PhishAwareness Web      http://localhost:5173   ^<-- THE MAIN APP
echo    - Remediation Portal      http://localhost:8100   ^<-- TRAINING PORTAL
echo    - GoPhish (if present)     https://127.0.0.1:3333  (admin)
echo.
echo  Main app: click "Create demo organization", then sign in.
echo  Portal:  Administrator -^> sign in with your PhishAwareness operator
echo           login; employees use "Create account" to start training.
echo           For the portal's background sync, generate the service token
echo           in the console (Manage -^> Integration) and paste it into the
echo           portal's Settings. Training works without it.
echo  To STOP everything: just close those windows.
echo ============================================================
pause
exit /b 0

:NOPY
echo [ERROR] Python 3.12 not found (py -3.12).
echo Install it from https://www.python.org/downloads/release/python-31210/
echo Tick "Add python.exe to PATH" during setup, then re-run this file.
pause & exit /b 1

:VENVFAIL
echo [ERROR] Could not create the virtual environment.
pause & exit /b 1

:PIPFAIL
echo [ERROR] Backend dependency install failed (check your internet connection).
pause & exit /b 1
