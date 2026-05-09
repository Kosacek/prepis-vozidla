import os


def test_generate_zmena_returns_url(client):
    payload = {
        "mode": "zmena",
        "novy_jmeno": "JAN NOVAK",
        "novy_rc_1": "850101",
        "novy_rc_2": "1234",
        "novy_adresa": "ADRESA 1",
        "novy_psc": "60200",
        "registracni_znacka": "1AB2345",
        "vin": "WBA3A5C51DF123456",
        "druh_vozidla": "osobni automobil",
        "zadost_zmena": "zápis A50-X",
        "novy_prov_jiny": False,
    }
    r = client.post("/api/generate", json=payload)
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert data["zmena"].startswith("/download/zmena_")
    assert "zmeny" not in data
    assert "zapis" not in data


def test_generate_unknown_mode_returns_400(client):
    r = client.post("/api/generate", json={"mode": "neznamy"})
    assert r.status_code == 400
    data = r.get_json()
    assert data["success"] is False
    assert "neznámý" in data["error"].lower()
