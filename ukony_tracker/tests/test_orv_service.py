"""ORV → VIN lookup (dataovozidlech.cz) + the /orv-lookup route. Fully mocked —
no network is ever touched."""
from unittest.mock import patch, MagicMock

import config
from services import orv_service


def _resp(status_code=200, json_data=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data or {}
    return m


def test_lookup_missing_key(monkeypatch):
    monkeypatch.setattr(config, "DATAOVOZIDLECH_API_KEY", "")
    assert orv_service.lookup_vin("UBE037263") == {
        "success": False, "error": "Chybí DATAOVOZIDLECH_API_KEY",
    }


def test_lookup_short_orv(monkeypatch):
    monkeypatch.setattr(config, "DATAOVOZIDLECH_API_KEY", "k")
    r = orv_service.lookup_vin("UBE12")
    assert r["success"] is False and "Neúplné" in r["error"]


def test_lookup_success_returns_vin_and_normalizes(monkeypatch):
    monkeypatch.setattr(config, "DATAOVOZIDLECH_API_KEY", "k")
    data = {"Status": 1, "Data": {
        "VIN": "TMBVIN1234567890", "TovarniZnacka": "ŠKODA", "ObchodniOznaceni": "OCTAVIA",
    }}
    with patch.object(orv_service.requests, "get", return_value=_resp(200, data)) as g:
        r = orv_service.lookup_vin("ube 037263")   # lower + spaces → normalized
    assert r == {"success": True, "vin": "TMBVIN1234567890", "znacka": "ŠKODA OCTAVIA"}
    assert g.call_args.kwargs["params"] == {"orv": "UBE037263"}
    assert g.call_args.kwargs["headers"] == {"api_key": "k"}


def test_lookup_not_found(monkeypatch):
    monkeypatch.setattr(config, "DATAOVOZIDLECH_API_KEY", "k")
    with patch.object(orv_service.requests, "get", return_value=_resp(200, {"Status": 3})):
        r = orv_service.lookup_vin("UBE037263")
    assert r == {"success": False, "error": "Vozidlo nenalezeno"}


def test_lookup_network_error(monkeypatch):
    monkeypatch.setattr(config, "DATAOVOZIDLECH_API_KEY", "k")
    with patch.object(orv_service.requests, "get", side_effect=Exception("boom")):
        r = orv_service.lookup_vin("UBE037263")
    assert r == {"success": False, "error": "Chyba spojení"}


def test_orv_lookup_route_returns_json(monkeypatch, tmp_path):
    import app as appmod
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(orv_service, "lookup_vin", lambda orv: {"success": True, "vin": "VIN-" + orv})
    a = appmod.create_app()
    a.testing = True
    r = a.test_client().get("/orv-lookup?orv=UBE037263")
    assert r.status_code == 200
    assert r.get_json() == {"success": True, "vin": "VIN-UBE037263"}
