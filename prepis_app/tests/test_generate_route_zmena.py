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


def test_generate_does_not_block_on_a_slow_tracker(client, monkeypatch, tmp_path):
    """The whole point of the 2026-09-13 fix: /api/generate must return long
    before the tracker push (network call to a sibling container) finishes."""
    import time
    import app as A

    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    os.makedirs(os.path.join(str(tmp_path), "output"), exist_ok=True)

    import tracker_push

    def _slow_post(url, json=None, headers=None, timeout=None):
        time.sleep(1.5)
        class _R:
            status_code = 201
            def json(self_):
                return {"status": "auto"}
        return _R()

    monkeypatch.setattr(tracker_push.requests, "post", _slow_post)

    payload = {
        "mode": "zmena", "registracni_znacka": "1AB2345", "vin": "TMBEK6NW7M3158470",
        "novy_jmeno": "JAN NOVÁK", "evidence_log": True,
    }
    t0 = time.time()
    r = client.post("/api/generate", json=payload)
    elapsed = time.time() - t0
    assert r.status_code == 200
    assert elapsed < 1.0, f"generate took {elapsed:.2f}s — the tracker push is blocking it again"
