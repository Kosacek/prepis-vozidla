"""Attribution: a session profile (config.PROFILY) chosen after login auto-logs
who added each car. No per-form picker."""
import pytest

import app as appmod
import db
import config
from repositories import firmy_repo, typy_repo, ukony_repo
from services import ingest_service


@pytest.fixture
def client_fid(tmp_path, monkeypatch):
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


def _set_profil(c, name):
    with c.session_transaction() as s:
        s["profil"] = name


# ── write path: only known profiles are ever stored ──────────────────────────

def test_pridat_ukon_stores_valid_profil(client_fid):
    c, fid = client_fid
    with c.application.app_context():
        conn = db.get_db()
        uid = ingest_service.pridat_ukon(conn, firma_id=fid, datum="2026-06-14",
                                         typ_kod="PŘEVOD", celkem=1300, zpracoval="Roman")
        assert ukony_repo.get(conn, uid)["zpracoval"] == "Roman"


def test_pridat_ukon_rejects_unknown_profil(client_fid):
    c, fid = client_fid
    with c.application.app_context():
        conn = db.get_db()
        for bad in ("  ", "Hacker", ""):
            uid = ingest_service.pridat_ukon(conn, firma_id=fid, datum="2026-06-14",
                                             typ_kod="PŘEVOD", celkem=1300, zpracoval=bad)
            assert ukony_repo.get(conn, uid)["zpracoval"] is None


# ── session profile auto-attributes new úkony ────────────────────────────────

def test_entry_add_uses_session_profil(client_fid):
    c, fid = client_fid
    _set_profil(c, "Petr")
    r = c.post(f"/ukony/{fid}", data={"datum": "2026-06-14", "typ_kod": "PŘEVOD",
                                      "celkem": "1300", "rz": "1AB2345", "mesic": "2026-06"})
    assert r.status_code in (302, 303)
    with c.application.app_context():
        assert ukony_repo.list(db.get_db(), firma_id=fid)[0]["zpracoval"] == "Petr"


def test_entry_form_has_no_per_row_picker(client_fid):
    c, fid = client_fid
    _set_profil(c, "David")
    assert 'name="zpracoval"' not in c.get(f"/ukony/{fid}").get_data(as_text=True)


# ── /kdo picker ──────────────────────────────────────────────────────────────

def test_kdo_page_lists_profiles(client_fid):
    c, _ = client_fid
    body = c.get("/kdo").get_data(as_text=True)
    for p in config.PROFILY:
        assert f'value="{p}"' in body


def test_kdo_post_sets_session_and_rejects_unknown(client_fid):
    c, _ = client_fid
    c.post("/kdo", data={"profil": "Roman"})
    with c.session_transaction() as s:
        assert s["profil"] == "Roman"
    c.post("/kdo", data={"profil": "Nobody"})       # not in PROFILY → ignored
    with c.session_transaction() as s:
        assert s["profil"] == "Roman"


# ── login gate requires a profile after auth ─────────────────────────────────

def test_gate_requires_profile_after_login(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "secret")
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with c.session_transaction() as s:
            s["authed"] = True          # logged in, but no profil chosen
        r = c.get("/ukony/vse")
        assert r.status_code in (302, 303) and "/kdo" in r.headers["Location"]
        # logout must still work even before a profile is chosen (not stuck at /kdo)
        assert c.post("/logout").status_code in (301, 302)
        with c.session_transaction() as s:
            s["authed"] = True
        c.post("/kdo", data={"profil": "Roman"})    # choose → now allowed
        assert c.get("/ukony/vse").status_code == 200


# ── edit preserves the original attribution ──────────────────────────────────

def test_edit_preserves_zpracoval(client_fid):
    c, fid = client_fid
    with c.application.app_context():
        uid = ukony_repo.create(db.get_db(), firma_id=fid, datum="2026-06-14",
                                typ_kod="PŘEVOD", celkem=1300, zpracoval="David")
    c.post(f"/ukony/{uid}/upravit", data={"datum": "2026-06-14", "typ_kod": "PŘEVOD",
                                          "celkem": "1500", "back": "/"})
    with c.application.app_context():
        row = ukony_repo.get(db.get_db(), uid)
    assert float(row["celkem"]) == 1500.0     # edit applied
    assert row["zpracoval"] == "David"          # attribution untouched


# ── display ──────────────────────────────────────────────────────────────────

def test_table_shows_kdo_column(client_fid):
    c, fid = client_fid
    with c.application.app_context():
        ukony_repo.create(db.get_db(), firma_id=fid, datum="2026-06-14",
                          typ_kod="PŘEVOD", celkem=1300, rz="KDO111", zpracoval="David")
    body = c.get("/ukony/vse").get_data(as_text=True)
    assert ">Kdo<" in body and 'class="kdo"' in body and "David" in body
