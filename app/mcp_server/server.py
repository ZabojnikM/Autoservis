"""MCP server Autoservisu (#148) – nástroje pro boty v OpenBotu nad stejnými funkcemi jako REST API.

Běží přímo v aplikaci na `/mcp/` (streamable HTTP, bez stavu). Přihlášení stejným klíčem jako API
(`Authorization: Bearer <klíč>` z Nastavení → API pro boty); nástroj bez oprávnění klíče vrátí chybu.
Zápis do skladu a do řádků zakázek je dvoukrokový: náhled (s otiskem) → ukázat uživateli → provedení.
"""
from __future__ import annotations

import contextlib
import contextvars

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from app.api import sklad as api_sklad, vozidla as api_vozidla, zakazky as api_zakazky
from app.services import ChybaValidace, NenalezenoError, api_klice

_hlavicka: contextvars.ContextVar[str | None] = contextvars.ContextVar("autoservis_mcp_hlavicka", default=None)

POKYNY = """Nástroje aplikace Autoservis (malý autoservis): sklad / ceník materiálu, zakázky a vozidla.
Pravidla:
- Před každým zápisem udělej náhled (nástroje nahled_*), ukaž ho uživateli srozumitelně česky a proveď (proved_*)
  až po jeho výslovném souhlasu – s otiskem a stejnými parametry z náhledu.
- Ceny jsou bez DPH, jako text s desetinnou tečkou. Ve starých zakázkách se ceny nemění, vystavené doklady nikdy.
- Kód dílu se v hledání porovnává i bez mezer a teček (25.011.00 = 2501100); předpona výrobce je první slovo (UFI, BO…).
- Každá hromadná změna se zálohuje a zapíše do deníku úprav v aplikaci."""

mcp = MCPServer(name="Autoservis", instructions=POKYNY)


@contextlib.contextmanager
def _spojeni(opravneni: str | None):
    """Spojení s databází (v testech přesměrované jako u webu) + ověřený klíč; chyby → ToolError pro model."""
    from app.db import get_session
    from app.main import app
    gen = app.dependency_overrides.get(get_session, get_session)()
    session = next(gen)
    try:
        klic = api_klice.over(session, _hlavicka.get(), opravneni)
        yield session, klic
    except (ChybaValidace, NenalezenoError, api_klice.ChybaPristupu) as e:
        session.rollback()
        raise ToolError(str(e)) from None
    finally:
        gen.close()


# ---------------------------------------------------------------- obecné

@mcp.tool(description="Kdo jsem: název klíče a oprávnění (sklad, zakazky, vozidla).")
def kdo_jsem() -> dict:
    with _spojeni(None) as (_, klic):
        return {"nazev": klic.nazev, "opravneni": klic.seznam_opravneni}


# ---------------------------------------------------------------- sklad

@mcp.tool(description="Hledá díly materiálu v ceníku (skladu). Filtr: q (kód i bez teček, název), predpona (výrobce, "
                      "např. UFI), katalog (id skladu), stav (aktivni/vyrazene/vse), pouziti (nikdy/pouzite), pouzito_min, "
                      "nepouzito_od (d.m.rrrr), cena_od, cena_do, marze_pod, problem (pod_nakupem/nulova_cena/bez_nakupu/"
                      "kod_podezrely/bez_kodu), kod_regex (regulární výraz na kód), razeni (kod/nazev/cena/nakup/marze/"
                      "pouzito/posledni, „-“ = sestupně).")
def hledej_dily(q: str = "", predpona: str = "", katalog: str = "", stav: str = "aktivni", pouziti: str = "",
                pouzito_min: str = "", nepouzito_od: str = "", cena_od: str = "", cena_do: str = "", marze_pod: str = "",
                problem: str = "", kod_regex: str = "", razeni: str = "kod", limit: int = 100, od: int = 0) -> dict:
    filtr = {k: v for k, v in locals().items() if k not in ("limit", "od") and v}
    with _spojeni("sklad") as (s, _):
        return api_sklad.dily(s, filtr, limit, od)


@mcp.tool(description="Detail dílu ceníku podle id (ceny bez DPH, marže, počet použití v zakázkách).")
def dil_detail(dil_id: int) -> dict:
    with _spojeni("sklad") as (s, _):
        return api_sklad.dil(s, dil_id)


@mcp.tool(description="Sklady (katalogy materiálu) s počty dílů.")
def sklady() -> list:
    with _spojeni("sklad") as (s, _):
        return api_sklad.sklady(s)


@mcp.tool(description="Kontroly kvality ceníku: duplicity, prodej pod nákupem, nulové ceny, podezřelé kódy, řádky bez vazby.")
def kontroly_skladu() -> list:
    with _spojeni("sklad") as (s, _):
        return api_sklad.kontroly_skladu(s)


@mcp.tool(description="Přehledy skladu: díly bez pohybu, marže podle skladu a výrobce, nejpoužívanější díly.")
def prehledy_skladu() -> dict:
    with _spojeni("sklad") as (s, _):
        return api_sklad.prehledy(s)


@mcp.tool(description="Skupiny dílů se stejným číslem pod různými kódy (kandidáti na sloučení), volitelně jen podle textu q.")
def duplicity(q: str = "", limit: int = 100) -> dict:
    with _spojeni("sklad") as (s, _):
        return api_sklad.duplicity(s, q, limit)


@mcp.tool(description="NÁHLED hromadné akce nad díly (nic neukládá). akce: ceny | presun | kopie | kody | vyradit | obnovit | "
                      "smazat. Díly: ids, nebo filtr (stejné klíče jako hledej_dily). parametry: ceny {cil: prodej/nakup/dph, "
                      "zpusob: procenta/marze, hodnota, zaokrouhleni: ''/koruny/devitky}; presun/kopie {katalog: id cíle, "
                      "kolize: preskocit/prepsat/sloucit}; kody {operace: vzor/predpona/sjednotit/nahradit, vzor: "
                      "'UFI ##.###.##', predpona, pole: kod/nazev, hledat, nahradit}. Vrací změny, přeskočené a otisk.")
def nahled_hromadne_akce(akce: str, ids: list[int] | None = None, filtr: dict | None = None,
                         parametry: dict | None = None) -> dict:
    with _spojeni("sklad") as (s, _):
        return api_sklad.nahled_akce(s, akce, ids, filtr, parametry)


@mcp.tool(description="PROVEDE hromadnou akci z náhledu – jen po souhlasu uživatele. Předej akci, ids a parametry přesně "
                      "z náhledu a jeho otisk. Před zápisem se databáze zazálohuje.")
def proved_hromadnou_akci(akce: str, ids: list[int], parametry: dict, otisk: str) -> dict:
    with _spojeni("sklad") as (s, klic):
        return api_sklad.proved_akce(s, klic, akce, ids, parametry, otisk)


@mcp.tool(description="NÁHLED sloučení karet ceníku do jedné (ponechat_id) s novým kódem / názvem / cenou bez DPH. "
                      "Staré karty se vyřadí, řádky starých zakázek dostanou nový kód, ceny v nich zůstanou.")
def nahled_slouceni(ponechat_id: int, ids: list[int], kod: str = "", nazev: str = "", cena: str = "") -> dict:
    with _spojeni("sklad") as (s, _):
        return api_sklad.nahled_slouceni(s, ponechat_id, ids, kod or None, nazev or None, cena or None)


@mcp.tool(description="PROVEDE sloučení z náhledu – jen po souhlasu uživatele, se stejnými parametry a otiskem.")
def proved_slouceni(ponechat_id: int, ids: list[int], otisk: str, kod: str = "", nazev: str = "", cena: str = "") -> dict:
    with _spojeni("sklad") as (s, klic):
        return api_sklad.proved_slouceni(s, klic, ponechat_id, ids, kod or None, nazev or None, cena or None, otisk)


# ---------------------------------------------------------------- zakázky

@mcp.tool(description="Hledá zakázky (číslo, SPZ, zákazník, požadavek). stav: otevrene/prijato/v_oprave/hotovo/predano; "
                      "od/do = datum příjmu d.m.rrrr.")
def hledej_zakazky(q: str = "", stav: str = "", vozidlo_id: int | None = None, od: str = "", do: str = "",
                   limit: int = 50) -> dict:
    with _spojeni("zakazky") as (s, _):
        return api_zakazky.zakazky(s, q, stav, vozidlo_id, od, do, limit)


@mcp.tool(description="Detail zakázky s řádky (materiál, práce), součty a vystavenými doklady.")
def zakazka_detail(zakazka_id: int) -> dict:
    with _spojeni("zakazky") as (s, _):
        return api_zakazky.zakazka(s, zakazka_id)


@mcp.tool(description="Hledá řádky napříč zakázkami: kod (i bez teček; presne=true jen přesná shoda), bez_vazby=true "
                      "řádky bez karty ceníku, karta_ceniku_id. typ: material/prace.")
def hledej_radky_zakazek(kod: str = "", presne: bool = False, bez_vazby: bool = False, karta_ceniku_id: int | None = None,
                         typ: str = "material", limit: int = 200) -> dict:
    with _spojeni("zakazky") as (s, _):
        return api_zakazky.radky(s, kod, presne, bez_vazby, karta_ceniku_id, typ, limit)


@mcp.tool(description="NÁHLED úpravy řádků zakázek (ids z hledej_radky_zakazek). zmena: kod, nazev, karta_ceniku_id "
                      "(napojí na kartu a převezme její kód, null = zrušit vazbu), mnozstvi a cena_bez_dph (jen otevřená "
                      "zakázka). Ceny starých zakázek a doklady se nemění.")
def nahled_upravy_radku(ids: list[int], zmena: dict) -> dict:
    with _spojeni("zakazky") as (s, _):
        return api_zakazky.nahled_uprav_radky(s, ids, zmena)


@mcp.tool(description="PROVEDE úpravu řádků z náhledu – jen po souhlasu uživatele, se stejnými ids, změnou a otiskem.")
def proved_upravu_radku(ids: list[int], zmena: dict, otisk: str) -> dict:
    with _spojeni("zakazky") as (s, klic):
        return api_zakazky.proved_uprav_radky(s, klic, ids, zmena, otisk)


@mcp.tool(description="Přidá díl z ceníku do OTEVŘENÉ zakázky (cena z ceníku). Jen na pokyn uživatele.")
def pridej_dil_do_zakazky(zakazka_id: int, karta_ceniku_id: int, mnozstvi: str = "1") -> dict:
    with _spojeni("zakazky") as (s, klic):
        return api_zakazky.pridej_dil(s, klic, zakazka_id, karta_ceniku_id, mnozstvi)


# ---------------------------------------------------------------- vozidla, zákazníci, příjem

@mcp.tool(description="Hledá vozidla podle SPZ, VIN, značky, modelu nebo zákazníka.")
def hledej_vozidla(q: str = "", limit: int = 50) -> dict:
    with _spojeni("vozidla") as (s, _):
        return api_vozidla.vozidla(s, q, limit)


@mcp.tool(description="Detail vozidla se zákazníkem a historií zakázek.")
def vozidlo_detail(vozidlo_id: int) -> dict:
    with _spojeni("vozidla") as (s, _):
        return api_vozidla.vozidlo(s, vozidlo_id)


@mcp.tool(description="Založí vozidlo. data: spz (povinná), vin, znacka, model, rok_vyroby, datum_registrace, kod_motoru, "
                      "objem, vykon, palivo, cislo_motoru, olej, barva, termin_stk, poznamka, zakaznik_id.")
def zaloz_vozidlo(data: dict) -> dict:
    with _spojeni("vozidla") as (s, klic):
        return api_vozidla.vytvor_vozidlo(s, klic, data)


@mcp.tool(description="Upraví vozidlo – jen zadaná pole (stejná jako zaloz_vozidlo).")
def uprav_vozidlo(vozidlo_id: int, data: dict) -> dict:
    with _spojeni("vozidla") as (s, klic):
        return api_vozidla.uprav_vozidlo(s, klic, vozidlo_id, data)


@mcp.tool(description="Hledá zákazníky podle jména, telefonu, e-mailu nebo IČO.")
def hledej_zakazniky(q: str = "", limit: int = 50) -> dict:
    with _spojeni("vozidla") as (s, _):
        return api_vozidla.zakaznici(s, q, limit)


@mcp.tool(description="Detail zákazníka s vozidly a zakázkami.")
def zakaznik_detail(zakaznik_id: int) -> dict:
    with _spojeni("vozidla") as (s, _):
        return api_vozidla.zakaznik(s, zakaznik_id)


@mcp.tool(description="Založí zákazníka. data: nazev (povinný), telefon, email, ulice, mesto, psc, ico, dic, poznamka.")
def zaloz_zakaznika(data: dict) -> dict:
    with _spojeni("vozidla") as (s, klic):
        return api_vozidla.vytvor_zakaznika(s, klic, data)


@mcp.tool(description="Upraví zákazníka – jen zadaná pole.")
def uprav_zakaznika(zakaznik_id: int, data: dict) -> dict:
    with _spojeni("vozidla") as (s, klic):
        return api_vozidla.uprav_zakaznika(s, klic, zakaznik_id, data)


@mcp.tool(description="Příjem nové zakázky. zakazka: pozadavek, tachometr, poznamka, termin_dokonceni, vozidlo_id. "
                      "vozidlo: údaje vozidla se SPZ (neexistující se založí). zakaznik: {id} existující, {nazev, …} nový, "
                      "{vyber: 'bez'} bez zákazníka, prázdné = zákazník vozidla.")
def prijem_zakazky(zakazka: dict, vozidlo: dict | None = None, zakaznik: dict | None = None) -> dict:
    with _spojeni("vozidla") as (s, klic):
        return api_vozidla.prijem(s, klic, zakazka, vozidlo, zakaznik)


# ---------------------------------------------------------------- ASGI aplikace pro /mcp

class _Prihlaseni:
    """Předá hlavičku Authorization nástrojům (ověřuje se v každém nástroji, včetně oprávnění)."""

    def __init__(self, aplikace):
        self.aplikace = aplikace

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.aplikace(scope, receive, send)
        hlavicky = dict(scope.get("headers") or [])
        token = _hlavicka.set(hlavicky.get(b"authorization", b"").decode("latin-1"))
        try:
            await self.aplikace(scope, receive, send)
        finally:
            _hlavicka.reset(token)


asgi = _Prihlaseni(mcp.streamable_http_app(
    streamable_http_path="/", stateless_http=True, json_response=True,
    # přístup chrání klíč; ochrana proti DNS rebindingu by odmítla adresy serveru v síti
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)))
