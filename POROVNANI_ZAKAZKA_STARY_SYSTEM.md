# Okno Zakázka – naše aplikace vs. starý systém

Stav k 18. 11. 2026 (aktualizováno po úpravách téhož dne). Podle snímku okna Zakázka ve starém systému a formuláře nové / upravené zakázky u nás.
Sloupec „Stav“: ✅ máme · ⚠️ máme jinak / částečně · ❌ chybí · 🚫 záměrně nepoužíváme · 📝 v plánu (ToDo v PLAN.md).

## Zákazník

| Naše aplikace | Starý systém | Stav |
|---|---|---|
| Jméno / firma + Vybrat + Nový | Firma (příjmení a jméno) + Vybrat | ✅ |
| — | Doplňující údaje (2 řádky) | ❌ |
| Ulice | Ulice | ✅ |
| PSČ + Město | Město (PSČ + město) | ✅ |
| Telefon | Telefon | ✅ |
| E-mail | E-mail | ✅ |
| IČO + tlačítko Načti | IČ + tlačítko Načti (údaje z rejstříku) | ⚠️ tlačítko je, napojení na ARES 📝 |
| DIČ | DIČ | ✅ |
| — | (Stát) DIČ DPH | ❌ (při importu jde do poznámky) |
| — | Typ (zákazníka) | ❌ |
| Poznámka u zákazníka (na kartě zákazníka) | Poznámky ke partnerovi (tlačítko) | ⚠️ není přístupná z okna zakázky |

## Zakázka

| Naše aplikace | Starý systém | Stav |
|---|---|---|
| Číslo zakázky (přidělí se při uložení) | Označení | ✅ |
| Stav (Přijato / V opravě / Hotovo / Předáno) – v detailu zakázky | — (Ukončení = Tab) | ✅ |
| — | Druh (zakázky) | ❌ |
| — | Pracovník | ❌ |
| — | Přistavil (kdo vůz přivezl) | ❌ |
| — | Převzal (kdo vůz převzal) | ❌ |
| Přijetí (datum a čas) | Datum a čas přijetí | ✅ |
| — (zrušeno, není potřeba) | Plán. ukončení | 🚫 |
| — | Předběžná cena | ❌ |
| — | Záloha | ❌ |
| — | Tisknout doklad pro zálohu | ❌ |
| — | Záloha účtována s DPH | ❌ |
| — | Číslo objednávky | ❌ |
| — | Č. pojistné události | ❌ |
| — | Schvalovací číslo | ❌ |
| Stav km | Stav km (v panelu Vozidlo) | ✅ |
| — (zrušeno, není potřeba) | Stav paliva (v panelu Vozidlo) | 🚫 |
| Popis zakázky (požadavek / závada) – nepovinný | Popis zakázky | ✅ |
| Interní poznámka | Popis interní (tlačítko) | ✅ |
| — | Popis vykonaných prací (tlačítko) | ❌ |
| — | Doporučené práce (tlačítko) | ❌ |
| — | Náhradní vozidlo | ❌ |
| — | Možno odpojit akumulátor (zaškrtávátko) | ❌ |
| — | Odevzdat staré díly (zaškrtávátko) | ❌ |

## Příslušenství a doplňky (při příjmu vozu)

| Naše aplikace | Starý systém | Stav |
|---|---|---|
| — | Rádio, Lékárnička, Trojúhelník, Nářadí, Světlomety, Zdvihák, Rezerva, Potahy, Pumpička, Opěrky, Anténa, Lano (zaškrtávátka) | ❌ |
| — | Ostatní doplňky (4 volná pole) | ❌ |
| — | Uložení bezp. klíče kol | ❌ |

## Vozidlo

| Naše aplikace | Starý systém | Stav |
|---|---|---|
| SPZ + Vybrat + Nový | RZ (SPZ) + Vybrat | ✅ |
| Značka + Model | Typ vozidla (značka a model, např. Volkswagen Transporter) | ✅ |
| Rok výroby + Datum 1. registrace | Rok výroby (celé datum) | ✅ |
| VIN | VIN | ✅ |
| Typ vozidla (TP) | Typ/variant/verze | ✅ |
| Kód motoru | Kód typu motoru | ✅ |
| — | Chlazení | ❌ |
| Olej | Olej | ✅ |
| Palivo | Druh paliva | ✅ |
| Objem | Objem | ✅ |
| Výkon | Výkon | ✅ |
| Barva | Barva | ✅ |
| Termín STK | Termín STK (červeně po termínu) | ✅ |
| Termín EK | Termín EK | ✅ |
| Historie vozidla (karta vozidla – zakázky, práce, materiál) | Historie vozidla (tlačítko) | ⚠️ není přístupná z okna zakázky |
| — | Termíny (tlačítko – další termíny) | ❌ |
| — | Načti z DK (načtení z dokladu / databáze) | ❌ |
| Poznámka u vozidla (na kartě vozidla) | k vozidlu (tlačítko – poznámky k vozidlu) | ⚠️ není přístupná z okna zakázky |

## Co máme navíc

- Položky zakázky (práce a materiál z ceníku) přímo v detailu zakázky, vystavení faktury / vyúčtování.

## Změny 18. 11. 2026

- Tlačítko **Načti** u IČO (příjem zakázky i formulář zákazníka) – zatím ohlásí „připravuje se“, napojení na ARES je v ToDo.
- Vozidlo: k roku výroby přibylo **Datum 1. registrace** (formulář vozidla, příjem zakázky, karta vozidla).
- **Plánované ukončení** a **Stav paliva** zrušeny z formuláře, detailu, tisku i seznamu zakázek (sloupec Termín).
  Hodnoty ze starého systému zůstaly v databázi, jen se nezobrazují.
- Popis zakázky už není povinný.
- Stav zakázky s filtrem v seznamu.
