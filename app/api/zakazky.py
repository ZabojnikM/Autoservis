"""API zakázek (#146) – hledání, detail, řádky napříč zakázkami a jejich hromadná úprava.

Úprava řádků materiálu (kód, název, napojení na kartu ceníku) jde i ve staré zakázce – ceny a množství
se tam nemění. Množství a cenu jde změnit jen v otevřené zakázce. Vystavené doklady jsou samostatné kopie
a nemění se nikdy.
"""
from __future__ import annotations

from datetime import datetime, time

from sqlmodel import Session, col, select

from app.api.spolecne import denik, hodnota, otisk, over_otisk, zaloha
from app.models import ApiKlic, Katalog, PolozkaCeniku, PolozkaZakazky, StavZakazky, TypPolozky, Zakazka
from app.services import (ChybaValidace, NenalezenoError, cisty_text, cti_datum, desetinne_nebo_none, polozky,
                          zakazky as zakazky_sluzba)

NAHLED_MAX = 200


def _zakazka(z: Zakazka) -> dict:
    return {"id": z.id, "cislo": z.cislo, "stav": z.stav, "nazev_stavu": z.nazev_stavu, "otevrena": z.je_otevrena,
            "prijato": hodnota(z.datum_prijeti), "pozadavek": z.pozadavek, "tachometr": z.tachometr,
            "vozidlo_id": z.vozidlo_id, "spz": z.vozidlo.spz if z.vozidlo else None,
            "vozidlo": z.vozidlo.popis if z.vozidlo else None,
            "zakaznik_id": z.zakaznik_id, "zakaznik": z.zakaznik.nazev if z.zakaznik else None}


def _radek(r: PolozkaZakazky, z: Zakazka | None = None) -> dict:
    d = {"id": r.id, "zakazka_id": r.zakazka_id, "typ": r.typ, "kod": r.kod, "nazev": r.nazev, "jednotka": r.jednotka,
         "mnozstvi": hodnota(r.mnozstvi), "cena_bez_dph": hodnota(r.cena), "dph": hodnota(r.sazba_dph),
         "karta_ceniku_id": r.polozka_ceniku_id, "sklad_id": r.katalog_id}
    if z is not None:
        d |= {"zakazka": z.cislo, "prijato": hodnota(z.datum_prijeti), "zakazka_otevrena": z.je_otevrena}
    return d


def _datum(text, nazev):
    if not cisty_text(text):
        return None
    try:
        return cti_datum(text)
    except ValueError:
        raise ChybaValidace(f"{nazev}: „{text}“ není datum (např. 1.1.2025).") from None


def zakazky(session: Session, q: str | None = None, stav: str | None = None, vozidlo_id: int | None = None,
            od: str | None = None, do: str | None = None, limit: int = 50) -> dict:
    """Zakázky od nejnovější. `stav` = prijato / v_oprave / hotovo / predano / otevrene."""
    if stav and stav != "otevrene" and stav not in StavZakazky.VSECHNY:
        raise ChybaValidace(f"Neznámý stav. Možnosti: otevrene, {', '.join(StavZakazky.VSECHNY)}.")
    dotaz = zakazky_sluzba._dotaz_seznamu(None if stav == "otevrene" else stav, stav == "otevrene", q)
    if vozidlo_id:
        dotaz = dotaz.where(Zakazka.vozidlo_id == int(vozidlo_id))
    if (d := _datum(od, "Od")):
        dotaz = dotaz.where(Zakazka.datum_prijeti >= datetime.combine(d, time.min))
    if (d := _datum(do, "Do")):
        dotaz = dotaz.where(Zakazka.datum_prijeti <= datetime.combine(d, time.max))
    vysledek = list(session.exec(dotaz.order_by(col(Zakazka.datum_prijeti).desc(), col(Zakazka.id).desc())
                                 .limit(max(1, min(int(limit or 50), 500)))))
    return {"pocet": len(vysledek), "zakazky": [_zakazka(z) for z in vysledek]}


def zakazka(session: Session, zakazka_id: int) -> dict:
    z = zakazky_sluzba.ziskej(session, zakazka_id)
    rek = polozky.rekapitulace(z)
    return _zakazka(z) | {
        "poznamka": z.poznamka, "polozky": [_radek(r) for r in z.polozky],
        "celkem_bez_dph": hodnota(rek.bez_dph), "celkem_s_dph": hodnota(rek.celkem),
        "doklady": [{"id": f.id, "cislo": f.cislo, "typ": f.typ} for f in z.faktury],
        "poznamka_k_dokladum": "Vystavené doklady jsou kopie – úprava řádků zakázky je nezmění."}


def radky(session: Session, kod: str | None = None, presne: bool = False, bez_vazby: bool = False,
          karta_ceniku_id: int | None = None, typ: str = TypPolozky.MATERIAL, limit: int = 200) -> dict:
    """Řádky zakázek napříč zakázkami. Kód se porovnává bez mezer, teček, pomlček a lomítek (presne=False),
    nebo přesně."""
    dotaz = select(PolozkaZakazky, Zakazka).join(Zakazka, Zakazka.id == PolozkaZakazky.zakazka_id)
    if typ:
        dotaz = dotaz.where(PolozkaZakazky.typ == typ)
    if bez_vazby:
        dotaz = dotaz.where(col(PolozkaZakazky.polozka_ceniku_id).is_(None))
    if karta_ceniku_id:
        dotaz = dotaz.where(PolozkaZakazky.polozka_ceniku_id == int(karta_ceniku_id))
    kod = cisty_text(kod)
    if kod and presne:
        dotaz = dotaz.where(PolozkaZakazky.kod == kod)
    vysledek = []
    hledany = "".join(z for z in (kod or "").upper() if z not in " .-/")
    for r, z in session.exec(dotaz.order_by(col(Zakazka.datum_prijeti).desc(), col(PolozkaZakazky.id))):
        if kod and not presne and hledany not in "".join(c for c in (r.kod or "").upper() if c not in " .-/"):
            continue
        vysledek.append((r, z))
    limit = max(1, min(int(limit or 200), 2000))
    return {"celkem": len(vysledek), "radky": [_radek(r, z) for r, z in vysledek[:limit]]}


# ---------------------------------------------------------------- hromadná úprava řádků

POLE_ZMENY = {"kod", "nazev", "karta_ceniku_id", "mnozstvi", "cena_bez_dph"}


def _plan(session: Session, ids, zmena: dict):
    """→ (změny [(radek, {pole: hodnota}, popis)], přeskočené [(radek, důvod)])."""
    zmena = {k: v for k, v in (zmena or {}).items() if k in POLE_ZMENY}
    if not zmena:
        raise ChybaValidace(f"Zadejte, co změnit: {', '.join(sorted(POLE_ZMENY))}.")
    ids = sorted({int(i) for i in ids or []})
    if not ids:
        raise ChybaValidace("Zadejte ids řádků (najdete je přes hledání řádků).")
    karta = None
    if "karta_ceniku_id" in zmena and zmena["karta_ceniku_id"] not in (None, ""):
        karta = session.get(PolozkaCeniku, int(zmena["karta_ceniku_id"]))
        if karta is None:
            raise NenalezenoError(f"Karta ceníku {zmena['karta_ceniku_id']} neexistuje.")
    mnozstvi = desetinne_nebo_none(zmena.get("mnozstvi"), "Množství") if "mnozstvi" in zmena else None
    cena = desetinne_nebo_none(zmena.get("cena_bez_dph"), "Cena") if "cena_bez_dph" in zmena else None
    if mnozstvi is not None and mnozstvi <= 0:
        raise ChybaValidace("Množství musí být kladné.")
    if cena is not None and cena < 0:
        raise ChybaValidace("Cena nemůže být záporná.")
    nazvy = {k.id: k.nazev for k in session.exec(select(Katalog))}
    radky_ = {r.id: (r, z) for r, z in session.exec(
        select(PolozkaZakazky, Zakazka).join(Zakazka, Zakazka.id == PolozkaZakazky.zakazka_id)
        .where(col(PolozkaZakazky.id).in_(ids)))}
    zmeny, preskocene = [], []
    for i in ids:
        if i not in radky_:
            preskocene.append(({"id": i}, "řádek neexistuje"))
            continue
        r, z = radky_[i]
        nove, popis = {}, []
        if "kod" in zmena or karta is not None:
            kod = cisty_text(zmena.get("kod")) if "kod" in zmena else karta.kod
            if kod != r.kod:
                nove["kod"] = kod
                popis.append(f"kód {r.kod or '–'} → {kod or '–'}")
        if "nazev" in zmena:
            nazev = cisty_text(zmena["nazev"])
            if not nazev:
                preskocene.append((_radek(r, z), "prázdný název"))
                continue
            if nazev != r.nazev:
                nove["nazev"] = nazev
                popis.append(f"název → {nazev}")
        if "karta_ceniku_id" in zmena:
            if karta is not None and r.typ != karta.typ:
                preskocene.append((_radek(r, z), "karta je jiného typu (materiál / práce)"))
                continue
            nova_id = karta.id if karta else None
            if nova_id != r.polozka_ceniku_id:
                nove["polozka_ceniku_id"] = nova_id
                nove["katalog_id"] = karta.katalog_id if karta else r.katalog_id
                popis.append(f"napojit na kartu {karta.kod} ({nazvy.get(karta.katalog_id, '')})" if karta
                             else "zrušit vazbu na ceník")
        if mnozstvi is not None or cena is not None:
            if not z.je_otevrena:
                preskocene.append((_radek(r, z), "množství a cenu jde měnit jen v otevřené zakázce"))
                continue
            if mnozstvi is not None and mnozstvi != r.mnozstvi:
                nove["mnozstvi"] = mnozstvi
                popis.append(f"množství {r.mnozstvi} → {mnozstvi}")
            if cena is not None and cena != r.cena:
                nove["cena"] = cena
                popis.append(f"cena {r.cena} → {cena}")
        if not nove:
            preskocene.append((_radek(r, z), "beze změny"))
            continue
        zmeny.append((r, z, nove, "; ".join(popis)))
    return zmeny, preskocene


def nahled_uprav_radky(session: Session, ids, zmena: dict) -> dict:
    zmeny, preskocene = _plan(session, ids, zmena)
    o = otisk("radky", sorted(int(i) for i in ids), zmena,
              [(r.id, sorted((k, str(v)) for k, v in n.items())) for r, _, n, _ in zmeny], [d for _, d in preskocene])
    return {"zmeni_se": len(zmeny), "preskoci_se": len(preskocene),
            "zmeny": [_radek(r, z) | {"zmena": p} for r, z, _, p in zmeny[:NAHLED_MAX]],
            "preskocene": [d | {"duvod": duvod} for d, duvod in preskocene[:NAHLED_MAX]],
            "poznamka": "Ceny ve starých zakázkách a vystavené doklady se nemění.", "otisk": o}


def proved_uprav_radky(session: Session, klic: ApiKlic | None, ids, zmena: dict, otisk_nahledu: str) -> dict:
    over_otisk(otisk_nahledu, nahled_uprav_radky(session, ids, zmena)["otisk"])
    zmeny, preskocene = _plan(session, ids, zmena)
    if not zmeny:
        raise ChybaValidace("Není co změnit.")
    z_ = zaloha()
    for r, _, nove, _ in zmeny:
        for pole, v in nove.items():
            setattr(r, pole, v)
        session.add(r)
    session.commit()
    text = f"Úprava řádků zakázek ({', '.join(sorted(k for k in zmena if k in POLE_ZMENY))}): změněno {len(zmeny)}, přeskočeno {len(preskocene)}."
    denik(session, klic, "Úprava řádků zakázek", text, len(zmeny), z_)
    return {"zmeneno": len(zmeny), "preskoceno": len(preskocene), "zaloha": z_, "popis": text}


def pridej_dil(session: Session, klic: ApiKlic | None, zakazka_id: int, karta_ceniku_id: int, mnozstvi="1") -> dict:
    """Přidá díl z ceníku do otevřené zakázky (cena z ceníku)."""
    r = polozky.pridej_z_ceniku(session, int(zakazka_id), int(karta_ceniku_id), mnozstvi=str(mnozstvi))
    denik(session, klic, "Přidat díl do zakázky", f"Zakázka {r.zakazka.cislo}: {r.kod or ''} {r.nazev} × {r.mnozstvi}", 1)
    return _radek(r)
