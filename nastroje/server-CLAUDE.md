# Testovací server Autoservisu (Linux) – pokyny pro agenta

Tato složka je **git klon** repozitáře `ZabojnikM/Autoservis` (GitHub) a běží z ní testovací
server aplikace jako služba systemd `autoservis`. Vývoj probíhá na jiném počítači. Nová verze se
na server dostane **jen přes git**: vývojář na GitHubu **vydá verzi** (značka `vX.Y.Z`
a GitHub Release) a aktualizace ji nainstaluje tlačítkem v aplikaci. Běžné commity mezi
vydáními se na server nedostanou. Kód se na server nikdy nenahrává přímo (sdílený disk, kopírování, scp).

Tento soubor je v repu jako `nastroje/server-CLAUDE.md`. `CLAUDE.md` v kořeni složky ho jen
importuje (`@nastroje/server-CLAUDE.md`), takže se aktualizuje spolu s aplikací.

## Co tu nedělat
- **Neupravuj kód** (`app/`, `UI/`, `tests/`, `*.md`…) a necommituj ani nepushuj. Aktualizace
  ručně upravené soubory odmítne přepsat a zablokuje se. Kdyby se to stalo:
  `git status` ukáže co, `git checkout -- <soubor>` to vrátí.
- Chyby a nápady zapisuj jako **GitHub Issue** do `ZabojnikM/Autoservis` (popis, kroky
  k reprodukci a verze z Nastavení nebo `git describe --tags --always`). Pokud tu nemáš
  přístup ke GitHubu, sepiš je uživateli.
- Nekopíruj sem soubory z jiných míst (ani přes sdílený disk).

## Co není v gitu (patří serveru, aktualizace na to nesahá)
- `data/` – databáze `autoservis.db` (všechna data i nastavení) a `data/backups/`
- `.venv/` – virtuální prostředí Pythonu
- `.env` – lokální nastavení (např. `AUTOSERVIS_DB` = cesta k jiné databázi)
- `CLAUDE.md` – jen import tohoto návodu

S databází zacházej opatrně. Před každým zásahem do ní (migrace, hromadné úpravy, import)
udělej kopii do `data/backups/`. Testovací záznamy označuj (např. „TEST“) a po testu
maž jen ty své.

## Aktualizace
**Nastavení → Aktualizace aplikace → Zkontrolovat aktualizace → Nainstalovat.**
Služba má `AUTOSERVIS_AKTUALIZACE=vydani`, takže se instaluje jen **poslední vydaná verze**
(nejvyšší značka `vX.Y.Z`, seznam vydání: https://github.com/ZabojnikM/Autoservis/releases).
Commity, které ještě nejsou vydané, se nenainstalují.
Instalace sama:
1. stáhne změny (`git fetch --tags`),
2. zazálohuje databázi do `data/backups/pred-aktualizaci-*.db`,
3. přepne kód na poslední vydání (`git checkout --detach vX.Y.Z`),
4. při změně `requirements.txt` spustí `pip install` (při chybě vrátí původní kód),
5. ukončí aplikaci – systemd (`Restart=always`) ji spustí znovu a stránka se sama obnoví.

**Vrátit předchozí verzi** vrátí kód. Databázi ne – záloha z doby před aktualizací je
v `data/backups/` (záznam o poslední aktualizaci: `data/backups/aktualizace.json`).

Totéž ručně z příkazové řádky (jako uživatel služby, ve složce aplikace):
```
git fetch --tags --prune origin
cp data/autoservis.db data/backups/rucne-$(date +%Y%m%d-%H%M%S).db
git checkout --detach "$(git tag -l 'v*' --sort=-v:refname | head -n1)"   # poslední vydání
.venv/bin/python -m pip install -r requirements.txt   # jen když se změnil requirements.txt
sudo systemctl restart autoservis
```

### Přepnutí serveru z větve `main` na vydání (jednorázově)
Dřív služba instalovala každý commit (`AUTOSERVIS_AKTUALIZACE=main`). Přepnutí na vydání:
```
sudo sed -i 's/AUTOSERVIS_AKTUALIZACE=main/AUTOSERVIS_AKTUALIZACE=vydani/' /etc/systemd/system/autoservis.service
sudo systemctl daemon-reload && sudo systemctl restart autoservis
```
Pak v aplikaci **Zkontrolovat aktualizace → Nainstalovat** (nebo ruční postup výše). Kdo by
chtěl na testovacím serveru dál zkoušet nevydané změny, nechá `main` – ostrý provoz vždy `vydani`.

## Příjem vozidel (záložka, jen čtení)
Záložka **Příjem vozidel** čte soubor návštěv, které ukládá Přijímací technik (OpenBot):
`/var/lib/openbot/OpenBot/Shared/autoservis-prototype/json-data/visits.json` (cesta je ve službě jako
`AUTOSERVIS_PRIJEM_JSON`). Soubor se otevírá při každém načtení stránky, nic se do něj nezapisuje
a nevystavuje se jako statický soubor. Původní stránku OpenBotu `/autoservis/view` nech v provozu.

Ověření práv pod účtem služby (adresář má 0700, soubor 0600):
```
UCET=$(systemctl show -p User --value autoservis)
sudo -u "$UCET" test -r /var/lib/openbot/OpenBot/Shared/autoservis-prototype/json-data/visits.json && echo "čte" || echo "NEČTE"
```
Když vyjde **NEČTE**, práva sám neměň – pošli uživateli název účtu (`$UCET`). Přístup pouze pro čtení
domluví se správcem OpenBotu tak, aby fungoval i po atomickém nahrazení souboru.
Po úpravě ověř, že po uložení nové návštěvy ji záložka po **Obnovit** ukáže bez restartu služby.
Když soubor nejde přečíst, záložka ukáže „Příjem vozidel je dočasně nedostupný“ – zakázky fungují dál.

## Kontrola, že aplikace běží
- `curl -s http://localhost:8001/api/zdravi` → `"stav":"ok"` a verze (testovací server běží na portu 8001, viz `ExecStart` ve službě)
- `systemctl status autoservis`, logy: `journalctl -u autoservis -n 50`
- spuštěná verze: `git describe --tags --always` (u vydání přesně `vX.Y.Z`, jinak `vX.Y.Z-počet-gcommit`)

## Nové zprovoznění (kdyby bylo potřeba celé znovu)
```
sudo apt install git python3-venv
git clone https://github.com/ZabojnikM/Autoservis.git /CESTA/K/AUTOSERVIS
cd /CESTA/K/AUTOSERVIS
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
echo '@nastroje/server-CLAUDE.md' > CLAUDE.md
```
Databázi (`data/autoservis.db`) a `.env` přenést ze zálohy. Služba systemd: šablona je
v `nastroje/autoservis.service` (doplnit uživatele a cestu, `AUTOSERVIS_AKTUALIZACE=vydani`,
`AUTOSERVIS_PRIJEM_JSON`),
zkopírovat do `/etc/systemd/system/` a `sudo systemctl daemon-reload && sudo systemctl enable --now autoservis`.
Složka musí patřit uživateli služby (jinak git hlásí „dubious ownership“ a aktualizace selže).

`spustit.bat` je jen pro vývoj na Windows, na serveru se nepoužívá.
