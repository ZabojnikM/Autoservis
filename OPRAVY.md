# Opravy – seznam k opravě

Záznam chyb a nelogičností k opravě. Zdroj: UX audit z 18. 11. 2026 – podrobný popis, postup a návrhy řešení
ke každému bodu jsou v [UX_PROBLEMY.md](UX_PROBLEMY.md) (číslo v závorce = číslo bodu tam).

Hotové body odškrtáváme `[x]` a doplníme datum. Nové chyby připisujeme na konec příslušné priority.

> Opraveno 18. 11. 2026 (109 testů prochází, ověřeno v prohlížeči na kopii ostré databáze).
> **Po aktualizaci restartujte server** (zavřít okno `spustit.bat` a spustit znovu) – při startu se do tabulky
> úhrad doplní sloupec `zruseno`, data zůstanou.

## Priorita 1 – chyby, riziko pro doklady a data

- [x] **Nevystavit fakturu bez údajů servisu** (1) – *18. 11. 2026*: faktura bez názvu/IČO/adresy servisu nejde vystavit
  (zašedlé tlačítko a červená hláška s odkazem do Nastavení); převodem jen s číslem účtu, jinak se nabídne hotově.
  Vyúčtování jde dál i bez údajů (jen upozornění).
- [x] **Jedinečný variabilní symbol** (2) – *18. 11. 2026*: vyúčtování má VS s 9 na začátku (VY20260003 → 920260003),
  při shodě s jiným dokladem se přidá další číslice. Vysvětleno v Nastavení u číselných řad.
  ⚠ Starší doklady se nemění – v ostré DB mají stejný VS **FV20260001 a VY20260001** (oba uhrazené, nevadí).
- [x] **Nepoužívat znovu čísla zakázek** (3) – *18. 11. 2026*: zakázku s doklady (i stornovanými) nejde smazat;
  nové číslo zakázky počítá i s čísly uvedenými na dokladech (po smazané 2026-0005 přijde 2026-0006).
- [x] **Chyba 500 při mazání zákazníka s doklady** (4) – *18. 11. 2026*: kontrola dokladů, tlačítko zašedlé s důvodem.

## Priorita 2 – nelogičnosti, které zdržují nebo matou

- [x] Storno dokladu s úhradou (5) – *18. 11. 2026*: storno jde i s úhradou – potvrzení napíše, kolik je uhrazeno,
  a storno úhrady zruší (zůstanou přeškrtnuté). Chyby storna/mazání vrací na detail s červenou hláškou (žádná stránka na adrese POST).
- [x] Vyúčtování „hotově, platí hned“ (6) – *18. 11. 2026*: díky bodu 5 je storno jeden krok.
- [x] Úhrady nemazat beze stopy (7) – *18. 11. 2026*: úhrada se „zruší“ – zůstane v historii přeškrtnutá s datem a časem zrušení.
- [x] Cena zadaná s DPH (8) – *18. 11. 2026*: v úpravě ceníku i položky se ukáže zase s DPH a zaškrtnutou volbou (150, ne 123.9669),
  ostatní ceny s desetinnou čárkou.
- [x] Barvy stavu dokladu (9) – *18. 11. 2026*: Uhrazeno zeleně, Neuhrazeno oranžově, Po splatnosti červeně,
  nový stav **Částečně uhrazeno**; „Zbývá“ červeně jen po splatnosti.
- [x] Normohodina vs. ceník (10) – *18. 11. 2026*: data jsem neměnil (rozhodnutí na vás); hodinová práce s jinou cenou
  než normohodina má v ceníku značku **≠ NH** s vysvětlením. „Mechanická práce“ 450 Kč/hod vs. normohodina 800 Kč – sjednoťte.
- [x] Sekce „Doklady“ na detailu zakázky (11) – *18. 11. 2026*: i stornované; po stornu hláška říká, že zakázka je ve stavu Hotovo.
- [x] Součet na detailu vozidla (12) – *18. 11. 2026*: „Vyfakturováno“ = jen platné doklady, zvlášť „Rozpracováno“ (otevřené zakázky).
- [x] Placeholdery (15) – *18. 11. 2026*: světle šedé kurzívou a s „např.“; v Nastavení už nevypadají jako vyplněný účet / DIČ.
- [x] Sjednotit formuláře (16) – *18. 11. 2026*: úprava zakázky je stejné okno jako nová zakázka (Zákazník | Zakázka | Vozidlo);
  formulář vozidla má stejné pořadí polí a stejný panel Zákazník (Firma + Vybrat / Nový).
- [x] V úpravě zakázky změnit vozidlo a datum přijetí (17) – *18. 11. 2026* (jde jen u zakázky bez platného dokladu).
- [x] Klávesnice (18) – *18. 11. 2026*: **Ctrl+Enter = uložit** v každém formuláři/okně, **Delete = odebrat vybraný řádek**
  (s potvrzením), nápověda kláves u tlačítek; v popisu zakázky nápověda „Enter = nový řádek, Tab = další pole“.
- [x] Validace (19) – *18. 11. 2026*: chyba ze serveru přesune kurzor na chybné pole a zvýrazní ho; rok výroby, množství
  a částka se kontrolují už v prohlížeči.
- [x] Mizející tlačítka Smazat (20) – *18. 11. 2026*: zakázka, vozidlo i zákazník mají zašedlé tlačítko s důvodem.
- [x] Okno „Přidat z ceníku“ (21) – *18. 11. 2026*: pevná výška (neposkakuje), hláška v pevném řádku, vpravo seznam
  „Na zakázce“ s okamžitým odebráním (✕), sloupec Cena s DPH, hláška o 100 položkách jen když jich je víc.
  Skladová zásoba zatím není – sklad je odložený (fáze 2b).

## Priorita 3 – drobnosti v UI

- [x] Ruční položka a úprava položky – stejný formulář (22) – *18. 11. 2026*
- [x] „Hotovo“ v okně ceníku → **Zavřít** (23) – *18. 11. 2026*
- [x] Zastaralá zelená hláška po založení (24) – *18. 11. 2026*: místo ní krátká hláška vpravo dole, bez `?nova=1`.
- [x] Úhrada předvyplněná s čárkou (25) – *18. 11. 2026*
- [x] Cena „150 Kč“ / „21 %“ (26) – *18. 11. 2026*: jednotku za číslem program tiše vynechá.
- [x] „Nová zakázka“ vs. „+ Příjem vozidla“ (27) – *18. 11. 2026*: horní tlačítko se jmenuje **+ Nová zakázka**.
- [x] Ceník jako ostatní seznamy (28) – *18. 11. 2026*: bez odkazů v řádku, dvojklik = upravit.
- [x] Jednotná adresa „Ulice 1, 110 00 Praha“ (29) – *18. 11. 2026* (i v tisku dokladů a zakázkového listu).
- [x] Kód dílu na dokladu (30) – *18. 11. 2026*: „Synpower olej motorový (kód Valvoline 5w40)“.
- [ ] Formáty čísel zakázek a dokladů (31) – **k rozhodnutí**: importované doklady si nechávají čísla ze starého systému.
  Do Nastavení doplněno vysvětlení; chcete-li sjednotit, rozhodněte tvar ostrých řad.
- [x] Ceník po uložení / smazání (32) – *18. 11. 2026*: nová položka se ukáže vyfiltrovaná a zvýrazněná;
  smazání vrátí na seznam se zachovaným hledáním.
- [x] Pevné šířky sloupců (33) – *18. 11. 2026*: položky zakázky, ceník a okno ceníku.
- [x] Filtr seznamu se nepropisuje do horního hledání (34) – *18. 11. 2026*
- [x] Vozidlo bez značky – „(neuvedeno)“ (35) – *18. 11. 2026*
- [x] Ikona v poli „Databáze zákazníků“ (36) – *18. 11. 2026*: pole ve formulářích už nejsou (panel Zákazník), CSS opraveno i obecně.
- [x] Hláška překrývá „verze 0.1.0“ (37) – *18. 11. 2026*: hlášky jsou vpravo dole; chybové červeně a déle.
- [x] Popisky polí (38) – *18. 11. 2026*: **ověřeno, že problém nebyl** – popisky jsou s poli propojené (obalující `<label>`);
  v auditu šlo o chybné čtení nástroje.
- [x] Počet u záložky Otevřené a Všechny, filtr Stornované ve Fakturách (39) – *18. 11. 2026*
- [x] Větší písmo v horní liště, menu a levém panelu tlačítek – *18. 11. 2026*: název, hledání a „+ Nová zakázka“
  ~15 px, položky menu ~15 px, tlačítka vlevo ~14 px s vyšším řádkem (panel o 20 px širší).
- [x] Horní lišta – *18. 11. 2026*: zrušeno duplicitní tlačítko „+ Nová zakázka“ vpravo nahoře (zůstává v levém panelu
  Zakázek); lišta vyšší, „Autoservis“ větší, hledací pole větší, se světlým rámečkem a žlutým zvýrazněním při psaní.

## K rozhodnutí / ověření

- [x] Vyúčtování (nedaňový doklad) bez DUZP (13) – *18. 11. 2026*: DUZP jen u faktury (formulář, detail i tisk).
- [ ] Storno faktury vs. opravný daňový doklad (14) – **probrat s účetní**; program zatím jen označí doklad jako stornovaný.
- [ ] Neprověřeno: mobilní zobrazení, tisk zakázkového listu, import ze starého systému

## Poznámky

- V ostré DB zůstaly z testu stornované doklady **FV20260002**, **VY20260002** a zákazník **TEST Zákazník UX** (na přání ponecháno).
- V ostré DB není vyplněné **Nastavení → Údaje servisu** a číslo účtu – **bez nich teď fakturu nejde vystavit**, doplňte je.
