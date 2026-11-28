# Autoservis – pokyny pro AI agenta (vývoj)

Tento soubor čtou agenti (OpenBot, Codex, Claude Code a další), kteří na projektu **vyvíjejí**.
Popis aplikace a ovládání je v [README.md](README.md), historie a deník změn v [PLAN.md](PLAN.md),
předání projektu a nastavení agenta v OpenBotu v [docs/OPENBOT.md](docs/OPENBOT.md).

> **Běžíš u ostrého provozu (Linux, služba systemd `autoservis`, port 8001)?**
> Pak tento soubor neplatí. Řiď se jen [nastroje/server-CLAUDE.md](nastroje/server-CLAUDE.md):
> v ostrém provozu se kód neupravuje, necommituje ani nepushuje a nic se tam nezkouší.

## Prostředí
| Prostředí | Kde | K čemu |
|---|---|---|
| **Ostrý provoz** | Linux, služba systemd `autoservis`, **port 8001**, ostrá databáze | práce servisu; aktualizuje se jen vydanými verzemi tlačítkem v Nastavení, **instaluje je výhradně majitel** |
| **Vývoj a testy** | Linux, **port 8002**, samostatné klony a kopie databáze | vývoj, náhledy a zkoušení před vydáním |

Jiné prostředí se nepoužívá.

## Komunikace
- S uživatelem mluv **česky**: v chatu, v souhrnech, v issues, v commitech i v textech aplikace.
- Uživatel je majitel autoservisu, ne programátor. Piš věcně a srozumitelně a vysvětluj, co se změnilo pro práci v dílně.

## Technologie a spuštění (vývoj, Linux)
- Python 3.12, FastAPI, SQLite (SQLModel), Jinja2 + HTMX, Pico.css + vlastní `app/web/static/app.css`.
- Prostředí: `python3.12 -m venv .venv` a pak `.venv/bin/python -m pip install -r requirements.txt`.
- Testy: `.venv/bin/python -m pytest`. **Před každým commitem musí procházet.**
- Spuštění: `.venv/bin/python -m uvicorn app.main:app --port <port>`.
- Jinou databázi vybere proměnná `AUTOSERVIS_DB` – pro náhledy a testy v prohlížeči vždy **kopie** databáze.
- Na testovací instanci 8002 se nasazuje ověřený `main` do samostatného klonu; před přepnutím konzistentní záloha
  SQLite (backup API) a pracovní kopie databáze. Kód se po změně `.py` načte až po restartu procesu.

## Data – ostrý provoz
- Ostrá databáze (8001) obsahuje **skutečná data servisu** (zákazníci, vozidla, zakázky, doklady). Do gitu nepatří
  (`.gitignore`). Ve vývoji se pracuje jen s kopií.
- Aplikace při startu (`init_db` v `app/db.py`) **hned spustí migrace**. Po instalaci vydání se tak migrace provede
  i nad ostrou databází. Z toho plyne:
  - Migraci a změnu schématu napiš a otestuj **nejdřív nad kopií DB** (8002), do vydání ji pusť až ověřenou.
  - Před každým zásahem do DB (migrace, hromadné úpravy, import) udělej zálohu do `data/backups/`
    (`pred-<co>-RRRRMMDD-HHMMSS.db`).
- Při testování v prohlížeči zakládej jen záznamy označené **TEST** a po testu maž **jen ty své**.
  Nikdy nemaž celou databázi. Testuje se jen na kopii (8002, `AUTOSERVIS_DB`), **nikdy v ostrém provozu**.
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

## Verze, vydání a ostrý provoz
- Verze má tvar `MAJOR.MINOR.OPRAVA`. Verze `1.0.0` přišla s úplným přechodem ze starého systému.
  Nová funkce zvýší MINOR, oprava vydané verze OPRAVA.
- Postup vydání je v README v části „Verze a vydání“: `APP_VERSION` v `app/config.py`, commit „Verze X.Y.Z“,
  `git tag -a vX.Y.Z`, push větve i značky a `gh release create` se seznamem uzavřených issues.
- **Ostrý provoz** (Linux, systemd `autoservis`, port 8001) instaluje **jen vydané verze**
  (`AUTOSERVIS_AKTUALIZACE=vydani`) tlačítkem *Nastavení → Aktualizace aplikace*; instaluje je **jen majitel**.
  Běžný push na `main` se tam nedostane. Vydává se jen verze ověřená na 8002.
- **Na server nic nekopíruj** (sdílený disk, scp, robocopy). Ručně změněné soubory zablokují aktualizaci.
  „Nahrát na server“ znamená vydat verzi a uživatel ji na serveru nainstaluje tlačítkem.
- Pokyny pro agenta u ostrého provozu: `nastroje/server-CLAUDE.md`, šablona služby: `nastroje/autoservis.service`.

## Napojení na okolí
- **Příjem vozidel** (záložka): příjmy zapisuje agent *Luigi* (přijímací technik) v OpenBotu přes MCP s oprávněním klíče
  „Příjem vozidel“ do tabulky `prijemvozidla` (posledních 30, bez fotek, #216). Soubor `visits.json` se už nečte.
- **Import ze starého systému**: export přes ODBC (602SQL, 32bit) **jen ke čtení nad zkušební kopií**
  (DSN `AutoservisTest`). Do originální databáze starého systému se nikdy nezapisuje.
  Skripty: `nastroje/stary_system_export.py` a `app/importers/stary_system.py`. Stav je v `IMPORT_STARY_SYSTEM.md`
  a v issue #10.
- **MCP ke starému systému** je samostatné soukromé repo `ZabojnikM/autoservis-mcp`. MCP server samotného
  Autoservisu (`app/mcp_server/server.py`, na `/mcp/`) a REST API (`app/api/`, `/api/v1`) jsou pro boty v OpenBotu;
  logika je v `app/api/*.py` (sdílí ji REST i MCP), klíče a zapnutí v *Nastavení → API pro boty* (#145–#148).
- **Registr silničních vozidel**: tlačítko Načti u VIN. API klíč je v Nastavení aplikace (v DB), ne v kódu.

## Bezpečnost
- Agent v OpenBotu běží s plným přístupem a bez potvrzování. O to opatrněji zacházej s ostrou DB:
  vždy nejdřív záloha a pak jen kopie.
- Hromadné mazání, mazání dat, přepisování historie gitu (`push --force`, `reset --hard` na `main`) a změny služby
  na serveru dělej jen se souhlasem uživatele.
