# Testovací server Autoservisu (Linux) – pokyny pro agenta

Tato složka je **testovací nasazení** aplikace Autoservis na Linuxu. Kód sem nahrává vývojový
počítač (Windows) přes sdílený disk skriptem `nastroje/nasadit-na-server.ps1`, který zrcadlí
poslední commit z gitu. Zdroj pravdy je GitHub repozitář `ZabojnikM/Autoservis`, ne tato složka.

## Co tu nedělat
- **Neupravuj kód** (`app/`, `UI/`, `tests/`, `*.md`…). Při dalším nasazení se všechny změny
  přepíšou nebo smažou. Chyby a nápady zapisuj jako **GitHub Issue** do `ZabojnikM/Autoservis`
  (popis, kroky k reprodukci, verze z `VERZE.txt`).
- Necommituj, tady není `.git`.
- Neukládej sem vlastní soubory mimo `data/`, `.venv/`, `.env`. Ostatní nasazení smaže.

## Co nasazení nikdy nepřepíše (patří serveru)
- `data/` – databáze `autoservis.db` (všechna data i nastavení) a zálohy
- `.venv/` – virtuální prostředí Pythonu (vytváří se na serveru, z Windows se nekopíruje)
- `.env` – lokální nastavení (např. `AUTOSERVIS_DB` = cesta k jiné databázi)

S databází zacházej opatrně. Před každým zásahem do ní (migrace, hromadné úpravy, import)
udělej kopii do `data/backups/`. Testovací záznamy označuj (např. „TEST“) a po testu
maž jen ty své.

## Po nasazení nové verze
1. Podívej se do `VERZE.txt` (commit, popis, čas nasazení a jestli se změnily závislosti).
2. Pokud je v `VERZE.txt` u závislostí `ZMENENY` (nebo `.venv` ještě neexistuje):
   `.venv/bin/python -m pip install -r requirements.txt`
3. **Restartuj aplikaci:** `sudo systemctl restart autoservis`
4. Ověř, že běží: `curl -s http://localhost:8000/api/zdravi` (vrátí `"stav":"ok"` a verzi).
   Při problému: `journalctl -u autoservis -n 50`

## První zprovoznění
```
sudo apt install python3-venv          # pokud chybí
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest             # volitelně: testy
```
Služba systemd: šablona je v `nastroje/autoservis.service`. Doplň v ní uživatele a cestu
k této složce, zkopíruj do `/etc/systemd/system/autoservis.service` a spusť:
```
sudo systemctl daemon-reload
sudo systemctl enable --now autoservis
```
Služba poslouchá na `0.0.0.0:8000` (dostupné z ostatních počítačů v síti) a po pádu nebo
ukončení se sama znovu spustí (`Restart=always`). Bez `--reload` – po nasazení se restartuje ručně (krok 3).

`spustit.bat` je jen pro vývoj na Windows, na serveru se nepoužívá.

## Hlášení zpět
Výsledky testování (co funguje / nefunguje) zapisuj do GitHub Issues, ne do souborů v této složce.
