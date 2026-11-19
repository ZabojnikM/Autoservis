# Testovací server Autoservisu – pokyny pro agenta

Tato složka je **testovací nasazení** aplikace Autoservis. Kód sem nahrává vývojový počítač
skriptem `nastroje/nasadit-na-server.ps1` (zrcadlí poslední commit z gitu). Zdroj pravdy je
GitHub repozitář `ZabojnikM/Autoservis`, ne tato složka.

## Co tu nedělat
- **Neupravuj kód** (`app/`, `UI/`, `tests/`, `*.md`…). Při dalším nasazení se všechny změny
  přepíšou nebo smažou. Chyby a nápady zapisuj jako **GitHub Issue** do `ZabojnikM/Autoservis`
  (popis, kroky k reprodukci, verze z `VERZE.txt`).
- Necommituj, tady není `.git`.
- Neukládej sem vlastní soubory mimo `data/`, `.venv/`, `.env`. Ostatní nasazení smaže.

## Co nasazení nikdy nepřepíše (patří serveru)
- `data/` – databáze `autoservis.db` a zálohy
- `.venv/` – virtuální prostředí Pythonu
- `.env` – lokální nastavení (např. `AUTOSERVIS_DB` = cesta k jiné databázi)

S databází zacházej opatrně. Před každým zásahem do ní (migrace, hromadné úpravy, import)
udělej kopii do `data/backups/`. Testovací záznamy označuj (např. „TEST“) a po testu
maž jen ty své.

## Po nasazení nové verze
1. Podívej se do `VERZE.txt` (commit, datum a popis nasazené verze).
2. Pokud se změnil `requirements.txt`:
   `.venv\Scripts\python -m pip install -r requirements.txt`
3. **Restartuj aplikaci.** Automatický reload (`--reload`) na Windows zamrzá, server proto
   pouštěj bez něj.

## První zprovoznění / spuštění
```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- `--host 0.0.0.0`, aby šla aplikace otevřít i z ostatních počítačů v síti
  (`spustit.bat` je pro vývoj: poslouchá jen na localhostu a používá `--reload`).
- Testy: `.venv\Scripts\python -m pytest`

## Hlášení zpět
Výsledky testování (co funguje / nefunguje) zapisuj do GitHub Issues, ne do souborů v této složce.
