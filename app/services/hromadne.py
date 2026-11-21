"""Hromadné akce nad vybranými díly materiálu ve Správě dat.

Každá akce se nejdřív naplánuje (`planuj`) – plán je zároveň náhled pro uživatele (stará → nová hodnota,
přeskočené díly s důvodem). Provedení (`proved`) plán sestaví znovu nad aktuálními daty, takže se provede
přesně to, co náhled ukazuje i po mezitímní změně ceníku.

- Změna cen (#138): prodej ± % nebo podle nákupu a marže, nákup ± %, sazba DPH, zaokrouhlení.
- Přesun / kopie mezi sklady (#139): kolize kódu v cílovém skladu = přeskočit / přepsat ceny / sloučit.
- Vyřadit, obnovit, trvale smazat (jen nikdy nepoužité) a smazání celého skladu (#140).
- Úprava kódů a názvů (#142): předpona výrobce, sjednocení zápisu, hledat a nahradit, přeformátování
  podle vzoru (#145, `UFI ##.###.##` – # = znak čísla dílu bez předpony a oddělovačů). Nový kód se propíše
  do řádků zakázek napojených na kartu (ceny v zakázkách se nemění, doklady vůbec).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from sqlmodel import Session, col, select

from app.models import Katalog, PolozkaCeniku, PolozkaZakazky
from app.services import ChybaValidace, cisty_text, desetinne_nebo_none, katalogy, slouceni
from app.services import sprava

AKCE = {
    "ceny": "Změna cen", "presun": "Přesun do jiného skladu", "kopie": "Kopie do jiného skladu",
    "kody": "Úprava kódů a názvů", "vyradit": "Vyřadit", "obnovit": "Obnovit vyřazené",
    "smazat": "Trvale smazat (jen nepoužité)",
}
ZAOKROUHLENI = {"": "na haléře", "koruny": "na celé koruny", "devitky": "nahoru na …9 Kč"}
KOLIZE = {"preskocit": "přeskočit", "prepsat": "přepsat ceny cílové karty", "sloucit": "sloučit do cílové karty"}


@dataclass
class Zmena:
    id: int
    kod: str
    nazev: str
    co: str = ""
    pred: str = ""
    po: str = ""
    preskoceno: str = ""


@dataclass
class Plan:
    akce: str
    popis: str
    zmeny: list[Zmena] = field(default_factory=list)
    operace: list = field(default_factory=list)   # („uprav“, id, {pole: hodnota}) / („smazat“, id) / …

    @property
    def provede_se(self) -> list[Zmena]:
        return [z for z in self.zmeny if not z.preskoceno]

    @property
    def preskoci_se(self) -> list[Zmena]:
        return [z for z in self.zmeny if z.preskoceno]


def _penize(hodnota) -> str:
    return "—" if hodnota is None else f"{Decimal(hodnota):,.2f}".replace(",", " ").replace(".", ",")


def zaokrouhli(cislo: Decimal, zpusob: str) -> Decimal:
    if zpusob == "koruny":
        return cislo.quantize(Decimal("1"), ROUND_HALF_UP)
    if zpusob == "devitky":
        cele = int(cislo.quantize(Decimal("1"), ROUND_CEILING))
        return Decimal(cele + (9 - cele % 10) % 10)
    return cislo.quantize(Decimal("0.01"), ROUND_HALF_UP)


def _karty(session: Session, ids) -> list[PolozkaCeniku]:
    karty = {p.id: p for p in session.exec(select(PolozkaCeniku).where(col(PolozkaCeniku.id).in_(list(ids))))}
    return [karty[i] for i in ids if i in karty]


def _zmena(p: PolozkaCeniku, **kw) -> Zmena:
    return Zmena(p.id, p.kod or "", p.nazev, **kw)


def _obsazene_kody(session: Session) -> dict[tuple, int]:
    return {(k, kod): i for i, k, kod in session.exec(select(PolozkaCeniku.id, PolozkaCeniku.katalog_id, PolozkaCeniku.kod))
            if kod}


def _cilovy_katalog(session: Session, hodnota) -> Katalog:
    text = str(hodnota or "").strip()
    if not text.isdigit():
        raise ChybaValidace("Vyberte cílový sklad.")
    return katalogy.ziskej(session, int(text))


# ---------------------------------------------------------------- jednotlivé akce

def _ceny(session, karty, par) -> Plan:
    cil, zpusob = par.get("cil") or "prodej", par.get("zpusob") or "procenta"
    hodnota = desetinne_nebo_none(par.get("hodnota"), "Hodnota")
    if hodnota is None:
        raise ChybaValidace("Zadejte hodnotu (procenta, marži nebo sazbu DPH).")
    zaokr = par.get("zaokrouhleni") or ""
    if cil == "dph":
        if not 0 <= hodnota < 100:
            raise ChybaValidace("Sazba DPH musí být 0–99 %.")
        popis = f"sazba DPH {hodnota.normalize():f} %"
    elif zpusob == "marze":
        if cil != "prodej":
            raise ChybaValidace("Podle marže jde nastavit jen prodejní cenu.")
        if not hodnota < 100:
            raise ChybaValidace("Marže musí být menší než 100 %.")
        popis = f"prodej podle nákupu s marží {hodnota.normalize():f} %, zaokrouhlit {ZAOKROUHLENI.get(zaokr, '')}"
    else:
        if hodnota <= -100:
            raise ChybaValidace("Snížení o 100 % a víc by dalo nulovou nebo zápornou cenu.")
        popis = (f"{'prodej' if cil == 'prodej' else 'nákup'} {'+' if hodnota >= 0 else ''}{hodnota.normalize():f} %, "
                 f"zaokrouhlit {ZAOKROUHLENI.get(zaokr, '')}")
    plan = Plan("ceny", popis)
    for p in karty:
        if cil == "dph":
            pred, nova, pole, co = p.sazba_dph, hodnota, "sazba_dph", "DPH %"
            text = lambda x: f"{Decimal(x).normalize():f} %"  # noqa: E731
        elif cil == "nakup":
            pred, pole, co, text = p.nakupni_cena, "nakupni_cena", "Nákup", _penize
            if pred is None:
                plan.zmeny.append(_zmena(p, co=co, preskoceno="nemá nákupní cenu"))
                continue
            nova = zaokrouhli(pred * (100 + hodnota) / 100, zaokr)
        else:
            pred, pole, co, text = p.cena, "cena", "Prodej", _penize
            if zpusob == "marze":
                if not p.nakupni_cena:
                    plan.zmeny.append(_zmena(p, co=co, preskoceno="nemá nákupní cenu"))
                    continue
                nova = zaokrouhli(p.nakupni_cena * 100 / (100 - hodnota), zaokr)
            else:
                nova = zaokrouhli(pred * (100 + hodnota) / 100, zaokr)
        if pred is not None and Decimal(pred) == nova:
            plan.zmeny.append(_zmena(p, co=co, pred=text(pred), po=text(nova), preskoceno="beze změny"))
            continue
        plan.zmeny.append(_zmena(p, co=co, pred=text(pred), po=text(nova)))
        plan.operace.append(("uprav", p.id, {pole: nova}))
    return plan


def _presun_kopie(session, karty, par, kopie: bool) -> Plan:
    cil = _cilovy_katalog(session, par.get("katalog"))
    kolize = par.get("kolize") or "preskocit"
    if kolize not in KOLIZE:
        kolize = "preskocit"
    if kopie and kolize == "sloucit":
        raise ChybaValidace("Sloučit do cílové karty jde jen při přesunu. Při kopii zvolte přeskočit, nebo přepsat ceny.")
    plan = Plan("kopie" if kopie else "presun", f"do skladu {cil.nazev}, při stejném kódu {KOLIZE[kolize]}")
    obsazene = _obsazene_kody(session)
    nazvy = {k.id: k.nazev for k in katalogy.seznam(session)}
    nove: set = set()
    for p in karty:
        z = _zmena(p, co="Sklad", pred=nazvy.get(p.katalog_id, ""), po=cil.nazev)
        if p.katalog_id == cil.id:
            z.preskoceno = "už je v cílovém skladu"
        elif p.kod and (cil.id, p.kod) in nove:
            z.preskoceno = "stejný kód už se do skladu přesouvá"
        elif p.kod and (cil.id, p.kod) in obsazene:
            jina = obsazene[(cil.id, p.kod)]
            if kolize == "preskocit":
                z.preskoceno = f"v cílovém skladu už je kód {p.kod}"
            elif kopie:   # přepsat ceny existující karty
                z.co, z.po = "Přepsat ceny", f"karta {p.kod} v {cil.nazev}: {_penize(p.cena)}"
                plan.operace.append(("uprav", jina, {"cena": p.cena, "nakupni_cena": p.nakupni_cena,
                                                     "sazba_dph": p.sazba_dph}))
            else:
                z.co = "Sloučit do"
                z.po = f"{p.kod} v {cil.nazev}" + (" (s cenami přesouvané karty)" if kolize == "prepsat" else "")
                plan.operace.append(("sloucit", p.id, jina, kolize == "prepsat", False))
        else:
            if p.kod:
                nove.add((cil.id, p.kod))
            plan.operace.append(("kopie", p.id, cil.id) if kopie else ("uprav", p.id, {"katalog_id": cil.id}))
        plan.zmeny.append(z)
    return plan


def _stav(session, karty, aktivni: bool) -> Plan:
    plan = Plan("obnovit" if aktivni else "vyradit", "obnovit vyřazené díly" if aktivni else "vyřadit díly")
    for p in karty:
        z = _zmena(p, co="Stav", pred="aktivní" if p.aktivni else "vyřazený", po="aktivní" if aktivni else "vyřazený")
        if p.aktivni == aktivni:
            z.preskoceno = "už je " + z.po
        else:
            plan.operace.append(("uprav", p.id, {"aktivni": aktivni}))
        plan.zmeny.append(z)
    return plan


def _smazat(session, karty, par) -> Plan:
    pouzite = sprava.pouziti(session)
    plan = Plan("smazat", "trvale smazat nepoužité díly")
    for p in karty:
        z = _zmena(p, co="Smazat", pred=_penize(p.cena), po="smaže se")
        pocet = pouzite.get(p.id, (0, None))[0]
        if pocet:
            z.preskoceno = f"použitý v {pocet} řádcích zakázek – jde jen vyřadit"
        else:
            plan.operace.append(("smazat", p.id))
        plan.zmeny.append(z)
    return plan


def _kody(session, karty, par) -> Plan:
    operace = par.get("operace") or "predpona"
    obsazene = _obsazene_kody(session)
    nove: set = set()
    if operace == "predpona":
        predpona = (cisty_text(par.get("predpona")) or "").upper()
        if not predpona or " " in predpona:
            raise ChybaValidace("Zadejte předponu výrobce jedním slovem, např. UFI.")
        popis, pole = f"doplnit předponu {predpona}", "kod"
        uprav = lambda kod: kod if kod.strip().upper().startswith(predpona + " ") else f"{predpona} {kod.strip()}"  # noqa: E731
    elif operace == "vzor":
        vzor = (cisty_text(par.get("vzor")) or "").upper()
        mist = vzor.count("#")
        if not mist:
            raise ChybaValidace("Zadejte vzor kódu, číslice označte #, např. UFI ##.###.##.")
        popis, pole = f"přeformátovat podle vzoru {vzor}", "kod"

        def uprav(kod: str) -> str:
            cislo = slouceni.klic_kodu(kod)
            if len(cislo) != mist:
                return kod   # nesedí – přeskočí se jako „beze změny“ s vlastním důvodem níže
            znaky = iter(cislo)
            return "".join(next(znaky) if z == "#" else z for z in vzor)
    elif operace == "sjednotit":
        popis, pole = "sjednotit zápis kódu (mezery, velká písmena)", "kod"
        uprav = lambda kod: " ".join(kod.split()).upper()  # noqa: E731
    elif operace == "nahradit":
        pole = "nazev" if par.get("pole") == "nazev" else "kod"
        hledat, nahradit = par.get("hledat") or "", par.get("nahradit") or ""
        if not hledat:
            raise ChybaValidace("Zadejte text, který se má nahradit.")
        popis = f"{'název' if pole == 'nazev' else 'kód'}: „{hledat}“ → „{nahradit}“"
        uprav = lambda text: text.replace(hledat, nahradit)  # noqa: E731
    else:
        raise ChybaValidace("Neznámá úprava kódů.")
    plan = Plan("kody", popis)
    for p in karty:
        stary = (p.kod or "") if pole == "kod" else p.nazev
        z = _zmena(p, co="Kód" if pole == "kod" else "Název", pred=stary)
        if pole == "kod" and not stary.strip():
            z.preskoceno = "nemá kód"
            plan.zmeny.append(z)
            continue
        novy = uprav(stary)
        novy = novy.strip() if pole == "nazev" else novy
        z.po = novy
        if operace == "vzor" and len(slouceni.klic_kodu(stary)) != mist:
            z.preskoceno = f"číslo {slouceni.klic_kodu(stary)} nesedí na vzor ({mist} znaků)"
        elif novy == stary:
            z.preskoceno = "beze změny"
        elif not novy.strip():
            z.preskoceno = "vyšel by prázdný " + ("kód" if pole == "kod" else "název")
        elif pole == "kod" and (((p.katalog_id, novy) in obsazene and obsazene[(p.katalog_id, novy)] != p.id)
                                or (p.katalog_id, novy) in nove):
            z.preskoceno = f"kód {novy} už ve skladu je – použijte Sloučit díly"
        else:
            if pole == "kod":
                nove.add((p.katalog_id, novy))
            plan.operace.append(("uprav", p.id, {pole: novy}))
        plan.zmeny.append(z)
    return plan


def planuj(session: Session, akce: str, ids, par: dict) -> Plan:
    if akce not in AKCE:
        raise ChybaValidace("Vyberte akci.")
    karty = _karty(session, ids)
    if not karty:
        raise ChybaValidace("Výběr neobsahuje žádné díly.")
    if akce == "ceny":
        return _ceny(session, karty, par)
    if akce in ("presun", "kopie"):
        return _presun_kopie(session, karty, par, kopie=akce == "kopie")
    if akce in ("vyradit", "obnovit"):
        return _stav(session, karty, aktivni=akce == "obnovit")
    if akce == "smazat":
        return _smazat(session, karty, par)
    return _kody(session, karty, par)


# ---------------------------------------------------------------- provedení

def proved(session: Session, plan: Plan) -> int:
    """Provede operace plánu; vrací počet změněných dílů. Úpravy v jedné transakci, sloučení každé zvlášť."""
    for op in plan.operace:
        druh = op[0]
        if druh == "uprav":
            _, pid, zmeny = op
            p = session.get(PolozkaCeniku, pid)
            for pole, hodnota in zmeny.items():
                setattr(p, pole, hodnota)
            session.add(p)
            if "kod" in zmeny or "katalog_id" in zmeny:
                for r in session.exec(select(PolozkaZakazky).where(PolozkaZakazky.polozka_ceniku_id == pid)):
                    if "kod" in zmeny:
                        r.kod = zmeny["kod"]
                    if "katalog_id" in zmeny:
                        r.katalog_id = zmeny["katalog_id"]
                    session.add(r)
        elif druh == "kopie":
            _, pid, katalog_id = op
            p = session.get(PolozkaCeniku, pid)
            session.add(PolozkaCeniku(katalog_id=katalog_id, kod=p.kod, nazev=p.nazev, typ=p.typ, jednotka=p.jednotka,
                                      cena=p.cena, sazba_dph=p.sazba_dph, nakupni_cena=p.nakupni_cena,
                                      zamenitelny_dil=p.zamenitelny_dil, poznamka=p.poznamka, aktivni=p.aktivni))
        elif druh == "smazat":
            session.delete(session.get(PolozkaCeniku, op[1]))
        session.flush()
    session.commit()
    for op in plan.operace:
        if op[0] == "sloucit":
            _, zdroj_id, cil_id, prepsat_ceny, smazat_zdroj = op
            zdroj, cil = session.get(PolozkaCeniku, zdroj_id), session.get(PolozkaCeniku, cil_id)
            if prepsat_ceny:
                cil.nakupni_cena, cil.sazba_dph = zdroj.nakupni_cena, zdroj.sazba_dph
            if not cil.aktivni:
                cil.aktivni = True
            session.add(cil)
            session.flush()
            slouceni.sluc(session, cil_id, [zdroj_id], cena=zdroj.cena if prepsat_ceny else None)
            if smazat_zdroj:
                session.delete(session.get(PolozkaCeniku, zdroj_id))
                session.commit()
    for op in plan.operace:   # úpravy až po sloučení (sloučení cílovou kartu aktivuje)
        if op[0] == "uprav_po":
            p = session.get(PolozkaCeniku, op[1])
            for pole, hodnota in op[2].items():
                setattr(p, pole, hodnota)
            session.add(p)
    session.commit()
    return len(plan.provede_se)


# ---------------------------------------------------------------- smazání celého skladu (#140)

def planuj_smazani_skladu(session: Session, katalog_id: int, cil_katalog, vyradit_presunute: bool) -> Plan:
    """Nepoužité díly skladu se smažou, použité přesunou do `cil_katalog` (stejný kód tam = sloučí se),
    volitelně se přesunuté vyřadí. Sklad se smaže až po provedení plánu (`smaz_sklad`)."""
    sklad = katalogy.ziskej(session, katalog_id)
    if sklad.vychozi:
        raise ChybaValidace("Výchozí sklad (s pracemi) nejde smazat.")
    karty = list(session.exec(select(PolozkaCeniku).where(PolozkaCeniku.katalog_id == katalog_id)))
    pouzite = sprava.pouziti(session)
    plan = Plan("smazat_sklad", f"smazat sklad {sklad.nazev}")
    pouzitych = [p for p in karty if pouzite.get(p.id, (0, None))[0]]
    cil = None
    if pouzitych:
        cil = _cilovy_katalog(session, cil_katalog)
        if cil.id == sklad.id:
            raise ChybaValidace("Cílový sklad musí být jiný než mazaný.")
        plan.popis += f"; použité díly přesunout do {cil.nazev}" + (" a vyřadit" if vyradit_presunute else "")
    obsazene = _obsazene_kody(session)
    nove: set = set()
    for p in karty:
        pocet = pouzite.get(p.id, (0, None))[0]
        if not pocet:
            plan.zmeny.append(_zmena(p, co="Smazat", pred=f"{_penize(p.cena)}", po="nepoužitý – smaže se"))
            plan.operace.append(("smazat", p.id))
            continue
        z = _zmena(p, co="Přesun", pred=f"použito {pocet}×", po=cil.nazev)
        if p.kod and ((cil.id, p.kod) in obsazene or (cil.id, p.kod) in nove):
            jina = obsazene.get((cil.id, p.kod))
            if jina is None:   # stejný kód dvakrát v mazaném skladu nebýt nemůže (unikátní index)
                z.preskoceno = "kolize kódu"
            else:
                z.co, z.po = "Sloučit do", f"{p.kod} v {cil.nazev}"
                plan.operace.append(("sloucit", p.id, jina, False, True))
                if vyradit_presunute:
                    z.po += " (vyřadit)"
                    plan.operace.append(("uprav_po", jina, {"aktivni": False}))
        else:
            if p.kod:
                nove.add((cil.id, p.kod))
            zmeny = {"katalog_id": cil.id}
            if vyradit_presunute:
                zmeny["aktivni"] = False
                z.po += " (vyřadit)"
            plan.operace.append(("uprav", p.id, zmeny))
        plan.zmeny.append(z)
    return plan


def smaz_sklad(session: Session, katalog_id: int) -> None:
    katalogy.smaz(session, katalog_id)
