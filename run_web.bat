@echo off
REM Starts the PhishAwareness frontend - Vite dev server on port 5173.
cd /d "%~dp0frontend"
if not exist node_modules echo Installing frontend dependencies, first run only...
if not exist node_modules call npm install
npm run dev
pause
