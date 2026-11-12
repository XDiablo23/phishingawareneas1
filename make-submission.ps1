# Build a clean submission archive from git.
#
# Zipping the project folder directly produces a ~111 MB archive: it sweeps up
# backend\.venv, frontend\node_modules, .git, frontend\dist, __pycache__ and
# the local SQLite databases. All of that is correctly gitignored, so the fix
# is to export what git actually tracks instead of what happens to be on disk.
#
#   .\make-submission.ps1              -> phishawareness-submission-<sha>.zip
#   .\make-submission.ps1 -Ref v1.0    -> export a tag/branch instead of HEAD

param(
    [string]$Ref = 'HEAD',
    [string]$OutDir = '..'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path '.git')) {
    Write-Host "Not a git repository - run this from the project root." -ForegroundColor Red
    exit 1
}

# Uncommitted work would silently be left OUT of the archive, since git archive
# exports the committed tree. Better to say so than to ship a stale zip.
$dirty = git status --porcelain
if ($dirty) {
    Write-Host "Working tree has uncommitted changes:" -ForegroundColor Yellow
    $dirty | ForEach-Object { Write-Host "   $_" -ForegroundColor DarkYellow }
    Write-Host "git archive exports the COMMITTED tree, so these will not be included." -ForegroundColor Yellow
    $answer = Read-Host "Continue anyway? (y/N)"
    if ($answer -notmatch '^[Yy]') { exit 1 }
}

$sha = (git rev-parse --short $Ref).Trim()
$out = Join-Path $OutDir "phishawareness-submission-$sha.zip"

git archive --format=zip --output=$out $Ref
if ($LASTEXITCODE -ne 0) { Write-Host "git archive failed." -ForegroundColor Red; exit 1 }

$resolved = (Resolve-Path $out).Path
$sizeMb = [math]::Round((Get-Item $resolved).Length / 1MB, 2)
$files = (git ls-tree -r --name-only $Ref | Measure-Object).Count

Write-Host ""
Write-Host "Submission archive written." -ForegroundColor Green
Write-Host "   $resolved" -ForegroundColor White
Write-Host "   $files tracked files, $sizeMb MB, from $Ref ($sha)" -ForegroundColor DarkGray
