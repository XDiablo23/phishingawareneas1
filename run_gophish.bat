@echo off
REM Starts GoPhish (the separate delivery tool) from the sibling folder.
REM Optional: the measurement app runs fine without it. GoPhish is only needed
REM to send a live practice campaign. You can close this window any time.
set "GPDIR="
for /d %%G in ("%~dp0..\gophish*") do set "GPDIR=%%G"
if not defined GPDIR (
  echo GoPhish folder not found next to the project ^(looked for "gophish*"^).
  echo The app does NOT need GoPhish to run - you can close this window.
  timeout /t 6 >nul
  exit /b 0
)
cd /d "%GPDIR%"
echo Starting GoPhish from:
echo   %GPDIR%
echo Admin UI: https://127.0.0.1:3333  (accept the self-signed certificate warning)
echo.
gophish.exe
pause
