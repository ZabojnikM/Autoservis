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

# Změnily se závislosti oproti verzi na serveru?
$reqNova = Join-Path $tmp "requirements.txt"
$reqServer = Join-Path $Cil "requirements.txt"
$zmenaZavislosti = -not (Test-Path $reqServer) -or
    ((Get-FileHash $reqNova).Hash -ne (Get-FileHash $reqServer).Hash)

# Zrcadlení na server; vyloučené složky/soubory robocopy na cíli nemaže
robocopy $tmp $Cil /MIR /R:2 /W:2 /NP /NFL /NDL `
    /XD data .venv venv .git .claude __pycache__ .pytest_cache `
    /XF .env *.db *.db-*
if ($LASTEXITCODE -ge 8) { throw "robocopy selhal (kód $LASTEXITCODE)" }

# Pokyny pro agenta běžícího přímo na serveru (Claude Code si CLAUDE.md načte sám)
$pokyny = Join-Path $tmp "nastroje\server-CLAUDE.md"
if (Test-Path $pokyny) { Copy-Item $pokyny (Join-Path $Cil "CLAUDE.md") -Force }

$zavislosti = if ($zmenaZavislosti) { "ZMENENY - spust pip install -r requirements.txt" } else { "beze zmeny" }
@(
    "$commit  $(git log -1 --format='%ci  %s')"
    "Nasazeno: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    "Zavislosti (requirements.txt): $zavislosti"
) | Set-Content (Join-Path $Cil "VERZE.txt") -Encoding utf8
Remove-Item $tmp -Recurse -Force

Write-Host "Nasazeno: $commit -> $Cil" -ForegroundColor Green
if ($zmenaZavislosti) { Write-Host "Závislosti se změnily - na serveru je potřeba pip install." -ForegroundColor Yellow }
Write-Host "Na serveru restartuj aplikaci." -ForegroundColor Yellow
