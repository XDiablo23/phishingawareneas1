<#
  PhishAwareness - one-click environment setup (Windows)

  Run it by double-clicking setup.bat (which requests admin and calls this).
  It will:
    1. Install Python 3.12 and Node.js LTS if missing (via winget)
    2. Download GoPhish (optional delivery tool) next to the project
    3. Create the Python virtualenv and install backend + portal dependencies
    4. Install the frontend (npm) dependencies

  The app runs on SQLite by default, so NO database install is required.
  Docker / PostgreSQL are optional and intentionally NOT auto-installed
  (Docker Desktop needs WSL2 + a reboot). See the note at the end.
#>
$ErrorActionPreference = 'Stop'
$Root   = $PSScriptRoot                 # ...\phishawareness
$Parent = Split-Path -Parent $Root      # ...\Capstone code and apps
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Test-Cmd($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Update-Path {
    $m = [Environment]::GetEnvironmentVariable('Path','Machine')
    $u = [Environment]::GetEnvironmentVariable('Path','User')
    $env:Path = "$m;$u"
}
function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Has-Py312 {
    try { & py -3.12 --version 1>$null 2>$null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}

Write-Host "PhishAwareness setup" -ForegroundColor White
Write-Host "Project: $Root" -ForegroundColor DarkGray

# ---------------------------------------------------------- Python 3.12
Step "Python 3.12"
if (Has-Py312) {
    Write-Host "Already installed." -ForegroundColor Green
} else {
    Write-Host "Installing Python 3.12 via winget..." -ForegroundColor Yellow
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
    Update-Path
}
if (-not (Has-Py312)) {
    Write-Host "Python 3.12 is still not available. Install it from https://www.python.org/downloads/ and re-run." -ForegroundColor Red
    Read-Host "Press Enter to exit"; exit 1
}

# ---------------------------------------------------------- Node.js
Step "Node.js (LTS)"
if (Test-Cmd node) {
    Write-Host "Already installed ($(node --version))." -ForegroundColor Green
} else {
    Write-Host "Installing Node.js LTS via winget..." -ForegroundColor Yellow
    winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements
    Update-Path
}

# ---------------------------------------------------------- GoPhish (optional)
Step "GoPhish (optional delivery tool)"
$existing = Get-ChildItem -Path $Parent -Directory -Filter 'gophish*' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    Write-Host "Already present: $($existing.Name)" -ForegroundColor Green
} else {
    try {
        $ver  = 'v0.12.1'
        $name = "gophish-$ver-windows-64bit"
        $url  = "https://github.com/gophish/gophish/releases/download/$ver/$name.zip"
        $zip  = Join-Path $Parent "$name.zip"
        $dest = Join-Path $Parent $name
        Write-Host "Downloading $name ..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Expand-Archive -Path $zip -DestinationPath $dest -Force
        Remove-Item $zip -Force
        Write-Host "GoPhish ready: $dest" -ForegroundColor Green
    } catch {
        Write-Host "GoPhish download skipped (optional - the app runs without it): $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}

# ---------------------------------------------------------- Backend + portal deps
Step "Backend + portal Python dependencies"
Set-Location (Join-Path $Root 'backend')
if (-not (Test-Path '.\.venv\Scripts\python.exe')) {
    Write-Host "Creating virtual environment (.venv)..." -ForegroundColor Yellow
    & py -3.12 -m venv .venv
}
$vpy = '.\.venv\Scripts\python.exe'
& $vpy -m pip install --upgrade pip
& $vpy -m pip install -r requirements-dev.txt
& $vpy -m pip install -r ..\portal\requirements.txt
Write-Host "Python dependencies installed." -ForegroundColor Green

# ---------------------------------------------------------- Frontend deps
Step "Frontend dependencies (npm)"
Set-Location (Join-Path $Root 'frontend')
if (Test-Cmd npm) {
    npm install
    Write-Host "Frontend dependencies installed." -ForegroundColor Green
} else {
    Write-Host "npm not on PATH in this window. Open a NEW terminal and run 'npm install' inside frontend\ ." -ForegroundColor DarkYellow
}

Set-Location $Root
Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host " Setup complete." -ForegroundColor Green
Write-Host " Launch everything: double-click  Start-PhishAwareness.bat" -ForegroundColor White
Write-Host "   API :8000   Console :5173   Portal :8100" -ForegroundColor DarkGray
Write-Host " Database: SQLite, created automatically - no DB install needed." -ForegroundColor DarkGray
Write-Host " (Optional) Postgres instead of SQLite:  docker compose up --build" -ForegroundColor DarkGray
Write-Host "=====================================================" -ForegroundColor Cyan

# The portal's background automation authenticates with a scoped service
# token that an admin generates in the console - it is deliberately no longer
# wired by the portal admin login (that used to store an operator password).
# Setup cannot mint it here: it needs a running API and a tenant, and neither
# exists until the operator seeds or creates one. So flag the step instead.
Write-Host "`n One more step for the Awareness Portal's automation:" -ForegroundColor Yellow
Write-Host "   1. Console (:5173)  -> Manage -> Integration" -ForegroundColor White
Write-Host "   2. 'Awareness & Remediation Portal' -> Generate the service token" -ForegroundColor White
Write-Host "   3. Portal (:8100)   -> Administrator -> Settings -> paste it in" -ForegroundColor White
Write-Host " Training and the console work without this; only the portal's" -ForegroundColor DarkGray
Write-Host " background sync (risk floors, in-person marks) needs it." -ForegroundColor DarkGray
Write-Host " Details: docs\PORTAL_GUIDE.md section 7." -ForegroundColor DarkGray
Read-Host "`nPress Enter to close"
