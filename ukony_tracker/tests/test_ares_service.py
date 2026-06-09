from unittest.mock import patch, MagicMock
from services import ares_service


def test_lookup_parses_ares():
    payload = {"obchodniJmeno": "AUTO CARDION s. r. o.",
               "sidlo": {"nazevUlice": "Heršpická", "cisloDomovni": 788,
                          "cisloOrientacni": 9, "nazevObce": "Brno", "psc": "63900"}}
    with patch("services.ares_service.requests.get") as g:
        g.return_value = MagicMock(status_code=200, json=lambda: payload)
        out = ares_service.lookup_ico("04156854")
    assert out["nazev"] == "AUTO CARDION s. r. o."
    assert out["psc"] == "63900"
    assert "Brno" in out["adresa"]


def test_lookup_not_found_returns_none():
    with patch("services.ares_service.requests.get") as g:
        g.return_value = MagicMock(status_code=404, json=lambda: {})
        assert ares_service.lookup_ico("00000000") is None


def test_lookup_pads_leading_zero_ico():
    with patch("services.ares_service.requests.get") as g:
        g.return_value = MagicMock(status_code=200, json=lambda: {"obchodniJmeno": "X", "sidlo": {}})
        ares_service.lookup_ico("4156854")
        assert "04156854" in g.call_args[0][0]
