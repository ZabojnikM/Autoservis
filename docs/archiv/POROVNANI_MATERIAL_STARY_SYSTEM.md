# Okno Materiál – naše aplikace vs. starý systém

> **Archiv – převod ze starého systému je dokončený (ostrý převod 23. 11. 2026).** Dokument zůstává jako historie.

Stav k 18. 11. 2026. Podle snímku okna Materiál (skladová karta) ve starém systému a formuláře položky ceníku u nás
(Ceník → Nová položka / Upravit, typ „Materiál“).
Sloupec „Stav“: ✅ máme · ⚠️ máme jinak / částečně · ❌ chybí · 🚫 záměrně nepoužíváme · 📝 v plánu.

U nás je materiál **položka ceníku** (stejný formulář jako práce, přepínač Práce / Materiál).
Sklad (skladové karty, množství, příjemky) zatím **není** – byl odložen (PLAN.md, fáze 2a).

## Identifikace

| Naše aplikace | Starý systém | Stav |
|---|---|---|
| — (při importu jen v poznámce „Skladová karta ze starého systému …“) | Skladová karta (označení, např. SKL7241) | ⚠️ jen v poznámce |
| Kód / číslo dílu – **první pole formuláře**, nepovinný | Číslo (např. GAT 6PK1018) | ✅ (import: Číslo → Kód) |
| Název (povinný) | Název | ✅ |
| — | Čárový kód | ❌ |
| **Zaměnitelný díl** (kód náhradního dílu, hledá se podle něj) | Náhrada za | ✅ |
| — | Uložení (místo ve skladu, výběr) | ❌ |
| Poznámka (2 řádky) | Popis (větší pole) + Automatický popis | ⚠️ bez automatického popisu |

## Sklad a množství

| Naše aplikace | Starý systém | Stav |
|---|---|---|
| — | Minimální množství | ❌ (není sklad) |
| Jednotka – **výběr** ks, l, m, cm, g, kg, sada (u práce hod, úkon) | Jednotka (výběr) | ✅ |
| — | Sklad (Hlavný / další sklady) | ❌ (není sklad) |
| — | Rezervované množství + Poznámka k rezervaci | ❌ (není sklad) |
| — (při importu jen v poznámce „stav ve starém systému …“) | Stav na skladě (v seznamu karet) | ⚠️ jen v poznámce |

## Ceny

| Naše aplikace | Starý systém | Stav |
|---|---|---|
| **Nákupní cena bez DPH / s DPH** (import: skladová cena; u 116 položek převedena z poznámky) | Skladová (nákupní) cena + F12 s DPH | ✅ |
| **Prodejní cena bez DPH / s DPH** | Cena 1 (prodejní) + F12 s DPH | ✅ (import: Cena 1 → Cena) |
| — | Cena 2 | ❌ |
| — | Cena 3 | ❌ |
| psát jde do pole bez DPH i s DPH, druhé se hned přepočítá (i při změně sazby) | tlačítka F12 – s DPH u každé ceny | ✅ jinak řešeno |
| — | Fixní prodejní ceny | ❌ |
| — | Přepočítat ceny (z nákupní podle marže) | ❌ |
| Sazba DPH % | Sazba DPH % | ✅ |
| Aktivní (vyřazená se nenabízí do zakázek) | Zařazovat do ceníku | ✅ podobné |

## Co máme navíc

- Typ položky **Práce / Materiál** v jednom ceníku; u práce **časová norma (hod)** a cena podle sazby normohodiny.
- Tlačítko **Uložit a další** pro rychlé zadávání více položek.
- Položky se přidávají do zakázky oknem **Přidat z ceníku** (hledání podle názvu i kódu).

## Změny 18. 11. 2026

- Kód / číslo dílu je první pole formuláře (kurzor začíná v něm), dál nepovinný.
- Nové pole **Zaměnitelný díl** (sloupec `polozkaceniku.zamenitelny_dil`), hledání v ceníku i podle něj.
- **Jednotka** je výběr: ks, l, m, cm, g, kg, sada; pro práci hod, úkon. Jiná dřívější jednotka zůstane nabídnutá.
- Ceny jako dvojice **bez DPH / s DPH** pro prodejní i **nákupní cenu** (nový sloupec `polozkaceniku.nakupni_cena`);
  zaškrtávátko „zadaná cena je s DPH“ zrušeno. Cena zadaná s DPH se uloží přesně (385 s DPH zůstane 385).
- Nákupní ceny ze starého systému převedeny z poznámek do nového pole (116 položek), import je dál plní sám.
  Záloha DB před změnou: `data/backups/autoservis-pred-nakupni-cenou-20261118.db`.

## Poznámky k rozhodnutí

- Většina chybějících polí (minimální množství, sklad, rezervace, uložení) patří ke **skladu** – dává smysl je doplnit,
  až se bude dělat sklad.
- Bez skladu by šlo hned doplnit: **nákupní (skladová) cena**, **Čárový kód**, **Náhrada za**, případně **Cena 2 / 3**
  a **Přepočítat ceny podle marže**.
- Skladová cena a stav ze starého systému jsou zatím jen v poznámce položky – při doplnění pole Nákupní cena je půjde přenést.
