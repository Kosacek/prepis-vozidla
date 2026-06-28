"""Dashboard recent-list: firm colors + the quick-find search."""
import pytest

import app as appmod
import db
import config
from repositories import firmy_repo, typy_repo, ukony_repo
from services import colors_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            conn = db.get_db()
            cardion = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="1")
            tesla = firmy_repo.create(conn, nazev="Tesla", zkratka="Tesla", ico="2")
            typy_repo.upsert(conn, "NOVÉ", 1000, 1)
            # A freshly registered car: no SPZ yet, identified by VIN.
            ukony_repo.create(conn, firma_id=tesla, datum="2026-06-28", typ_kod="NOVÉ",
                              celkem=1000, rz=None, vin="XP7YGCEL6TB924790",
                              poznamka="Kancelář DHS s.r.o.")
            ukony_repo.create(conn, firma_id=cardion, datum="2026-06-26", typ_kod="NOVÉ",
                              celkem=1300, rz="2BS2200", vin="WBACV61030LJ71367")
        yield c, cardion, tesla


# ── repo.search ───────────────────────────────────────────────────────────────

def test_search_by_vin_fragment(client):
    c, _, _ = client
    with c.application.app_context():
        rows = ukony_repo.search(db.get_db(), "924790")   # a few VIN digits
    assert len(rows) == 1 and rows[0]["vin"] == "XP7YGCEL6TB924790"


def test_search_is_case_insensitive_and_matches_firm(client):
    c, _, _ = client
    with c.application.app_context():
        by_firm = ukony_repo.search(db.get_db(), "cardion")   # lowercase
        by_pozn = ukony_repo.search(db.get_db(), "DHS")
    assert len(by_firm) == 1 and by_firm[0]["firma_zkratka"] == "Cardion"
    assert len(by_pozn) == 1 and "DHS" in by_pozn[0]["poznamka"]


def test_search_blank_returns_empty(client):
    c, _, _ = client
    with c.application.app_context():
        assert ukony_repo.search(db.get_db(), "   ") == []


def test_search_respects_limit(client):
    c, _, tesla = client
    with c.application.app_context():
        conn = db.get_db()
        for i in range(5):
            ukony_repo.create(conn, firma_id=tesla, datum="2026-06-20", typ_kod="NOVÉ",
                              celkem=1000, vin=f"VINLIMIT{i:08d}")
        rows = ukony_repo.search(conn, "VINLIMIT", limit=3)
    assert len(rows) == 3


# ── colors_service ────────────────────────────────────────────────────────────

def test_firma_color_map_uses_brand_colors(client):
    c, _, _ = client
    with c.application.app_context():
        cmap = colors_service.firma_color_map(db.get_db())
    assert set(cmap) == {"Cardion", "Tesla"}
    assert cmap["Tesla"] == colors_service.BRAND_COLORS["Tesla"]      # Tesla red
    assert cmap["Cardion"] == colors_service.BRAND_COLORS["Cardion"]  # Volvo navy
    assert cmap["Tesla"] != cmap["Cardion"]


def test_firma_color_map_falls_back_to_palette_for_unknown_firm(client):
    c, _, _ = client
    with c.application.app_context():
        conn = db.get_db()
        firmy_repo.create(conn, nazev="Neznámá", zkratka="Neznámá", ico="9")
        cmap = colors_service.firma_color_map(conn)
    assert cmap["Neznámá"] in colors_service.PALETTE   # no brand → palette fallback


# ── /ukony/hledat route ───────────────────────────────────────────────────────

def test_hledat_returns_matching_row_with_edit_link(client):
    c, _, _ = client
    body = c.get("/ukony/hledat?q=924790").get_data(as_text=True)
    assert "XP7YGCEL6TB924790" in body
    assert "/upravit?back=" in body                    # clicking opens the edit page (back encoded)
    assert "firma-dot" in body                         # firm color rendered


def test_hledat_no_match_shows_message(client):
    c, _, _ = client
    body = c.get("/ukony/hledat?q=NOSUCHVIN").get_data(as_text=True)
    assert "Nic nenalezeno." in body


def test_dashboard_renders_search_box_and_firm_colors(client):
    c, _, _ = client
    body = c.get("/").get_data(as_text=True)
    assert 'id="recent-search"' in body                # the quick-find box
    assert "firma-dot" in body                         # colored firm dots in the list
    assert "window.FIRMA_COLORS" in body               # chart shares the same map
