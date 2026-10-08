import pytest
import app as appmod
import db
import config
from repositories import firmy_repo, ukony_repo
from services.ingest_service import pridat_ukon


VIN = "TMBEK6NW7M3158470"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "INTEGRATION_API_KEY", "")
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            firmy_repo.create(db.get_db(), nazev="Cardion", zkratka="Cardion", ico="04156854")
        yield c


@pytest.fixture
def make_ukon(client):
    def create(**fields):
        with client.application.app_context():
            conn = db.get_db()
            defaults = {
                "firma_id": firmy_repo.get_by_ico(conn, "04156854")["id"],
                "datum": "2026-09-12", "typ_kod": "ZÁPIS", "celkem": 1300,
                "vin": VIN,
            }
            defaults.update(fields)
            return pridat_ukon(conn, **defaults)
    return create


def _get_ukon(client, uid):
    with client.application.app_context():
        return dict(ukony_repo.get(db.get_db(), uid))


def test_hledat_vin_across_firms_newest_first(client, make_ukon):
    with client.application.app_context():
        other_firm = firmy_repo.create(
            db.get_db(), nazev="ALBION s.r.o.", zkratka="ALB", aktivni=0,
        )
    older = make_ukon(datum="2026-09-11")
    newer = make_ukon(firma_id=other_firm)
    newest = make_ukon(vin="  tmb ek6nw7m3158470  ")
    with client.application.app_context():
        ukony_repo.update(db.get_db(), newest, vin="  tmb ek6nw7m3158470  ")
    make_ukon(vin="OTHER", datum="2026-10-08")

    r = client.get("/api/ukony/hledat", query_string={"vin": "  tmb ek6nw7m3158470  "})
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"ukony"}
    assert [u["id"] for u in body["ukony"]] == [newest, newer, older]
    assert body["ukony"][1] == {
        "id": newer, "datum": "2026-09-12", "firma_id": other_firm,
        "firma": "ALBION s.r.o.", "firma_zkratka": "ALB", "typ_kod": "ZÁPIS",
        "rz": None, "vin": VIN, "orv": None, "celkem": 1300,
    }
    assert all(type(u["celkem"]) is int for u in body["ukony"])


def test_hledat_vin_priority_and_rz_fallback(client, make_ukon):
    by_vin = make_ukon(rz="9ZZ9999")
    by_rz = make_ukon(vin="OTHER", rz="  1ab 2345  ")
    with client.application.app_context():
        ukony_repo.update(db.get_db(), by_rz, rz="  1ab 2345  ")
    r = client.get("/api/ukony/hledat", query_string={"vin": VIN, "rz": "1AB2345"})
    assert r.status_code == 200
    assert [u["id"] for u in r.get_json()["ukony"]] == [by_vin]

    r = client.get("/api/ukony/hledat", query_string={"vin": "   ", "rz": "  1ab 2345  "})
    assert r.status_code == 200
    assert [u["id"] for u in r.get_json()["ukony"]] == [by_rz]


@pytest.mark.parametrize("query", [{}, {"vin": "   ", "rz": "   "}])
def test_hledat_requires_vehicle(client, query):
    r = client.get("/api/ukony/hledat", query_string=query)
    assert r.status_code == 400
    assert set(r.get_json()) == {"error"}


@pytest.mark.parametrize("query", [
    {"vin": "UNKNOWN"}, {"rz": "UNKNOWN"}, {"vin": "UNKNOWN", "rz": "1AB2345"},
])
def test_hledat_no_matches_returns_empty_list(client, make_ukon, query):
    make_ukon(rz="1AB2345")
    r = client.get("/api/ukony/hledat", query_string=query)
    assert r.status_code == 200
    assert r.get_json() == {"ukony": []}


def test_hledat_limit_twenty(client, make_ukon):
    ids = [make_ukon() for _ in range(22)]
    r = client.get("/api/ukony/hledat", query_string={"vin": VIN})
    assert r.status_code == 200
    assert [u["id"] for u in r.get_json()["ukony"]] == list(reversed(ids))[:20]


@pytest.mark.parametrize("key", [None, "wrong"])
@pytest.mark.parametrize("method", ["get", "post"])
def test_endpoints_require_api_key(client, make_ukon, monkeypatch, key, method):
    uid = make_ukon()
    before = _get_ukon(client, uid)
    monkeypatch.setattr(config, "INTEGRATION_API_KEY", "test-api-key")
    headers = {} if key is None else {"X-Api-Key": key}
    if method == "get":
        r = client.get("/api/ukony/hledat", query_string={"vin": VIN}, headers=headers)
    else:
        r = client.post(f"/api/ukony/{uid}/doplnit", json={"rz": "1AB2345"}, headers=headers)
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthorized"}
    assert _get_ukon(client, uid) == before

    headers = {"X-Api-Key": "test-api-key"}
    if method == "get":
        r = client.get("/api/ukony/hledat", query_string={"vin": VIN}, headers=headers)
    else:
        r = client.post(f"/api/ukony/{uid}/doplnit", json={"rz": "1AB2345"}, headers=headers)
    assert r.status_code == 200


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_doplnit_empty_fields_and_normalize(client, make_ukon, empty):
    uid = make_ukon(rz=empty, orv=empty)
    r = client.post(f"/api/ukony/{uid}/doplnit", json={"rz": " 1ab-23 45 ", "orv": " ube-037 263 "})
    assert r.status_code == 200
    assert r.get_json() == {"id": uid, "rz": "1AB2345", "orv": "UBE037263", "zmeneno": ["rz", "orv"]}
    stored = _get_ukon(client, uid)
    assert stored["rz"] == "1AB2345"
    assert stored["orv"] == "UBE037263"


@pytest.mark.parametrize("field,existing", [("rz", "9ZZ9999"), ("orv", "ABC123456")])
def test_doplnit_conflict_writes_nothing(client, make_ukon, monkeypatch, field, existing):
    uid = make_ukon(**{field: existing})
    before = _get_ukon(client, uid)
    monkeypatch.setattr(db, "now_iso", lambda: "2026-10-08T12:00:00+00:00")
    r = client.post(f"/api/ukony/{uid}/doplnit", json={"rz": "1AB2345", "orv": "UBE037263"})
    assert r.status_code == 409
    error = "RZ už je vyplněná jinak." if field == "rz" else "ORV už je vyplněné jinak."
    assert r.get_json() == {"error": error, "pole": field, "stavajici": existing}
    assert _get_ukon(client, uid) == before


def test_doplnit_idempotent(client, make_ukon, monkeypatch):
    uid = make_ukon()
    payload = {"rz": "1AB2345", "orv": "UBE037263"}
    assert client.post(f"/api/ukony/{uid}/doplnit", json=payload).status_code == 200
    before = _get_ukon(client, uid)
    monkeypatch.setattr(db, "now_iso", lambda: "2026-10-08T12:00:00+00:00")
    r = client.post(f"/api/ukony/{uid}/doplnit", json={"rz": " 1ab-2345 ", "orv": " ube-037263 "})
    assert r.status_code == 200
    assert r.get_json() == {"id": uid, **payload, "zmeneno": []}
    assert _get_ukon(client, uid) == before


@pytest.mark.parametrize("field,value", [("rz", "1AB2345"), ("orv", "UBE037263")])
def test_doplnit_single_field(client, make_ukon, field, value):
    uid = make_ukon()
    r = client.post(f"/api/ukony/{uid}/doplnit", json={field: value})
    assert r.status_code == 200
    expected = {"id": uid, "rz": None, "orv": None, "zmeneno": [field]}
    expected[field] = value
    assert r.get_json() == expected


def test_doplnit_same_value_omitted_from_changes(client, make_ukon):
    uid = make_ukon(rz="1AB2345")
    r = client.post(f"/api/ukony/{uid}/doplnit", json={"rz": "1AB2345", "orv": "UBE037263"})
    assert r.status_code == 200
    assert r.get_json() == {"id": uid, "rz": "1AB2345", "orv": "UBE037263", "zmeneno": ["orv"]}


@pytest.mark.parametrize("payload", [
    {}, {"vin": VIN}, {"rz": ""}, {"rz": "AB12"}, {"rz": "123456789"},
    {"rz": "AB12!"}, {"rz": None}, {"rz": 12345},
    {"orv": ""}, {"orv": "AB123456"}, {"orv": "ABCD123456"},
    {"orv": "ABC12345"}, {"orv": "ABC1234567"}, {"orv": "ABC１２３４５６"},
    {"orv": None}, {"orv": []}, {"rz": "1AB2345", "orv": "invalid"},
    [], ["rz"], "rz", None,
])
def test_doplnit_invalid_payload_400(client, make_ukon, payload):
    uid = make_ukon()
    before = _get_ukon(client, uid)
    r = client.post(f"/api/ukony/{uid}/doplnit", json=payload)
    assert r.status_code == 400
    assert set(r.get_json()) == {"error"}
    assert _get_ukon(client, uid) == before


def test_doplnit_unknown_id_404(client):
    r = client.post("/api/ukony/99999/doplnit", json={"rz": "1AB2345"})
    assert r.status_code == 404
    assert r.get_json() == {"error": "Úkon nenalezen."}


def test_doplnit_preserves_all_other_columns(client, make_ukon, monkeypatch):
    uid = make_ukon(
        celkem=1750.5, zaplaceno_kc=500, datum="2026-08-01",
        poznamka="Původní poznámka", prevod="A → B", zdroj="prepis_app", zpracoval="David",
    )
    before = _get_ukon(client, uid)
    timestamp = "2026-10-08T12:00:00+00:00"
    monkeypatch.setattr(db, "now_iso", lambda: timestamp)
    r = client.post(f"/api/ukony/{uid}/doplnit", json={
        "rz": "1AB2345", "orv": "UBE037263", "celkem": 0,
        "datum": "2020-01-01", "firma_id": 999, "stav_platby": "zaplaceno",
        "vin": "OTHER", "zaplaceno_kc": 0, "poznamka": "Přepsat",
    })
    assert r.status_code == 200
    assert _get_ukon(client, uid) == {
        **before, "rz": "1AB2345", "orv": "UBE037263", "updated_at": timestamp,
    }
