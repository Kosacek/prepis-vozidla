"""Dashboard route tests (Task 14)."""
import pytest
import app as appmod
import db
import config
from repositories import firmy_repo, typy_repo, ukony_repo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            conn = db.get_db()
            fid = firmy_repo.create(conn, nazev="TestFirma", zkratka="TF", ico="99")
            typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
            # Two úkony in 2026-05: one paid, one unpaid
            ukony_repo.create(
                conn,
                firma_id=fid,
                datum="2026-05-10",
                typ_kod="PŘEVOD",
                celkem=100000,
                rz="AA1111",
                stav_platby="zaplaceno",
                zaplaceno_kc=100000,
            )
            ukony_repo.create(
                conn,
                firma_id=fid,
                datum="2026-05-15",
                typ_kod="PŘEVOD",
                celkem=45700,
                rz="BB2222",
                stav_platby="nezaplaceno",
                zaplaceno_kc=0,
            )
        yield c, fid


def test_dashboard_ok(client):
    """GET / returns 200 with chart canvas and Přehled heading."""
    c, _ = client
    r = c.get("/?rok=2026")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Přehled" in body
    assert "trendChart" in body


def test_dashboard_ytd_total(client):
    """YTD tržby (145700) appears in the rendered page."""
    c, _ = client
    r = c.get("/?rok=2026")
    body = r.get_data(as_text=True)
    assert "145700" in body


def test_dashboard_firma_zkratka(client):
    """Firma zkratka appears in the per-firma breakdown."""
    c, _ = client
    r = c.get("/?rok=2026")
    body = r.get_data(as_text=True)
    assert "TF" in body


def test_dashboard_nezaplaceno(client):
    """Outstanding balance (45700) appears in the KPI block."""
    c, _ = client
    r = c.get("/?rok=2026")
    body = r.get_data(as_text=True)
    assert "45700" in body


def test_dashboard_has_typy_chart_and_no_kdo_dluzi(client):
    """Typy úkonů wheel moved to the side column; the 'Kdo dluží' panel is gone."""
    c, _ = client
    body = c.get("/?rok=2026").get_data(as_text=True)
    assert 'id="typChart"' in body          # types doughnut still rendered
    assert "Kdo dluží" not in body          # debt panel removed per request
