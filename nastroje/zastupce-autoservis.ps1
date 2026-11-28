# Vytvoří na ploše (a v nabídce Start) zástupce „Autoservis“, který otevře aplikaci
# ve vlastním okně Chrome nebo Edge bez adresního řádku (režim --app). Nic neinstaluje, jde smazat jako běžný zástupce.
#
# Použití (nebo dvojklik na zastupce-autoservis.bat):
#   powershell -ExecutionPolicy Bypass -File zastupce-autoservis.ps1 -Adresa http://server:8001
param(
    [string]$Adresa
)

if (-not $Adresa) {
    $Adresa = Read-Host 'Adresa Autoservisu (např. http://server:8001)'
}
$Adresa = $Adresa.Trim().TrimEnd('/')
if (-not $Adresa) { Write-Host 'Adresa nevyplněna, konec.'; exit 1 }
if ($Adresa -notmatch '^https?://') { $Adresa = "http://$Adresa" }

# Prohlížeč: přednost má Chrome, jinak Edge
$kandidati = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)
$prohlizec = $kandidati | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $prohlizec) { Write-Host 'Nenašel jsem Chrome ani Edge.'; exit 1 }

# Ikona ze serveru; když se nepodaří stáhnout, použije se ikona prohlížeče
$slozka = Join-Path $env:LOCALAPPDATA 'Autoservis'
New-Item -ItemType Directory -Force $slozka | Out-Null
$ikona = Join-Path $slozka 'autoservis.ico'
try {
    Invoke-WebRequest -Uri "$Adresa/static/autoservis.ico" -OutFile $ikona -UseBasicParsing -TimeoutSec 10
} catch {
    Write-Host "Ikonu se nepodařilo stáhnout ($($_.Exception.Message)), použiju ikonu prohlížeče."
    Write-Host 'Zkontrolujte, že adresa je správná a server běží.'
    $ikona = $prohlizec
}

# Chrome používá vlastní profil; Edge si ponechá dosavadní profil.
$nazevProfilu = 'prohlizec'
if ((Split-Path $prohlizec -Leaf) -eq 'chrome.exe') {
    $nazevProfilu = 'prohlizec-chrome'
}
$profil = Join-Path $slozka $nazevProfilu

$shell = New-Object -ComObject WScript.Shell
$cile = @(
    [Environment]::GetFolderPath('Desktop'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) '')
)
foreach ($cil in $cile) {
    $lnk = $shell.CreateShortcut((Join-Path $cil 'Autoservis.lnk'))
    $lnk.TargetPath = $prohlizec
    # Volbu „Spustit: maximalizované“ ve vlastnostech zástupce prohlížeč ignoruje a běžící prohlížeč
    # ignoruje i --start-maximized. Proto vlastní profil: okno Autoservisu je samostatný proces
    # a přepínač se uplatní vždy (zároveň se nemíchá s ostatními okny prohlížeče).
    $lnk.Arguments = "--app=$Adresa/ --user-data-dir=`"$profil`" --start-maximized --disable-print-preview --no-first-run --no-default-browser-check"
    $lnk.WindowStyle = 3
    $lnk.IconLocation = "$ikona,0"
    $lnk.Description = 'Autoservis'
    $lnk.WorkingDirectory = Split-Path $prohlizec
    $lnk.Save()
    Write-Host "Vytvořen zástupce: $(Join-Path $cil 'Autoservis.lnk')"
}
Write-Host "Hotovo. Zástupce otevře $Adresa/ ve vlastním okně."
