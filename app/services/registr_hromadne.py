"""Hromadné doplnění údajů vozidel z Registru silničních vozidel (#126).

Běží na pozadí ve vlákně aplikace: po jednom dotazu na každý VIN, tempo do 22 dotazů za minutu
(limit API je 27 za minutu na klíč). Doplňuje kód motoru, stav vozidla v registru a platnost STK:
- stav PROVOZOVANÉ → STK z registru (když ji registr vrátí),
- jiný neprázdný stav → STK se vymaže (vozidlo mimo provoz, žádné upozornění na propadlou STK),
- chyba dotazu nebo chybějící stav → dosavadní STK zůstává.
Vozidla načtená z registru už dnes se přeskočí, takže po restartu aplikace jde běh spustit znovu a naváže.
"""
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlmodel import Session, col, select

from app.models import Vozidlo
from app.services import registr_vozidel

TEMPO_ZA_MINUTU = 22
PAUZA_PRI_LIMITU = 65  # s – po hlášce o překročení limitu
PROVOZOVANE = "PROVOZOVANÉ"


@dataclass
class Beh:
    bezi: bool = False
    celkem: int = 0
    hotovo: int = 0
    aktualizovano: int = 0
    nenalezeno: int = 0
    preskoceno: int = 0          # bez VIN nebo načtená už dnes
    chyby: list = field(default_factory=list)   # [(SPZ, text)]
    nenalezene: list = field(default_factory=list)  # SPZ
    zacatek: datetime | None = None
    konec: datetime | None = None
    zastaveno: bool = False


_beh = Beh()
_zamek = threading.Lock()
_stop = threading.Event()


def stav() -> Beh:
    return _beh


def je_mimo_provoz(stav_registru: str | None) -> bool:
    return bool(stav_registru) and stav_registru.strip().upper() != PROVOZOVANE


def aplikuj(vozidlo: Vozidlo, data: dict, ted: datetime | None = None) -> None:
    """Zapíše do vozidla kód motoru, stav v registru a STK podle pravidel výše."""
    kod = registr_vozidel._text(data.get("MotorTyp"))
    if kod:
        vozidlo.kod_motoru = kod
    stav_registru = registr_vozidel._text(data.get("StatusNazev"))
    if stav_registru:
        vozidlo.stav_registru = stav_registru.upper()
        if je_mimo_provoz(stav_registru):
            vozidlo.termin_stk = None
        else:
            stk = registr_vozidel._datum(data.get("PravidelnaTechnickaProhlidkaDo"))
            if stk:
                vozidlo.termin_stk = date.fromisoformat(stk)
    vozidlo.registr_nacteno = ted or datetime.now()


def _k_nacteni(session: Session, dnes: date) -> tuple[list[int], int]:
    """Id vozidel s VIN, která dnes ještě nebyla načtená; počet přeskočených (bez VIN / už dnes)."""
    vsechna = session.exec(select(Vozidlo.id, Vozidlo.vin, Vozidlo.registr_nacteno).order_by(col(Vozidlo.id))).all()
    k_nacteni = [i for i, vin, kdy in vsechna if vin and vin.strip() and not (kdy and kdy.date() == dnes)]
    return k_nacteni, len(vsechna) - len(k_nacteni)


def spust(engine, api_klic: str, limit: int | None = None, nacti=registr_vozidel.nacti, cekej=time.sleep,
          na_pozadi: bool = True) -> bool:
    """Spustí běh (vrací False, když už jeden běží). `limit` = nejvýš tolik vozidel (zkušební běh)."""
    global _beh
    with _zamek:
        if _beh.bezi:
            return False
        _stop.clear()
        with Session(engine) as session:
            ids, preskoceno = _k_nacteni(session, date.today())
        if limit:
            ids = ids[:limit]
        _beh = Beh(bezi=True, celkem=len(ids), preskoceno=preskoceno, zacatek=datetime.now())
    vlakno = threading.Thread(target=_pracuj, args=(engine, api_klic, ids, nacti, cekej), daemon=True,
                              name="registr-hromadne")
    if na_pozadi:
        vlakno.start()
    else:
        vlakno.run()
    return True


def zastav() -> None:
    _stop.set()


def _pracuj(engine, api_klic, ids, nacti, cekej) -> None:
    interval = 60 / TEMPO_ZA_MINUTU
    try:
        for vozidlo_id in ids:
            if _stop.is_set():
                _beh.zastaveno = True
                break
            with Session(engine) as session:
                vozidlo = session.get(Vozidlo, vozidlo_id)
                if not vozidlo or not vozidlo.vin:
                    _beh.preskoceno += 1
                    _beh.hotovo += 1
                    continue
                for pokus in (1, 2):
                    try:
                        data = nacti(api_klic, vin=vozidlo.vin)
                    except registr_vozidel.ChybaRegistru as e:
                        text = str(e)
                        if "limit" in text and pokus == 1:
                            cekej(PAUZA_PRI_LIMITU)
                            continue
                        if "nenalezeno" in text:
                            _beh.nenalezeno += 1
                            _beh.nenalezene.append(vozidlo.spz)
                        else:
                            _beh.chyby.append((vozidlo.spz, text))
                            if "API klíč" in text:  # neplatný klíč – dál nemá smysl pokračovat
                                _stop.set()
                        break
                    except Exception as e:  # noqa: BLE001 – jedna chyba nesmí zastavit celý běh
                        _beh.chyby.append((vozidlo.spz, f"neočekávaná chyba: {e}"))
                        break
                    else:
                        aplikuj(vozidlo, data)
                        session.add(vozidlo)
                        session.commit()
                        _beh.aktualizovano += 1
                        break
            _beh.hotovo += 1
            if _beh.hotovo < len(ids) and not _stop.is_set():
                cekej(interval)
    finally:
        _beh.bezi = False
        _beh.konec = datetime.now()
