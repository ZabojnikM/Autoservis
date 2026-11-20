# Autoservis – pokyny pro AI agenta (vývoj)

Tento soubor čtou agenti (OpenBot, Codex, Claude Code a další), kteří na projektu **vyvíjejí**.
Popis aplikace a ovládání je v [README.md](README.md), historie a deník změn v [PLAN.md](PLAN.md),
předání projektu a nastavení agenta v OpenBotu v [docs/OPENBOT.md](docs/OPENBOT.md).

> **Běžíš na testovacím serveru (Linux, služba systemd `autoservis`, port 8001)?**
> Pak tento soubor neplatí. Řiď se jen [nastroje/server-CLAUDE.md](nastroje/server-CLAUDE.md):
> na serveru se kód neupravuje, necommituje ani nepushuje.

## Komunikace
- S uživatelem mluv **česky**: v chatu, v souhrnech, v issues, v commitech i v textech aplikace.
- Uživatel je majitel autoservisu, ne programátor. Piš věcně a srozumitelně a vysvětluj, co se změnilo pro práci v dílně.

## Technologie a spuštění (vývojový počítač, Windows)
- Python 3.12, FastAPI, SQLite (SQLModel), Jinja2 + HTMX, Pico.css + vlastní `app/web/static/app.css`.
- Prostředí: `py -3.12 -m venv .venv` a pak `.\.venv\Scripts\python -m pip install -r requirements.txt`.
- Testy: `.\.venv\Scripts\python -m pytest`. **Před každým commitem musí procházet.**
- Spuštění: `spustit.bat`, případně `.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000`.
  Konfigurace pro náhled jsou v `.claude/launch.json` (porty 8000, 8001, 8002, 8010).
- Jinou databázi vybere proměnná `AUTOSERVIS_DB`, například kopie na portu 8010.
- **`uvicorn --reload` na Windows zamrzá**: vypíše „Reloading…“, ale dál běží starý Python kód. Šablony a CSS se
  načtou, `.py` ne. Po změně `.py` server zastav a spusť znovu. Uživateli připomeň, ať po aktualizaci zavře
  okno `spustit.bat` a spustí ho znovu.

## Data – ostrý provoz
- `data/autoservis.db` obsahuje **skutečná data servisu** (zákazníci, vozidla, zakázky, doklady). Do gitu nepatří
  (`.gitignore`). Kopie a zálohy dostaneš soukromě, ne přes GitHub.
- Aplikace uživatele na `http://localhost:8000` běží nad ostrou DB. Po uložení `.py` se restartuje a při startu
  (`init_db` v `app/db.py`) **hned spustí migrace**. Z toho plyne:
  - Migraci a změnu schématu napiš a otestuj **nejdřív mimo `app/`**, skriptem nad kopií DB. Do `app/db.py`
    ji vlož až hotovou. Případně požádej uživatele, ať aplikaci na :8000 zastaví.
  - Před každým zásahem do DB (migrace, hromadné úpravy, import) udělej zálohu do `data/backups/`
    (`pred-<co>-RRRRMMDD-HHMMSS.db`).
- Při testování v prohlížeči zakládej jen záznamy označené **TEST** a po testu maž **jen ty své**.
  Nikdy nemaž celou databázi. Na testy používej kopii (port 8010, `AUTOSERVIS_DB`).
- Peníze se ukládají jako přesná desetinná čísla (text), ne float. Vystavený doklad je kopie a už se nemění.

## Veřejné repo – co sem nepatří
Repo `ZabojnikM/Autoservis` je **veřejné** (licence MIT). Do kódu, komentářů, dokumentů, názvů souborů,
commitů, issues ani release notes **nepiš**:
- **název původního programu**, ze kterého se přechází. V repu se mu říká jen **„starý systém“**
  (importér `app/importers/stary_system.py`, `ImportMapa.zdroj = "stary_system"`, náhradní čísla s prefixem `SS`).
  Skutečný název, jeho zkratku ani doménu najdeš v soukromých podkladech. Před každým pushem ověř
  `git grep -i <název>`, výsledek musí být prázdný.
- osobní údaje zákazníků, SPZ, VIN a telefony ze skutečných dat, IP adresy, hesla a API klíče.

## Úkoly a dokumentace
- **Všechny úkoly, chyby a nápady vedeme v [GitHub Issues](https://github.com/ZabojnikM/Autoservis/issues)**
  (`gh issue create`). Do MD souborů nepiš `- [ ]` seznamy. Po dokončení issue zavři s odkazem na commit.
- `PLAN.md` obsahuje popis projektu a **deník změn** (datum, co a odkaz na issue). Po větší změně ho doplň.
- Když se změní ovládání nebo funkce, aktualizuj `README.md`.
- Commit zprávy píšeme česky, krátce a věcně, s číslem issue: `Okno Přidat z ceníku (#68)`.

## Vzhled a UX
- Aplikace je **jen pro počítač**, cílové okno má 1920×1080. Mobil a tablet se neřeší (byla by to samostatná
  větev vývoje). Mobilní nálezy do issues nezakládej.
- Desktopové ovládání podle starého systému: menu nahoře, akce ve sloupci vlevo, v seznamech otevře záznam jeden klik na řádek (#39, #89),
  formuláře v okně nad stránkou, Enter přejde na další pole, Ctrl+Enter uloží a Esc zavře okno. Podrobnosti jsou
  v `VZHLED.md`, `UX_PROBLEMY.md` a v README v části „Ovládání“.
- Změnu UI ověř v prohlížeči (náhled nad kopií DB), ne jen testy.

## Verze, vydání a testovací server
- Verze má tvar `MAJOR.MINOR.OPRAVA`, zatím `0.x`. Verze `1.0.0` přijde s úplným přechodem ze starého systému.
  Nová funkce zvýší MINOR, oprava vydané verze OPRAVA.
- Postup vydání je v README v části „Verze a vydání“: `APP_VERSION` v `app/config.py`, commit „Verze X.Y.Z“,
  `git tag -a vX.Y.Z`, push větve i značky a `gh release create` se seznamem uzavřených issues.
- **Testovací server** (Linux, systemd `autoservis`, port 8001) instaluje **jen vydané verze**
  (`AUTOSERVIS_AKTUALIZACE=vydani`) tlačítkem *Nastavení → Aktualizace aplikace*. Běžný push na `main`
  se na server nedostane.
- **Na server nic nekopíruj** (sdílený disk, scp, robocopy). Ručně změněné soubory zablokují aktualizaci.
  „Nahrát na server“ znamená vydat verzi a uživatel ji na serveru nainstaluje tlačítkem.
- Pokyny pro agenta na serveru: `nastroje/server-CLAUDE.md`, šablona služby: `nastroje/autoservis.service`.

## Napojení na okolí
- **Příjem vozidel** (záložka, jen čtení): čte `visits.json`, který ukládá agent *Přijímací technik* v OpenBotu
  na serveru (`AUTOSERVIS_PRIJEM_JSON`, výchozí cesta je v `app/config.py`). Do souboru se nikdy nezapisuje.
  Když chybí, záložka ukáže „dočasně nedostupný“ a zbytek aplikace funguje dál.
- **Import ze starého systému**: export přes ODBC (602SQL, 32bit) **jen ke čtení nad zkušební kopií**
  (DSN `AutoservisTest`). Do originální databáze starého systému se nikdy nezapisuje.
  Skripty: `nastroje/stary_system_export.py` a `app/importers/stary_system.py`. Stav je v `IMPORT_STARY_SYSTEM.md`
  a v issue #10.
- **MCP ke starému systému** je samostatné soukromé repo `ZabojnikM/autoservis-mcp`. MCP server samotného
  Autoservisu (`app/mcp_server/`) je zatím jen připravený.
- **Registr silničních vozidel**: tlačítko Načti u VIN. API klíč je v Nastavení aplikace (v DB), ne v kódu.

## Bezpečnost
- Agent v OpenBotu běží s plným přístupem a bez potvrzování. O to opatrněji zacházej s ostrou DB:
  vždy nejdřív záloha a pak jen kopie.
- Hromadné mazání, mazání dat, přepisování historie gitu (`push --force`, `reset --hard` na `main`) a změny služby
  na serveru dělej jen se souhlasem uživatele.
