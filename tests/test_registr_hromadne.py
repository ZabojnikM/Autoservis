"""#126: hromadné doplnění údajů vozidel z registru – pravidla pro STK, běh s napodobeným registrem, zobrazení."""
from datetime import date, datetime

from fastapi.testclient import TestClient

from app.main import app
from app.models import Vozidlo
from app.services import nastaveni, registr_hromadne
from app.services.registr_vozidel import ChybaRegistru


def _vozidla(session):
    v = [Vozidlo(spz="1HR0001", vin="VIN0000000000001", termin_stk=date(2025, 1, 1), kod_motoru="STARY"),
         Vozidlo(spz="1HR0002", vin="VIN0000000000002", termin_stk=date(2027, 5, 5)),
         Vozidlo(spz="1HR0003", vin="VIN0000000000003", termin_stk=date(2026, 3, 3)),
         Vozidlo(spz="1HR0004", vin="VIN0000000000004", termin_stk=date(2026, 4, 4)),
         Vozidlo(spz="1HR0005", vin=None)]
    session.add_all(v)
    session.commit()
    return v


REGISTR = {
    "VIN0000000000001": {"MotorTyp": "CAYC", "StatusNazev": "PROVOZOVANÉ", "PravidelnaTechnickaProhlidkaDo": "2028-02-01T00:00:00"},
    "VIN0000000000002": {"MotorTyp": "BXE", "StatusNazev": "VYŘAZENÉ Z PROVOZU", "PravidelnaTechnickaProhlidkaDo": "2027-05-05T00:00:00"},
    "VIN0000000000004": {"MotorTyp": "AZQ"},  # bez stavu → STK zůstává
}


def _nacti(api_klic, vin=None):
    if vin == "VIN0000000000003":
        raise ChybaRegistru("Vozidlo v registru nenalezeno.")
    return REGISTR[vin]


def test_pravidla_stk_a_beh(session):
    v1, v2, v3, v4, v5 = _vozidla(session)
    cekani = []
    assert registr_hromadne.spust(session.get_bind(), "KLIC", nacti=_nacti, cekej=cekani.append, na_pozadi=False)
    beh = registr_hromadne.stav()
    assert not beh.bezi and beh.celkem == 4 and beh.hotovo == 4
    assert (beh.aktualizovano, beh.nenalezeno, beh.preskoceno, len(beh.chyby)) == (3, 1, 1, 0)
    assert beh.nenalezene == ["1HR0003"]
    assert len(cekani) == 3  # tempo mezi dotazy, po posledním se nečeká
    session.expire_all()
    v1, v2, v3, v4 = (session.get(Vozidlo, v.id) for v in (v1, v2, v3, v4))
    assert (v1.kod_motoru, v1.stav_registru, v1.termin_stk) == ("CAYC", "PROVOZOVANÉ", date(2028, 2, 1))
    assert (v2.kod_motoru, v2.stav_registru, v2.termin_stk) == ("BXE", "VYŘAZENÉ Z PROVOZU", None)  # mimo provoz
    assert v3.termin_stk == date(2026, 3, 3) and v3.registr_nacteno is None  # nenalezeno → beze změny
    assert (v4.kod_motoru, v4.stav_registru, v4.termin_stk) == ("AZQ", None, date(2026, 4, 4))  # bez stavu
    assert v1.registr_nacteno.date() == date.today()

    # druhý běh téhož dne přeskočí už načtená vozidla (navázání po restartu)
    assert registr_hromadne.spust(session.get_bind(), "KLIC", nacti=_nacti, cekej=lambda s: None, na_pozadi=False)
    assert registr_hromadne.stav().celkem == 1  # jen nenalezené z minula


def test_limit_dotazu_pocka_a_spatny_klic_zastavi(session):
    _vozidla(session)
    pokusy, cekani = [], []

    def nacti(api_klic, vin=None):
        pokusy.append(vin)
        if len(pokusy) == 1:
            raise ChybaRegistru("Registr vozidel: překročen limit dotazů (27 za minutu). Zkuste to za chvíli.")
        raise ChybaRegistru("Registr vozidel odmítl API klíč – zkontrolujte ho v Nastavení.")

    registr_hromadne.spust(session.get_bind(), "KLIC", nacti=nacti, cekej=cekani.append, na_pozadi=False)
    beh = registr_hromadne.stav()
    assert registr_hromadne.PAUZA_PRI_LIMITU in cekani  # po limitu počká a zkusí znovu
    assert len(beh.chyby) == 1 and "API klíč" in beh.chyby[0][1] and beh.zastaveno


def test_zkusebni_beh_s_limitem(session):
    _vozidla(session)
    registr_hromadne.spust(session.get_bind(), "KLIC", limit=2, nacti=lambda k, vin=None: REGISTR.get(vin, {}),
                           cekej=lambda s: None, na_pozadi=False)
    assert registr_hromadne.stav().celkem == 2


def test_zobrazeni_mimo_provoz_a_nastaveni(session):
    v = Vozidlo(spz="1HR0009", vin="VIN0000000000009", stav_registru="VYŘAZENÉ Z PROVOZU",
                registr_nacteno=datetime(2026, 11, 20, 10, 0))
    session.add(v)
    session.commit()
    klient = TestClient(app)
    karta = klient.get(f"/vozidla/{v.id}").text
    assert 'title="Stav v registru vozidel">vyřazené z provozu</span>' in karta and "po termínu" not in karta
    assert "Stav v registru" in karta
    seznam = klient.get("/vozidla", params={"q": "1HR0009"}).text
    assert "vyřazené z provozu" in seznam
    stranka = klient.get("/nastaveni").text
    assert "Doplnit údaje z registru" in stranka and 'id="registr-beh"' in stranka
    # bez API klíče se běh nespustí
    nastaveni.uloz(session, {"api_klic_registr": ""})
    r = klient.post("/nastaveni/registr/doplnit")
    assert "Nejdřív zadejte a uložte API klíč" in r.text
