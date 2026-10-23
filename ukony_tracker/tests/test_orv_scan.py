"""Offline scan contract, atomic fill matrix, upload and session boundaries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta
from io import BytesIO
from types import SimpleNamespace as NS

import pytest

import app as appmod
import config
import db
from repositories import firmy_repo, ukony_repo
from services import orv_images, orv_scan_service as scan
from services.ingest_service import pridat_ukon

VIN = "TMBEK6NW7M3158470"
RECENT = date.today().isoformat()   # inside the match window
DATA = {"typ": "orv", "rz": "5AB1234", "vin": VIN, "orv_cislo": "UBE037263",
        "provozovatel": "BSAuto s.r.o."}


class FakeClient:
    def __init__(self, data=None, error=None):
        self.data = DATA.copy() if data is None else data
        self.error = error
        self.messages = self
        self.calls = []

    def with_options(self, **options):
        assert options == {"timeout": 45, "max_retries": 0}
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return NS(content=[NS(type="thinking", thinking="private"),
                           NS(type="tool_use", name="zapsat_dokument", input=self.data)],
                  usage=NS(input_tokens=100, output_tokens=25), stop_reason="tool_use")


def test_extract_normalizes_and_uses_strict_tool():
    fake = FakeClient({"typ": "orv", "rz": " 5ab-12 34 ", "vin": "tmb-ek6nw7m3158470",
                       "orv_cislo": " ube\t037-263 ", "provozovatel": " BSAuto   s.r.o. "})
    assert scan.extract(b"photo", "image/jpeg", client=fake) == DATA
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["max_tokens"] == 1024
    assert call["output_config"] == {"effort": "low"}
    assert call["thinking"] == {"type": "disabled"}
    assert not {"temperature", "top_p", "top_k", "tool_choice"} & call.keys()
    assert len(call["tools"]) == 1 and call["tools"][0]["strict"] is True
    schema = call["tools"][0]["input_schema"]
    assert set(schema["required"]) == set(DATA)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["orv_cislo"]["type"] == ["string", "null"]
    assert schema["properties"]["provozovatel"]["type"] == ["string", "null"]
    assert call["messages"][0]["content"][0]["source"] == {
        "type": "base64", "media_type": "image/jpeg", "data": "cGhvdG8="}
    assert scan.tokens.get() == 125


@pytest.fixture(autouse=True)
def no_registry_network(monkeypatch):
    monkeypatch.setattr(scan.orv_service, "lookup_vin", lambda _orv: {"success": False, "error": "offline"})


@pytest.mark.parametrize("field,value", [
    ("rz", "1234"), ("rz", "123456789"), ("rz", "ABC!123"), ("rz", 12345),
    ("vin", "AB12"), ("vin", "A" * 18), ("orv_cislo", "UB0037263"),
    ("orv_cislo", "UB037263"), ("orv_cislo", "UBE03726O"), ("orv_cislo", "UBE０３７２６３"),
])
def test_invalid_fields_are_null_never_repaired(field, value):
    result = scan.extract(b"photo", "image/png", client=FakeClient({**DATA, field: value}))
    assert result[field] is None


def test_no_legible_fields_and_missing_tool():
    result = scan.extract(b"p", "image/jpeg", client=FakeClient(dict.fromkeys(DATA, None) | {"typ": "orv"}))
    assert result == {"typ": "necitelne", "rz": None, "vin": None, "orv_cislo": None,
                      "provozovatel": None}
    fake = FakeClient()
    fake.create = lambda **kw: NS(content=[NS(type="thinking")])
    with pytest.raises(scan.ScanUnavailable):
        scan.extract(b"p", "image/jpeg", client=fake)


@pytest.fixture
def make(conn):
    fid = firmy_repo.create(conn, nazev="BSAuto", zkratka="BS")
    def create(**fields):
        return pridat_ukon(conn, **({"firma_id": fid, "datum": RECENT, "typ_kod": "ZÁPIS",
                                   "celkem": 1300, "vin": VIN} | fields))
    return create


@pytest.mark.parametrize("fields,expected,changes", [
    ({}, "doplneno", ["rz", "orv"]),
    ({"orv": "UBE037263"}, "doplneno", ["rz"]),
    ({"rz": "5AB1234"}, "doplneno", ["orv"]),
    ({"rz": " 5ab-1234 ", "orv": " ube 037263 "}, "uz_doplneno", []),
    ({"rz": "9ZZ9999"}, "doplneno", ["rz", "orv"]),
    ({"orv": "ABC123456"}, "doplneno", ["rz", "orv"]),
    ({"rz": "9ZZ9999", "orv": "ABC123456"}, "doplneno", ["rz", "orv"]),
])
def test_fill_matrix(conn, make, fields, expected, changes):
    uid = make(**fields)
    before = dict(ukony_repo.get(conn, uid))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    after = dict(ukony_repo.get(conn, uid))
    assert result["stav"] == expected and result["doplneno"] == changes
    assert result["ukon"] == {"id": uid, "datum": RECENT, "firma": "BSAuto",
                              "typ": "ZÁPIS", "celkem": 1300.0}
    assert all(before[k] == after[k] for k in before if k not in changes + ["updated_at"])
    overwritten = [k for k, v in fields.items() if v.strip().upper().replace(" ", "").replace("-", "")
                   != (DATA["orv_cislo"] if k == "orv" else DATA[k])]
    assert result.get("prepsano", []) == overwritten
    for key in overwritten:
        assert result["zmeny"][key]["pred"] == fields[key]
    for key in changes:
        assert after[key] == DATA["orv_cislo" if key == "orv" else key]
    assert not conn.in_transaction


def test_vin_preference_creates_even_if_rz_belongs_to_another_vin(conn, make):
    make(vin="OTHER", rz=DATA["rz"])
    before = conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0]
    assert scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())["stav"] == "bez_firmy"
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == before
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient({**DATA, "vin": None}))
    assert result["stav"] == "doplneno" and result["doplneno"] == ["orv"]


def test_front_photo_looks_up_vin_before_transaction_and_fills(conn, make, monkeypatch):
    uid = make()
    photo_data = {**DATA, "vin": None}
    events = []
    original_transaction = scan.transaction

    @contextmanager
    def transaction_spy(connection):
        events.append("transaction")
        with original_transaction(connection):
            yield

    def lookup(orv):
        events.append("lookup")
        assert orv == DATA["orv_cislo"]
        return {"success": True, "vin": " tmb-ek6nw7m3158470 "}

    monkeypatch.setattr(scan, "transaction", transaction_spy)
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo_data), lookup=lookup)
    assert events == ["lookup", "transaction"]
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    assert result["vin"] == VIN and result["vin_zdroj"] == "registr"
    assert result["doplneno"] == ["rz", "orv"]
    assert ukony_repo.get(conn, uid)["rz"] == DATA["rz"]
    assert ukony_repo.get(conn, uid)["orv"] == DATA["orv_cislo"]


def test_lookup_failure_falls_back_to_rz(conn, make):
    uid = make(vin="OTHER", rz=DATA["rz"])
    photo_data = {**DATA, "vin": None}
    calls = []
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo_data),
                          lookup=lambda orv: calls.append(orv) or {"success": False, "error": "offline"})
    assert calls == [DATA["orv_cislo"]]
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    assert result["vin"] is None and result["vin_zdroj"] is None
    assert result["doplneno"] == ["orv"]


def test_invalid_registry_vin_is_ignored_and_explained(conn):
    photo_data = {**DATA, "vin": None}
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo_data),
                          lookup=lambda _orv: {"success": True, "vin": "not a vin!"})
    assert result["stav"] == "bez_firmy" and result["vin"] is None
    assert result["vin_zdroj"] is None
    assert result["rz"] == DATA["rz"] and result["orv_cislo"] == DATA["orv_cislo"]


def test_registry_no_match_names_vin_source(conn):
    photo_data = {**DATA, "vin": None}
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo_data),
                          lookup=lambda _orv: {"success": True, "vin": VIN})
    assert result["stav"] == "bez_firmy" and result["vin"] == VIN
    assert result["vin_zdroj"] == "registr"
    assert result["vin"] == VIN and result["vin_zdroj"] == "registr"
    assert result["rz"] == DATA["rz"] and result["orv_cislo"] == DATA["orv_cislo"]


def test_lookup_skipped_when_photo_has_vin_or_no_orv(conn, make):
    make()
    calls = []
    lookup = lambda orv: calls.append(orv) or {"success": False}
    photo_with_vin = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(), lookup=lookup)
    assert photo_with_vin["vin_zdroj"] == "foto" and calls == []
    no_orv = {**DATA, "vin": None, "orv_cislo": None}
    scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(no_orv), lookup=lookup)
    assert calls == []


@pytest.mark.parametrize("other_fields,expected", [({}, "vice_shod"),
    ({"rz": DATA["rz"], "orv": DATA["orv_cislo"]}, "doplneno")])
def test_multiple_matches(conn, make, other_fields, expected):
    target = make()
    other = make(**other_fields)
    before = dict(ukony_repo.get(conn, other))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == expected
    assert dict(ukony_repo.get(conn, other)) == before
    if expected == "doplneno":
        assert result["ukon"]["id"] == target
    else:
        assert ukony_repo.get(conn, target)["rz"] is None


def test_overwrite_picks_newest_when_no_row_awaits(conn, make):
    old = make(datum=(date.today() - timedelta(days=1)).isoformat(), rz="1AA1111", orv="AAA111111")
    new = make(datum=RECENT, rz="1AA1111", orv="AAA111111")
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == new
    assert result["prepsano"] == ["rz", "orv"]
    assert ukony_repo.get(conn, new)["orv"] == DATA["orv_cislo"]
    assert ukony_repo.get(conn, old)["orv"] == "AAA111111"


@pytest.mark.parametrize("filled", [True, False])
def test_car_back_after_window_is_a_new_ukon_not_the_old_one(conn, make, filled):
    # 2026-10-21: EL375AT from August (JE & NE) got its ORV overwritten by a
    # new techničák — the car had been sold and bought back. Old úkony stay as they are.
    window = scan.MATCH_WINDOW_DAYS if filled else scan.AWAITING_WINDOW_DAYS
    old_date = (date.today() - timedelta(days=window + 1)).isoformat()
    fields = {"rz": "1AA1111", "orv": "UBC425944"} if filled else {}
    old = make(datum=old_date, **fields)
    before = dict(ukony_repo.get(conn, old))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert dict(ukony_repo.get(conn, old)) == before
    assert result["stav"] in ("zalozeno", "bez_firmy")
    assert result["predchozi"]["id"] == old and result["predchozi"]["datum"] == old_date


def test_window_edge_still_matches(conn, make):
    edge = (date.today() - timedelta(days=scan.MATCH_WINDOW_DAYS)).isoformat()
    uid = make(datum=edge)
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid


@pytest.mark.parametrize("prevod,operator,same", [
    ("AUTO CARDION s. r. o. → XYZ s.r.o.", "XYZ, s.r.o.", True),          # scanning that sale
    ("AUTO CARDION s. r. o. → XYZ s.r.o.", "Auto Cardion s.r.o.", False),  # bought back = new sale
    ("Ing. Jakub Šebesta → JE & NE, spol. s r.o.", "JE & NE spol. s r. o.", True),
    ("JE & NE, spol. s r.o. → Ing. Jakub Šebesta", "ŠEBESTA JAKUB", True),
    ("JE & NE, spol. s r.o. → Ing. Jakub Šebesta", "ŠEBESTA PETR", False),
    ("AUTO CARDION s. r. o. → XYZ s.r.o.", None, True),                   # unreadable → date only
    (None, "XYZ s.r.o.", True),                                            # no transfer line → date only
])
def test_owner_on_orv_must_be_the_new_owner_of_that_sale(conn, make, prevod, operator, same):
    uid = make(prevod=prevod)
    before = dict(ukony_repo.get(conn, uid))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient({**DATA, "provozovatel": operator}))
    if same:
        assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    else:
        assert dict(ukony_repo.get(conn, uid)) == before
        assert result["stav"] in ("zalozeno", "bez_firmy") and result["predchozi"]["id"] == uid


def test_new_car_waiting_for_its_plate_is_filled_days_later(conn, make):
    # 2026-10-23: NOVÉ úkony from 21.10. with empty RZ/ORV (Cardion) were
    # skipped as "too old" and the scan made duplicate ORV rows instead.
    two_days = (date.today() - timedelta(days=2)).isoformat()
    uid = make(datum=two_days, typ_kod="NOVÉ", prevod="CARDION s.r.o.")
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    assert ukony_repo.get(conn, uid)["rz"] == DATA["rz"]
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1


def test_complete_ukon_from_two_days_ago_is_not_overwritten(conn, make):
    uid = make(datum=(date.today() - timedelta(days=2)).isoformat(), rz="1AA1111", orv="UBC425944")
    before = dict(ukony_repo.get(conn, uid))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "bez_firmy" and result["predchozi"]["id"] == uid
    assert dict(ukony_repo.get(conn, uid)) == before


def test_waiting_ukon_older_than_window_is_left_alone(conn, make):
    old = (date.today() - timedelta(days=scan.AWAITING_WINDOW_DAYS + 1)).isoformat()
    uid = make(datum=old)
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "bez_firmy" and ukony_repo.get(conn, uid)["rz"] is None


def test_api_fill_still_refuses_to_overwrite(conn, make):
    from services.vehicle_fill_service import FillError, doplnit
    uid = make(orv="ABC123456")
    with pytest.raises(FillError) as exc:
        doplnit(conn, uid, {"orv": "UBE037263"})
    assert exc.value.status == 409
    assert ukony_repo.get(conn, uid)["orv"] == "ABC123456"


def test_ambiguity_beyond_api_display_limit(conn, make):
    make()
    for _ in range(20):
        make(rz=DATA["rz"], orv=DATA["orv_cislo"])
    make()
    assert scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())["stav"] == "vice_shod"


@pytest.mark.parametrize("data,state", [
    ({**DATA, "typ": "jine"}, "necitelne"),
    ({**DATA, "rz": None, "orv_cislo": None}, "necitelne"),
    ({**DATA, "rz": None, "vin": None}, "nenalezeno"),
])
def test_unusable_photo_changes_nothing(conn, make, data, state):
    uid = make()
    before = dict(ukony_repo.get(conn, uid))
    assert scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(data))["stav"] == state
    assert dict(ukony_repo.get(conn, uid)) == before


def test_provider_failure_and_rollback(conn, make, monkeypatch):
    uid = make()
    before = dict(ukony_repo.get(conn, uid))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(error=TimeoutError("secret")))
    assert result["stav"] == "chyba" and "secret" not in result["zprava"]
    update = ukony_repo.update
    def fail(*args, **kwargs):
        update(*args, **kwargs)
        raise RuntimeError("after write")
    monkeypatch.setattr(ukony_repo, "update", fail)
    assert scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())["stav"] == "chyba"
    assert dict(ukony_repo.get(conn, uid)) == before


def test_concurrent_photos_fill_once(conn, make):
    make()
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    def process(_):
        c = db.connect(path)
        try:
            return scan.zpracuj(c, b"p", "image/jpeg", client=FakeClient())["stav"]
        finally:
            c.close()
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sorted(pool.map(process, range(3))) == ["doplneno", "uz_doplneno", "uz_doplneno"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "routes.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        yield c


@pytest.fixture
def vision(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-never-sent")
    original = scan.extract
    fake = FakeClient()
    monkeypatch.setattr(scan, "extract", lambda data, mime, **kw: original(data, mime, client=fake))
    return fake


def photo(fmt="PNG"):
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (24, 16), "green").save(buf, format=fmt)
    return buf.getvalue()


def post(client, data=None, mime="image/jpeg"):
    return client.post("/ukony/orv-sken", data={"foto": (BytesIO(photo() if data is None else data), "foto", mime)})


def test_route_login_and_key(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "test-password")
    assert client.get("/ukony/orv-sken").status_code == 302
    assert post(client).status_code == 302
    with client.session_transaction() as s:
        s["authed"] = True
    r = post(client)
    assert r.status_code == 503 and r.json == {"error": "Čtení fotek není nastavené."}


def test_fragment_button_and_shared_thinking(client):
    r = client.get("/ukony/orv-sken")
    assert r.status_code == 200 and 'id="orv-video"' in r.text
    assert 'capture="environment"' in r.text and 'id="orv-results"' in r.text
    page = client.get("/ukony/vse").text
    assert 'data-orv-sken' in page and 'Techničák' in page
    assert 'Doplnit RZ a ORV z techničáku' in page and 'js/thinking.js' in page
    assert 'js/thinking.js' in client.get('/zeptej').text


# Big payloads are built lazily: a multi-MB bytes literal as a parametrize value
# ends up in the test id and overflows Windows' 32 KB environment-variable limit.
@pytest.mark.parametrize("make,expected", [
    pytest.param(lambda: b"not an image", 400, id="not-an-image"),
    pytest.param(lambda: b"GIF89a", 400, id="gif"),
    pytest.param(lambda: b"\xff\xd8\xffbroken", 400, id="broken-jpeg"),
    pytest.param(lambda: b"x" * (8 * 1024 * 1024 + 1), 413, id="just-over-8mb"),
    pytest.param(lambda: b"x" * (9 * 1024 * 1024), 413, id="9mb")])
def test_route_invalid_upload(client, vision, make, expected):
    r = post(client, make())
    assert r.status_code == expected and r.is_json and "error" in r.json
    assert not vision.calls


def test_missing_multiple_photos_and_memory_stream(client, vision):
    assert client.post('/ukony/orv-sken').status_code == 400
    r = client.post('/ukony/orv-sken', data={'foto': [(BytesIO(photo()), 'a'), (BytesIO(photo()), 'b')]})
    assert r.status_code == 400
    with client.application.test_request_context('/ukony/orv-sken', method='POST',
            data={'foto': (BytesIO(photo() + b' ' * 600000), 'large.png')}):
        from flask import request
        assert isinstance(request.files['foto'].stream, BytesIO)


def test_happy_json_sniffs_bytes_and_logs(client, vision, monkeypatch):
    from routes import orv_scan
    logs = []
    monkeypatch.setattr(orv_scan.logger, "info", lambda *args: logs.append(args))
    with client.application.app_context():
        c = db.get_db()
        fid = firmy_repo.create(c, nazev="BSAuto", zkratka="BS")
        uid = pridat_ukon(c, firma_id=fid, datum=RECENT, typ_kod="ZÁPIS", celkem=1300, vin=VIN)
    result = post(client, mime="application/octet-stream")
    assert result.status_code == 200 and result.json["stav"] == "doplneno"
    assert result.json["ukon"]["id"] == uid and result.json["doplneno"] == ["rz", "orv"]
    assert len(logs) == 1 and logs[0][1:3] == ("doplneno", uid) and logs[0][-1] == 125


def test_rate_limit_session_and_window(client, vision, monkeypatch):
    from routes import orv_scan
    monkeypatch.setattr(orv_scan.time, "time", lambda: 2000)
    client.get('/ukony/orv-sken')
    with client.session_transaction() as s:
        sid = s['orvsken_sid']
    with client.application.app_context():
        c = db.get_db()
        c.executemany('INSERT INTO orv_scan_rate VALUES (?, ?)', [(sid, 2000)] * 59)
        c.commit()
    assert post(client).status_code == 200
    # Another worker / application instance must see the same DB quota.
    other = appmod.create_app().test_client()
    with other.session_transaction() as s:
        s['orvsken_sid'] = sid
    assert post(other).status_code == 429
    with client.application.test_client() as fresh:
        assert post(fresh).status_code == 200
    monkeypatch.setattr(orv_scan.time, "time", lambda: 2601)
    assert post(client).status_code == 200


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "HEIF"])
def test_supported_images_converted_in_memory(fmt):
    if fmt == "HEIF":
        from pillow_heif import register_heif_opener
        register_heif_opener()
    data, mime = orv_images.prepare(photo(fmt))
    assert mime == "image/jpeg" and data.startswith(b'\xff\xd8\xff')
