"""API skladu (#145) – funkce sdílené REST rozhraním `/api/v1/sklad` a MCP serverem.

Čtení vrací slovníky připravené pro JSON. Zápis je dvoukrokový: `nahled_*` vrátí plán s otiskem,
`proved_*` ho sestaví znovu a provede jen při stejném otisku, se zálohou a zápisem do deníku úprav.
"""
from __future__ import annotations

from sqlmodel import Session, col, select

from app.api.spolecne import denik, hodnota, otisk, over_otisk, zaloha
from app.models import ApiKlic, PolozkaCeniku, PolozkaZakazky
from app.services import ChybaValidace, NenalezenoError, hromadne, katalogy, kontroly, slouceni, sprava

AKCE = hromadne.AKCE
NAHLED_MAX = 200


def _dil(r: sprava.Radek) -> dict:
    p = r.karta
    return {"id": p.id, "kod": p.kod, "nazev": p.nazev, "sklad": r.katalog, "sklad_id": p.katalog_id,
            "prodej_bez_dph": hodnota(p.cena), "nakup_bez_dph": hodnota(p.nakupni_cena), "dph": hodnota(p.sazba_dph),
            "marze": hodnota(r.marze), "pouzito": r.pouzito, "naposledy": hodnota(r.posledni), "aktivni": p.aktivni,
            "jednotka": p.jednotka, "zamenitelny_dil": p.zamenitelny_dil, "poznamka": p.poznamka}


def _radky(session: Session, filtr: dict | None) -> list[sprava.Radek]:
    filtr = {k: str(v) for k, v in (filtr or {}).items() if v is not None}
    regex = filtr.pop("kod_regex", None)
    if filtr.get("kod_vzor"):  # #151: vzor se zástupnými znaky jako v Excelu / Accessu (* ? # [ ])
        filtr["vzor"] = filtr.pop("kod_vzor")
    radky = sprava.vyber(session, sprava.Filtr.z_dat(filtr))
    if regex:
        import re
        try:
            vzor = re.compile(regex)
        except re.error as e:
            raise ChybaValidace(f"Neplatný regulární výraz kódu: {e}") from None
        radky = [r for r in radky if r.karta.kod and vzor.search(r.karta.kod)]
    return radky


def dily(session: Session, filtr: dict | None = None, limit: int = 100, od: int = 0) -> dict:
    """Díly materiálu podle filtru (klíče jako v Správě dat: katalog, q, predpona, stav, pouziti, pouzito_min,
    nepouzito_od, cena_od, cena_do, marze_pod, problem, razeni; navíc kod_vzor (zástupné znaky * ? # [ ])
    a kod_regex)."""
    radky = _radky(session, filtr)
    limit = max(1, min(int(limit or 100), 1000))
    return {"celkem": len(radky), "od": od, "dily": [_dil(r) for r in radky[od:od + limit]]}


def dil(session: Session, dil_id: int) -> dict:
    radky = [r for r in sprava.vyber(session, sprava.Filtr(stav="vse")) if r.karta.id == dil_id]
    if not radky:
        raise NenalezenoError(f"Díl {dil_id} v ceníku materiálu není.")
    return _dil(radky[0])


def sklady(session: Session) -> list[dict]:
    vsechny = sprava.vyber(session, sprava.Filtr(stav="vse"))
    return [{"id": k.id, "nazev": k.nazev, "vychozi": k.vychozi,
             "dilu": sum(1 for r in vsechny if r.karta.katalog_id == k.id),
             "aktivnich": sum(1 for r in vsechny if r.karta.katalog_id == k.id and r.karta.aktivni)}
            for k in katalogy.seznam(session)]


def kontroly_skladu(session: Session) -> list[dict]:
    return [{"nazev": k.nazev, "pocet": k.pocet, "popis": k.popis, "filtr_v_aplikaci": k.odkaz}
            for k in kontroly.prehled_kontrol(session)]


def prehledy(session: Session) -> dict:
    p = kontroly.prehledy(session)
    marze = lambda s: {"nazev": s.nazev, "dilu": s.dilu, "s_nakupem": s.s_nakupem,  # noqa: E731
                       "prumerna_marze": hodnota(s.prumer), "pod_nakupem": s.pod_nakupem}
    return {"aktivnich_dilu": p["aktivnich"], "nikdy_nepouzite": p["nikdy"],
            "bez_pohybu": [{"nazev": n, "pocet": c} for n, c, _ in p["bez_pohybu"]],
            "marze_podle_skladu": [marze(s) for s in p["podle_skladu"]],
            "marze_podle_vyrobce": [marze(s) for s in p["podle_vyrobce"]],
            "nejpouzivanejsi": [_dil(r) for r in p["nejpouzivanejsi"]]}


def duplicity(session: Session, q: str | None = None, limit: int = 100) -> dict:
    skupiny = slouceni.navrhy(session, q)
    return {"celkem": len(skupiny), "skupiny": [
        {"cislo_dilu": s.klic, "navrzena_karta_id": s.cil_id, "pouzito": s.pouzito,
         "karty": [{"id": k.id, "kod": k.kod, "nazev": k.nazev, "sklad": k.katalog, "prodej_bez_dph": hodnota(k.cena),
                    "pouzito": k.pouzito} for k in s.karty]} for s in skupiny[:limit]]}


# ---------------------------------------------------------------- hromadné akce

def _ids(session: Session, ids, filtr) -> list[int]:
    if ids:
        return sprava.ids_z_vyberu(session, sprava.Filtr(), "vybrane", ids)
    if filtr:
        return [r.karta.id for r in _radky(session, filtr)]
    raise ChybaValidace("Zadejte ids dílů, nebo filtr.")


def _plan(session, akce, ids, parametry):
    if akce not in AKCE:
        raise ChybaValidace(f"Neznámá akce „{akce}“. Možnosti: {', '.join(AKCE)}.")
    plan = hromadne.planuj(session, akce, ids, {k: str(v) for k, v in (parametry or {}).items()})
    o = otisk(akce, ids, parametry or {}, [(z.id, z.co, z.pred, z.po, z.preskoceno) for z in plan.zmeny])
    return plan, o


def nahled_akce(session: Session, akce: str, ids=None, filtr=None, parametry=None) -> dict:
    """Náhled hromadné akce: ceny, presun, kopie, kody, vyradit, obnovit, smazat."""
    ids = _ids(session, ids, filtr)
    plan, o = _plan(session, akce, ids, parametry)
    zmena = lambda z: {"id": z.id, "kod": z.kod, "nazev": z.nazev, "co": z.co, "ted": z.pred, "nove": z.po}  # noqa: E731
    return {"akce": akce, "nazev_akce": AKCE[akce], "popis": plan.popis, "ids": ids, "parametry": parametry or {},
            "zmeni_se": len(plan.provede_se), "preskoci_se": len(plan.preskoci_se),
            "zmeny": [zmena(z) for z in plan.provede_se[:NAHLED_MAX]],
            "preskocene": [zmena(z) | {"duvod": z.preskoceno} for z in plan.preskoci_se[:NAHLED_MAX]],
            "otisk": o}


def proved_akce(session: Session, klic: ApiKlic | None, akce: str, ids, parametry, otisk_nahledu: str) -> dict:
    ids = [int(i) for i in ids or []]
    plan, o = _plan(session, akce, ids, parametry)
    over_otisk(otisk_nahledu, o)
    if not plan.provede_se:
        raise ChybaValidace("Není co změnit – všechny díly by se přeskočily.")
    z = zaloha()
    pocet = hromadne.proved(session, plan)
    text = f"{AKCE[akce]}: {plan.popis}. Změněno dílů {pocet}, přeskočeno {len(plan.preskoci_se)}."
    denik(session, klic, AKCE[akce], text, pocet, z)
    return {"zmeneno": pocet, "preskoceno": len(plan.preskoci_se), "zaloha": z, "popis": text}


# ---------------------------------------------------------------- sloučení dílů

def _slouceni(session, cil_id, ids):
    ids = sorted({int(i) for i in ids or []} | {int(cil_id)})
    karty = {p.id: p for p in session.exec(select(PolozkaCeniku).where(col(PolozkaCeniku.id).in_(ids)))}
    chybi = [i for i in ids if i not in karty]
    if chybi:
        raise NenalezenoError(f"Karty {chybi} v ceníku nejsou.")
    radku = len(session.exec(select(PolozkaZakazky.id).where(col(PolozkaZakazky.polozka_ceniku_id).in_(ids))).all())
    return ids, karty, radku


def nahled_slouceni(session: Session, cil_id: int, ids, kod=None, nazev=None, cena=None) -> dict:
    ids, karty, radku = _slouceni(session, cil_id, ids)
    cil = karty[int(cil_id)]
    o = otisk("sloucit", ids, cil_id, kod, nazev, cena, [(p.id, p.kod, str(p.cena), p.aktivni) for p in karty.values()], radku)
    return {"ponechat": {"id": cil.id, "kod": cil.kod, "novy_kod": kod or cil.kod, "novy_nazev": nazev or cil.nazev,
                         "nova_cena_bez_dph": str(cena) if cena not in (None, "") else hodnota(cil.cena)},
            "vyradit": [{"id": p.id, "kod": p.kod, "nazev": p.nazev} for i, p in karty.items() if i != cil.id],
            "radku_zakazek_napojenych": radku,
            "poznamka": "Ve starých zakázkách se přepíše kód a vazba, ceny v nich a vystavené doklady zůstanou.",
            "otisk": o}


def proved_slouceni(session: Session, klic: ApiKlic | None, cil_id: int, ids, kod=None, nazev=None, cena=None,
                    otisk_nahledu: str = "") -> dict:
    over_otisk(otisk_nahledu, nahled_slouceni(session, cil_id, ids, kod, nazev, cena)["otisk"])
    z = zaloha()
    v = slouceni.sluc(session, int(cil_id), [int(i) for i in ids], kod, nazev, cena)
    denik(session, klic, "Sloučit díly", v.text, v.karet + 1, z)
    return {"kod": v.kod, "vyrazeno_karet": v.karet, "prepsano_radku": v.radku, "zaloha": z}
