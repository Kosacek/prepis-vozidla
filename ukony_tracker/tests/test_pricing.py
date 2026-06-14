"""Per-firm pricing: overrides repo, effective-price cascade, ceník routes,
entry-form prefill, and žádost auto-create using the firm's price."""
import pytest

import app as appmod
import db
import config
from repositories import firmy_repo, typy_repo, firma_ceny_repo, ukony_repo
from services import pricing_service, prichozi_service


def _setup(conn):
    f1 = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="11111111")
    f2 = firmy_repo.create(conn, nazev="Albion", zkratka="Albion", ico="22222222")
    typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
    typy_repo.upsert(conn, "DOVOZ", 2000, 2)
    return f1, f2


# ── firma_ceny_repo ───────────────────────────────────────────────────────────

def test_set_get_delete_override(conn):
    f1, _ = _setup(conn)
    firma_ceny_repo.set_price(conn, f1, "PŘEVOD", 1500)
    assert firma_ceny_repo.get(conn, f1, "PŘEVOD") == 1500
    assert firma_ceny_repo.get_map(conn, f1) == {"PŘEVOD": 1500}
    firma_ceny_repo.set_price(conn, f1, "PŘEVOD", None)  # blank removes
    assert firma_ceny_repo.get(conn, f1, "PŘEVOD") is None
    assert firma_ceny_repo.get_map(conn, f1) == {}


def test_override_upsert(conn):
    f1, _ = _setup(conn)
    firma_ceny_repo.set_price(conn, f1, "PŘEVOD", 1500)
    firma_ceny_repo.set_price(conn, f1, "PŘEVOD", 1600)
    assert firma_ceny_repo.get(conn, f1, "PŘEVOD") == 1600


# ── pricing_service cascade ───────────────────────────────────────────────────

def test_effective_price_cascade(conn):
    f1, f2 = _setup(conn)
    firma_ceny_repo.set_price(conn, f1, "PŘEVOD", 1500)
    assert pricing_service.effective_price(conn, f1, "PŘEVOD") == 1500   # firm override
    assert pricing_service.effective_price(conn, f2, "PŘEVOD") == 1300   # type default
    assert pricing_service.effective_price(conn, f1, "NEEXISTUJE") is None


def test_firm_price_map(conn):
    f1, _ = _setup(conn)
    firma_ceny_repo.set_price(conn, f1, "PŘEVOD", 1500)
    m = pricing_service.firm_price_map(conn, f1)
    assert m["PŘEVOD"] == 1500 and m["DOVOZ"] == 2000


# ── žádost auto-create uses the firm's price ──────────────────────────────────

def test_autocreate_uses_firm_override(conn):
    f1, _ = _setup(conn)
    firma_ceny_repo.set_price(conn, f1, "PŘEVOD", 1500)
    res = prichozi_service.intake(conn, {
        "zadost_id": "p1", "mode": "prevod", "datum": "2026-06-14", "novy_ico": "11111111",
    })
    assert res["status"] == "auto"
    assert ukony_repo.get(conn, res["ukon_id"])["celkem"] == 1500  # firm price, not 1300


# ── ceník routes + entry-form prefill ─────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            conn = db.get_db()
            fid = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="11111111")
            typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
        yield c, fid


def test_cenik_save_and_revert(client):
    c, fid = client
    r = c.post(f"/firmy/{fid}/ceny", data={"cena_PŘEVOD": "1500"})
    assert r.status_code in (302, 303)
    with c.application.app_context():
        assert firma_ceny_repo.get(db.get_db(), fid, "PŘEVOD") == 1500
    body = c.get(f"/firmy/{fid}/ceny").get_data(as_text=True)
    assert "Ceník" in body and "1500" in body
    c.post(f"/firmy/{fid}/ceny", data={"cena_PŘEVOD": ""})  # blank → revert to default
    with c.application.app_context():
        assert firma_ceny_repo.get(db.get_db(), fid, "PŘEVOD") is None


def test_entry_form_uses_firm_price(client):
    c, fid = client
    with c.application.app_context():
        firma_ceny_repo.set_price(db.get_db(), fid, "PŘEVOD", 1500)
    body = c.get(f"/ukony/{fid}").get_data(as_text=True)
    assert 'data-cena="1500"' in body  # PŘEVOD button carries this firm's price
