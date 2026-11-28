# Autoservis

Jednoduchý a lehký software pro správu malého autoservisu – příjem zakázek, databáze vozidel a zákazníků, ceník a sklad.
Plán vývoje a stav jednotlivých kroků: [PLAN.md](PLAN.md).
Pokyny pro AI agenty: [AGENTS.md](AGENTS.md), předání projektu do OpenBotu: [docs/OPENBOT.md](docs/OPENBOT.md).

**Technologie:** Python 3.12, FastAPI, SQLite, Jinja2 + HTMX, Pico.css + vlastní desktopový styl (`app.css`).

> ⚠️ Ostrý provoz běží na linuxovém serveru (služba systemd `autoservis`, port 8001) s **ostrými daty**.
> Vývoj a zkoušení probíhá na testovací instanci (port 8002) nad kopií databáze. Aktualizace se instalují
> tlačítkem v Nastavení (aplikace před instalací sama zazálohuje databázi).

## Instalace a spuštění (Linux)

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

V ostrém provozu běží aplikace jako služba systemd (šablona `nastroje/autoservis.service`, postup
v `nastroje/server-CLAUDE.md`). Spuštění nad jinou databází (např. kopií pro zkoušení) – proměnná `AUTOSERVIS_DB`:

```bash
AUTOSERVIS_DB=data/autoservis-kopie.db .venv/bin/python -m uvicorn app.main:app --port 8002
```

## Zástupce na ploše (pracovní počítače)

Aplikace se na pracovních počítačích neinstaluje – běží na serveru a otevírá se v prohlížeči. Aby vypadala jako
samostatný program (vlastní okno bez adresního řádku, ikona na ploše a v nabídce Start), stačí na každém počítači
jednou spustit `nastroje\zastupce-autoservis.bat` (dvojklik) a zadat adresu serveru, např. `http://server:8001`.
Skript použije Chrome (případně Edge) v režimu `--app` a stáhne ikonu ze serveru. Zástupce jde kdykoli smazat.

Nejjednodušší je stáhnout instalátor přímo z aplikace: **Nastavení → Aplikace v samostatném okně (Windows)**.
Stáhne se jediný soubor `Autoservis-zastupce.bat` s už vyplněnou adresou serveru – stačí ho spustit dvojklikem.

Bez dotazu na adresu:

```powershell
powershell -ExecutionPolicy Bypass -File nastroje\zastupce-autoservis.ps1 -Adresa http://server:8001
```

## Ovládání (desktopový vzhled jako starý systém)

- **Menu** je vodorovně nahoře, **tlačítka akcí** ve sloupci vlevo (na mobilu řádkem nad obsahem).
- **Nastavení → Doplnit údaje vozidel z registru** načte u všech vozidel s VIN kód motoru, stav v registru a platnost STK (na pozadí, asi 22 vozidel za minutu, s průběhem a přehledem). Vozidlo mimo provoz má místo STK šedě svůj stav.
- **Datum** se píše do obyčejného pole jako `20.11.2026` (bez kalendáře). Stačí i zkráceně: `20.11.` = letošní rok, `20.11.26` nebo `20112026`. Po opuštění pole se datum doplní celé, neplatné datum aplikace odmítne.
- **Seznamy**: jedním **kliknutím** na řádek záznam otevřete (Ctrl+klik = nová karta), stejně i u zakázek ve vyhledávání. Nápověda dole i bublina na řádku to říkají stejně.
  Klik na **hlavičku sloupce** seřadí (znovu = opačně), hledání filtruje **při psaní**, zobrazí se 100 řádků
  a další přes **Načíst další / Načíst vše** ve stavovém řádku. Text se řadí podle české abecedy.
- Formuláře (zakázka, vozidlo, zákazník, ceník, položka zakázky, vystavení dokladu) se otevírají jako **okno**
  nad stránkou; Esc = Zrušit (při neuložených změnách se zeptá).
  Ctrl+klik otevře formulář jako celou stránku.
- Ve formulářích **Enter přejde na další pole**, **Ctrl+Enter uloží**. Ve víceřádkovém popisu je Enter nový řádek (Tab = další pole).
- Okno **Přidat materiál z ceníku** po otevření ukáže **30 nejpoužívanějších dílů** (sloupec Použito). Při hledání je přesná shoda kódu nahoře, pak díly podle počtu použití. Díly použité aspoň 3× jsou světle podbarvené, pod čarou „Méně používané díly“ jsou díly použité 1–2× a nepoužité.
- V okně **Přidat materiál z ceníku** Enter v hledání **vloží díl**, když se text přesně shoduje s jeho kódem (velikost písmen a mezery nevadí). Jinak otevře **Nový materiál** s kódem z hledání. Řádek vybraný šipkami vloží Enter jako dřív.
- V mřížce položek **Delete** odebere vybraný řádek (s potvrzením).
- **Ovládání šipkami** (#185), když se nepíše do pole a není otevřené okno:
  - **Seznamy** (Zakázky, Vozidla, Zákazníci, Materiál, Práce, Faktury, Příjem): **↑/↓** vybere řádek (po otevření
    je vybraný první), **Enter** ho otevře, **←/→** přejde na sousední záložku hlavního menu
    (Zakázky → Vozidla → Zákazníci → Materiál → Práce → Faktury → Příjem vozidel a zase Zakázky),
    **Insert** a **Ctrl+N** = nový záznam (u Faktur a Příjmu nic). **Home** / **End** první a poslední řádek,
    **Page Up** / **Page Down** o deset řádků. Psaní písmen a číslic skočí do hledání; z hledání **↓** zpět do seznamu, **Esc** ven.
  - **Detail zakázky**: **↑/↓** projde materiál i práci, **Enter** otevře úpravu položky, **Insert** otevře ceník
    oddílu vybraného řádku (bez výběru ceník materiálu), **Ctrl+←/→** změní množství o 1 a řádek zůstane vybraný,
    takže to jde opakovat (pod 1 jen ručně),
    **Delete** položku odebere. **Home** / **End** a **Page Up** / **Page Down** platí i tady.
    **Esc** vrátí na seznam zakázek. Když je kurzor v poli, první Esc z pole vyskočí a další vrátí na seznam.
    Otevřené okno Esc nejdřív zavře.
  - **Karta vozidla a zákazníka**: **Esc** stejně vrátí na seznam vozidel nebo zákazníků.
  - **Otazník** v horní liště, vlevo od ozubeného kola, otevře okno s klávesami právě otevřené obrazovky. **Esc** ho zavře
    a šipky zase ovládají seznam.
  - **Okno Přidat z ceníku**: **Tab / Shift+Tab** přepne sklad, **↑/↓** vybere řádek,
    **←/→** ubere / přidá kus (u vybraného řádku), **Enter** vloží. Ikona vedle kódu ho zkopíruje do schránky.
  - **Okno Z historie** (tlačítko *Z historie* u materiálu zakázky, #188): materiál dříve vydaný na vozidlo, od
    nejčastěji použitého. **↑/↓** vybere řádek, **Mezerník** nebo dvojklik ho zaškrtne (v poli hledání a množství
    se píše normálně), **Enter** / *Vložit* vloží všechno označené (bez označení vybraný řádek), **Esc** zavře.
    Díl z ceníku se vloží za aktuální cenu z ceníku, díl mimo ceník za cenu ze starší zakázky.
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
  web/           # stránky po oblastech (zakazky.py, vozidla.py, zakaznici.py, prijem.py, cenik.py, faktury.py,
                 #   nastaveni.py, společné pomůcky spolecne.py; routes.py je spojí), templates/ (Jinja2 + HTMX),
                 #   static/app.css a static/app.js (ovládání: okna, klávesnice, kopírování)
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

- **Seznam zakázek** se řadí podle čísla od nejnovější – nejnovější zakázka nahoře (#210); jinak řadit jde kliknutím na záhlaví sloupce.
- **Zakázky**: číslování `RRRR-0001`, stavy Přijato → V opravě → Předáno → Uzavřeno (s dokladem).
  V jedné liště jsou zleva **Nová zakázka**, přepínač **Všechny** / **Otevřené**, hledání a výběr roku (#213).
  Výchozí jsou otevřené zakázky, výběr roku platí pro obě volby.
  **Předáno** znamená vozidlo u zákazníka, zakázka zůstává otevřená, dokud není doklad. **Uzavřít bez dokladu** zavře zakázku
  bez faktury (např. záruka). Seznam zakázek i faktur se otevře na aktuální rok, volba „všechny roky“
  ukáže i starší. Termín dokončení (po termínu červeně), tisk zakázkového listu (tlačítko Tisk).
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
- **Skrýt sklad** (#150): *Nastavení → Katalogy materiálu → Skrýt / Zobrazit*. Skrytý sklad se nenabízí na kartě
  Materiál ani při přidávání materiálu do zakázky (seznam, hledání, přesný kód, Z historie). Staré zakázky a doklady
  se nemění, Správa dat ho vidí dál (přesun dílů). Výchozí katalog skrýt nejde.
- **Import LKQ** (Materiál i zakázka, #8, #199): dodací list LKQ jako **CSV** z e-shopu, nebo jeho **PDF**. Z PDF se
  načte jen dodané zboží (oddíl „Zatím nedodané zboží“ se přeskočí); nákup = „Vaše cena/ks bez DPH“, prodej =
  „Běžná cena/ks bez DPH“, DPH 21 %. Díly se spárují s ceníkem podle kódu, nové se založí, v zakázce se vloží zaškrtnuté.
- **Množství a cena za kus bez DPH** se mění přímo v řádku zakázky (Enter nebo opuštění pole uloží, #163).
  Ručně změněná cena platí jen pro tento řádek, ceník se nemění; když se liší od ceníku, je pod ní šedě
  „ceník …“. Tlačítko *Upravit* u položky z ceníku dál upravuje kartu ceníku (i s cenou v ceníku).
- Peníze se ukládají přesně (desetinná čísla jako text, žádné zaokrouhlovací chyby float).
- **Správa dat** (#132): samostatná záložka v horním menu pro hromadné úpravy skladu a databáze. Běžně je
  skrytá, zapíná se v *Nastavení → Správa dat*. Vypnutá záložka se nezobrazuje a její stránky nejdou otevřít.
- **Statistiky** (#160): záložka s výkonem servisu po měsících a za rok – počet zakázek, materiál (prodej, nákup
  a výdělek), práce a hodiny, celkem a srovnání s předchozím rokem (u běžného roku za stejné období). Počítá se
  z uzavřených zakázek podle data uzavření. Výdělek na materiálu je odhad podle dnešní nákupní ceny v ceníku.
  Běžně je skrytá, zapíná se v *Nastavení → Statistiky*.
- **Sloučit díly** (*Správa dat → Sloučit díly*, #130): stejný díl vedený pod více kódy („2501100“, „25.011.00“)
  se sloučí do jedné karty s novým kódem (např. `UFI 25.011.00`), názvem a cenou.
  - Návrh skupin vznikne sám podle čísla dílu bez mezer, teček, pomlček a předpony výrobce. Díly s úplně jiným
    číslem jde sloučit ručně přes hledání.
  - Ostatní karty se nesmažou, jen vyřadí (s poznámkou, kam byly sloučeny). Staré kódy s jiným číslem dílu se
    zapíšou do „Zaměnitelný díl“, ať je hledání najde.
  - Ve starých zakázkách se přepíše kód a řádky se napojí na ponechanou kartu: historie vozidla ukáže jeden díl
    s novým kódem a vložení z historie vezme novou cenu. **Ceny v zakázkách a vystavené doklady se nemění.**
  - Hromadně: *Stáhnout návrh (CSV)* → v Excelu upravit sloupce Ponechat, Sloučit, Nový kód, Nový název,
    Nová cena → *Nahrát seznam (CSV)* → náhled → *Sloučit vybrané skupiny*. Do skupiny jde přidat i jinou kartu
    řádkem se stejným číslem skupiny a jejím ID.
  - Před každým sloučením se databáze zazálohuje do `data/backups` (`pred-sloucenim-…db`, posledních 10).
- **Import do skladu** (*Správa dat → Import do skladu*, #134): seznam dílů od dodavatele (dodací list LKQ, nebo
  tabulka CSV se sloupci Kód, Název, Prodej / MOC / Cena a nepovinně Nákup) se nahraje do zvoleného nebo nového
  skladu (katalogu, výchozí název „Nový sklad“).
  - Ke každému dílu se dohledají staré karty se stejným číslem bez předpony výrobce, teček a mezer
    (`UFI 25.011.00` ↔ `25.011.00`, `2501100`). V náhledu je jde odškrtnout nebo dopsat další starý kód.
  - Import založí kartu v cílovém skladu (existující se stejným kódem dostane nové ceny) a staré karty do ní
    sloučí stejně jako Sloučit díly. Ceny v zakázkách a vystavené doklady se nemění. Před importem záloha.
  - Díl bez prodejní ceny se nezaloží (v náhledu je označený).
  - Režim *jen nové / jen aktualizace cen / obojí*, párování *podle čísla dílu* (se sloučením starých karet) nebo
    *jen podle přesného kódu*, volitelně vyřadit díly skladu, které v souboru nejsou (#137). Čte i sloupec DPH,
    takže jde nahrát zpět vlastní export.
- **Díly a hromadné úpravy** (*Správa dat → Díly*, #136): tabulka dílů napříč sklady s filtrem (sklad, text, výrobce
  podle předpony, aktivní / vyřazené, použití, nepoužité od data, cena od–do, marže pod %, problém) a řazením
  kliknutím na záhlaví. Akce běží nad zaškrtnutými díly nebo nad všemi podle filtru, vždy přes náhled
  (stará → nová hodnota, přeskočené s důvodem), potvrzení a zálohu:
  - **Export do CSV** s volbou sloupců (jde nahrát zpět Importem do skladu).
  - **Změna cen** (#138): prodej / nákup ± %, prodej podle nákupu a marže, sazba DPH; zaokrouhlení na haléře,
    koruny nebo nahoru na …9 Kč. Ceny ve starých zakázkách se nemění.
  - **Přesun a kopie do jiného skladu** (#139): při stejném kódu v cílovém skladu přeskočit, přepsat ceny, nebo
    (u přesunu) sloučit do cílové karty. Zakázky zůstávají napojené.
  - **Vyřadit, obnovit, trvale smazat** (#140) – smazat jde jen díl, který nikdy nebyl v zakázce.
  - **Úprava kódů a názvů** (#142): doplnit předponu výrobce, sjednotit zápis kódu, hledat a nahradit. Nový kód se
    propíše do starých zakázek, kolize kódu ve skladu se v náhledu přeskočí.
  - Marže = (prodej − nákup) / prodej.
- **Sklady** (#140): počty dílů a smazání celého skladu – nepoužité díly se smažou, použité se přesunou
  do zvoleného skladu (stejný kód = sloučí se), volitelně se vyřadí.
- **Kontroly ceníku** (#141): duplicity, prodej pod nákupem, nulové ceny, bez nákupní ceny, podezřelé kódy, díly bez
  kódu a řádky zakázek bez vazby na ceník (napojit podle kódu, ceny se nemění).
- **Přehledy** (#143): díly bez pohybu, marže podle skladu a výrobce, nejpoužívanější díly.
- **Deník úprav** (#136): každá hromadná úprava se zapíše s názvem zálohy, ze které jde stav vrátit
  (*Nastavení → Zálohy databáze*).

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

- **Stav tisku** (#167): v přehledu Faktury sloupec **Tisk** – *Vytištěno* / *Nevytištěno*. Otevření náhledu stav
  nemění. Po zavření tiskového okna se aplikace zeptá „Vytiskl se doklad?“ (prohlížeč to sám nepozná); ručně jde
  stav přepnout v detailu dokladu (*Označit jako vytištěné* / *Zrušit označení tisku*). Doklady ze starého systému
  jsou označené jako vytištěné.

### Výstupní doklady

Aplikace tiskne jen tyto doklady:

- **Zakázkový list** (A4) – detail zakázky → **Zakázkový list** (otevře se v nové kartě rovnou s tiskem);
  bez položek má prázdné řádky pro ruční zápis, vždy podpisy pro příjem a předání vozidla
- **Odběratel a vozidlo dokladu** (#208) – v okně vystavení jsou předvyplněné ze zakázky a jdou změnit jen pro doklad (zakázka zůstává): odběratel přes **Vybrat** / **Nový**, vozidlo přes SPZ, **Vybrat** (vozidla odběratele nahoře) nebo **Bez vozidla**. Ručně vyplněný odběratel se při vystavení uloží jako nový zákazník (se stejným IČO se použije existující). Doklad je na kartě vybraného zákazníka; stav tachometru jen u vozidla zakázky. Faktura jde vystavit i ze zakázky bez zákazníka;
- **Faktura – daňový doklad** – placená převodem (účet + QR) nebo hotově; tlačítko **Otevřít PDF** (v detailu, v seznamu dokladů odkaz PDF) otevře doklad jako PDF `<číslo>.pdf` ze stejné šablony jako tisk v nové záložce a označí ho jako vytištěný; uložit jde ikonou stahování v prohlížeči PDF nebo Ctrl+S (#189, #193 – Chrome přes http přímé stažení blokuje); částka k úhradě se zaokrouhlí na celé koruny (vypnout jde v Nastavení → Doklady);
  **vyžaduje zákazníka** na zakázce
- **Vyúčtování zakázky** – jde i **bez zákazníka** (odběratel nepovinný)

## API a MCP pro boty (#145–#148)

*Nastavení → API pro boty*: zapnutí (výchozí vypnuto) a klíče pro boty v OpenBotu. Každý klíč má oprávnění
**sklad**, **zakázky**, **vozidla a příjem** a / nebo **příjem vozidel**. Klíč se ukáže jen při vytvoření (v databázi je jen otisk),
zrušit jde kdykoli.

- **REST API** `/api/v1` (hlavička `Authorization: Bearer <klíč>`, odpovědi JSON, ceny bez DPH jako text):
  - sklad: `GET sklad/dily` (filtr jako ve Správě dat + `kod_regex`), `sklad/dily/{id}`, `sklad/sklady`,
    `sklad/kontroly`, `sklad/prehledy`, `sklad/duplicity`; zápis `POST sklad/akce/nahled` → `sklad/akce/provest`
    a `sklad/sloucit/nahled` → `sklad/sloucit/provest`,
  - zakázky: `GET zakazky`, `zakazky/{id}`, `zakazky/radky` (kód i bez teček, bez vazby, podle karty); zápis
    `POST zakazky/radky/nahled` → `zakazky/radky/provest` (kód, název, napojení na kartu; množství a cena jen
    v otevřené zakázce), `POST zakazky/{id}/polozky` (díl z ceníku do otevřené zakázky),
  - vozidla a příjem: `GET/POST vozidla`, `GET/PATCH vozidla/{id}`, totéž pro `zakaznici`, `POST prijem`.
- Hromadný zápis je **dvoukrokový**: náhled vrátí plán a `otisk`, provedení projde jen se stejným otiskem (data se
  mezitím nezměnila). Před zápisem záloha, každý zápis v **Deníku úprav** s názvem klíče.
- **MCP server** na `/mcp/` (streamable HTTP, stejný klíč v hlavičce) nabízí stejné funkce jako nástroje pro boty
  (`hledej_dily`, `nahled_hromadne_akce`, `proved_hromadnou_akci`, `hledej_radky_zakazek`, `prijem_zakazky`…).
- **Příjem vozidel (#216):** záložku Příjem vozidel plní Luigi (přijímací technik v OpenBotu) přes MCP s oprávněním
  **Příjem vozidel**. Technik posílá jen přečtené údaje (`uloz_prijem`: SPZ, VIN, km, nejistá pole; `id` při doplnění),
  zbytek udělá Autoservis:
  - VIN opraví (bez mezer a pomlček, O/Q → 0, I → 1 – tato písmena ve VIN nikdy nejsou) a zkontroluje 17 znaků,
  - příjem se stejnou SPZ / VIN z posledních 24 hodin doplní, nový nezaloží; jiná SPZ je vždy jiné auto,
  - vozidlo najde v databázi (chybějící VIN doplní z ní), u nového auta načte údaje z Registru vozidel
    (klíč registru je v Nastavení),
  - vrátí stav (hotovo, nové auto, chybí VIN, neplatný VIN, VIN není v registru, VIN nesedí, SPZ nesedí, konflikt, registr
    nedostupný) s dalším krokem pro technika; stav čekající na doplnění ukáže záložka u VIN.
  Dále `prijmy`, `smaz_prijem` a ke čtení `hledej_vozidla`, `vozidlo_detail`. Drží se **posledních 30** příjmů, fotky
  se neukládají. Vozidla, zákazníky ani zakázky tento klíč měnit nemůže. Oprava VIN (O/Q → 0, I → 1) platí i pro
  vozidla ve formuláři.
- Přeformátování kódu podle vzoru (`UFI ##.###.##`) je i ve Správě dat → Díly → Úprava kódů.
- **Vzor kódu** ve filtru Správy dat → Díly (a `kod_vzor` v API / MCP, #151): zástupné znaky jako v Excelu a Accessu –
  `*` cokoli, `?` jeden znak, `#` číslice, `[abc]` / `[a-c]` výběr, `[!abc]` mimo výběr, ostatní znaky doslova; platí na
  celý kód (`30 ## ####`, `UFI 30.*`). Předpona jde napsat (např. `30`). Tlačítko **Nápověda k hledání** otevře návod.

## Import ze starého systému

Postup, stav a otevřená rozhodnutí: [IMPORT_STARY_SYSTEM.md](docs/archiv/IMPORT_STARY_SYSTEM.md) (archiv, převod je hotový). Export běží přes ODBC ovladač 602SQL
**jen ke čtení nad kopií** databáze (DSN `AutoservisTest`); do originální databáze starého systému se nikdy nezapisuje.
Zatím naimportován testovací vzorek 50 zakázek (záznamy mají poznámku „Importováno ze starého systému“).

## Aktualizace databáze

Při spuštění se do existující databáze automaticky doplní nové tabulky i sloupce – data zůstanou.
Před aktualizací programu přesto doporučujeme zálohu (zkopírovat `data/autoservis.db`).

## Zálohy databáze

*Nastavení → Zálohy databáze* (#76):

- **Denní záloha** se dělá automaticky na serveru do `data/backups` (`denni-…db`), uchovává se posledních 14.
- **Týdenní záloha** se ukládá do složky zadané v Nastavení, typicky na sdílený disk připojený k serveru.
  Uchovávají se poslední 3 (`autoservis-tydenni-…db`). Prázdná složka týdenní zálohy vypne.
  Ve složce musí být prázdný soubor `.autoservis-cil-zaloh`. Bez něj se do složky nezapisuje, takže při
  nepřipojeném sdíleném disku záloha neskončí v prázdném přípojném bodu na lokálním disku.
  Zálohy se nešifrují – cílové sdílení musí být soukromé.
- Prázdná databáze (bez zakázek a zákazníků, typicky nová instalace) se automaticky nezálohuje, aby
  nevytlačila dobré zálohy. Po nové instalaci stačí zadat složku a obnovit zálohu (#83).
- **Zálohovat teď** udělá ruční zálohu (`rucni-…db`), ta se sama nemaže. Zálohy na serveru jdou stáhnout.
- Každá záloha je konzistentní kopie přes SQLite backup a před uložením se kontroluje (`integrity_check`).
  Aplikace maže jen své staré denní a týdenní zálohy, zálohy před aktualizací ani jiné soubory ve složce nemaže.
- Plánovač běží uvnitř aplikace a každých 10 minut ověří, zda je záloha na řadě. Na vývojovém počítači
  ho jde vypnout proměnnou `AUTOSERVIS_AUTOZALOHY=0`.

### Obnova ze zálohy

U každé zálohy v *Nastavení → Zálohy databáze* je tlačítko **Obnovit** (zálohy na serveru i týdenní ve složce, #77):

1. Záloha se zkontroluje (je to neporušená databáze Autoservisu). Záloha ze sdílené složky se nejdřív zkopíruje na server.
2. Současný stav se uloží do zálohy `pred-obnovou-…db`, ta se sama nemaže. Obnovu tak jde vrátit obnovením této zálohy.
3. Databáze se přepíše obsahem zálohy za běhu aplikace a starší záloha dostane nové sloupce (stejně jako při startu).

Změny provedené po čase zálohy se obnovou ztratí, proto aplikace před obnovou žádá potvrzení.

**Ruční obnova, když aplikace nenaběhne:**

1. Aplikaci zastavte (služba `autoservis` – správce serveru).
2. Poškozenou databázi přejmenujte, například `data/autoservis.db` → `data/autoservis-poskozena-RRRRMMDD.db`
   (i soubory `-wal` a `-shm`, pokud vedle ní jsou). Nic nemažte.
3. Vybranou zálohu (`data/backups/…db` nebo týdenní ze sdílené složky) zkopírujte jako `data/autoservis.db`.
4. Kontrola: `python -c "import sqlite3; print(sqlite3.connect('data/autoservis.db').execute('pragma integrity_check').fetchone()[0])"`
   musí vypsat `ok`.
5. Aplikaci spusťte. Při startu sama doplní chybějící sloupce. Na serveru je potřeba dodržet práva souboru (vlastník
   účtu služby, 0600).

## Verze a vydání

Číslování `MAJOR.MINOR.OPRAVA` (`1.0.0` = úplný přechod ze starého systému, hotový):
nová funkce / větší změna = další MINOR (1.4.0 → 1.5.0), jen oprava vydané verze = OPRAVA (1.4.0 → 1.4.1).
Ostrý provoz instaluje **jen vydané verze**, ověřené na testovací instanci 8002 (`AUTOSERVIS_AKTUALIZACE=vydani`, viz `nastroje/server-CLAUDE.md`),
běžné commity do `main` se na něj nedostanou.

Vydání nové verze (ve vývojovém klonu, testy musí procházet):
1. zvýšit `APP_VERSION` v `app/config.py` a commitnout („Verze X.Y.Z“),
2. `git tag -a vX.Y.Z -m "Verze X.Y.Z"` a `git push origin main vX.Y.Z`,
3. GitHub Release ze značky se seznamem změn (uzavřená issues od minulé verze):
   `gh release create vX.Y.Z --title "Verze X.Y.Z" --notes-file poznamky.md`,
4. na serveru Nastavení → Aktualizace aplikace → Zkontrolovat aktualizace → Nainstalovat.

Seznam vydání: https://github.com/ZabojnikM/Autoservis/releases
