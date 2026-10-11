"""ORV company matching, atomic auto-create and manual assignment contract."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from types import SimpleNamespace as NS

import pytest

import app as appmod
import config
import db
from repositories import firma_ceny_repo, firmy_repo, typy_repo, ukony_repo
from services import orv_scan_service as scan
from services.firma_match import match_firma

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


def test_auto_create_uses_match_type_price_today_and_photo_fields(conn):
    fid = _ready(conn)
    result = scan.zpracuj(conn, b"photo", "image/jpeg", client=FakeClient(PHOTO), zpracoval="David")
    assert result["stav"] == "zalozeno"
    u = ukony_repo.get(conn, result["ukon"]["id"])
    assert result["ukon"] == {"id": u["id"], "datum": date.today().isoformat(),
                              "firma": "BSAuto", "typ": "ORV", "celkem": 1300.0}
    assert (u["firma_id"], u["typ_kod"], u["celkem"], u["datum"]) == (
        fid, "ORV", 1300, date.today().isoformat())
    assert (u["rz"], u["vin"], u["orv"]) == (PHOTO["rz"], VIN, PHOTO["orv_cislo"])
    assert (u["poznamka"], u["zpracoval"], u["zdroj"]) == ("Z TECHNIČÁKU", "David", "orv_sken")


def test_no_confident_firm_returns_bez_firmy_without_insert_and_no_identifier_stays_uncreated(conn):
    _ready(conn)
    before = conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0]
    unmatched = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(
        {**PHOTO, "provozovatel": "Neznámá společnost"}))
    assert unmatched["stav"] == "bez_firmy"
    assert {k: unmatched[k] for k in ("rz", "vin", "orv_cislo", "provozovatel", "vin_zdroj")} == {
        "rz": PHOTO["rz"], "vin": VIN, "orv_cislo": PHOTO["orv_cislo"],
        "provozovatel": "Neznámá společnost", "vin_zdroj": "foto"}
    no_identity = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(
        {**PHOTO, "rz": None, "vin": None}), lookup=lambda _: {"success": False})
    assert no_identity["stav"] == "nenalezeno"
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == before


def test_same_vehicle_is_created_once_for_repeated_and_concurrent_photos(conn):
    _ready(conn)
    first = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(PHOTO))
    second = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(PHOTO))
    assert [first["stav"], second["stav"]] == ["zalozeno", "uz_doplneno"]
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1

    conn.execute("DELETE FROM ukony")
    conn.commit()
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    def process(_):
        c = db.connect(path)
        try:
            return scan.zpracuj(c, b"p", "image/jpeg", client=FakeClient(PHOTO))["stav"]
        finally:
            c.close()
    with ThreadPoolExecutor(max_workers=3) as pool:
        states = list(pool.map(process, range(3)))
    assert states.count("zalozeno") == 1
    assert states.count("uz_doplneno") == 2
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1


def test_missing_orv_type_uses_first_active_type_and_marks_fallback(conn):
    _ready(conn)
    conn.execute("DELETE FROM typy_ukonu WHERE kod='ORV'")
    conn.commit()
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(PHOTO))
    assert result["stav"] == "zalozeno"
    assert result["ukon"]["typ"] == "KOLA" and result["typ_nahrada"] is True
    assert "KOLA" in result["zprava"]


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
