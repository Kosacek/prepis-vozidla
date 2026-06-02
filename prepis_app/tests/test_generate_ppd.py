"""Integration: PPD is generated alongside the žádost via /api/generate.

DATA_DIR is monkeypatched to a tmp dir so the test never touches the real
NAS evidence ledger / counter.
"""
import os

import app as appmod


def _payload(**over):
    base = {
        "mode": "prevod",
        "registracni_znacka": "1AB2345",
        "vin": "WBA3A5C51DF123456",
        "puvodni_jmeno": "JAN PRODÁVAJÍCÍ",
        "novy_jmeno": "PETR KUPUJÍCÍ",
        "ppd_castka": "1300",
        "ppd_prijato_od": "PETR KUPUJÍCÍ",
    }
    base.update(over)
    return base


def test_generate_includes_ppd(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json=_payload())
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert data["ppd"].startswith("/download/ppd_")
    # file written + evidence row created under the tmp DATA_DIR
    fname = data["ppd"].split("/")[-1]
    assert os.path.exists(os.path.join(str(tmp_path), "output", fname))
    assert os.path.exists(os.path.join(str(tmp_path), "ppd_evidence.xlsx"))


def test_zero_amount_skips_ppd(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json=_payload(ppd_castka="0"))
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert "ppd" not in data            # opt-out
    assert data.get("zmeny")            # žádosti still produced
