"""REST API `/api/v1` pro boty (#145–#147). Přihlášení hlavičkou `Authorization: Bearer <klíč>` z Nastavení.

Chyby vrací JSON `{"chyba": "…"}`: 401 klíč, 403 oprávnění / vypnuté API, 404 nenalezeno, 422 neplatná data.
"""
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header

from app.api import sklad, vozidla, zakazky
from app.models import ApiKlic
from app.services import api_klice
from app.web.spolecne import DB

router = APIRouter(prefix="/api/v1", tags=["API pro boty"])


def _klic(opravneni: str | None):
    def zavislost(db: DB, authorization: Annotated[str | None, Header()] = None) -> ApiKlic:
        return api_klice.over(db, authorization, opravneni)
    return zavislost


Klic = Annotated[ApiKlic, Depends(_klic(None))]
Sklad = Annotated[ApiKlic, Depends(_klic("sklad"))]
Zakazky = Annotated[ApiKlic, Depends(_klic("zakazky"))]
Vozidla = Annotated[ApiKlic, Depends(_klic("vozidla"))]
Telo = Annotated[dict, Body()]


@router.get("/ja")
def ja(klic: Klic):
    """Kdo jsem a co smím – pro kontrolu klíče."""
    return {"nazev": klic.nazev, "opravneni": klic.seznam_opravneni}


# ---------------------------------------------------------------- sklad

@router.get("/sklad/dily")
def sklad_dily(db: DB, _: Sklad, katalog: str = "", q: str = "", predpona: str = "", stav: str = "aktivni",
               pouziti: str = "", pouzito_min: str = "", nepouzito_od: str = "", cena_od: str = "", cena_do: str = "",
               marze_pod: str = "", problem: str = "", razeni: str = "kod", kod_regex: str = "", kod_vzor: str = "",
               limit: int = 100, od: int = 0):
    filtr = {k: v for k, v in locals().items() if k not in ("db", "_", "limit", "od") and v}
    return sklad.dily(db, filtr, limit, od)


@router.get("/sklad/dily/{dil_id}")
def sklad_dil(db: DB, _: Sklad, dil_id: int):
    return sklad.dil(db, dil_id)


@router.get("/sklad/sklady")
def sklad_sklady(db: DB, _: Sklad):
    return sklad.sklady(db)


@router.get("/sklad/kontroly")
def sklad_kontroly(db: DB, _: Sklad):
    return sklad.kontroly_skladu(db)


@router.get("/sklad/prehledy")
def sklad_prehledy(db: DB, _: Sklad):
    return sklad.prehledy(db)


@router.get("/sklad/duplicity")
def sklad_duplicity(db: DB, _: Sklad, q: str = "", limit: int = 100):
    return sklad.duplicity(db, q, limit)


@router.post("/sklad/akce/nahled")
def sklad_akce_nahled(db: DB, _: Sklad, data: Telo):
    return sklad.nahled_akce(db, data.get("akce", ""), data.get("ids"), data.get("filtr"), data.get("parametry"))


@router.post("/sklad/akce/provest")
def sklad_akce_provest(db: DB, klic: Sklad, data: Telo):
    return sklad.proved_akce(db, klic, data.get("akce", ""), data.get("ids"), data.get("parametry"), data.get("otisk", ""))


@router.post("/sklad/sloucit/nahled")
def sklad_sloucit_nahled(db: DB, _: Sklad, data: Telo):
    return sklad.nahled_slouceni(db, data.get("ponechat_id"), data.get("ids"), data.get("kod"), data.get("nazev"),
                                 data.get("cena"))


@router.post("/sklad/sloucit/provest")
def sklad_sloucit_provest(db: DB, klic: Sklad, data: Telo):
    return sklad.proved_slouceni(db, klic, data.get("ponechat_id"), data.get("ids"), data.get("kod"), data.get("nazev"),
                                 data.get("cena"), data.get("otisk", ""))


# ---------------------------------------------------------------- zakázky

@router.get("/zakazky")
def zakazky_seznam(db: DB, _: Zakazky, q: str = "", stav: str = "", vozidlo_id: int | None = None, od: str = "",
                   do: str = "", limit: int = 50):
    return zakazky.zakazky(db, q, stav, vozidlo_id, od, do, limit)


@router.get("/zakazky/radky")
def zakazky_radky(db: DB, _: Zakazky, kod: str = "", presne: bool = False, bez_vazby: bool = False,
                  karta_ceniku_id: int | None = None, typ: str = "material", limit: int = 200):
    return zakazky.radky(db, kod, presne, bez_vazby, karta_ceniku_id, typ, limit)


@router.post("/zakazky/radky/nahled")
def zakazky_radky_nahled(db: DB, _: Zakazky, data: Telo):
    return zakazky.nahled_uprav_radky(db, data.get("ids"), data.get("zmena"))


@router.post("/zakazky/radky/provest")
def zakazky_radky_provest(db: DB, klic: Zakazky, data: Telo):
    return zakazky.proved_uprav_radky(db, klic, data.get("ids"), data.get("zmena"), data.get("otisk", ""))


@router.get("/zakazky/{zakazka_id}")
def zakazky_detail(db: DB, _: Zakazky, zakazka_id: int):
    return zakazky.zakazka(db, zakazka_id)


@router.post("/zakazky/{zakazka_id}/polozky")
def zakazky_pridej_dil(db: DB, klic: Zakazky, zakazka_id: int, data: Telo):
    return zakazky.pridej_dil(db, klic, zakazka_id, data.get("karta_ceniku_id"), data.get("mnozstvi", "1"))


# ---------------------------------------------------------------- vozidla, zákazníci, příjem

@router.get("/vozidla")
def vozidla_seznam(db: DB, _: Vozidla, q: str = "", limit: int = 50):
    return vozidla.vozidla(db, q, limit)


@router.post("/vozidla")
def vozidla_nove(db: DB, klic: Vozidla, data: Telo):
    return vozidla.vytvor_vozidlo(db, klic, data)


@router.get("/vozidla/{vozidlo_id}")
def vozidla_detail(db: DB, _: Vozidla, vozidlo_id: int):
    return vozidla.vozidlo(db, vozidlo_id)


@router.patch("/vozidla/{vozidlo_id}")
def vozidla_uprav(db: DB, klic: Vozidla, vozidlo_id: int, data: Telo):
    return vozidla.uprav_vozidlo(db, klic, vozidlo_id, data)


@router.get("/zakaznici")
def zakaznici_seznam(db: DB, _: Vozidla, q: str = "", limit: int = 50):
    return vozidla.zakaznici(db, q, limit)


@router.post("/zakaznici")
def zakaznici_novy(db: DB, klic: Vozidla, data: Telo):
    return vozidla.vytvor_zakaznika(db, klic, data)


@router.get("/zakaznici/{zakaznik_id}")
def zakaznici_detail(db: DB, _: Vozidla, zakaznik_id: int):
    return vozidla.zakaznik(db, zakaznik_id)


@router.patch("/zakaznici/{zakaznik_id}")
def zakaznici_uprav(db: DB, klic: Vozidla, zakaznik_id: int, data: Telo):
    return vozidla.uprav_zakaznika(db, klic, zakaznik_id, data)


@router.post("/prijem")
def prijem(db: DB, klic: Vozidla, data: Telo):
    """Příjem nové zakázky: {"zakazka": {...}, "vozidlo": {...}, "zakaznik": {...}}."""
    return vozidla.prijem(db, klic, data.get("zakazka") or {}, data.get("vozidlo"), data.get("zakaznik"))
