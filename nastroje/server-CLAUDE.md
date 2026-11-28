# Ostrý provoz Autoservisu (Linux, port 8001) – pokyny pro agenta

Tato složka je **git klon** repozitáře `ZabojnikM/Autoservis` (GitHub) a běží z ní **ostrý provoz**
aplikace jako služba systemd `autoservis` (port 8001) s **ostrou databází servisu**. Vývoj a zkoušení
probíhá jinde (testovací instance na portu 8002), tady se nic nezkouší. Nová verze se
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
- **Nic tu nezkoušej** a nezakládej testovací záznamy – na zkoušení je testovací instance 8002.
- **Neinstaluj aktualizace ani nevracej verzi** – dělá to výhradně majitel servisu tlačítkem v aplikaci.
- Data v databázi jen čti. Zásah do dat (oprava, mazání, obnova ze zálohy) jen na výslovný pokyn majitele
  a vždy po záloze.

## Co není v gitu (patří serveru, aktualizace na to nesahá)
- `data/` – databáze `autoservis.db` (všechna data i nastavení) a `data/backups/`
- `.venv/` – virtuální prostředí Pythonu
- `.env` – lokální nastavení (např. `AUTOSERVIS_DB` = cesta k jiné databázi)
- `CLAUDE.md` – jen import tohoto návodu

Databáze obsahuje skutečná data servisu. Před každým zásahem do ní (jen na pokyn majitele)
udělej zálohu do `data/backups/` přes SQLite backup (ne prostým kopírováním souboru za běhu).

## Aktualizace (instaluje jen majitel)
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

Totéž ručně z příkazové řádky (jen na pokyn majitele, jako uživatel služby, ve složce aplikace):
```
git fetch --tags --prune origin
.venv/bin/python -c "import sqlite3,sys; sqlite3.connect('data/autoservis.db').backup(sqlite3.connect(sys.argv[1]))" data/backups/rucne-$(date +%Y%m%d-%H%M%S).db
git checkout --detach "$(git tag -l 'v*' --sort=-v:refname | head -n1)"   # poslední vydání
.venv/bin/python -m pip install -r requirements.txt   # jen když se změnil requirements.txt
sudo systemctl restart autoservis
```

Ostrý provoz má vždy `AUTOSERVIS_AKTUALIZACE=vydani` (nikdy `main`).

## Příjem vozidel (záložka)
Příjmy zapisuje agent Luigi (přijímací technik v OpenBotu) přes MCP (`/mcp/`) klíčem s oprávněním **Příjem vozidel**
(Nastavení → API pro boty). Ukládají se v databázi aplikace, drží se posledních 30, fotky se neukládají (#216).
Soubor `visits.json` ani proměnná `AUTOSERVIS_PRIJEM_JSON` se už nepoužívají – ve službě mohou zůstat, nevadí.

## Kontrola, že aplikace běží
- `curl -s http://localhost:8001/api/zdravi` → `"stav":"ok"` a verze (ostrý provoz běží na portu 8001, viz `ExecStart` ve službě)
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
v `nastroje/autoservis.service` (doplnit uživatele a cestu, `AUTOSERVIS_AKTUALIZACE=vydani`),
zkopírovat do `/etc/systemd/system/` a `sudo systemctl daemon-reload && sudo systemctl enable --now autoservis`.
Složka musí patřit uživateli služby (jinak git hlásí „dubious ownership“ a aktualizace selže).
