# UX audit – Autoservis (18. 11. 2026)

Procházeno v prohlížeči nad ostrou databází (`data/autoservis.db`), okno 1280 × 850.
Prošlé kroky: nová zakázka s novým zákazníkem a vozidlem → přidání materiálu a práce z ceníku → ruční položka →
úprava a odebrání položky → faktura → úhrada → storno → vyúčtování → storno → nový materiál v ceníku a jeho smazání →
nové vozidlo a jeho smazání → smazání zakázky, vozidla a zákazníka.

Seznam k odškrtávání: [OPRAVY.md](OPRAVY.md).

Závažnost: 🔴 chyba / riziko pro data či doklady · 🟠 nelogičnost, která zdržuje nebo mate · 🟡 drobnost v UI

## Přehled problémů

**Doklady a data**
1. 🔴 Fakturu jde vystavit bez údajů dodavatele (servisu) – na tisku je „— vyplňte v Nastavení —“
2. 🔴 Faktura a vyúčtování mají stejný variabilní symbol (FV20260002 i VY20260002 → VS 20260002)
3. 🔴 Po smazání zakázky se její číslo použije znovu, i když na něj odkazuje (stornovaný) doklad
4. 🔴 Smazání zákazníka, který má doklady, skončí chybou „Internal Server Error“ (HTTP 500)
5. 🟠 Tlačítko Stornovat je aktivní i na dokladu s úhradou – chyba přijde až po potvrzení
6. 🟠 Vyúčtování se ve výchozím stavu vystaví jako hotově zaplacené – storno pak znamená dva kroky
7. 🟠 Úhrady jde smazat bez jakékoli stopy (žádná historie)
8. 🟠 Cena zadaná „s DPH“ se v ceníku uloží jako 123.9669 a takhle se i zobrazí v úpravě
9. 🟠 Stav dokladu: „Neuhrazeno“ je zeleně, „Uhrazeno“ šedě; částečná úhrada se nijak neliší
10. 🟠 Sazba normohodiny (800 Kč) a cena „Mechanická práce“ v ceníku (450 Kč/hod) si odporují
11. 🟠 Na detailu zakázky nejsou vidět její doklady (ani ty stornované)
12. 🟠 Vozidlo ukazuje „Celkem 3 200,45 Kč“ i za zakázku, jejíž doklady byly stornované
13. 🟡 Vyúčtování (nedaňový doklad) má pole DUZP
14. 🟡 Storno faktury nevytváří opravný daňový doklad (zkontrolovat s účetní)

**Formuláře a ovládání**
15. 🟠 Zápisky v polích (placeholdery) vypadají jako vyplněné hodnoty
16. 🟠 Nová zakázka, úprava zakázky a nové vozidlo mají každý jiné rozvržení a jiný výběr zákazníka
17. 🟠 V úpravě zakázky nejde změnit vozidlo ani datum přijetí
18. 🟠 Enter se chová v každém okně jinak; klávesa Delete na řádku nic nedělá
19. 🟠 Chyby se ukážou až po odeslání, bez zvýraznění pole a kurzor neskočí na chybné pole
20. 🟠 Tlačítka Smazat zakázku / Smazat vozidlo bez vysvětlení zmizí
21. 🟠 Okno „Přidat z ceníku“: poskakuje, nevidí se, co už je přidané, a hláška o 100 položkách svítí pořád
22. 🟡 Formuláře ruční položky a úpravy položky mají jiné popisky a jiná povinná pole
23. 🟡 Tlačítko „Hotovo“ v okně ceníku se plete se stavem zakázky „Hotovo“
24. 🟡 Zelená hláška „Zakázka … byla založena“ zůstává na stránce i po dalších úpravách
25. 🟡 Částka v úhradě je předvyplněná s tečkou (3200.45), jinde se používá čárka
26. 🟡 Do ceny nejde napsat „150 Kč“ (nepovolí jednotku)
27. 🟡 „Nová zakázka“ a „+ Příjem vozidla“ jsou dvě tlačítka na totéž
28. 🟡 Ceník se ovládá jinak než ostatní seznamy (odkaz „upravit“ v každém řádku)

**Zobrazení**
29. 🟡 Adresa se jednou píše s čárkou, jindy bez ní; PSČ bez mezery
30. 🟡 Na dokladu se kód dílu lepí za název („Synpower olej motorový Valvoline 5w40“)
31. 🟡 Několik formátů čísel zakázek a dokladů vedle sebe (2026-0001 / ZAK2026/0193, FV20260002 / 26020059 / 260107VYUC)
32. 🟡 Nově uložená položka ceníku se nezvýrazní a po smazání se zruší filtr hledání
33. 🟡 V tabulkách se mění šířky sloupců podle obsahu (tabulka „skáče“)
34. 🟡 Hledání v seznamu se propíše i do horního globálního hledání
35. 🟡 Vozidlo bez značky má v seznamu jako odkaz jen „—“
36. 🟡 Ikona v poli „Databáze zákazníků“ překrývá první písmeno textu
37. 🟡 Hláška vpravo nahoře překrývá „verze 0.1.0“
38. 🟡 Pole formulářů nemají propojené popisky (čtečky obrazovky je nepřečtou)
39. 🟡 V Zakázkách chybí počet u záložky „Otevřené“, ve Fakturách chybí filtr „Stornované“

---

## Podrobnosti

### 1. 🔴 Faktura jde vystavit bez údajů dodavatele
- **Kde:** Zakázka → Vystavit fakturu.
- **Co se stalo:** Okno ukáže žluté varování „Nejsou vyplněné údaje servisu…“, ale tlačítko *Vystavit fakturu* normálně projde.
  Na tisku FV20260002 je u dodavatele „— vyplňte v Nastavení —“, chybí IČO a DIČ. Při platbě převodem chybí číslo účtu a QR platba.
- **Proč je to problém:** Takový doklad není platný daňový doklad a pozdější doplnění Nastavení ho už neopraví (doklad je kopie).
  V ostré databázi teď Nastavení vyplněné **není**.
- **Návrh:** Bez názvu, IČO a adresy servisu fakturu nevystavit (vyúčtování případně jen s varováním). U formy „převodem“ vyžadovat číslo účtu.

### 2. 🔴 Stejný variabilní symbol u faktury a vyúčtování
- **Kde:** `app/services/faktury.py` – `variabilni_symbol()` bere jen číslice z čísla dokladu.
- **Co se stalo:** FV20260002 i VY20260002 dostaly VS **20260002**.
- **Proč je to problém:** Platby z banky nepůjde jednoznačně spárovat.
- **Návrh:** Řady odlišit i číslicemi (např. faktury 1RRRRnnnn, vyúčtování 2RRRRnnnn) nebo hlídat, aby VS byl jedinečný napříč typy.

### 3. 🔴 Číslo smazané zakázky se použije znovu
- **Co se stalo:** Zakázka 2026-0005 měla dva stornované doklady. Po odebrání položek šla smazat. Formulář nové zakázky pak nabídl
  znovu označení **2026-0005**. Tisk stornované FV20260002 dál uvádí „Zakázka 2026-0005“.
- **Proč je to problém:** Dva různé zásahy pod stejným číslem; dohledávání podle čísla zakázky přestane fungovat.
- **Návrh:** Zakázku s doklady (i stornovanými) nemazat – jen ji zrušit / označit jako stornovanou. Čísla nikdy znovu nepoužívat.

### 4. 🔴 Smazání zákazníka s doklady → chyba 500
- **Kde:** Zákazník → Smazat zákazníka (zákazník bez vozidel a zakázek, ale se 2 doklady).
- **Co se stalo:** Po potvrzení se ukáže černá stránka „Internal Server Error“. V logu `FOREIGN KEY constraint failed` u `DELETE FROM zakaznik`.
- **Příčina:** `zakaznici.smaz()` kontroluje jen vozidla a zakázky, ne doklady.
- **Návrh:** Kontrolovat i doklady a ukázat srozumitelnou hlášku; tlačítko v tom případě raději vůbec nenabízet.

### 5. 🟠 Storno dokladu s úhradou
- **Co se stalo:** *Stornovat doklad* je aktivní, potvrzovací okno o úhradách mlčí. Až po potvrzení přijde červená hláška
  „Doklad má úhrady – nejdřív je odeberte.“ Stránka pak zůstane na adrese `/faktury/50/storno` (HTTP 422) – F5 by požadavek odeslal znovu.
- **Návrh:** S úhradou tlačítko zakázat s vysvětlením, nebo storno rovnou nabídnout i s vrácením úhrady (zápornou úhradou).
  Po chybě přesměrovat zpět na detail.

### 6. 🟠 Vyúčtování je ve výchozím stavu „hotově, zaplaceno“
- Po přepnutí na Vyúčtování se nastaví *Hotově* a zaškrtne *zákazník platí hned*. Doklad se rovnou vystaví jako uhrazený.
  Při chybě je pak potřeba nejdřív smazat úhradu a teprve potom stornovat. Výchozí volba je pro hotovost rozumná, jen se to při stornu
  nevysvětlí (viz bod 5).

### 7. 🟠 Úhrady se mažou beze stopy
- Křížek u úhrady ji po potvrzení úplně smaže. U skutečně přijatých peněz (pokladna) chybí historie, kdo a kdy úhradu zrušil.
- **Návrh:** Úhradu místo smazání stornovat (zůstane přeškrtnutá) nebo aspoň zapsat do historie.

### 8. 🟠 Cena „s DPH“ v ceníku
- Nový materiál, cena 150 se zaškrtnutým *zadaná cena je s DPH* → uloží se 123,97 bez DPH (v seznamu 150,00 s DPH – v pořádku).
- V úpravě položky je ale pole *Cena za jednotku* = **123.9669** (4 desetinná místa a desetinná tečka) a zaškrtávátko „s DPH“ je prázdné.
- **Návrh:** Při úpravě zobrazovat cenu zaokrouhleně s čárkou; pokud byla zadána s DPH, ukázat ji znovu s DPH.

### 9. 🟠 Barvy stavu dokladu
- Na detailu dokladu je štítek „Neuhrazeno“ zelený a „Uhrazeno“ šedý. Zelená obvykle znamená „v pořádku / zaplaceno“.
- Po zapsání částečné úhrady (1 000 z 3 200,45 Kč) zůstal štítek „Neuhrazeno“ – stav „Částečně uhrazeno“ chybí.
- Řádek „Zbývá“ je červeně, i když doklad ještě není po splatnosti.

### 10. 🟠 Normohodina vs. ceník
- Nastavení: sazba normohodiny 800 Kč. Ceník: „Mechanická práce“ (MECH) 450 Kč/hod. Ruční práce bez ceny dostane 800 Kč.
  Stejná hodina tak stojí různě podle toho, jak se zadá. Buď sjednotit data, nebo u práce v ceníku ukazovat, že se odchyluje od normohodiny.

### 11. 🟠 Zakázka nezobrazuje své doklady
- Po stornu faktury a vyúčtování na detailu zakázky není žádná zmínka, že k ní existovaly doklady FV20260002 a VY20260002.
  Chybí sekce „Doklady“ (vozidlo i zákazník ji mají). Stav zakázky se po stornu nastavil na „Hotovo“ (před fakturací byl „Přijato“).

### 12. 🟠 Součet na vozidle
- Detail vozidla ukazoval „Celkem 3 200,45 Kč“ za zakázku, jejíž oba doklady byly stornované. Není jasné, jestli jde o vyfakturováno,
  nebo o hodnotu otevřených zakázek – doplnit popisek nebo počítat jen platné doklady.

### 13. 🟡 DUZP na vyúčtování
- Vyúčtování není daňový doklad, ale formulář i doklad pole DUZP mají. Zvážit skrytí.

### 14. 🟡 Storno vs. opravný daňový doklad
- Storno vystavené faktury jen označí doklad jako stornovaný. U plátce DPH se odeslaná faktura opravuje opravným daňovým dokladem.
  Neověřoval jsem, jak to má být u vás – doporučuji probrat s účetní.

### 15. 🟠 Placeholdery vypadají jako hodnoty
- Barva placeholderu (#646B79) je blízko barvě textu (#23262C). Prázdná pole tak vypadají vyplněně:
  - nová zakázka: Značka „Škoda“, Model „Octavia 1.9 TDI“, Druh paliva „benzín / nafta“,
  - ruční položka: Cena „práce v hod: 800“, Jednotka „hod / ks / l“,
  - **Nastavení:** DIČ „CZ12345678“, Číslo účtu „123456789/0800“, IBAN „CZ65 0800 …“ – vypadá to, že účet je nastavený, a přitom není.
- **Návrh:** Placeholdery zesvětlit / dát kurzívou, nebo ukázkové hodnoty přesunout do nápovědy pod pole („např. …“).

### 16. 🟠 Tři různé formuláře pro totéž
- *Nová zakázka*: tři panely Zákazník | Zakázka | Vozidlo, zákazník přes tlačítka **Vybrat / Nový**.
- *Upravit zakázku*: dva panely Zakázka | Zákazník, zákazník přes **Databáze zákazníků**, vyhledávací pole a přepínače
  „TEST Zákazník UX / Nový zákazník / Bez zákazníka“.
- *Nové vozidlo*: jiné pořadí polí (Rok výroby vedle SPZ) a opět jiný výběr zákazníka.
- Uživatel se musí učit tři různé ovládání. Doporučuji jeden společný blok „Zákazník“ a jedno pořadí polí vozidla.

### 17. 🟠 Úprava zakázky neumí změnit vozidlo ani datum přijetí
- Když se při příjmu splete SPZ nebo datum, oprava jde jen smazáním a novým založením zakázky (a to jen bez položek).

### 18. 🟠 Klávesnice
- Nová zakázka: Enter přejde na další pole, v *Popisu zakázky* (textarea) ale udělá nový řádek a dál se jde jen Tabem.
- Okno ceníku: Enter v množství položku **přidá**.
- Úprava / ruční položka: Enter jen přeskakuje pole, uložit jde jen myší.
- Vybraný řádek položky nejde odebrat klávesou Delete.
- **Návrh:** Sjednotit (např. Ctrl+Enter = uložit všude) a přidat Delete = Odebrat s potvrzením.

### 19. 🟠 Validace až po odeslání
- Rok výroby „20O5“ → hláška „Rok výroby musí být celé číslo.“ až po kliknutí na Uložit; pole není zvýrazněné a kurzor skočí na SPZ.
- Totéž u ceny „150 Kč“ v ceníku (kurzor skočí na Název).
- **Návrh:** Zvýraznit chybné pole a dát na něj kurzor; jednoduché kontroly dělat už při psaní.

### 20. 🟠 Mizející tlačítka Smazat
- *Smazat zakázku* zmizí, jakmile má zakázka položku; *Smazat vozidlo* zmizí, když má vozidlo zakázku. Uživatel neví proč.
- **Návrh:** Tlačítko nechat zašedlé s vysvětlivkou („nejdřív odeberte položky“).

### 21. 🟠 Okno „Přidat z ceníku“
- Okno je svisle na středu a při hledání mění výšku → poskakuje. Zelená hláška „Přidáno: …“ ho navíc posune dolů,
  takže hrozí kliknutí na vedlejší řádek.
- Co už bylo přidáno, je vidět jen jako počet („2 položek“). Chybí seznam přidaných a možnost vrátit.
- Pod tabulkou svítí „Zobrazeno nejvýš 100 položek – upřesněte hledání“ i když je výsledek 1 nebo 18 řádků.
- V ceníku je mnoho položek „Olejový filtr“ se stejným názvem; rozliší je jen kód (vhodné doplnit značku / vozidlo).
- Ceník neukazuje cenu s DPH ani skladovou zásobu.

### 22. 🟡 Ruční položka vs. Upravit položku
- „Cena/j. bez DPH“ (nepovinná) × „Cena za jednotku bez DPH *“ (povinná); „cena je s DPH“ × „zadaná cena je s DPH“;
  tlačítko „Přidat položku“ × „Uložit“. Jedna a ta samá položka by měla mít stejný formulář.

### 23. 🟡 Dvě různá „Hotovo“
- Okno ceníku se zavírá tlačítkem **Hotovo** a na stejné stránce je stav zakázky **Hotovo**. Zavírací tlačítko přejmenovat na „Zavřít“.

### 24. 🟡 Zastaralá zelená hláška
- „Zakázka 2026-0005 byla založena.“ zůstává nahoře i po přidání a úpravách položek (adresa končí `?nova=1`) a k tomu se ukazují
  vlastní hlášky vpravo nahoře. Totéž u faktury („byla vystavena“) po zapsání úhrady.

### 25. 🟡 Desetinná tečka v úhradě
- *Zapsat úhradu* předvyplní „3200.45“, všude jinde v aplikaci je „3 200,45“.

### 26. 🟡 Cena s „Kč“
- „150 Kč“ → „Cena: „150 Kč“ není číslo.“ Stačilo by „Kč“ a mezery tiše odstranit.

### 27. 🟡 Dvě tlačítka na novou zakázku
- V Zakázkách je vlevo *Nová zakázka* a nahoře *+ Příjem vozidla* – dělají totéž. Sjednotit název.

### 28. 🟡 Ceník se ovládá jinak
- Ostatní seznamy: klik = vybrat, dvojklik / Otevřít = otevřít. Ceník má navíc název jako odkaz a v každém řádku odkaz „upravit“.

### 29. 🟡 Formát adresy
- Zakázka a faktura: „Testovací 1 11000 Praha“, detail zákazníka: „Testovací 1, 11000 Praha“. PSČ by mělo být „110 00“.

### 30. 🟡 Kód dílu za názvem
- Na dokladu i v tisku: „Synpower olej motorový Valvoline 5w40“, „Mechanická práce MECH“. Kód vypadá jako součást názvu –
  dát ho do samostatného sloupce nebo do závorky.

### 31. 🟡 Formáty čísel
- Zakázky: „2026-0001“ vedle importovaných „ZAK2026/0193“. Doklady: „FV20260002“, „VY20260001“ vedle „26020059“ a „260107VYUC“.
  Pochopitelné kvůli importu ze starého systému, ale pro uživatele matoucí. Zvážit, jak bude vypadat ostrá řada (viz i bod 2).

### 32. 🟡 Ceník po uložení / smazání
- Nová položka se po uložení v seznamu nezvýrazní ani na ni seznam neodroluje (je řazeno podle abecedy, takže je kdesi dole).
- Po smazání položky se zruší rozepsané hledání a ukáže se celý ceník.

### 33. 🟡 Skákající sloupce
- Šířka sloupců v tabulkách (položky zakázky, ceník, okno ceníku) se mění podle obsahu – po odebrání položky nebo při hledání tabulka „poskočí“.

### 34. 🟡 Globální hledání přebírá filtr seznamu
- Na `/zakaznici?q=TEST` se „TEST“ objeví i v horním poli *Hledat SPZ, VIN, jméno…*. Není jasné, které pole filtruje.

### 35. 🟡 Vozidlo bez značky
- V seznamu vozidel je u vozidel bez značky/modelu odkaz „—“. Lépe ukázat „(neuvedeno)“ a odkaz dát na SPZ.

### 36. 🟡 Ikona v poli
- V poli „Databáze zákazníků – klikněte, nebo hledejte…“ (nové vozidlo, úprava zakázky) ikona zakrývá první písmeno.

### 37. 🟡 Hláška překrývá verzi
- Zelená hláška vpravo nahoře („Položka přidána.“ apod.) leží přes text „verze 0.1.0“ v liště menu.

### 38. 🟡 Přístupnost
- Pole formulářů nemají popisky propojené s polem (`<label for>`), v přístupnosti jsou to jen bezejmenné „textbox“.
  Klik na popisek tak ani nepřesune kurzor do pole.

### 39. 🟡 Chybějící počty a filtry
- Zakázky: záložky mají počet (Přijato 5, Předáno 47…), jen „Otevřené“ ne.
- Faktury: filtry Neuhrazené / Po splatnosti / Uhrazené / Všechny – chybí „Stornované“.

---

## Co funguje dobře
- Rychlé zadání zakázky jen z klávesnice, SPZ se po Enteru dohledá („Nové vozidlo – uloží se se zakázkou“).
- Potvrzovací okna aplikace s bezpečnou výchozí volbou „Ne“ a srozumitelným textem („Odebrat úhradu 1 000,00 Kč ze 18.11.2026?“).
- Okamžité přepočty součtů, DPH po sazbách a zaokrouhlení při hotovosti.
- Stornovaný doklad je v seznamu přeškrtnutý a v tisku má razítko STORNO.
- Hledání SPZ funguje i s mezerou a malými písmeny („9t9 9999“).

## Co zůstalo po testu v databázi
- Doklady **FV20260002** a **VY20260002** (stornované, zákazník „TEST Zákazník UX“) – doklady aplikace smazat nedovolí.
- Zákazník **TEST Zákazník UX** – kvůli dokladům nejde smazat (bod 4).
- Zakázka 2026-0005, vozidla 9T99999 a 9T99998 a materiál TEST-001 jsou smazané.

Neprocházel jsem: mobilní zobrazení, sklad (v menu je zatím neaktivní), tisk zakázkového listu a import ze starého systému.
