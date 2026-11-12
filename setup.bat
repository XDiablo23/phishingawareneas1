@echo off
REM =====================================================================
REM  PhishAwareness - one-click setup
REM  Installs Python 3.12, Node.js, GoPhish (optional) and all project
REM  dependencies, so the app is ready to run. Uses winget.
REM
REM  Administrator rights are required to install Python/Node, so you
REM  will see a Windows UAC prompt. The app itself runs without admin.
REM  After this finishes, double-click Start-PhishAwareness.bat.
REM =====================================================================
net session >nul 2>&1
if %errorLevel% NEQ 0 (
  echo Requesting administrator privileges to install prerequisites...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
