"""Best-effort push to the Úkony Tracker."""
import json
from datetime import date

import tracker_push


def test_build_payload_uses_today_not_form_date():
    data = {
        "mode": "prevod",
        "registracni_znacka": "1ab2345",
        "vin": "tmbvin1234567890",
        "znacka": "Škoda Octavia",
        "osvedceni_serie": "ABC",
        "osvedceni_cislo": "123456",
        "novy_jmeno": "Cardion s.r.o.",
        "novy_ico": "04156854",
        "puvodni_jmeno": "Jan Novák",
        "dne": "2099-01-01",  # the žádost's post-dated form date — must be ignored
    }
    p = tracker_push.build_payload(data)
    assert p["mode"] == "prevod"
    assert p["rz"] == "1ab2345"
    assert p["znacka"] == "Škoda Octavia"
    assert p["novy_ico"] == "04156854"
    assert p["osvedceni_serie"] == "ABC" and p["osvedceni_cislo"] == "123456"
    assert len(p["zadost_id"]) >= 16              # uuid present
    assert p["datum"] == date.today().isoformat()  # real today, NOT 2099 form date
    # no sensitive fields leak
    assert "rc_1" not in p and "puvodni_adresa" not in p


def test_build_payload_forwards_operator_name_when_jiny():
    """When 'jiný provozovatel' is checked, the operator name is forwarded so the
    tracker inbox can headline the real client over a leasing-company owner."""
    data = {
        "mode": "zapis",
        "novy_jmeno": "Raiffeisen-Leasing s.r.o.",
        "novy_ico": "61467863",
        "novy_prov_jiny": True,
        "novy_prov_jmeno": "Jan Řidič",
        "novy_prov_ico": "11111111",
    }
    p = tracker_push.build_payload(data)
    assert p["novy_prov_jmeno"] == "Jan Řidič"
    assert p["novy_prov_ico"] == "11111111"          # ico still forwarded
    assert p["novy_jmeno"] == "Raiffeisen-Leasing s.r.o."  # owner kept for reference


def test_build_payload_drops_operator_name_when_not_jiny():
    """No distinct operator → no name forwarded (avoid leaking a stale field that
    the PDF leaves blank). The ico stays unconditional, matching prior behavior."""
    data = {
        "mode": "prevod",
        "novy_jmeno": "Jan Novák",
        "novy_prov_jmeno": "STALE LEFTOVER",  # box unchecked → must NOT be sent
        "novy_prov_ico": "",
    }
    p = tracker_push.build_payload(data)
    assert p["novy_prov_jmeno"] is None
    assert p["puvodni_prov_jmeno"] is None


def test_build_payload_gates_each_side_independently():
    """A 'jiný provozovatel' flag on one side must not leak the other side's
    operator name (guards a copy-paste flag mix-up)."""
    data = {
        "mode": "prevod",
        "puvodni_prov_jiny": True, "puvodni_prov_jmeno": "Seller Operator",
        "novy_prov_jiny": False, "novy_prov_jmeno": "Should Not Send",
    }
    p = tracker_push.build_payload(data)
    assert p["puvodni_prov_jmeno"] == "Seller Operator"
    assert p["novy_prov_jmeno"] is None


def test_push_records_failure_when_unreachable(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker_push, "UKONY_API_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(tracker_push, "TIMEOUT", 0.2)
    res = tracker_push.push({"mode": "zmena", "registracni_znacka": "X"}, str(tmp_path))
    assert res is None  # never raises
    log = tmp_path / "failed_pushes.jsonl"
    assert log.exists()
    rec = json.loads(log.read_text(encoding="utf-8").strip())
    assert rec["payload"]["mode"] == "zmena"


def test_push_success_sends_key_and_returns_json(tmp_path, monkeypatch):
    captured = {}

    class _Resp:
        status_code = 201

        def json(self):
            return {"status": "auto", "ukon_id": 7}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", "s3cret")
    monkeypatch.setattr(tracker_push.requests, "post", _fake_post)
    res = tracker_push.push({"mode": "prevod", "novy_ico": "1"}, str(tmp_path))
    assert res == {"status": "auto", "ukon_id": 7}
    assert captured["url"].endswith("/api/prichozi")
    assert captured["headers"]["X-Api-Key"] == "s3cret"
    assert not (tmp_path / "failed_pushes.jsonl").exists()  # no failure recorded
