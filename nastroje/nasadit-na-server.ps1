# Nahraje poslední commit (HEAD) na testovací server (sdílený disk W:).
# Použití:  powershell -ExecutionPolicy Bypass -File nastroje\nasadit-na-server.ps1
# Nikdy nepřepisuje data/, .venv/ ani .env na serveru.
param(
    [string]$Cil = "W:\"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not (Test-Path $Cil)) { throw "Cíl $Cil není dostupný (je připojený síťový disk?)" }

$neulozene = git status --porcelain
if ($neulozene) {
    Write-Warning "Máš necommitnuté změny - na server půjde jen poslední commit:"
    $neulozene | ForEach-Object { Write-Host "  $_" }
}

$commit = git rev-parse --short HEAD
$tmp = Join-Path $env:TEMP "autoservis-nasazeni"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory $tmp | Out-Null

# Export čistého obsahu commitu (bez .git, .venv, databází)
git archive --format=zip -o "$tmp.zip" HEAD
Expand-Archive "$tmp.zip" $tmp -Force
Remove-Item "$tmp.zip"

# Zrcadlení na server; vyloučené složky/soubory robocopy na cíli nemaže
robocopy $tmp $Cil /MIR /R:2 /W:2 /NP /NFL /NDL `
    /XD data .venv venv .git .claude __pycache__ .pytest_cache `
    /XF .env *.db *.db-*
if ($LASTEXITCODE -ge 8) { throw "robocopy selhal (kód $LASTEXITCODE)" }

# Pokyny pro agenta běžícího přímo na serveru (Claude Code si CLAUDE.md načte sám)
$pokyny = Join-Path $tmp "nastroje\server-CLAUDE.md"
if (Test-Path $pokyny) { Copy-Item $pokyny (Join-Path $Cil "CLAUDE.md") -Force }

"$commit  $(git log -1 --format='%ci  %s')" | Set-Content (Join-Path $Cil "VERZE.txt") -Encoding utf8
Remove-Item $tmp -Recurse -Force

Write-Host "Nasazeno: $commit -> $Cil" -ForegroundColor Green
Write-Host "Na serveru restartuj aplikaci (spustit.bat); při změně requirements.txt i pip install." -ForegroundColor Yellow
