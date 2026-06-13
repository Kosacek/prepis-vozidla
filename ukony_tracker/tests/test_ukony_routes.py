import pytest
import app as appmod
import db
import config
from repositories import firmy_repo, typy_repo, ukony_repo


@pytest.fixture
def client_fid(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            conn = db.get_db()
            fid = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="1")
            typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
        yield c, fid


def test_entry_page_renders(client_fid):
    c, fid = client_fid
    r = c.get(f"/ukony/{fid}")
    assert r.status_code == 200
    assert "Nový úkon" in r.get_data(as_text=True)


def test_post_creates_ukon(client_fid):
    c, fid = client_fid
    r = c.post(
        f"/ukony/{fid}",
        data={
            "datum": "2026-05-04",
            "typ_kod": "PŘEVOD",
            "celkem": "1300",
            "rz": "3BP3552",
            "mesic": "2026-05",
        },
    )
    assert r.status_code in (302, 303)
    with c.application.app_context():
        rows = ukony_repo.list(db.get_db(), firma_id=fid)
    assert len(rows) == 1 and rows[0]["rz"] == "3BP3552"


# ── helpers ────────────────────────────────────────────────────────────────

def _seed_ukon(app, fid, rz="1AA1111", celkem=1300):
    """Create one úkon and return its id."""
    with app.app_context():
        conn = db.get_db()
        return ukony_repo.create(
            conn,
            firma_id=fid,
            datum="2026-05-10",
            typ_kod="PŘEVOD",
            celkem=celkem,
            rz=rz,
        )


# ── Task-13 route tests ─────────────────────────────────────────────────────

def test_table_renders(client_fid):
    """GET /ukony/vse returns 200 and shows the seeded RZ."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid, rz="ZZZ9999")
    r = c.get("/ukony/vse")
    assert r.status_code == 200
    assert "ZZZ9999" in r.get_data(as_text=True)


def test_table_filter_by_stav(client_fid):
    """GET /ukony/vse?stav=nezaplaceno returns 200."""
    c, fid = client_fid
    _seed_ukon(c.application, fid)
    r = c.get("/ukony/vse?stav=nezaplaceno")
    assert r.status_code == 200


def test_mark_paid_full(client_fid):
    """POST /ukony/<id>/zaplaceno without castka marks row as zaplaceno with full amount."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid, celkem=1300)
    r = c.post(f"/ukony/{uid}/zaplaceno", data={"back": "/ukony/vse"})
    assert r.status_code in (302, 303)
    with c.application.app_context():
        row = ukony_repo.get(db.get_db(), uid)
    assert row["stav_platby"] == "zaplaceno"
    assert float(row["zaplaceno_kc"]) == 1300.0


def test_mark_paid_partial(client_fid):
    """POST /ukony/<id>/zaplaceno with castka < celkem marks row as castecne."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid, celkem=1300)
    r = c.post(f"/ukony/{uid}/zaplaceno", data={"castka": "500", "back": "/ukony/vse"})
    assert r.status_code in (302, 303)
    with c.application.app_context():
        row = ukony_repo.get(db.get_db(), uid)
    assert row["stav_platby"] == "castecne"
    assert float(row["zaplaceno_kc"]) == 500.0


def test_delete_ukon(client_fid):
    """POST /ukony/<id>/smazat removes the row."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid)
    r = c.post(f"/ukony/{uid}/smazat", data={"back": "/ukony/vse"})
    assert r.status_code in (302, 303)
    with c.application.app_context():
        assert ukony_repo.get(db.get_db(), uid) is None


def test_edit_save_persists(client_fid):
    """POST /ukony/<id>/upravit updates celkem in the database."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid, celkem=1300)
    r = c.post(
        f"/ukony/{uid}/upravit",
        data={
            "datum": "2026-05-10",
            "rz": "1AA1111",
            "typ_kod": "PŘEVOD",
            "celkem": "999",
            "vin": "",
            "poznamka": "",
            "back": "/ukony/vse",
        },
    )
    assert r.status_code in (302, 303)
    with c.application.app_context():
        row = ukony_repo.get(db.get_db(), uid)
    assert float(row["celkem"]) == 999.0


def test_edit_form_renders(client_fid):
    """GET /ukony/<id>/upravit returns 200 with the current RZ pre-filled."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid, rz="EDIT123")
    r = c.get(f"/ukony/{uid}/upravit")
    assert r.status_code == 200
    assert "EDIT123" in r.get_data(as_text=True)


def test_edit_raising_celkem_rederives_to_castecne(client_fid):
    """Editing celkem ABOVE a fully-paid amount must drop stav to 'castecne'."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid, celkem=1300)
    with c.application.app_context():
        ukony_repo.update(db.get_db(), uid, zaplaceno_kc=1300, stav_platby="zaplaceno")
    c.post(f"/ukony/{uid}/upravit", data={"datum": "2026-05-10", "typ_kod": "PŘEVOD", "celkem": "2000"})
    with c.application.app_context():
        row = ukony_repo.get(db.get_db(), uid)
    assert float(row["celkem"]) == 2000.0
    assert float(row["zaplaceno_kc"]) == 1300.0
    assert row["stav_platby"] == "castecne"


def test_unmark_paid_via_castka_zero(client_fid):
    """Clicking the zapl. badge posts castka=0 — payment must reset to nezaplaceno."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid, celkem=1300)
    c.post(f"/ukony/{uid}/zaplaceno", data={})              # mark fully paid
    c.post(f"/ukony/{uid}/zaplaceno", data={"castka": "0"})  # undo
    with c.application.app_context():
        row = ukony_repo.get(db.get_db(), uid)
    assert row["stav_platby"] == "nezaplaceno"
    assert float(row["zaplaceno_kc"]) == 0.0


def test_edit_can_change_datum(client_fid):
    """The date is editable on the edit form (deliberate change is allowed)."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid, celkem=1300)  # datum 2026-05-10
    c.post(f"/ukony/{uid}/upravit", data={"datum": "2026-06-30", "typ_kod": "PŘEVOD",
                                          "celkem": "1300", "rz": "NEW123"})
    with c.application.app_context():
        row = ukony_repo.get(db.get_db(), uid)
    assert row["datum"] == "2026-06-30"  # changed as requested
    assert row["rz"] == "NEW123"


def test_edit_blank_datum_rejected(client_fid):
    """A blank/invalid date is rejected so it can't wipe the stored date."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid, celkem=1300)  # datum 2026-05-10
    c.post(f"/ukony/{uid}/upravit", data={"datum": "", "typ_kod": "PŘEVOD", "celkem": "1300"})
    with c.application.app_context():
        row = ukony_repo.get(db.get_db(), uid)
    assert row["datum"] == "2026-05-10"  # untouched


def test_edit_uppercases_rz_and_vin(client_fid):
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid)
    c.post(f"/ukony/{uid}/upravit", data={"datum": "2026-05-10", "typ_kod": "PŘEVOD",
                                          "celkem": "1300", "rz": "3bk9696", "vin": "tmbjj7ns"})
    with c.application.app_context():
        row = ukony_repo.get(db.get_db(), uid)
    assert row["rz"] == "3BK9696" and row["vin"] == "TMBJJ7NS"


def test_edit_lowering_celkem_to_paid_rederives_to_zaplaceno(client_fid):
    """Lowering celkem down to the amount already received must become 'zaplaceno'."""
    c, fid = client_fid
    uid = _seed_ukon(c.application, fid, celkem=1300)
    with c.application.app_context():
        ukony_repo.update(db.get_db(), uid, zaplaceno_kc=800, stav_platby="castecne")
    c.post(f"/ukony/{uid}/upravit", data={"datum": "2026-05-10", "typ_kod": "PŘEVOD", "celkem": "800"})
    with c.application.app_context():
        row = ukony_repo.get(db.get_db(), uid)
    assert float(row["celkem"]) == 800.0
    assert float(row["zaplaceno_kc"]) == 800.0
    assert row["stav_platby"] == "zaplaceno"
