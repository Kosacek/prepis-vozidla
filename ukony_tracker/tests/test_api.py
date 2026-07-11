import pytest
import app as appmod
import db
import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            from repositories import firmy_repo
            firmy_repo.create(db.get_db(), nazev="Cardion", zkratka="Cardion", ico="04156854")
        yield c


def test_api_creates_by_ico(client):
    r = client.post(
        "/api/ukony",
        json={
            "ico": "04156854",
            "datum": "2026-05-04",
            "typ_kod": "PŘEVOD",
            "celkem": 1300,
            "zdroj": "prepis_app",
        },
    )
    assert r.status_code == 201


def test_api_unknown_firma_400(client):
    r = client.post(
        "/api/ukony",
        json={
            "ico": "99999999",
            "datum": "2026-05-04",
            "typ_kod": "PŘEVOD",
            "celkem": 1300,
        },
    )
    assert r.status_code == 400


# ── /api/prichozi (žádost intake) ─────────────────────────────────────────────

def test_prichozi_auto_creates_when_ico_matches(client):
    with client.application.app_context():
        from repositories import typy_repo
        typy_repo.upsert(db.get_db(), "PŘEVOD", 1300, 1)
    r = client.post("/api/prichozi", json={
        "zadost_id": "api-zz1", "mode": "prevod", "datum": "2026-06-14",
        "rz": "1ab2345", "novy_ico": "04156854", "novy_jmeno": "Cardion",
    })
    assert r.status_code == 201
    body = r.get_json()
    assert body["status"] == "auto" and "ukon_id" in body


def test_prichozi_queues_when_no_match(client):
    r = client.post("/api/prichozi", json={
        "zadost_id": "api-zz2", "mode": "prevod", "datum": "2026-06-14", "novy_ico": "00000000",
    })
    assert r.status_code == 201
    assert r.get_json()["status"] == "pending"


def test_prichozi_duplicate_zadost_id(client):
    p = {"zadost_id": "api-dup", "mode": "zmena", "datum": "2026-06-14"}
    assert client.post("/api/prichozi", json=p).get_json()["status"] == "pending"
    r2 = client.post("/api/prichozi", json=p)
    assert r2.status_code == 200 and r2.get_json()["status"] == "duplicate"


# ── /api/evidence-meta (firms/types/prices for zadosti's picker) ──────────────

def test_evidence_meta(client):
    with client.application.app_context():
        from repositories import typy_repo
        typy_repo.upsert(db.get_db(), "PŘEVOD", 1300, 1)
    r = client.get("/api/evidence-meta")
    assert r.status_code == 200
    body = r.get_json()
    assert "04156854" in {f["ico"] for f in body["firmy"]}       # seeded Cardion
    kods = {t["kod"] for t in body["typy"]}
    assert "PŘEVOD" in kods and "KOLA" in kods                    # incl. new change type
    fid = next(f["id"] for f in body["firmy"] if f["ico"] == "04156854")
    assert body["ceny"][str(fid)]["PŘEVOD"] == 1300              # firm's effective price


# ── API key auth ──────────────────────────────────────────────────────────────

def test_api_open_when_no_key_configured(client):
    # INTEGRATION_API_KEY unset (default) → existing keyless calls keep working.
    r = client.post("/api/prichozi", json={"zadost_id": "nokey", "mode": "zmena", "datum": "2026-06-14"})
    assert r.status_code == 201


def test_api_requires_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(config, "INTEGRATION_API_KEY", "s3cret")
    # missing key → 401
    assert client.post("/api/prichozi", json={"zadost_id": "k1", "mode": "zmena", "datum": "2026-06-14"}).status_code == 401
    # wrong key → 401
    assert client.post("/api/prichozi", headers={"X-Api-Key": "nope"},
                       json={"zadost_id": "k2", "mode": "zmena", "datum": "2026-06-14"}).status_code == 401
    # correct key → ok
    r = client.post("/api/prichozi", headers={"X-Api-Key": "s3cret"},
                    json={"zadost_id": "k3", "mode": "zmena", "datum": "2026-06-14"})
    assert r.status_code == 201
    # the existing /api/ukony is also protected when a key is set
    assert client.post("/api/ukony", json={"ico": "04156854", "datum": "2026-06-14",
                                           "typ_kod": "PŘEVOD", "celkem": 1300}).status_code == 401
