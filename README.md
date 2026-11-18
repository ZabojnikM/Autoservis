# Autoservis

Jednoduchý a lehký software pro správu malého autoservisu – příjem zakázek, databáze vozidel a zákazníků, ceník a sklad.
Plán vývoje a stav jednotlivých kroků: [PLAN.md](PLAN.md).

**Technologie:** Python 3.12, FastAPI, SQLite, Jinja2 + HTMX, Pico.css + vlastní desktopový styl (`app.css`).

> ⚠️ `data/autoservis.db` obsahuje **ostrá data**. Před aktualizací programu ji zkopírujte (záloha).

## První spuštění (Windows, PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Spuštění aplikace

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Nebo dvojklikem na `spustit.bat`. Aplikace pak běží na <http://localhost:8000>.

Spuštění nad jinou databází (např. kopií s importem ze starého systému) – proměnná `AUTOSERVIS_DB`:

```powershell
$env:AUTOSERVIS_DB = "data\autoservis-import.db"; .\.venv\Scripts\python -m uvicorn app.main:app --port 8001
```

## Ovládání (desktopový vzhled jako starý systém)

- **Menu** je vodorovně nahoře, **tlačítka akcí** ve sloupci vlevo (na mobilu řádkem nad obsahem).
- **Seznamy**: kliknutím vyberete řádek, **dvojklikem** ho otevřete; Otevřít / Upravit vlevo pracují s vybraným řádkem.
  Klik na **hlavičku sloupce** seřadí (znovu = opačně), hledání filtruje **při psaní**, zobrazí se 100 řádků
  a další přes **Načíst další / Načíst vše** ve stavovém řádku. Text se řadí podle české abecedy.
- Formuláře (zakázka, vozidlo, zákazník, ceník, položka zakázky, vystavení dokladu) se otevírají jako **okno**
  nad stránkou; Esc = Zrušit (při neuložených změnách se zeptá).
  Ctrl+klik otevře formulář jako celou stránku.
- Ve formulářích **Enter přejde na další pole**, **Ctrl+Enter uloží**. Ve víceřádkovém popisu je Enter nový řádek (Tab = další pole).
- V mřížce položek **Delete** odebere vybraný řádek (s potvrzením).
- Chyba ve formuláři přesune kurzor na pole, kterého se týká, a zvýrazní ho.
- Mazání, storno a zavření okna s neuloženými změnami se ptá v **okně aplikace** (výchozí volba je bezpečná „Ne“);
  po uložení se vpravo dole krátce ukáže hláška („Vozidlo uloženo.“ apod.), chyba červeně.
- Když něco smazat nejde (zakázka s položkami nebo doklady, vozidlo se zakázkami…), tlačítko je zašedlé a důvod je napsaný pod ním.
- Po spuštění se otevře **seznam zakázek** (nástěnka byla zrušena, neuhrazené doklady jsou ve Fakturách).

## Testy

```powershell
.\.venv\Scripts\python -m pytest
```

## Struktura projektu

```
app/
  main.py        # vstupní bod FastAPI, obsluha chyb
  config.py      # nastavení (cesta k databázi, …)
  db.py          # připojení k SQLite, vytvoření tabulek
  models/        # datové modely: Zakaznik, Vozidlo, Zakazka
  services/      # business logika – sdílená pro web, MCP a importy
    zakazky.py   #   příjem vozidla, číslování RRRR-0001, stavy
    vozidla.py   #   SPZ/VIN (normalizace, duplicity), historie
    zakaznici.py
    hledani.py   #   globální hledání
    cenik.py     #   ceník práce a materiálu
    polozky.py   #   položky zakázky, součty a DPH
    nastaveni.py #   DPH, údaje servisu, číselné řady
    faktury.py   #   faktury, úhrady, storno, QR platba
  web/           # stránky: routes.py, templates/ (Jinja2 + HTMX), static/app.css
  api/           # REST endpointy (později)
  mcp_server/    # MCP server (fáze 6)
  importers/     # stary_system.py – import z exportu starého systému; další importy (fáze 7)
nastroje/        # stary_system_export.py – export ze starého systému přes ODBC (jen čtení)
data/            # autoservis.db (ostrá data), autoservis-import.db (kopie), backups/, stary-system-export/
tests/
```

## Co aplikace umí (fáze 1)

- **Nová zakázka** (`+ Nová zakázka`) – rozložení jako okno Zakázka ve starém systému:
  vlevo **Zákazník**, uprostřed **Zakázka** (označení, datum a čas přijetí, plánované ukončení, km, palivo),
  vpravo **Vozidlo** (SPZ, typ, VIN, rok, kód motoru, objem, výkon, palivo, olej, barva, č. motoru, STK).
  Tlačítko **Načti** u VIN doplní údaje z Registru silničních vozidel (API klíč v Nastavení).
  Po zadání SPZ a Enteru (Tab) se známé vozidlo vyplní i s majitelem. **Vybrat** otevře okno databáze
  (u vozidla nejdřív vozidla vybraného zákazníka), **Nový** panel vyprázdní. Údaje v panelech jdou přímo
  upravit – **OK** uloží zakázku a změny se zapíšou i k zákazníkovi a vozidlu (zaškrtnutím
  *Uložit jako nového zákazníka* vznikne nový). Prázdný panel zákazníka = zakázka bez zákazníka.
  Enter přechází na další pole.
- **Úprava zakázky** je stejné okno jako nová zakázka – jde změnit i vozidlo (jiná SPZ / Vybrat) a datum přijetí
  (jen dokud k zakázce není platný doklad). **Formulář vozidla** má stejný panel Zákazník (Firma + Vybrat / Nový).
  Zákazníka jde kdykoli doplnit, změnit nebo odebrat (prázdný panel = bez zákazníka); vozidlu bez zákazníka
  se zákazník zakázky přiřadí automaticky.

> **Po aktualizaci programu server restartujte** (zavřít okno `spustit.bat` a spustit znovu) –
> automatické načtení změn kódu na Windows někdy zamrzne a běží dál stará verze.
- **Zakázky**: číslování `RRRR-0001`, stavy Přijato → V opravě → Předáno → Uzavřeno (s dokladem),
  termín dokončení (po termínu červeně), tisk zakázkového listu (tlačítko Tisk).
- **Vozidla** a **Zákazníci**: seznam, hledání, detail, úpravy, historie zakázek.
- **Hledání** v horní liště: SPZ, VIN, jméno, telefon, IČO, číslo zakázky.

## Ceník a položky zakázky (fáze 2a)

- **Ceník** (`/cenik` materiál, `/prace` práce): cena bez DPH (lze zadat i s DPH), sazba DPH.
  Každá položka má vlastní pevnou cenu za jednotku (normohodiny se nepoužívají).
- **Na zakázce** se položky přidávají hledáním v ceníku, nebo ručně (volitelně „uložit i do ceníku“);
  cena je vždy povinná.
- Součty: práce, materiál, základ a **DPH po sazbách** (počítá se ze součtu základů), celkem k úhradě.
- **Nastavení** (`/nastaveni`): plátce DPH, výchozí sazba DPH, měna, API klíč registru vozidel.
- Řádek zakázky je kopie ceníku – pozdější změna ceníku už vystavené zakázky nemění.
- Peníze se ukládají přesně (desetinná čísla jako text, žádné zaokrouhlovací chyby float).

## Faktury a vyúčtování (fáze 3)

1. Nejdřív v **Nastavení** vyplňte údaje servisu (název, IČO, adresa, DIČ), číslo účtu a číselné řady.
   **Bez údajů servisu nejde vystavit fakturu**, bez čísla účtu jen s platbou hotově (vyúčtování jde i bez nich).
2. Na zakázce s položkami: **Vystavit fakturu** nebo **Vyúčtování** → zkontrolovat data, formu úhrady a odběratele → vystavit.
   Zakázka se tím uzavře. Doklad je kopie – už se nemění. Variabilní symbol = číslice z čísla dokladu,
   u vyúčtování s 9 na začátku (FV20260001 → 20260001, VY20260001 → 920260001).
3. **Tisk / PDF**: A4; při platbě převodem s číslem účtu a QR platbou. PDF přes tisk prohlížeče („Uložit jako PDF“).
4. **Úhrady** na detailu dokladu – převodem nebo hotově, i částečné, záporná = vrácení. Zrušená úhrada zůstane
   v historii přeškrtnutá. Stavy: **Neuhrazeno** (oranžově), **Částečně uhrazeno**, **Po splatnosti** (červeně),
   **Uhrazeno** (zeleně), **Stornováno**; v přehledu **Faktury** i filtr Stornované.
5. Chyba na dokladu → **Stornovat**, opravit zakázku a vystavit nový doklad. Případné úhrady storno zruší
   (potvrzení na ně upozorní) – peníze vraťte, nebo je započtěte na nový doklad. Zakázku s doklady nejde smazat.

### Výstupní doklady

Aplikace tiskne jen tyto doklady:

- **Zakázkový list** (A4) – detail zakázky → **Zakázkový list** (otevře se v nové kartě rovnou s tiskem);
  bez položek má prázdné řádky pro ruční zápis, vždy podpisy pro příjem a předání vozidla
- **Faktura – daňový doklad** – placená převodem (účet + QR) nebo hotově (zaokrouhlení na koruny);
  **vyžaduje zákazníka** na zakázce
- **Vyúčtování zakázky** – jde i **bez zákazníka** (odběratel nepovinný)

## Import ze starého systému

Postup, stav a otevřená rozhodnutí: [IMPORT_STARY_SYSTEM.md](IMPORT_STARY_SYSTEM.md). Export běží přes ODBC ovladač 602SQL
**jen ke čtení nad kopií** databáze (DSN `AutoservisTest`); do originální databáze starého systému se nikdy nezapisuje.
Zatím naimportován testovací vzorek 50 zakázek (záznamy mají poznámku „Importováno ze starého systému“).

## Aktualizace databáze

Při spuštění se do existující databáze automaticky doplní nové tabulky i sloupce – data zůstanou.
Před aktualizací programu přesto doporučujeme zálohu (zkopírovat `data/autoservis.db`).
