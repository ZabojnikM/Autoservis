# Vzhled aplikace – styl „Moderní“

Platí od 18. 11. 2026. Vybráno ze vzorníku stylů [UI/index.html](UI/index.html) (styl č. 3 „Moderní SaaS“).
Předtím byl krátce nasazený styl 7 „Material Dílna“ (černo-žlutý); nahrazen tímto.

## Kde to je

| Soubor | Co |
|---|---|
| `app/web/static/app.css` | oddíl **VZHLED „MODERNÍ“** úplně na konci souboru – musí zůstat poslední, přepisuje vše nad ním |
| `app/web/templates/base.html` | načítá písmo Inter z Google Fonts (bez internetu se použije systémové písmo) |
| `UI/index.html` | vzorník 10 stylů, samostatná stránka bez vazby na aplikaci (přepínání šipkami ←/→ nebo 1–9, 0) |

Rozložení obrazovek (sloupec akcí vlevo, panely formuláře vedle sebe) zůstává z oddílu „DESKTOPOVÝ VZHLED“.
Vrstva „Moderní“ mění barvy, písmo, tvary, stíny **i rozměry** (pododdíl „ROZMĚRY stylu Moderní“ na úplném konci `app.css`).
Obrazovky jsou proto vzdušnější než dřív – formulář příjmu se na menší monitor nemusí vejít celý bez posouvání.

## Charakter

- Bílé karty na světle šedém pozadí, jemné rámečky a měkké stíny.
- Jeden akcent: fialovo-modrá. Ostatní barvy jen pro stavy.
- Zaoblené rohy: karty 12 px, tlačítka a pole 8 px, stavové štítky jako „pilulky“.
- Hlavičky tabulek malými šedými velkými písmeny, data normálním písmem.

## Barvy (proměnné v `:root[data-theme="light"]`)

| Proměnná | Hodnota | Použití |
|---|---|---|
| `--akcent` | `#5b5bd6` | hlavní tlačítka, aktivní pole, proužek vybraného řádku |
| `--akcent-tmavy` | `#4646b8` | hover tlačítek, odkazy v tabulkách, text aktivní záložky |
| `--akcent-svetly` | `#eeeefd` | podklad aktivní položky menu / filtru, vybraný řádek |
| `--text` | `#111827` | běžný text a nadpisy |
| `--text-tlumeny` | `#5b6472` | poznámky, stavový řádek |
| `--plocha` | `#f4f4f8` | pozadí stránky |
| `--ram` | `#e5e7eb` | rámečky karet, tabulek, polí |
| `--titulek` | `#fafafa` | hlavičky tabulek a panelů |
| `--stin` | měkký dvojitý stín | karty, panely, tabulky |

### Stavy zakázek

Štítek = text v barvě stavu na světlém podkladu té barvy (12 %), s tečkou před textem.

| Stav | Barva |
|---|---|
| Přijato | `#475569` (šedomodrá) |
| V opravě | `#b45309` (tmavě oranžová) |
| Hotovo | `#15803d` (zelená) |
| Předáno | `#1d4ed8` (modrá) |
| Chyba / storno | `#b91c1c` (červená) |

## Rozměry

Základ písma 14 px (1 rem = 14 px), řádkování 1,45.

| Prvek | Rozměr |
|---|---|
| Nadpis stránky (h1) | 1,6 rem (≈ 22 px), tučný |
| Text v tabulce | 0,95 rem (≈ 13,3 px) |
| Hlavička tabulky | 0,72 rem, velká písmena, proložení 0,05 em |
| Buňka tabulky – seznam zakázek | odsazení 12 px / 16 px → řádek ≈ 46 px (třída `seznam-zakazek`, jen stránka Zakázky) |
| Buňka tabulky – všechny ostatní | odsazení 5 px / 12 px (`--radek`) → řádek ≈ 30 px; vozidla, zákazníci, ceník, faktury, položky, okna výběru – víc řádků na obrazovku |
| Popisek pole | 0,85 rem, polotučný; mezera pod polem 12 px |
| Pole formuláře | odsazení 9–10 px / 12 px → výška ≈ 40 px |
| Tlačítko | odsazení 9 px / 16 px |
| Stavový štítek | 0,8 rem, odsazení 2 px / 9 px |
| Horní lišta | výška 58 px, odsazení 10 px / 20 px |
| Menu | položky 7 px / 12 px, mezera 4 px |
| Obsah stránky | odsazení 20 px |
| Mezery mezi kartami | 16 px (`--mezera`) |
| Sloupec akcí | šířka 170 px, vnitřní odsazení 12 px, mezera mezi tlačítky 8 px |
| Karta seznamu | nadpis 18 px / 20 px, filtry a hledání odsazené 20 px zleva |
| Panely detailu | odsazení 16 px, titulek panelu 8 px / 16 px |
| Formulář příjmu | sloupce Zákazník : Zakázka : Vozidlo = 1 : 1 : 1,2 |
| Zaoblení | karty 12 px, tlačítka a pole 8 px, okna 14 px, štítky úplně oblé |

Hustotu celé aplikace jde změnit na jednom místě: `--radek` (výška řádků tabulek; seznam zakázek má vlastní hodnotu
v pravidle `table.seznam-zakazek`), `--mezera` (mezery mezi kartami)
a `--pico-form-element-spacing-vertical` (výška polí).

## Prvky

- **Horní lišta** – bílá s čarou dole; hledání v šedém poli, které se při psaní zbělí a dostane fialový prstenec; „+ Nová zakázka“ fialové.
- **Menu** – bílé, položky jako pilulky; aktivní = světle fialový podklad + tmavě fialový tučný text; hover = světle šedý podklad.
- **Tlačítka** – hlavní fialová s bílým textem; vedlejší bílá s šedým rámečkem a tmavým textem; obrysová s fialovým rámečkem; neaktivní šedá.
- **Tabulky** – bílá karta se stínem, jen vodorovné čáry; hover = velmi světle fialová; vybraný řádek = světle fialový + 3 px fialový proužek vlevo; čísla zakázek (odkazy) tmavě fialová tučně.
- **Filtry stavů** – pilulky jako menu.
- **Formuláře** – bílá pole s šedým rámečkem 8 px; aktivní pole fialový rámeček + prstenec; panely (fieldset) jako bílé karty.
- **SPZ** – všude jako světle šedý štítek (`#f1f2f5`, rámeček `#d1d5db`, zaoblení 6 px) s černým tučným písmem Inter 1,05 em.
  Víc SPZ v jedné buňce (vozidla zákazníka) je tak jasně oddělených; štítek-odkaz při najetí zfialoví.
  V poli pro zadání SPZ jen tučné písmo (bez štítku). Při tisku bez podkladu, jen tenký rámeček.
- **Okna (dialogy)** – zaoblení 14 px, bez rámečku.

## Pravidla čitelnosti

- Barevný text jen v tmavém odstínu (kontrast aspoň 4,5 : 1 na bílé). Světlé barvy jen jako podklad.
- Tlumený text nesvětlejší než `#5b6472`.
- Vybraný řádek musí být poznat i bez barvy – proto proužek vlevo.
- Při tisku se stíny a barevné podklady štítků vypínají.

## Jak změnit

- Barvy: upravit proměnné na začátku oddílu „VZHLED MODERNÍ“ v `app.css`.
- Vrátit dřívější vzhled: smazat celý oddíl „VZHLED MODERNÍ“ (zůstane modrý desktopový vzhled).
- Vyzkoušet jiný styl: otevřít `UI/index.html`, vybrat, a podle něj přepsat oddíl na konci `app.css`.
- Server po změně CSS restartovat není potřeba (soubor má verzi podle času změny), stačí F5.
