"""ORV company matching, atomic auto-create and manual assignment contract."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from types import SimpleNamespace as NS

import pytest

import app as appmod
import config
import db
from repositories import firma_ceny_repo, firmy_repo, typy_repo, ukony_repo
from services import orv_scan_service as scan
from services.firma_match import match_firma
from services.ingest_service import pridat_ukon

VIN = "TMBEK6NW7M3158470"
PHOTO = {"typ": "orv", "rz": "8T25415", "vin": VIN, "orv_cislo": "UBE037263",
         "provozovatel": "BSAuto, s.r.o."}


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.messages = self

    def with_options(self, **_kwargs):
        return self

    def create(self, **_kwargs):
        return NS(content=[NS(type="tool_use", name="zapsat_dokument", input=self.data)],
                  usage=NS(input_tokens=1, output_tokens=1), stop_reason="tool_use")


@pytest.mark.parametrize("printed,firm_name,shortcut,confidence", [
    ("BSAuto", "BSAuto", "BS", "presna"),
    ("Skoda Auto s.r.o.", "Škoda Auto, s.r.o.", "SA", "presna"),
    ("Město spol. a.s.", "Mesto a.s.", "MA", "presna"),
    ("PRAHA MOTORS - oddělení", "Praha Motors", "PM", "obsahuje"),
])
def test_firma_match_normalizes_exact_suffix_and_contained_names(conn, printed, firm_name, shortcut, confidence):
    fid = firmy_repo.create(conn, nazev=firm_name, zkratka=shortcut)
    assert match_firma(conn, printed) == {
        "firma_id": fid, "firma": firm_name,
        "jistota": confidence,
    }


def test_firma_match_ignores_ambiguous_short_and_inactive(conn):
    firmy_repo.create(conn, nazev="Auto Sever servis", zkratka="AS1")
    firmy_repo.create(conn, nazev="Auto Sever bazar", zkratka="AS2")
    assert match_firma(conn, "AUTO SEVER") is None
    assert match_firma(conn, "AUTO") is None
    inactive = firmy_repo.create(conn, nazev="Mimo provoz s.r.o.", zkratka="MP", aktivni=0)
    assert match_firma(conn, "Mimo provoz") is None
    assert firmy_repo.get(conn, inactive)["aktivni"] == 0


def _ready(conn, *, override=1300):
    fid = firmy_repo.create(conn, nazev="BSAuto", zkratka="BS")
    typy_repo.upsert(conn, "ORV", 900, 1)
    firma_ceny_repo.set_price(conn, fid, "ORV", override)
    return fid


def test_scan_never_creates_an_ukon_and_only_preselects_the_firm(conn):
    # David 2026-10-23: no automatic "ORV · 1 000 Kč · Z TECHNIČÁKU" rows.
    fid = _ready(conn)
    result = scan.zpracuj(conn, b"photo", "image/jpeg", client=FakeClient(PHOTO), zpracoval="David")
    assert result["stav"] == "bez_firmy" and result["navrh_firma_id"] == fid
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 0


def test_no_confident_firm_returns_bez_firmy_without_insert_and_no_identifier_stays_uncreated(conn):
    _ready(conn)
    before = conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0]
    unmatched = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(
        {**PHOTO, "provozovatel": "Neznámá společnost"}))
    assert unmatched["stav"] == "bez_firmy" and unmatched["navrh_firma_id"] is None
    assert {k: unmatched[k] for k in ("rz", "vin", "orv_cislo", "provozovatel", "vin_zdroj")} == {
        "rz": PHOTO["rz"], "vin": VIN, "orv_cislo": PHOTO["orv_cislo"],
        "provozovatel": "Neznámá společnost", "vin_zdroj": "foto"}
    no_identity = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(
        {**PHOTO, "rz": None, "vin": None}), lookup=lambda _: {"success": False})
    assert no_identity["stav"] == "nenalezeno"
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == before


@pytest.mark.parametrize("poznamka", [None, "ACC"])
def test_user_chosen_firm_and_type_create_with_price_and_note(conn, poznamka):
    fid = _ready(conn)
    data = {**PHOTO, "vin_zdroj": "foto"}
    result = scan.zalozit_pro_firmu(conn, data, firma_id=fid, typ_kod="ORV",
                                    zpracoval="David", poznamka=poznamka)
    assert result["stav"] == "zalozeno"
    u = ukony_repo.get(conn, result["ukon"]["id"])
    assert (u["firma_id"], u["typ_kod"], u["celkem"], u["datum"]) == (
        fid, "ORV", 1300, date.today().isoformat())
    assert (u["rz"], u["vin"], u["orv"]) == (PHOTO["rz"], VIN, PHOTO["orv_cislo"])
    assert (u["poznamka"], u["zpracoval"], u["zdroj"]) == (poznamka, "David", "orv_sken")
    assert result["ukon"]["poznamka"] == poznamka
    assert result["ukon"]["stav_platby"] == "nezaplaceno"


def _old_ukon(conn, fid, *, days=3, poznamka=None):
    """A complete úkon of the same car older than MATCH_WINDOW_DAYS."""
    datum = (date.today() - timedelta(days=days)).isoformat()
    return pridat_ukon(conn, firma_id=fid, datum=datum, typ_kod="ORV", celkem=900,
                       rz=PHOTO["rz"], vin=VIN, orv=PHOTO["orv_cislo"], poznamka=poznamka)


def test_existing_car_outside_window_blocks_creation_without_confirmation(conn):
    # 2026-11-05: #1537 (27.10., PŘEVOD from žádosti) vs. #1573 (3.11., NOVÉ
    # from the scan) — the scan treated the older úkon as "another sale".
    fid = _ready(conn)
    old = _old_ukon(conn, fid, poznamka="původní")
    data = {**PHOTO, "vin_zdroj": "foto"}
    blocked = scan.zalozit_pro_firmu(conn, data, firma_id=fid, typ_kod="ORV")
    assert blocked["stav"] == "jiz_v_evidence"
    assert blocked["vyzaduje_potvrzeni"] is True
    assert [u["id"] for u in blocked["existujici"]] == [old]
    assert blocked["existujici"][0]["poznamka"] == "původní"
    assert blocked["ukon"]["id"] == old and blocked["ukon"]["datum"] == (
        date.today() - timedelta(days=3)).isoformat()
    assert f"#{old}" in blocked["zprava"] and "Přesto založit nový úkon" in blocked["zprava"]
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1
    # Repeating the unconfirmed assignment still inserts nothing.
    again = scan.zalozit_pro_firmu(conn, data, firma_id=fid, typ_kod="ORV")
    assert again["stav"] == "jiz_v_evidence"
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1


def test_confirmed_new_ukon_keeps_note_and_repeated_confirm_dedupes(conn):
    fid = _ready(conn)
    old = _old_ukon(conn, fid)
    data = {**PHOTO, "vin_zdroj": "foto"}
    result = scan.zalozit_pro_firmu(conn, data, firma_id=fid, typ_kod="ORV",
                                    zpracoval="David", poznamka="ACC", potvrdit_novy=True)
    assert result["stav"] == "zalozeno"
    new_id = result["ukon"]["id"]
    assert new_id != old and result["ukon"]["poznamka"] == "ACC"
    assert ukony_repo.get(conn, new_id)["poznamka"] == "ACC"
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 2
    # Today's new úkon is inside the match window → a repeated confirm fills it
    # instead of creating a third úkon.
    again = scan.zalozit_pro_firmu(conn, data, firma_id=fid, typ_kod="ORV",
                                   poznamka="ACC", potvrdit_novy=True)
    assert again["stav"] == "uz_doplneno" and again["ukon"]["id"] == new_id
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 2


def test_created_ukon_carries_firm_identity_for_the_card(conn):
    # The result card shows the Úkony-style firm dot + zkratka.
    fid = _ready(conn)
    result = scan.zalozit_pro_firmu(conn, {**PHOTO, "vin_zdroj": "foto"}, firma_id=fid, typ_kod="ORV")
    assert result["stav"] == "zalozeno"
    assert result["ukon"]["firma_id"] == fid
    assert result["ukon"]["firma_zkratka"] == "BS"


def test_same_vehicle_is_created_once_for_repeated_and_concurrent_assignments(conn):
    fid = _ready(conn)
    data = {**PHOTO, "vin_zdroj": "foto"}
    first = scan.zalozit_pro_firmu(conn, data, firma_id=fid, typ_kod="ORV")
    second = scan.zalozit_pro_firmu(conn, data, firma_id=fid, typ_kod="ORV")
    assert [first["stav"], second["stav"]] == ["zalozeno", "uz_doplneno"]
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1

    conn.execute("DELETE FROM ukony")
    conn.commit()
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    def process(_):
        c = db.connect(path)
        try:
            return scan.zalozit_pro_firmu(c, data, firma_id=fid, typ_kod="ORV")["stav"]
        finally:
            c.close()
    with ThreadPoolExecutor(max_workers=3) as pool:
        states = list(pool.map(process, range(3)))
    assert states.count("zalozeno") == 1
    assert states.count("uz_doplneno") == 2
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "orv.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    app = appmod.create_app()
    app.testing = True
    with app.test_client() as test_client:
        with app.app_context():
            conn = db.get_db()
            _ready(conn)
        yield test_client


def _assigned(vin=VIN, *, firma=1, typ="ORV"):
    return {"rz": "8T25415", "vin": vin, "orv_cislo": "UBE037263",
            "firma_id": firma, "typ_kod": typ, "provozovatel": "BSAuto", "vin_zdroj": "foto"}


def test_zalozit_endpoint_valid_dedupes_invalid_firma_and_type(client):
    response = client.post("/ukony/orv-sken/zalozit", json={"auta": [_assigned(), _assigned()],
                                                              "zpracoval": "David"})
    assert response.status_code == 200
    assert [r["stav"] for r in response.json["results"]] == ["zalozeno", "uz_doplneno"]
    with client.application.app_context():
        conn = db.get_db()
        assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1
        assert conn.execute("SELECT zpracoval FROM ukony").fetchone()[0] == "David"
    assert client.post("/ukony/orv-sken/zalozit", json={"auta": [_assigned(firma=999)]}).status_code == 400
    assert client.post("/ukony/orv-sken/zalozit", json={"auta": [_assigned(typ="MISSING")]}).status_code == 400


def test_zalozit_endpoint_requires_session_when_login_is_enabled(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "secret")
    response = client.post("/ukony/orv-sken/zalozit", json={"auta": [_assigned()]})
    assert response.status_code == 302


@pytest.mark.parametrize("item,error", [
    ({"poznamka": "A" * 121}, "Poznámka"),
    ({"poznamka": 5}, "Neplatná poznámka"),
    ({"poznamka": True}, "Neplatná poznámka"),
    ({"poznamka": "=cmd|' /C calc'!A0"}, "Poznámka"),
    ({"poznamka": {"text": "ACC"}}, "Neplatná poznámka"),
    ({"potvrdit_novy": "true"}, "potvrzení"),
    ({"potvrdit_novy": 1}, "potvrzení"),
    ({"potvrdit_novy": []}, "potvrzení"),
])
def test_zalozit_endpoint_validates_poznamka_and_confirmation(client, item, error):
    response = client.post("/ukony/orv-sken/zalozit", json={"auta": [{**_assigned(), **item}]})
    assert response.status_code == 400 and error in response.json["error"]
    with client.application.app_context():
        assert db.get_db().execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 0


def test_zalozit_endpoint_saves_normalized_note(client):
    note = "  ACC   sada  " + "x" * 108  # after collapsing still ≤120 chars
    response = client.post("/ukony/orv-sken/zalozit",
                           json={"auta": [{**_assigned(), "poznamka": note}], "zpracoval": "David"})
    assert response.status_code == 200
    result = response.json["results"][0]
    assert result["stav"] == "zalozeno"
    assert result["ukon"]["poznamka"] == ("ACC sada " + "x" * 108).strip()
    with client.application.app_context():
        u = ukony_repo.get(db.get_db(), result["ukon"]["id"])
        assert u["poznamka"] == "ACC sada " + "x" * 108
    # Blank and exactly 120 chars are both accepted.
    blank = client.post("/ukony/orv-sken/zalozit", json={"auta": [{
        **_assigned(vin="TMBBLANK000000001"), "poznamka": "   "}]})
    assert blank.status_code == 200 and blank.json["results"][0]["ukon"]["poznamka"] is None
    exact = client.post("/ukony/orv-sken/zalozit", json={"auta": [{
        **_assigned(vin="TMBOTHER000000001"), "poznamka": "A" * 120, "potvrdit_novy": True}]})
    assert exact.status_code == 200 and exact.json["results"][0]["ukon"]["poznamka"] == "A" * 120


def test_zalozit_endpoint_refuses_duplicate_until_confirmed(client):
    with client.application.app_context():
        conn = db.get_db()
        fid = firmy_repo.list_all(conn, only_active=True)[0]["id"]
        old = _old_ukon(conn, fid)
    car = {**_assigned(firma=fid), "poznamka": "ACC"}
    blocked = client.post("/ukony/orv-sken/zalozit", json={"auta": [car]})
    assert blocked.status_code == 200
    result = blocked.json["results"][0]
    assert result["stav"] == "jiz_v_evidence"
    assert result["ukon"]["id"] == old and result["existujici"][0]["id"] == old
    assert result["vyzaduje_potvrzeni"] is True
    with client.application.app_context():
        conn = db.get_db()
        assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1
    confirmed = client.post("/ukony/orv-sken/zalozit",
                            json={"auta": [{**car, "potvrdit_novy": True}]})
    assert confirmed.status_code == 200
    created = confirmed.json["results"][0]
    assert created["stav"] == "zalozeno" and created["ukon"]["id"] != old
    with client.application.app_context():
        conn = db.get_db()
        assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 2
        assert ukony_repo.get(conn, created["ukon"]["id"])["poznamka"] == "ACC"
