# Autoservis – plán projektu

> Jednoduchý a lehký software pro správu malého autoservisu.
> Primárně: **příjem vozidel (zakázky)**, **databáze vozidel a zákazníků**, **jednoduchý ceník / sklad**.
> Připraveno na **napojení přes MCP** a na **importy z různých souborů**.

Tento soubor slouží jako živý plán – hotové kroky odškrtáváme `[x]` a doplňujeme datum do sekce [Deník změn](#deník-změn).

## Úkoly

Od 19. 11. 2026 se **všechny otevřené úkoly, chyby, rozhodnutí a nápady sledují v
[GitHub Issues](https://github.com/ZabojnikM/Autoservis/issues)** – tento soubor je popis projektu a deník změn,
ne seznam úkolů. Výsledky UX auditu z 18. 11. 2026 jsou v [UX_PROBLEMY.md](UX_PROBLEMY.md).

---

## 1. Průzkum podobných softwarů

### 1.1 Komerční řešení (inspirace)

| Software | Trh | Co si vzít jako inspiraci |
|---|---|---|
| **Shop-Ware, Tekmetric, Shopmonkey, AutoLeap** | USA | Tok *příjem → zakázka → odhad → práce → faktura*, stav zakázky, vyhledání vozidla podle VIN/SPZ, digitální zakázkový list |
| **Orderry / RO App** | mezinárodní | Zakázky + CRM + sklad v jednom, normohodiny, jednoduché UI |
| **CarisDMS (TEAS)** | ČR | Zakázkový list s čárovým kódem, plánování oprav, samostatný skladový modul |
| **Anolla** | ČR/SK | Online rezervace termínů (pro nás až pozdější fáze) |

### 1.2 Open-source projekty (struktura dat, nic nepřebíráme)

- `ChanMeng666/automotive-repair-management-system` – Flask + MySQL, rozhraní technik/admin
- `wangonya/auto-repair-saas` – Django, zakázky a zákazníci
- `GusPietrasanta/auto-repair-shop-management`, *Garage Buddy* – ASP.NET, job cards
- České bakalářské práce (ČVUT – „Informační systém pro správu autoservisu“) – rezervace, faktury, zakázky, zákazníci, sklad

### 1.3 Aktuálně používaný software – starý systém

Slovenský desktopový program (jednorázová licence: 150 € jedno PC / 300 € síť, +50 € eKasa, +50 € podpis na tabletu).

| Funkce ve starém systému | U nás |
|---|---|
| Zakázky, evidence práce **podle zaměstnanců** | Fáze 1–2 (doplnit pole „mechanik“ u položky práce) |
| Partneři + jejich vozidla a **historie servisu** | Fáze 1 |
| Termíny / plánování zakázek | Backlog (kalendář) |
| Sklad, **import příjemek** od Inter Cars, LKQ/AutoKelly, Nextis, APSi | Fáze 5–6 (importéry dodavatelů) |
| Faktury, **export do účetnictví** (Pohoda, Money S3, MRP, Omega, MK-soft) | Fáze 7 |
| Načtení firmy podle **IČO** z registrů SK/CZ | Backlog (ARES / RPO) |
| eKasa (SK pokladna), eFaktúra | Jen pokud bude potřeba |
| Síťová verze | Máme zdarma – webová aplikace |

**Klíčové:** naplánovat **migraci dat ze starého systému** (zákazníci, vozidla, historie zakázek, ceník/sklad).

#### Co uživatel ve starém systému reálně používá: **zakázky, sklad, faktury + vyúčtování**
(zdroj: nápověda starého systému, verze 5.00)

**Zakázky**
- Povinné jen: firma/jméno, označení zakázky, **SPZ** (Enter po SPZ doplní vozidlo + majitele).
- Odběratel vybraný ze seznamu; změna adresy na zakázce se propíše do partnera.
- **Druhy zakázek** – u každého druhu se určí, které položky se fakturují (např. záruční).
- **Materiál** = výdej ze skladové karty (výběr prodejní ceny, množství) → odečte sklad.
- **Předběžný výdej** materiálu i práce – neovlivní sklad, jde i bez zásoby, zobrazuje se červeně, je jen na předfaktuře; později „Potvrdit výdaj“.
- **Vykonané práce** ze seznamu předvolených prací (F9), možnost uložit novou práci do seznamu; práce přiřazena **1 nebo více pracovníkům** → výkaz práce za období.
- Plánovaný termín ukončení (po termínu červeně), seznam otevřených / uzavřených zakázek.
- Tisk: zakázkový list, soupis materiálu a prací, **předávací protokol vozidla**, **předfaktura / zálohová / proforma**.
- Smazat zakázku jen když je prázdná.
- **Uzavření zakázky → faktura NEBO vyúčtování** (případně jen dodací list; dodací listy lze později hromadně vyfakturovat).

**Sklad**
- Více skladů, **skladová karta**: skladová cena + **3 prodejní ceny** (kategorie zákazníků), rezervované množství (info).
- **Příjem**: nákupní cena ≠ skladová → vážený průměr (+ nabídka přepočtu prodejních cen podle rabatů) nebo nová karta.
- **Přímý prodej** materiálu (i s prací, bez zakázky) → faktura/vyúčtování nebo dodací list; až 5 rozpracovaných prodejů.
- **Výdej do spotřeby** (samostatná výdejka), **převod mezi sklady** (převodka).
- Doklady: **výdejka, příjemka, převodka** se kumulují jako „otevřený“ doklad a pak uzavřou; storno pohybu; volitelně 1 výdejka na zakázku.
- Inventura, ceník, volitelně povolený záporný stav.

**Faktury a vyúčtování**
- Přehled dokladů: výchozí jen neuhrazené; barvy – uhrazená (černá), před splatností (zelená), **po splatnosti (červená)**.
- **Úhrady**: více úhrad k jedné faktuře, hotově / převodem, záporná úhrada = vrácení.
- Nastavení: plátce DPH, texty pod položkami, zaokrouhlení, konst. symbol, splatnost, vystavil.
- **Číselné řady**: prefix + číslo (počet cifer) + suffix pro každý typ dokladu.
- Export: CSV, PDF, export pro účetnictví.

**Ostatní, co se hodí převzít**
- Historie vozidla (materiál / práce po zakázkách) a historie partnera, tisk evidenčního listu vozidla.
- Načtení firmy podle **IČO** z registru.
- Rychlé klávesy a fulltext (F7 / Ctrl+F7 filtr při psaní), zadání ceny s DPH (F12).
- Zálohování, uzávěrka k datu (zákaz zápisu do starého období).

#### Databáze starého systému (pro migraci)
- **602SQL server „AutosDB“ v. 11** – jeden databázový soubor (~830 MB).
- Cesty k datům: (a) exporty **CSV** z „Tlač dokladů“, (b) **ODBC ovladač 602SQL** a čtení tabulek přímo (jen čtení, nad **kopií** zálohy).
- Do originální databáze **nikdy nezapisovat**.

### 1.4 Závěry z průzkumu

1. Srdcem všech systémů je **zakázka** navázaná na **vozidlo** a **zákazníka**.
2. Vozidlo se hledá podle **SPZ** nebo **VIN** – to musí být nejrychlejší akce v aplikaci.
3. Velké systémy jsou přeplácané a drahé (např. Shop-Ware od ~279 USD/měsíc) – naše výhoda je **jednoduchost**.
4. Zakázka má **stavy** (přijato → v opravě → hotovo → předáno/vyfakturováno).
5. Položky zakázky = **práce** (normohodiny / pevná cena) + **materiál** (ze skladu/ceníku).
6. Ceník a sklad se dají začít jako jedna tabulka „položky“, sklad (množství, příjemky) přidat později.

---

## 2. Vzhled a UX

> Původní návrh (levé menu, vzdušný web, nástěnka) byl 18. 11. 2026 nahrazen **desktopovým vzhledem podle starého systému**.
> Zvoleno **řešení 1 – web se vzhledem desktopového programu** (ze 3 variant: 1 = úprava webu, 2 = PWA + tabulková
> knihovna, 3 = nativní aplikace PySide6). PWA a klávesové zkratky odloženy (nízká priorita).

**Platná pravidla vzhledu (dodržovat u každé nové obrazovky):**
- **Lokální webová aplikace** v prohlížeči; **primární obrazovka 1920×1080** (rozhodnuto 19. 11. 2026, dřív 1366×768)
  – hlavní okna se vejdou bez posouvání.
- **Jen počítač – mobil se zatím neřeší** (rozhodnuto 19. 11. 2026). Mobilní zobrazení by byla úplně jiná větev
  vývoje (samostatné rozhraní), ne úprava tohoto desktopového. Chyby a návrhy jen pro telefon se do issues nezakládají.
- **Hustý desktopový styl**: písmo 14 px, šedá plocha, bílé panely s šedým titulkem, tabulky jako mřížka. Vždy **světlý režim**.
- **Horní lišta**: logo, hledání (SPZ, VIN, jméno, číslo zakázky), tlačítko **+ Příjem vozidla**.
- **Menu vodorovně nahoře** pod lištou: Zakázky, Vozidla, Zákazníci, Ceník, Sklad (zatím neaktivní), Faktury, Nastavení.
- **Tlačítka akcí ve svislém sloupci vlevo** (blok `akce` v šabloně).
- **Seznamy**: klik vybere řádek, **dvojklik otevře**; tlačítka Nový / Otevřít / Upravit pracují s vybraným řádkem;
  filtry stavů jako záložky; stavový řádek s počtem záznamů.
- **Formuláře jako okna** (dialog nad stránkou, `data-okno` + `?okno=1`): OK/Zrušit vlevo, Esc = Zrušit
  (zeptá se při neuložených změnách), **Enter = další pole** (`form.enter-dalsi`). Přímá adresa funguje i jako celá stránka.
- **Úvodní stránka = seznam zakázek** (nástěnka zrušena; neuhrazené doklady jsou ve Fakturách).
- Čeština, datum `DD.MM.RRRR`, měna Kč, DPH 21 %.

---

## 3. Architektura (potvrzeno 17. 11. 2026)

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Web UI      │   │  MCP server  │   │  Importy     │
│ (prohlížeč)  │   │ (AI asistent)│   │ CSV/XLSX/... │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │ HTTP/REST        │                  │
       └──────────┬───────┴──────────────────┘
          ┌───────▼────────┐
          │ Servisní vrstva│  ← veškerá logika jen tady
          │  (services)    │
          └───────┬────────┘
          ┌───────▼────────┐
          │ SQLite databáze│  (jeden soubor, snadná záloha)
          └────────────────┘
```

**Klíčový princip:** veškerá logika (vytvoření zakázky, hledání vozidla, …) je v **servisní vrstvě**.
Web UI, MCP server i importy jsou jen tenké „vstupy“, které volají stejné funkce. Díky tomu přidání MCP ani importů nebude vyžadovat přepisování.

### Doporučený technologický stack

| Část | Volba | Proč |
|---|---|---|
| Jazyk | **Python 3.12+** | Jednoduchý, oficiální MCP SDK, výborné knihovny na importy (CSV, Excel) |
| Backend / API | **FastAPI** | Lehký, automatická dokumentace API |
| Databáze | **SQLite** + SQLModel/SQLAlchemy | Žádný server, jeden soubor, záloha = zkopírovat soubor |
| Migrace DB | Alembic | Bezpečné přidávání sloupců v dalších fázích |
| Frontend | **Jinja2 šablony + HTMX** + Pico.css s vlastním desktopovým stylem (`app.css`) | Žádný build, žádný Node.js, rychlé a lehké |
| MCP | oficiální `mcp` Python SDK | Nástroje typu `najdi_vozidlo`, `vytvor_zakazku` |
| PDF | tisk HTML přes prohlížeč („Uložit jako PDF“) | Bez další závislosti; WeasyPrint jen když bude potřeba |
| QR platba | `segno` | SPAYD QR na faktuře |
| Testy | pytest | |

### Struktura složek (skutečná)

```
autoservis/
  app/
    main.py, config.py, db.py   # vstup, nastavení (AUTOSERVIS_DB), SQLite + doplňování sloupců
    models/        # datové modely (DB tabulky)
    services/      # business logika – sdílená pro UI, MCP, importy
    web/           # stránky po oblastech + routes.py (spojení), spolecne.py, sablony.py, templates/, static/app.css, static/app.js
    importers/     # stary_system.py (import z JSON exportu starého systému)
    api/           # REST endpointy (zatím jen /api/zdravi v main.py)
    mcp_server/    # MCP server (fáze 6, prázdné)
  nastroje/        # stary_system_export.py – export ze starého systému přes ODBC (32bit)
  data/            # autoservis.db (ostrá data!), autoservis-import.db, backups/, stary-system-export/
  tests/
  PLAN.md, IMPORT_STARY_SYSTEM.md, README.md
```

Druhá konfigurace v `.claude/launch.json` (`autoservis-import`, port 8001) spouští aplikaci nad kopií `autoservis-import.db`.

---

## 4. Datový model (základ)

**Fáze 1:**
- **Zakaznik** – id, jméno/firma, telefon, e-mail, adresa, IČO, DIČ, poznámka
- **Vozidlo** – id, SPZ, VIN, značka, model, rok výroby, motor/palivo, barva, poznámka, `zakaznik_id`
- **Zakazka** – id, číslo zakázky (např. `2026-0001`), `vozidlo_id`, `zakaznik_id`, datum přijetí, stav tachometru, stav paliva, popis závady / požadavek zákazníka, stav (přijato / v opravě / hotovo / předáno), předpokládané datum dokončení, poznámka

**Fáze 2+:**
- **PolozkaCeniku** – kód, název, typ (práce / materiál), jednotka, nákupní cena, prodejní cena, DPH
- **PolozkaZakazky** – `zakazka_id`, položka z ceníku nebo ručně, množství, cena
- **SkladovyPohyb** – příjem / výdej, množství, datum, doklad
- **Faktura** – číslo, datum vystavení, DUZP, splatnost, odkaz na zakázku, stav úhrady
- **Nastaveni** – údaje servisu (název, IČO, adresa, účet, logo), číselné řady

---

## 5. Plán vývoje po fázích

### Fáze 0 – Příprava ✅
- [x] Průzkum podobných softwarů
- [x] Návrh vzhledu, základních funkcí a architektury (tento dokument)
- [x] Potvrdit technologický stack → **Python + FastAPI + SQLite + HTMX**
- [x] `.gitignore`, README
- [x] Git repozitář na GitHubu
- [x] Založit Python projekt (venv, `requirements.txt`), kostru složek
- [x] Spustit prázdnou aplikaci v prohlížeči (nástěnka s menu, `/api/zdravi`, 2 testy prochází)

### Fáze 1 – Příjem zakázky + databáze vozidel (MVP) ✅
- [x] Databáze SQLite + modely Zákazník, Vozidlo, Zakázka
- [x] Servisní vrstva: CRUD zákazníků, vozidel, zakázek
- [x] Stránka **Vozidla**: seznam, vyhledávání (SPZ/VIN/značka), detail, přidat/upravit
- [x] Stránka **Zákazníci**: seznam, detail s vozidly, přidat/upravit
- [x] **Příjem zakázky** – jeden formulář: najdi vozidlo podle SPZ → když neexistuje, rovnou ho založ i se zákazníkem → vyplň tachometr, závadu → uložit
- [x] Automatické číslování zakázek
- [x] Seznam zakázek s filtrem podle stavu, změna stavu
- [x] Detail vozidla s **historií zakázek**
- [x] Jednoduchá nástěnka (otevřené zakázky) – *18. 11. 2026 zrušena, úvod = seznam zakázek*
- [x] Základní testy servisní vrstvy
- [x] Návod na spuštění v README (+ testy webu, celkem 26)
- [x] Globální hledání v horní liště (přesná SPZ → rovnou detail vozidla), tisk zakázkového listu přes prohlížeč

### Fáze 2a – Ceník a položky zakázky ✅
- [x] Ceník: **práce** a **materiál** (kód, název, jednotka, cena bez DPH, sazba DPH, vyřazení), hledání, filtr
- [x] Práce s pevnou cenou (časová norma / normohodiny zrušeny 18. 11. 2026)
- [x] Zadání ceny **s DPH** → přepočet na cenu bez DPH (jako F12 ve starém systému)
- [x] Zakázka: přidání položek **z ceníku** (hledání) i **ručně** (+ volba „uložit i do ceníku“), úprava a odebrání řádku
- [x] Součty: práce / materiál / bez DPH / **DPH po sazbách ze součtu základů** / celkem; tisk zakázkového listu s položkami
- [x] Nastavení: plátce DPH, výchozí sazba DPH, měna
- [x] Řádky zakázky jsou kopie – změna či smazání ceníku zakázky nezmění; předanou zakázku nelze měnit; smazat jde jen prázdnou zakázku

### Fáze 2b – Sklad (odloženo) ☐
Úkoly v issue [#12](https://github.com/ZabojnikM/Autoservis/issues/12).

### Fáze 3 – Faktury a vyúčtování ✅ (základ)
- [x] Nastavení: **údaje servisu** (dodavatel), bankovní účet (IBAN se dopočítá), **číselné řady** `FV{RRRR}` / `VY{RRRR}` + počet číslic, splatnost, text pod dokladem
- [x] **Uzavření zakázky → faktura nebo vyúčtování** (data, DUZP, splatnost, forma úhrady, odběratel upravitelný jen pro doklad, „platí hned“)
- [x] Doklad je neměnná kopie (položky, odběratel, vozidlo); zakázka se uzavře a nejde znovu otevřít bez storna
- [x] **Storno** (číslo zůstává obsazené, zakázka se znovu otevře) – jen bez úhrad
- [x] Přehled dokladů: neuhrazené / po splatnosti / uhrazené / vše (barevně), hledání, rok, typ, součty; výchozí filtr = neuhrazené
- [x] **Úhrady** – více úhrad na doklad, **převodem / hotově** (karta odebrána), vrácení (záporná), kontrola přeplatku
- [x] Hotovost se volitelně zaokrouhluje na koruny, **QR platba** (SPAYD), VS z čísla dokladu
- [x] **Tisk / PDF** faktury a vyúčtování (A4, přes prohlížeč „Uložit jako PDF“)
- [x] Automatické doplňování nových sloupců do existující databáze (`db.doplnit_sloupce`)
- Druhy zakázek (záruční… – co se fakturuje) → [#13](https://github.com/ZabojnikM/Autoservis/issues/13)

> **Rozhodnutí uživatele (17. 11. 2026):** výstupní doklady jen **zakázkový list, faktura (převodem / hotově)
> a vyúčtování**. Předfaktura, dodací list s hromadnou fakturací, platba kartou a export CSV byly
> vytvořeny a na přání **odebrány** – nepřidávat bez vyžádání.

### Fáze UI – Desktopový vzhled jako starý systém ◐ (průběžně, viz sekce 2)
**Hotovo (18. 11. 2026)**
- [x] Porovnání 3 řešení (web / PWA + tabulky / nativní) → zvoleno řešení 1
- [x] Hustý desktopový styl, mřížky s výběrem řádku a dvojklikem, filtry jako záložky, vynucený světlý režim
- [x] Menu vodorovně nahoře, tlačítka akcí ve sloupci vlevo na seznamech i detailech
- [x] Nová zakázka a úprava zakázky zhuštěné na 1366×768 a otevírané jako **okno**
- [x] Nástěnka zrušena, úvod = seznam zakázek

**Plán dalších úprav UI** (pořadí = doporučená priorita)
1. [x] **Sjednotit zbývající formuláře do stylu okna** *(18. 11. 2026)* – nové/úprava **vozidla** (panely Vozidlo |
   Zákazník + Poznámka), nový/úprava **zákazníka**, položka **ceníku** (Uložit a další nechá okno otevřené,
   Smazat vlevo, dvojklik na řádek ceníku otevře okno), úprava **položky zakázky**, **vystavení faktury /
   vyúčtování** (panely Doklad a úhrada | Odběratel, přepnutí typu v okně). Makra `zacatek_formulare` a
   `tlacitka_formulare`, šířky oken `uzky` / `stredni`. Úhrada v okně doplněna v kroku 6.
2. [x] **Detail zakázky jako pracovní okno** *(18. 11. 2026)* – stav jako tlačítka v liště nadpisu, hlavička
   v jednom pásu (Vozidlo | Zákazník | Zakázka | Požadavek), **položky jako mřížka** (klik vybere řádek →
   Upravit položku / Odebrat položku vlevo, dvojklik = úprava v okně), součty ve spodní liště.
   **Přidat z ceníku** = okno s hledáním při psaní (bez hledání prvních 100 položek), u řádku množství + Přidat,
   okno zůstane otevřené s hláškou „Přidáno: …“ a po zavření se detail obnoví. **Ruční položka** = samostatné okno.
   Vyúčtovaná / předaná zakázka nemá akce pro položky.
3. [x] **Stejné chování všech seznamů** *(18. 11. 2026)* – zakázky, vozidla, zákazníci, ceník, faktury:
   **řazení kliknutím na hlavičku** (▲/▼, v SQL; faktury v Pythonu kvůli počítanému stavu), **filtr při psaní**
   (HTMX, zachová řazení), **načítání po 100 řádcích** („Načíst další“ / „Načíst vše“), stavový řádek
   „Zobrazeno X z Y“ všude. Odstraněny tiché limity (vozidla/zákazníci 200, zakázky 300, ceník 500, faktury 1000).
   **České řazení** (kolace `cs` v SQLite: č za c, ch za h, bez ohledu na velikost písmen). Modul `services/strankovani.py`.
4. [x] **Detail vozidla a zákazníka** *(18. 11. 2026)* – údaje v pásu panelů (vozidlo: Vozidlo | Motor |
   Termíny a historie | Majitel; zákazník: Kontakt | Adresa a firma | Souhrn | Poznámka) a **záložky historie**:
   vozidlo **Zakázky / Práce / Materiál** (položky ze všech zakázek, jako historie vozidla ve starém systému),
   zákazník **Vozidla / Zakázky / Doklady** (historie partnera, neuhrazeno). Mřížky s výběrem řádku a dvojklikem,
   u zákazníka „Nová zakázka“ pro vybrané vozidlo. Souhrny: návštěvy, poslední km, útrata celkem, STK/EK po termínu červeně.
5. [x] **Zakázkový list A4** *(18. 11. 2026)* – `/zakazky/{id}/tisk` (tlačítko „Zakázkový list“ v detailu otevře
   novou kartu a rovnou tisk): servis, zákazník, vozidlo, údaje příjmu, požadavek, položky se součty (bez položek
   8 prázdných řádků pro ruční zápis), podpisy příjmu i předání. Interní poznámka se netiskne. Společný rám
   `_tisk_a4.html` sdílí i faktura. Do ~8 položek se vejde na 1 stranu A4, delší pokračuje na další.
6. [x] **Drobnosti konzistence** *(18. 11. 2026)* – **okno potvrzení aplikace** místo systémového `confirm()`/`alert()`
   (mazání, storno, odebrání řádku, zavření okna s neuloženými změnami; u nebezpečných akcí červené tlačítko
   a výchozí volba „Ne“; formuláře přes `data-potvrdit`), **krátká hláška vpravo nahoře** po uložení / smazání
   (cookie `zprava`, sama zmizí po 3 s), tlačítka jednotně *Uložit + Zrušit* (okno) / *Uložit + Zpět* (stránka),
   „OK – uložit zakázku“ → „Uložit zakázku“, Nastavení má Uložit vlevo, **úhrada v okně** (dokončen i krok 1),
   povinná pole s hvězdičkou a červeným rámečkem po opuštění prázdného pole.
7. Další kroky UI jsou v issues: offline [#16](https://github.com/ZabojnikM/Autoservis/issues/16),
   klávesové zkratky [#17](https://github.com/ZabojnikM/Autoservis/issues/17), PWA [#18](https://github.com/ZabojnikM/Autoservis/issues/18),
   ověření mobil/tablet/tisk [#19](https://github.com/ZabojnikM/Autoservis/issues/19).

> Pro věrnější kopii starého systému: poslat **snímky obrazovek** starého systému (okna Zakázka, Sklad, Faktury), nebo zapnout
> *computer use* a nechat starý systém projít (odloženo 18. 11. 2026). Zakázku zkoušet jen nad testovací kopií.

### Fáze 4 – Tisk ✅
- [x] **Zakázkový list** jako samostatná A4 stránka ve stylu faktury (18. 11. 2026)
- [x] Faktura / vyúčtování v PDF (hotovo ve fázi 3)

### Fáze 5 – Migrace dat ze starého systému ◐ (plán a postup: [IMPORT_STARY_SYSTEM.md](docs/archiv/IMPORT_STARY_SYSTEM.md))
- [x] Zjistit cestu: ODBC ovladač 602SQL (DSN `AutoservisTest`, čtení přes Autoservis-MCP)
- [x] Pracovat jen nad **kopií** databáze (originál nikdy neměnit)
- [x] Etapa 1: testovací vzorek 50 zakázek s vozidly, zákazníky, ceníkem a doklady (importér `app/importers/stary_system.py`)
- Zbývající převod dat a rozhodnutí A–D → [#10](https://github.com/ZabojnikM/Autoservis/issues/10)

### Fáze 6 – MCP napojení ☐
Úkoly v issue [#20](https://github.com/ZabojnikM/Autoservis/issues/20).

### Fáze 7 – Importy ze souborů ☐
Úkoly v issues [#21](https://github.com/ZabojnikM/Autoservis/issues/21) a [#8](https://github.com/ZabojnikM/Autoservis/issues/8) (dodací listy ZLKQ).

### Další nápady
Backlog je v issue [#22](https://github.com/ZabojnikM/Autoservis/issues/22), zálohování v [#7](https://github.com/ZabojnikM/Autoservis/issues/7),
ARES v [#11](https://github.com/ZabojnikM/Autoservis/issues/11).
Hotovo: dekódování VIN z Registru silničních vozidel (18. 11. 2026).

---

## 6. Otevřené otázky

Přesunuto do issue [#23](https://github.com/ZabojnikM/Autoservis/issues/23).
Vyřešeno: technologie (Python + FastAPI + SQLite + HTMX), cesta k datům starého systému (ODBC),
používané moduly starého systému (zakázky, sklad, faktury + vyúčtování).

---

## Deník změn

| Datum | Co se udělalo |
|---|---|
| 2026-11-17 | Průzkum podobných softwarů, návrh vzhledu, architektury a plánu fází (PLAN.md) |
| 2026-11-17 | Fáze 0: stack potvrzen, kostra projektu, venv + závislosti, prázdná aplikace běží na localhost:8000, testy OK. Git chybí. |
| 2026-11-17 | Doplněno srovnání s aktuálně používaným starým systémem (sekce 1.3) |
| 2026-11-17 | Z nápovědy starého systému sepsány požadavky (zakázky, sklad, faktury + vyúčtování); fáze přeskládány: Sklad → Faktury → Tisk → Migrace ze starého systému → MCP → Importy |
| 2026-11-17 | **Fáze 1 hotová**: modely + servisní vrstva, příjem vozidla (HTMX dohledání SPZ), zakázky se stavy, vozidla, zákazníci, nástěnka, hledání; 26 testů, ověřeno v prohlížeči |
| 2026-11-17 | **Fáze 2a hotová (jen ceník, sklad odložen na přání)**: ceník práce/materiál, normohodiny, položky zakázky z ceníku i ručně, součty s DPH, nastavení; 41 testů, ověřeno v prohlížeči (i mobil) |
| 2026-11-17 | **Fáze 3 (základ) hotová**: faktura / vyúčtování ze zakázky, číselné řady, úhrady, storno, přehled + nástěnka, QR platba, tisk A4/PDF, CSV export, údaje servisu v nastavení; 57 testů, ověřeno v prohlížeči. Nová závislost `segno` (QR kód). |
| 2026-11-17 | Předfaktury (zálohy s převodem na konečný doklad), dodací listy + hromadná fakturace, automatická migrace nových sloupců; 69 testů, ověřeno v prohlížeči |
| 2026-11-17 | Na přání zjednodušeno: výstupní doklady jen zakázkový list, faktura (převodem / hotově), vyúčtování. Odebrány předfaktura, dodací list + hromadná fakturace, platba kartou, export CSV; 59 testů, ověřeno v prohlížeči |
| 2026-11-17 | Zákazník nepovinný: zakázka i vozidlo jdou založit **bez zákazníka** (volba při příjmu), doplnit/změnit později u zakázky i vozidla; vyúčtování bez zákazníka ano, **faktura vyžaduje zákazníka**; 64 testů, ověřeno v prohlížeči |
| 2026-11-17 | **Import ze starého systému – etapa 1**: export přes ODBC (jen čtení), opakovatelný importér s mapou ID, posledních 50 zakázek do kopie `autoservis-import.db`, `AUTOSERVIS_DB` pro spuštění nad kopií; 73 testů, ověřeno v prohlížeči |
| 2026-11-17 | Příjem vozidla: výběr z **databáze vozidel** (hledání i podle zákazníka), tlačítka **Uložit vozidlo / Uložit zákazníka do databáze**, procházení zákazníků, zákazník zakázky volitelný i u známého vozidla; 77 testů, ověřeno v prohlížeči |
| 2026-11-17 | Výběr vozidla a zákazníka v **okně databáze** (seznam s filtrem jako stránky Vozidla / Zákazníci, tlačítko Vložit; vozidlo vloží i svého zákazníka); 78 testů, ověřeno v prohlížeči |
| 2026-11-17 | **Nová zakázka jako okno Zakázka ve starém systému** (vlevo zákazník, uprostřed zakázka, vpravo vozidlo; upravitelné panely, OK uloží i změny zákazníka/vozidla, „Uložit jako nového zákazníka“, Enter = další pole). Vozidlo: kód motoru, objem, výkon, č. motoru, olej, STK, EK (doplněno i u importovaných). Zrušena tlačítka „Uložit vozidlo/zákazníka“. Vynecháno (ve starém systému nepoužívané): druh, pracovník, přistavil/převzal, záloha, příslušenství, ARES, čtení z TP; 82 testů, ověřeno v prohlížeči |
| 2026-11-17 | Úprava vozidla: výběr zákazníka jako v zakázce (stávající / nový / bez zákazníka), totéž v úpravě zakázky; oprava pádu při duplicitní SPZ + nový zákazník; upozornění na restart serveru (reload na Windows zamrzá); 65 testů |
| 2026-11-18 | **Desktopový vzhled (řešení 1, bez PWA)**: hustší styl jako starý systém (14 px písmo, šedá plocha, panely s titulkem, nástrojové lišty, filtry jako záložky, tabulky jako mřížka s výběrem řádku a otevřením dvojklikem, stavový řádek u zakázek), vynucený světlý režim. PWA a klávesové zkratky odloženy; 82 testů, ověřeno v prohlížeči (i mobil) |
| 2026-11-18 | Rozložení jako starý systém: **menu vodorovně nahoře**, **tlačítka akcí ve sloupci vlevo** (původně vpravo, přesunuto na přání). Nová zakázka: OK/Zrušit vlevo, popis a poznámka v panelu Zakázka, zhuštěné popisky – celé okno se vejde na 1366×768. Úprava zakázky stejně: Uložit/Zpět vlevo, panely Zakázka a Zákazník vedle sebe. **Nástěnka zrušena** – úvodní stránka `/` přesměruje na seznam zakázek. **Nová zakázka a úprava zakázky jako okno** (dialog nad stránkou, `?okno=1` vrací jen obsah okna přes `_okno.html`; uložení přes HX-Redirect / HX-Refresh; Esc/Zrušit se zeptá při neuložených změnách); přímé adresy fungují dál jako celé stránky; 83 testů (blok `akce` v šablonách; seznamy: Nový / Otevřít / Upravit nad vybraným řádkem, detaily: Upravit, Tisk, Smazat/Storno, Zpět). Na mobilu jsou akce řádkem nad obsahem; ověřeno v prohlížeči |
| 2026-11-18 | Revize projektu a všech konverzací: PLAN.md srovnán se skutečným stavem (sekce Vzhled a UX, architektura, nová fáze **UI – desktopový vzhled** s plánem dalších úprav, otevřené otázky), README doplněno (ovládání, import ze starého systému, `AUTOSERVIS_DB`); 83 testů prochází |
| 2026-11-18 | **UI krok 1 – formuláře jako okna**: vozidlo, zákazník, ceník, položka zakázky a vystavení dokladu se otevírají jako okno (akce vlevo, zhuštěné panely, chyba zůstane v okně, Esc/Zrušit); přímé adresy dál fungují jako celé stránky. Opraveny zdeformované přepínače ve formulářích. 87 testů, ověřeno v prohlížeči na kopii `autoservis-import.db` (zkušební položka ceníku smazána) |
| 2026-11-18 | **UI krok 2 – detail zakázky jako pracovní okno**: hlavička v pásu, mřížka položek s výběrem řádku (Upravit / Odebrat vlevo, dvojklik), součty v liště, okno **Přidat z ceníku** (F9 styl, přidávání více položek za sebou), okno **Ruční položka**. Na 1366×768 se zakázka s 5 položkami vejde do půlky obrazovky. 90 testů, ověřeno v prohlížeči na kopii DB (přidaná zkušební položka odebrána). Tisk zakázkového listu z nového rozložení neověřen |
| 2026-11-18 | **UI krok 3 – jednotné seznamy**: řazení podle sloupců, filtr při psaní, načítání po dávkách 100 řádků, stavový řádek ve všech 5 seznamech, české řazení textu, zrušené skryté limity počtu záznamů. Ceník se nově výchozí řadí podle názvu (dřív práce před materiálem – jde zvolit kliknutím na Typ). 97 testů, ověřeno v prohlížeči na kopii DB (jen čtení) |
| 2026-11-18 | **UI krok 6 – jednotné drobnosti**: vlastní okno potvrzení místo `confirm()`/`alert()`, krátké hlášky po uložení/smazání, jednotná tlačítka, úhrada v okně, Nastavení s akcemi vlevo, zvýraznění neplatných povinných polí. 104 testů, ověřeno v prohlížeči na kopii DB (uložení beze změny, „Ne“ u odebrání nic nesmaže) |
| 2026-11-18 | **UI krok 5 – zakázkový list A4**: samostatný tiskový doklad (servis, zákazník, vozidlo, požadavek, položky se součty nebo prázdné řádky, podpisy příjmu a předání), tlačítko v detailu otevře tisk v nové kartě; společný tiskový rám s fakturou. 100 testů, ověřeno v prohlížeči na kopii DB (1 strana A4 do ~8 položek) |
| 2026-11-18 | **UI krok 4 – detail vozidla a zákazníka**: panely v pásu, záložky historie (vozidlo: zakázky / práce / materiál; zákazník: vozidla / zakázky / doklady), souhrny (útrata, neuhrazeno, poslední km), tlačítka pro vybraný řádek. 99 testů, ověřeno v prohlížeči na kopii DB (jen čtení) |
| 2026-11-18 | **UX audit** na ostré DB (zakázka, položky, faktura, úhrada, storno, vyúčtování, ceník, vozidla): 39 nálezů v [UX_PROBLEMY.md](UX_PROBLEMY.md), seznam k opravě v OPRAVY.md (zrušen 19. 11. 2026, zbytek v GitHub Issues). Testovací záznamy smazány kromě 2 stornovaných dokladů a zákazníka TEST (nejdou smazat) |
| 2026-11-18 | **Opravy z UX auditu**: faktura jen s údaji servisu (převodem jen s účtem), VS vyúčtování s 9 na začátku, zakázku s doklady nejde smazat a její číslo se znovu nepřidělí, mazání zákazníka s doklady bez chyby 500; storno i s úhradami, zrušené úhrady zůstávají v historii (nový sloupec `uhrada.zruseno`), stav Částečně uhrazeno a nové barvy, filtr Stornované; úprava zakázky ve stejném okně jako příjem (změna vozidla a data přijetí), formulář vozidla s panelem Zákazník; Ctrl+Enter = uložit, Delete = odebrat řádek, kurzor na chybné pole; okno ceníku s pevnou výškou a seznamem „Na zakázce“; cena s DPH se v úpravě ukáže s DPH; „150 Kč“ jako číslo; jednotná adresa a PSČ, kód dílu na dokladu v závorce, hlášky vpravo dole. 109 testů, ověřeno v prohlížeči na kopii ostré DB |
| 2026-11-18 | **Vzhled „Moderní“** (styl 3 ze vzorníku `UI/index.html`, popis ve [VZHLED.md](VZHLED.md)): barvy, písmo Inter, rozměry, husté řádky tabulek (kromě seznamu zakázek), SPZ jako štítek. Seznam vozidel: Značka, Model, Typ vozidla, Kód motoru, Rok, VIN, Majitel; karta vozidla; seznam zákazníků s celou adresou. Popis zakázky nepovinný |
| 2026-11-18 | Podle porovnání se starým systémem ([POROVNANI_ZAKAZKA_STARY_SYSTEM.md](docs/archiv/POROVNANI_ZAKAZKA_STARY_SYSTEM.md)): vozidlo má nové pole **Datum 1. registrace** (nový sloupec `vozidlo.datum_registrace`, záloha DB v `data/backups/`), zrušeno zadávání **Plánovaného ukončení** a **Stavu paliva** (sloupce v DB zůstaly), tlačítko **Načti** u IČO (ARES zatím ne) |
| 2026-11-18 | Ceník – materiál podle porovnání se starým systémem ([POROVNANI_MATERIAL_STARY_SYSTEM.md](docs/archiv/POROVNANI_MATERIAL_STARY_SYSTEM.md)): kód jako první pole, **Zaměnitelný díl**, výběr jednotek, ceny bez DPH / s DPH s okamžitým přepočtem, nová **Nákupní cena** (u 116 položek ze starého systému převedena z poznámky, záloha DB v `data/backups/`); 112 testů |
| 2026-11-18 | **Ceník rozdělen na dva**: menu „Ceník“ (materiál, `/cenik`) a „Práce“ (`/prace`) místo nepoužívaného „Sklad“. Každý má vlastní sloupce (materiál: kód, název, zaměnitelný díl, MJ, nákup, prodej, DPH, prodej s DPH; práce: kód, název, norma, MJ, cena, DPH, cena s DPH) a vlastní okno pro novou položku / úpravu. V databázi dál jedna tabulka (typ), okno Přidat z ceníku v zakázce nabízí obojí; 112 testů |
| 2026-11-18 | **Napojení na Registr silničních vozidel** (veřejné API Datové kostky MD, `app/services/registr_vozidel.py`): tlačítko **Načti** u VIN ve formuláři vozidla i na příjmu doplní značku, model, kód motoru, objem, výkon, palivo, barvu, typ vozidla (varianta + verze), datum 1. registrace a termín STK; rok výroby (z 1. registrace) jen do prázdného pole; doplněná pole zeleně, uloží se až tlačítkem Uložit. API klíč v Nastavení → Registr vozidel. Ověřeno proti skutečnému API – údaje se shodují s převzatými ze starého systému; 129 testů |
| 2026-11-18 | **Zrušen Termín EK a normohodiny**: EK zmizel z formuláře vozidla, příjmu, karty vozidla i importu ze starého systému. Normohodiny: pryč sazba v Nastavení, časová norma v ceníku prací (sloupec Norma, značka „≠ NH“), výpočet ceny hodiny × sazba; práce i ruční položka teď vždy potřebuje cenu. V ostré DB nic nepoužívalo EK ani časovou normu, ceny se nezměnily; sloupce `vozidlo.termin_ek` a `polozkaceniku.cas_nh` v DB zůstaly (aplikace je nečte); 130 testů |
| 2026-11-18 | **Okno Přidat z ceníku**: opravené pole množství (předvyplněno 1), dvojklik / Enter (šipky ↓ ↑) přidá řádek, tlačítko **Upravit** otevře kartu položky ceníku a po uložení se vrátí do okna; tlačítko **Storno** zavře okno a vrátí položky přidané v něm (Zavřít je nechá); tlačítko **Import** připravené (zatím nefunkční). Tlačítko návratu všude jednotně „Zpět“ |
| 2026-11-18 | Seznamy bez velkého nadpisu (název karty je v horní liště): Zakázky, Vozidla, Zákazníci, Ceník, Práce, Faktury, Nastavení. **Zakázky bez vyhledávacího pole** (stačí záložky stavů a řazení, hledat jde horní lištou). Historie vozidla a seznam zakázek při stejném čase přijetí řadí novější založenou první; 135 testů |
| 2026-11-19 | Úkoly přesunuty do **GitHub Issues** (#1–#23): z PLAN.md a OPRAVY.md převedeny otevřené body (import, sklad, ARES, MCP, importy, UI, otázky, backlog), OPRAVY.md smazán, v PLAN.md místo seznamů odkazy na issues |
| 2026-11-19 | **Doklady, stavy a vzhled** ([#31](https://github.com/ZabojnikM/Autoservis/issues/31), [#32](https://github.com/ZabojnikM/Autoservis/issues/32), [#34](https://github.com/ZabojnikM/Autoservis/issues/34), [#35](https://github.com/ZabojnikM/Autoservis/issues/35), [#37](https://github.com/ZabojnikM/Autoservis/issues/37), [#38](https://github.com/ZabojnikM/Autoservis/issues/38), [#40](https://github.com/ZabojnikM/Autoservis/issues/40)): plátce DPH potřebuje k faktuře DIČ (Nastavení vyjmenuje a označí chybějící údaje), hotovost má splatnost v den vystavení; storno vrátí zakázce stav před vystavením (`faktura.stav_zakazky_pred`), Uzavřeno bez dokladu jen s potvrzením a se štítkem „bez dokladu“; `app.css` pročištěn (mrtvá a mobilní pravidla, 191 přepsaných deklarací pryč – ověřeno shodou snímků), písmo 15 px, záhlaví tabulek 12 px, přepínač stavu se zvýrazněným aktuálním stavem, Přidat v okně ceníku obrysově a Vložit s počtem, Smazat plnou červenou, Tab přeskočí tlačítka Vybrat/Nový/Načti, skloňování „položka/y/ek“, skrytý nehotový Import; 156 testů |
| 2026-11-20 | Automatické zálohy databáze (#76): denně na serveru (14), týdně do složky z Nastavení (3), ruční záloha a stažení |
| 2026-11-20 | Obnova databáze ze zálohy v Nastavení (#77): kontrola zálohy, záloha před obnovou, migrace; postup ruční obnovy v README |
| 2026-11-20 | Prázdná databáze se automaticky nezálohuje (#83), nová instalace tak nevytlačí dobré zálohy |
| 2026-11-20 | Příjem vozidel: kompaktní seznam se stavem u tlačítka, zákazník a kopírování VIN (#82) |
| 2026-11-20 | Stavy zakázky: tlačítko bez dokladu se jmenuje „Uzavřít bez dokladu“, u Předáno je napsané, že zakázka zmizí z otevřených (#90). Příjem vozidel: klik na řádek otevře podrobnosti, tlačítko jen svou akci (#85). Seznamy zakázek a faktur se otevřou na aktuální rok (#91) |
| 2026-11-20 | Vzhled: zakázka se jedním klikem otevře i ve vyhledávání, bublina i nápověda říkají totéž (#89). Červená jen u mazání, Zpět a Zrušit neutrální, jedna hlavní akce na obrazovce (#87). Seznam zakázek: stav hned za zákazníkem, vozidlo se nezkracuje, husté řádky (#88). Hledání v seznamu má štítek a krátkou nápovědu (#86) |
| 2026-11-20 | Datum bez kalendáře: všechna pole s datem jsou textová 20.11.2026, se zkráceným zápisem (20.11., 20112026) a kontrolou (#94) |
| 2026-11-20 | Okno Přidat materiál: tlačítka v titulku stejně velká (dlouhý název katalogu se zkrátí), okraj vlevo jako vpravo; Enter v hledání vloží díl s přesně shodným kódem, jinak otevře Nový materiál (#96) |
| 2026-11-20 | Okno Přidat z ceníku (materiál i práce): tlačítka v titulku vysoká 36 px a s písmem jako Ceník / Nový v zakázce, v okně 1280 px se nezalomí (#98) |
| 2026-11-20 | Seznam zakázek: místo Požadavku VIN s Kopírovat, kód motoru a platnost STK (propadlá červeně), řazení podle nich; tlačítko Kopírovat je v celé aplikaci jedno a stejné (#99) |
| 2026-11-20 | **Verze 0.7.2**: vzhled seznamů a tlačítek (#86–#89), datum bez kalendáře (#94), okno Přidat z ceníku (#96, #98), seznam zakázek s VIN a STK (#99) |
| 2026-11-20 | Okno Přidat materiál: po otevření 30 nejpoužívanějších dílů, sloupec Použito, při hledání řazení podle použití, podbarvení a oddělovač nepoužitých; Zaměnitelný díl jen když je vyplněný (#102) |
| 2026-11-20 | Okno Přidat materiál: podbarvení a čára „Méně používané díly“ podle hranice 3 použití (#113) |
| 2026-11-20 | Z historie: přesný kód nahoře, pak podle počtu použití na vozidle, při shodě novější výš (#115) |
| 2026-11-20 | Detail zakázky: Upravit vlevo, Smazat na pravém okraji řádku položky, obě svisle na středu (#103) |
| 2026-11-20 | Detail zakázky: bez štítku zdrojového katalogu za názvem dílu (#103) |
| 2026-11-20 | Detail zakázky: tlačítko Nová zakázka nahoře v levém sloupci |
| 2026-11-20 | Nová zakázka: panely Vozidlo · Zakázka · Zákazník (#104); okno Databáze zákazníků na jeden řádek, Vozidla jako počet a první SPZ (#120) |
| 2026-11-20 | Číslo dokladu jako jedno pole (#106); STK všude: propadlá červeně se štítkem „po termínu“, prázdná šedě „nevyplněno“, sloupec Platnost STK v seznamu vozidel (#107); ceník materiálu se sloupcem Použito (#122) |
| 2026-11-20 | **Verze 0.7.3**: okno Přidat materiál s nejpoužívanějšími díly (#102, #113, #115), řádek položky a detail zakázky (#103, Nová zakázka), nová zakázka s vozidlem první a okno zákazníků (#104, #120), číslo dokladu (#106), STK (#107), Použito v ceníku (#122) |
| 2026-11-20 | Upravit materiál: volba katalogu jako u nového materiálu, změna díl přesune; duplicitní kód v cílovém katalogu se odmítne s hláškou (#124) |
| 2026-11-20 | Hromadné doplnění údajů vozidel z registru v Nastavení: kód motoru, stav v registru a STK (provozované = STK z registru, mimo provoz = stav místo STK), na pozadí 22 VIN/min s průběhem a přehledem (#126) |
| 2026-11-20 | **Verze 0.8.0**: hromadné doplnění údajů vozidel z registru (#126), volba katalogu v úpravě materiálu (#124) |
| 2026-11-21 | Sloučit díly v ceníku materiálu: návrh skupin podle čísla dílu, ruční skupina, hromadně ze seznamu CSV; staré zakázky dostanou nový kód a vazbu na kartu, ceny a doklady beze změny, záloha před sloučením (#130) |
| 2026-11-21 | Záložka Správa dat (zapíná se v Nastavení, výchozí skrytá); Sloučit díly přesunuto z Materiálu do ní; oprava pádu hromadného sloučení při chybné skupině (#132) |
| 2026-11-21 | Správa dat: Import do skladu – seznam dílů od dodavatele do nového / zvoleného katalogu, staré karty se stejným číslem se napárují a sloučí (#134) |
| 2026-11-21 | Správa dat: Díly s filtrem a řazením, export CSV, hromadná změna cen, přesun / kopie mezi sklady, vyřazení / obnovení / smazání, úprava kódů a názvů, smazání skladu, rozšířený import, kontroly ceníku, přehledy a deník úprav (#136–#143) |
| 2026-11-21 | API pro boty s klíči podle oprávnění (sklad, zakázky, vozidla a příjem), přeformátování kódu podle vzoru, MCP server na /mcp/ (#145–#148) |
| 2026-11-21 | Filtr dílů: vzor kódu se zástupnými znaky (* ? # [ ]) i v API/MCP, předpona pro psaní, okno Nápověda k hledání (#151) |
| 2026-11-21 | Tisk dokladů: sloupce Kód a S DPH, bez poznámky importu (#127); ikona kopírování před VIN a kódem materiálu (#154, #156); kód materiálu tučně (#158) |
| 2026-11-21 | Záložka Statistiky (zapíná se v Nastavení): výkon servisu po měsících a za rok z uzavřených zakázek, výdělek na materiálu jako odhad, srovnání s předchozím rokem (#160) |
| 2026-11-22 | Detail zakázky: celkem s DPH tučně (#162), smazání zakázky v okně úpravy (#165), ruční cena za kus jen v řádku zakázky – ceník beze změny (#163) |
| 2026-11-22 | Seznam zakázek jen Otevřené (i předané bez dokladu) a Uzavřené (#166) |
| 2026-11-22 | Stav tisku dokladů: sloupec Tisk v přehledu faktur, dotaz po tisku, ruční přepnutí; doklady ze starého systému označeny jako vytištěné (#167) |
| 2026-11-22 | Skrýt sklad z nabídek a z výběru materiálu v zakázkách, přepínač v Nastavení → Katalogy materiálu (#150) |
| 2026-11-22 | Přehled Faktury: přepínač Vyúčtování / Faktury jako tlačítka, bez volby Všechny (#175) |
| 2026-11-22 | Tisk faktury a vyúčtování: položky menším písmem 8 pt (#177) |
| 2026-11-22 | Tisk faktury a vyúčtování: víc místa pro název položky, číselné sloupce úzké (#179) |
| 2026-11-22 | Tisk faktury bez nápisu „Uhrazeno – neplaťte.“ (#181) |
| 2026-11-22 | Přehled Faktury si pamatuje poslední volbu Vyúčtování / Faktury (#183) |
| 2026-11-22 | Ovládání šipkami v seznamech a v detailu zakázky (↑/↓, Enter, ←/→ záložky, Insert, psaní do hledání) (#185) |
| 2026-11-22 | Šipky: ←/→ přepínají hlavní záložky menu (dokola); okno ceníku Tab = další ceník, ←/→ = kusy (#185) |
| 2026-11-23 | Na celé koruny se zaokrouhlují všechny nové doklady včetně faktury převodem (i částka v QR platbě) (#190) |
| 2026-11-23 | Faktura a vyúčtování: tlačítko Stáhnout PDF (server, WeasyPrint, stejná tisková šablona), stažení označí doklad jako vytištěný (#189) |
| 2026-11-23 | Zakázka: tlačítko a okno Z historie se zaškrtávátky a hromadným vložením (aktuální ceny z ceníku), Z historie odebráno z okna ceníku, kopírování kódu v obou oknech (#188) |
| 2026-11-23 | Kopírování kódu/VIN spolehlivě i na http a v řádcích seznamů (zápis v události copy), fajfka jen při úspěchu (#195) |
| 2026-11-23 | Okna Přidat z ceníku a Z historie: nadpis na středu, tlačítka nad hledáním, hláška dole (#197) |
| 2026-11-23 | Import LKQ čte i PDF dodací list (jen dodané zboží, knihovna pypdf) (#199) |
| 2026-11-23 | Klávesy: Insert na zakázce otevře ceník vybraného oddílu, otazník s nápovědou obrazovky, Ctrl+N jako Insert na seznamech, Home/End a Page Up/Down, Ctrl+šipky mění množství (#202) |
| 2026-11-23 | Nápověda: po Esc seznam zase poslouchá šipky, text okna se nezalamuje do posuvníku; Ctrl+šipka na zakázce mění množství opakovaně (#204) |
| 2026-11-23 | Esc na detailu zakázky, vozidla a zákazníka vrátí na seznam (z pole nejdřív vyskočí, okno se zavře první) (#206) |
| 2026-11-26 | Příjem vozidel z databáze: technik zapisuje přes MCP (oprávnění Příjem vozidel, posledních 30, bez fotek, registr podle VIN), visits.json se už nečte (#216) |
| 2026-11-26 | Příjem: vyhodnocení v Autoservisu – oprava VIN (O/Q → 0, I → 1), spojení se stejnou SPZ / VIN za 24 h, VIN z databáze, registr u nového auta, stav s dalším krokem; technik už registr nevolá (#216) |
| 2026-11-28 | Návody pro agenty a README podle ostrého provozu: 8001 ostrý provoz, 8002 vývoj a testy, bez Windows (#230) |
| 2026-11-28 | Úklid kódu: webové stránky rozdělené podle oblastí, JavaScript v static/app.js, testy webu po oblastech; nepoužívané importy pryč, dokumenty převodu v docs/archiv (#233, #234) |
| 2026-11-28 | PIN pro vstup do Nastavení (30 min, blokace po 5 pokusech, příkaz pro zrušení) a ochrana proti podvrženým požadavkům z cizích stránek (#219, #220) |
| 2026-11-28 | Databáze v režimu WAL s čekáním na zámek 15 s; zálohy vždy jeden soubor v běžném režimu (#228) |
| 2026-11-28 | Záznam událostí do logs/autoservis.log s rotací, náhled a stažení v Nastavení, bez osobních údajů (#225) |

## Zdroje průzkumu

- https://orderry.com/blog/best-auto-repair-software/
- https://roapp.io/blog/how-to-choose-the-best-auto-repair-shop-software-in-2026-10313/
- https://www.softwareadvice.com/auto-repair
- https://gitnux.org/best/auto-repair-order-software/
- https://www.teas.cz/carisdms.html
- https://anolla.com/cs/software-pro-autoservisy
- https://dspace.cvut.cz/handle/10467/94654
- https://medevel.com/free-garage-software-15-open-source-car-repair-and-service-apps/
