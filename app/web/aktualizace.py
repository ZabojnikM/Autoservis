"""Sekce Aktualizace v Nastavení (HTMX blok #aktualizace)."""
from fastapi import APIRouter, Request

from app.services import aktualizace as akt
from app.web.sablony import templates

router = APIRouter(prefix="/nastaveni/aktualizace")


def _blok(request: Request, s: akt.Stav | None = None, chyba: str = "", hlaseni: str = "", ceka_na: str = ""):
    if s is None:
        try:
            s = akt.stav()
        except akt.ChybaAktualizace as e:
            s, chyba = akt.Stav(kanal=akt.kanal(), git=False), chyba or str(e)
    return templates.TemplateResponse(request, "_aktualizace.html", {
        "s": s, "chyba": chyba, "hlaseni": hlaseni, "ceka_na": ceka_na, "kanaly": akt.KANALY,
        "spusteny": akt.spusteny_commit(),
    })


@router.get("")
def blok(request: Request):
    return _blok(request)


@router.post("/zkontrolovat")
def zkontrolovat(request: Request):
    try:
        return _blok(request, akt.stav(zkontrolovat=True))
    except akt.ChybaAktualizace as e:
        return _blok(request, chyba=str(e))


def _po_zmene(request: Request, nova: str, zprava: str):
    if akt.restart_mozny():
        akt.naplanuj_restart()
        return _blok(request, hlaseni=f"{zprava} Aplikace se restartuje…", ceka_na=nova[:7])
    return _blok(request, hlaseni=f"{zprava} Restartujte aplikaci, aby se změny projevily.")


@router.post("/instalovat")
def instalovat(request: Request):
    try:
        z = akt.nainstaluj()
    except akt.ChybaAktualizace as e:
        return _blok(request, chyba=str(e))
    return _po_zmene(request, z["nova"], f"Nainstalováno {z['cil']} ({z['nova'][:7]}).")


@router.post("/vratit")
def vratit(request: Request):
    try:
        z = akt.vrat()
    except akt.ChybaAktualizace as e:
        return _blok(request, chyba=str(e))
    return _po_zmene(request, z["predchozi"], f"Vrácena předchozí verze ({z['predchozi'][:7]}).")


@router.get("/spusteno")
def spusteno():
    """Commit běžícího procesu – stránka podle něj pozná, že restart proběhl."""
    return {"commit": akt.spusteny_commit()}
