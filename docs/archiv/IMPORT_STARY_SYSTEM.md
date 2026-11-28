# Plán importu dat ze starého systému → Autoservis

> **Archiv – převod ze starého systému je dokončený (ostrý převod 23. 11. 2026).** Dokument zůstává jako historie.

Stav: **etapa 1 schválena** (17. 11. 2026). Odpovídá fázi 5 v [PLAN.md](../../PLAN.md).

## Etapa 1 – testovací vzorek (rozhodnutí uživatele 17. 11. 2026)

- Jen **posledních 50 zakázek** (podle ID) a k nim: vozidla, zákazníci (odběratel zakázky + majitel vozidla),
  práce a materiál na zakázkách, **doklady k těmto zakázkám** s položkami a slevami.
- **Ceník** = jen skladové karty a předvolené práce použité v těchto zakázkách.
- **Všechny importované doklady jako uhrazené** (úhrada na celou částku, datum D_ZAPLAT, jinak datum vystavení).
- Ostrý import později z čerstvé kopie starého systému (rozhodnutí D). Rozhodnutí A–C níže platí až pro plný import.
- Import se provede do kopie `data/autoservis-import.db`; přepnutí na ni až po kontrole.

**Výsledek (17. 11. 2026):** 50 zakázek (205 položek), 45 vozidel, 30 zákazníků, 47 dokladů (všechny uhrazené),
ceník 116 materiálů + 6 prací. Částky dokladů sedí se starým systémem (rozdíl z haléřů jde do zaokrouhlení). 12 upozornění:
2 anonymní odběratelé „_“ → bez zákazníka, 3 zakázky bez vozidla → vozidlo `BEZSPZ-SSZ…`, 2 vozidla bez SPZ → `BEZSPZ-SS…`,
2 vyúčtování bez položek ve starém systému → jeden souhrnný řádek.

### Jak import spustit

```powershell
# 1) export ze starého systému (32bitový Python z Autoservis-MCP, jen čtení)
C:\Autoservis-MCP\.venv\Scripts\python.exe nastroje\stary_system_export.py data\stary-system-export\vzorek.json --zakazek 50
# 2) import do kopie databáze (protokol vznikne vedle exportu)
.\.venv\Scripts\python -m app.importers.stary_system data\stary-system-export\vzorek.json --db data\autoservis-import.db --z-kopie data\autoservis.db
# 3) aplikace nad kopií (port 8001)
$env:AUTOSERVIS_DB="data\autoservis-import.db"; .\.venv\Scripts\python -m uvicorn app.main:app --port 8001
```

Import je opakovatelný (tabulka `importmapa`) – nové spuštění přidá jen to, co ještě převedené není.

## 1. Co ve starém systému je (zjištěno čtením DSN `AutoservisTest`, jen SELECT)

| Tabulka starého systému | Řádků | Význam | Kam u nás |
|---|---:|---|---|
| PARTNERI | 791 (z toho 4 jen dodavatelé) | zákazníci + dodavatelé | `Zakaznik` (787) |
| VOZIDLA | 1 336 | vozidla, každé má majitele | `Vozidlo` |
| ZAKAZKY | 4 300 (2003–2026, 9 otevřených) | zakázky | `Zakazka` |
| VYKPRACE | 5 829 | vykonané práce na zakázce | `PolozkaZakazky` (práce) + `PolozkaFaktury` |
| POHYBY, DRUH = −1 | 16 960 | výdej materiálu do zakázky | `PolozkaZakazky` (materiál) + `PolozkaFaktury` |
| ZLAVY | 285 | slevy na dokladu | záporný řádek `PolozkaFaktury` |
| FAKTURY | 4 297 (2 454 vyúčtování, 1 843 faktur) | doklady | `Faktura` |
| PPD | 401 | pokladní doklady (hotovostní úhrady) | `Uhrada` (hotově) |
| PRACE | 17 | předvolené práce | `PolozkaCeniku` (práce) |
| SKLKARTY | 13 132 (2 305 se zásobou, 3 047 použito od 2020) | skladové karty | `PolozkaCeniku` (materiál) |

**Neimportuje se:** příjemky a skladové doklady (SKLDOKLADY, POHYBY +1), stav skladu (sklad zatím nemáme, fáze 2b),
pracovníci a jejich podíly (PRACPRAC), termíny (1), bonusy, EET, dodací listy (7), předfaktury (3), systémové tabulky.
Vše zůstane ve starém systému a ve staging exportu, takže to jde doplnit později.

Měna je ve všech dokladech **Kč** (MENAEURO = 0), sazby DPH 21 % (dříve 20 %, jednou 14 %).

## 2. Postup (technicky)

Starý systém se čte jen 32bitovým ODBC, naše aplikace běží na 64bitovém Pythonu, proto dva kroky:

1. **Export (jen čtení)** – skript v `C:\Autoservis-MCP` (32bitový Python) přečte vybrané tabulky přes SELECT
   a uloží je jako JSON do `data/stary-system-export/<datum>/` + soubor s počty řádků. Do starého systému se nic nezapisuje.
2. **Import** – nový modul `app/importers/stary_system.py`:
   - pracuje vždy nad **kopií** databáze `data/autoservis-import.db` (vytvoří se z aktuální `autoservis.db`),
   - vše v jedné transakci; při chybě se nic neuloží,
   - nová tabulka `importmapa (tabulka, puvodni_id, nove_id)` → import jde **spustit znovu** (aktualizuje, neduplikuje).
     Díky tomu se dá v den přechodu udělat poslední „dorovnání“ ze starého systému,
   - na konci **protokol** `data/stary-system-export/<datum>/protokol.md`: počty, přeskočené záznamy, opravy, kontrolní součty.
3. **Kontrola** – aplikaci spustím nad kopií (nová proměnná `AUTOSERVIS_DB` v `config.py`), ty si projdeš
   pár vozidel, zakázek a faktur a porovnáš se starým systémem.
4. **Přepnutí** – po tvém OK: záloha `autoservis.db` → `autoservis-pred-importem-<datum>.db`, kopie se stane ostrou DB.

Testy: pytest nad malými vymyšlenými vzorky (žádná skutečná data v testech).

## 3. Mapování polí

**Zákazník** ← PARTNERI (jen odběratelé)
- `nazev` = MENO1 (+ MENO2, pokud je vyplněné a liší se), MENO3 → poznámka
- ulice, město, PSČ, IČO, DIČ, telefon, e-mail 1 : 1; IČ DPH a POZNAMKA → poznámka

**Vozidlo** ← VOZIDLA
- `spz` = SPZ_P (normalizovaná jako v aplikaci); `vin` = CKAROSERIE
- `znacka` / `model` = TYPAUTA rozdělené za prvním slovem („Škoda Octavia 1.9 TDI“ → Škoda / Octavia 1.9 TDI)
- `rok_vyroby` z VYROBENE: „2008“ i „20080305“ → 2008; nesmysly („97“, „4,2005“, „20007“) → prázdné + poznámka
- `palivo`: BA… → benzín, NM/NA/N → nafta, EL → elektro, BA+LPG → LPG, EL+BA → hybrid, jinak původní text
- `motor` = KODTYPUMOT, objem, výkon (spojeno); `barva` = FARBA
- `poznamka` = POZNAMKA + STK do, EK do, č. motoru, doplňky (co je vyplněné)

**Zakázka** ← ZAKAZKY
- `cislo` = OZNACENIE (např. `ZAK2026/0210`) – nekoliduje s naší řadou `2026-0001`
- `datum_prijeti` = D_PRIJATIA + C_PRIJATIA, `tachometr` = TACHOMETER, `termin_dokonceni` = D_UKONCPLAN
- `pozadavek` = POPIS; `poznamka` = popis vykonaných prací + interní popis
- `stav`: uzavřená → **Předáno** (`uzavreno` = D_UKONCENIA), otevřená → **Přijato**, plánovaná (JEPLAN) → Přijato + poznámka „plán“
- `zakaznik_id` z ID_ODBER (odběratel na zakázce)
- Položky: práce z VYKPRACE (JEDCENA bez DPH, množství, sazba), materiál z POHYBY (FAKCENA bez DPH; sleva ZLAVA % se
  započte do ceny), kód a název z karty/práce. Řádky bez ceníkové vazby zůstanou jako ruční řádky (jako u nás).

**Faktura / Vyúčtování** ← FAKTURY
- `typ` = vyúčtování, když VYUCTOV = 1, jinak faktura; `cislo` = OZNACENIE
- odběratel = kopie MENO1–3, adresa, IČO, DIČ z dokladu (ne z aktuálního partnera)
- data: vystavení, DUZP = D_DODANIA, splatnost; `forma_uhrady`: PP → převodem, Hotovost → hotově, Karta (1×) → hotově + poznámka
- `celkem` = S_DPH, `zaokrouhleni` = ZAOKRUH – **přebírá se ze starého systému beze změny**
- položky = práce + materiál s vazbou na doklad + slevy (záporné řádky)
- Kontrola: součet položek vs. BEZ_DPH dokladu. Celkově sedí na 0,2 % (23,30 vs 23,34 mil. Kč);
  doklady, kde rozdíl nesedí, vypíšu v protokolu a dorovnám řádkem „Rozdíl z převodu ze starého systému“, aby částka dokladu seděla.
- doklad je u nás neměnný, storno ani úprava importovaných dokladů se nepředpokládá

**Úhrady** – viz rozhodnutí B.

**Ceník** ← PRACE (práce, jednotka hod → norma) a SKLKARTY (materiál)
- `kod` = katalogové číslo CISLO, pokud je jedinečné, jinak interní OZNACENIE (52 čísel se opakuje)
- `cena` = CENAPR1 (1. prodejní cena bez DPH), `jednotka`, `sazba_dph`; vyřazené karty → neaktivní
- skladová cena, ceny 2–3 a stav zásoby → poznámka (do zavedení skladu)

## 4. Problémy v datech a jak je vyřeším

| Problém | Počet | Řešení |
|---|---:|---|
| vozidlo bez SPZ (u nás povinná a jedinečná) | 23 | SPZ = `BEZSPZ-<id>`, poznámka |
| stejná SPZ u více vozidel | 2 SPZ (4 vozidla) | novější ponechá SPZ, starší dostane `<SPZ>-<id>` + poznámka „duplicita ze starého systému“ |
| stejný VIN u více vozidel | 11 VIN (22 vozidel) | VIN zůstane u vozidla s poslední zakázkou, ostatním se přesune do poznámky |
| zakázka bez vozidla | 3 | vozidlo se dohledá podle SPZ/VIN uložených na zakázce, jinak se založí z údajů zakázky |
| duplicitní číslo zakázky | 4 | druhé dostane příponu `-2` |
| duplicitní číslo dokladu | 1 | totéž |
| víc dokladů k jedné zakázce | 7 zakázek | všechny se naimportují a navážou na zakázku |
| zákazník bez jména | 0 | – |

## 5. Co už je v nové aplikaci

V `autoservis.db` je dnes 1 zákazník, 1 vozidlo a 1 zakázka 2026-0001. Import je **zachová**.
Pokud SPZ tohoto vozidla je i ve starém systému, vozidlo se spojí (údaje ze starého systému doplní jen prázdná pole); zákazník podobně podle IČO / jména + telefonu.

## 6. Rozhodnutí pro tebe (doporučení je první)

- **A. Rozsah historie:** importovat **vše od 2003** (4 300 zakázek, historie vozidel kompletní) × jen posledních N let.
- **B. Neuhrazené faktury převodem:** ve starém systému je 1 101 faktur převodem (2014–2026, 8,5 mil. Kč) vedených jako neuhrazené –
  úhrady se tam zjevně neevidovaly. Doporučuji: faktury vystavené **před 1. 10. 2026** označit jako uhrazené
  (úhrada se datem splatnosti a poznámkou „import – úhrada neevidována ve starém systému“), novější nechat neuhrazené, ať je zkontroluješ.
  Uhrazené (SPLATENA = 1) dostanou úhradu na celou částku k D_ZAPLAT (hotovost podle PPD).
- **C. Ceník materiálu:** importovat jen karty **se zásobou nebo použité od 2020** (~3 500) × všech 13 132 karet.
- **D. Které DSN použít:** import poběží z `AutoservisTest`. Pro ostrý import v den přechodu je potřeba čerstvá kopie ze starého systému
  (nebo DSN na ostrou DB – jen čtení, ale až to výslovně povolíš).

## 7. Kroky a odhad

1. Exportní skript (32 bit) + export do JSON — čtení cca minuty
2. `importmapa`, `AUTOSERVIS_DB`, importér: zákazníci → vozidla → ceník → zakázky + položky → faktury + položky + úhrady
3. Testy na vymyšlených vzorcích
4. Zkušební import do kopie + protokol, kontrola v prohlížeči (seznamy, detail vozidla s historií, faktura, přehled faktur)
5. Tvoje kontrola → přepnutí se zálohou
6. Zápis do PLAN.md (fáze 5) a README
