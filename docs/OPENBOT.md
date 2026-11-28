# Předání projektu Autoservis agentovi v OpenBotu

Návod, jak v [OpenBotu](https://openbot.run/) nastavit agenta, který bude Autoservis dál vyvíjet.

## Co kde je
| Co | Kde |
|---|---|
| Kód, dokumentace, pokyny pro agenta (`AGENTS.md`) | GitHub `ZabojnikM/Autoservis` (veřejné) |
| Úkoly, chyby, nápady | [GitHub Issues](https://github.com/ZabojnikM/Autoservis/issues) |
| Vydané verze | [GitHub Releases](https://github.com/ZabojnikM/Autoservis/releases) |
| Most ke starému systému (MCP) | GitHub `ZabojnikM/autoservis-mcp` (soukromé) |
| Ostrá databáze, zálohy, soukromé poznámky, lokální nastavení | **soukromý ZIP**, předává se mimo GitHub |

## 1. Přístup ke GitHubu
1. V OpenBotu připoj GitHub (konektor GitHub, přihlášení kódem zařízení).
2. Aplikaci **OpenBot GitHub App** nainstaluj na repozitáře `ZabojnikM/Autoservis`
   a podle potřeby i `ZabojnikM/autoservis-mcp`.
3. Agent pak má `git` a `gh` (issues, release) a GitHub MCP.

## 2. Vytvoření agenta
Nový agent, poskytovatel **Claude Code**, případně Codex, na linuxovém serveru s OpenBotem.
Do pole pro popis agenta vlož prompt z oddílu 3. Po vytvoření zkontroluj, že `AGENTS.md` v pracovní složce
agenta obsahuje text z oddílu 4, a ulož ho.

## 3. Prompt pro vytvoření agenta
```text
Vytvoř agenta „Vývojář Autoservisu“. Mluví česky. Vyvíjí a udržuje aplikaci Autoservis – evidenci zakázek,
vozidel, zákazníků, ceníku a faktur pro malý autoservis (Python 3.12, FastAPI, SQLite, Jinja2 + HTMX).
Kód je v GitHub repu ZabojnikM/Autoservis (veřejné). Úkoly vede v GitHub Issues, vydává verze přes značky
vX.Y.Z a GitHub Releases. Ostrý provoz (port 8001) instaluje jen vydané verze a instaluje je majitel; vývoj a testy
běží na testovací instanci (port 8002) nad kopií databáze. Do ostrého provozu se nic nekopíruje.
Uživatel je majitel servisu, ne programátor: vysvětluj srozumitelně a u rizikových kroků
(ostrá databáze, mazání, vydání verze) se nejdřív zeptej.
Jako instrukce agenta použij text z docs/OPENBOT.md, oddíl 4, z repa ZabojnikM/Autoservis.
```

## 4. Instrukce agenta (`AGENTS.md` v pracovní složce agenta)
```markdown
# Vývojář Autoservisu

Mluv česky. Vyvíjíš aplikaci Autoservis (GitHub ZabojnikM/Autoservis).

## Start
1. Pokud ve své pracovní složce nemáš složku `Autoservis`, naklonuj ji:
   `git clone https://github.com/ZabojnikM/Autoservis.git`
2. Přečti a dodržuj `Autoservis/AGENTS.md`. Je to hlavní návod k projektu a má přednost před tímto souborem.
3. Soukromé podklady (ZIP od uživatele) rozbal do složky `soukrome/` **vedle** klonu, nikdy ne dovnitř repa.
   Začni souborem `soukrome/CTI-ME.md`.
4. Otevřené úkoly: `gh issue list --repo ZabojnikM/Autoservis`.

## Zásady
- Ostrá data jsou jen v soukromých podkladech. Pracuj nad kopií a před každým zásahem do DB udělej zálohu.
- Do veřejného repa nikdy nepiš název starého systému, osobní údaje, IP adresy ani klíče.
- Před commitem musí projít `pytest`. Commity piš česky s číslem issue.
- Vydání verze, mazání dat a změny na serveru dělej jen se souhlasem uživatele.
```

## 5. Soukromý ZIP
Obsahuje to, co do veřejného repa nepatří. Podrobný popis je v `CTI-ME.md` uvnitř ZIPu:
- `data/` – ostrá databáze (snímek), importní kopie, zálohy a vzorek exportu ze starého systému,
- `soukrome-poznamky.md` – název starého systému, adresy serveru, ODBC/DSN a ověřené zvyklosti,
- `pamet-claude/` – poznámky, které si dosavadní agent (Claude Code) vedl o projektu,
- `autoservis-mcp-lokalni/` – lokální nastavení mostu ke starému systému.

ZIP agentovi předej přílohou ve zprávě v OpenBotu (limit 100 MB na soubor), nebo ho ulož do složky
`OpenBot/Shared`, kterou vidí všichni agenti.

## 6. Upozornění
- Agenti v OpenBotu běží s plným přístupem k souborům a příkazům, bez potvrzování jednotlivých kroků.
  Ostrou databázi proto dej agentovi jen jako kopii. Ostrý provoz (8001) a testovací instance (8002) mají vlastní data.
- Agenti kolem Autoservisu: *Vývojář Autoservisu* (vývoj, testovací instance 8002, vydání), *Luigi* (přijímací
  technik – zapisuje příjmy přes MCP s oprávněním Příjem vozidel, #216) a *Skladník* (sklad a ceník přes MCP).
  Nový vývojářský agent jejich soubory jen čte.
