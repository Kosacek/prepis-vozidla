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


def test_build_payload_forwards_profil():
    """The chosen profile (who filled it out) is forwarded so the tracker can
    record who added the car."""
    p = tracker_push.build_payload({"mode": "prevod", "profil": "Roman"})
    assert p["profil"] == "Roman"
    # absent / blank → None (no attribution)
    assert tracker_push.build_payload({"mode": "prevod"})["profil"] is None
    assert tracker_push.build_payload({"mode": "prevod", "profil": "  "})["profil"] is None


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


def test_build_payload_explicit_evidence_assignment():
    """Firm/type/price chosen on the last page ride along so the tracker creates
    the úkon directly; the browser's stable zadost_id is reused (dedup)."""
    p = tracker_push.build_payload({
        "mode": "zmena", "zadost_id": "stable-123",
        "evidence_firma_id": "5", "evidence_typ": "KOLA", "evidence_cena": "450",
    })
    assert p["zadost_id"] == "stable-123"     # reused, not a fresh uuid
    assert p["firma_id"] == 5                  # coerced to int
    assert p["typ_kod"] == "KOLA"
    assert p["celkem"] == "450"                # passed through (tracker coerces)


def test_build_payload_forwards_zaplaceno_checkbox():
    """Last page's 'ÚKON UŽ ZAPLACEN' checkbox → tracker's zaplaceno flag."""
    p = tracker_push.build_payload({"mode": "prevod", "evidence_zaplaceno": True})
    assert p["zaplaceno"] is True


def test_build_payload_zaplaceno_false_when_unchecked():
    """An unchecked box (False, not absent — that's what the JS sends) and a
    payload that never mentions it must both mean 'not paid'."""
    assert tracker_push.build_payload({"mode": "prevod", "evidence_zaplaceno": False})["zaplaceno"] is False
    assert tracker_push.build_payload({"mode": "prevod"})["zaplaceno"] is False


def test_build_payload_forwards_note():
    p = tracker_push.build_payload({
        "mode": "zmena", "evidence_firma_id": "3", "evidence_typ": "KOLA",
        "evidence_poznamka": "  zimní sada  ",
    })
    assert p["poznamka"] == "zimní sada"                        # trimmed
    assert "poznamka" not in tracker_push.build_payload({"mode": "prevod"})


def test_build_payload_no_explicit_assignment():
    p = tracker_push.build_payload({"mode": "prevod", "novy_ico": "1"})
    assert "firma_id" not in p                 # absent → tracker auto-matches by IČO
    assert len(p["zadost_id"]) >= 16           # falls back to a fresh uuid


def test_build_payload_ignores_blank_or_bad_firma():
    assert "firma_id" not in tracker_push.build_payload({"mode": "prevod", "evidence_firma_id": ""})
    assert "firma_id" not in tracker_push.build_payload({"mode": "prevod", "evidence_firma_id": "abc"})


def test_fetch_meta_ok(monkeypatch):
    class _R:
        status_code = 200
        def json(self):
            return {"firmy": [{"id": 1, "nazev": "C"}], "typy": [], "ceny": {}}
    cap = {}
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", "k")
    monkeypatch.setattr(tracker_push.requests, "get",
                        lambda url, headers=None, timeout=None: (cap.update(url=url, headers=headers) or _R()))
    m = tracker_push.fetch_meta()
    assert m["firmy"][0]["id"] == 1
    assert cap["url"].endswith("/api/evidence-meta")
    assert cap["headers"]["X-Api-Key"] == "k"


def test_fetch_meta_none_on_failure(monkeypatch):
    monkeypatch.setattr(tracker_push, "UKONY_API_URL", "http://127.0.0.1:1")
    assert tracker_push.fetch_meta() is None    # never raises


def test_push_records_failure_when_unreachable(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker_push, "UKONY_API_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(tracker_push, "TIMEOUT", 0.2)
    monkeypatch.setattr(tracker_push, "RETRY_DELAYS", ())  # don't actually sleep in tests
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


# ── retries within a single push() ───────────────────────────────────────────

def test_push_retries_before_giving_up(tmp_path, monkeypatch):
    calls = []
    # Same NUMBER of retries as production (2), just zero-duration so the test
    # doesn't actually sleep.
    monkeypatch.setattr(tracker_push, "RETRY_DELAYS", (0, 0))

    def _flaky(url, json=None, headers=None, timeout=None):
        calls.append(1)
        raise ConnectionError("nope")

    monkeypatch.setattr(tracker_push.requests, "post", _flaky)
    res = tracker_push.push({"mode": "prevod"}, str(tmp_path))
    assert res is None
    assert len(calls) == 3  # first attempt + 2 retries (len(RETRY_DELAYS)+1)
    assert (tmp_path / "failed_pushes.jsonl").exists()


def test_push_succeeds_on_second_attempt_without_recording_failure(tmp_path, monkeypatch):
    attempts = {"n": 0}
    monkeypatch.setattr(tracker_push, "RETRY_DELAYS", (0,))

    class _Ok:
        status_code = 201
        def json(self):
            return {"status": "auto"}

    def _fake(url, json=None, headers=None, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("read timed out")
        return _Ok()

    monkeypatch.setattr(tracker_push.requests, "post", _fake)
    res = tracker_push.push({"mode": "prevod"}, str(tmp_path))
    assert res == {"status": "auto"}
    assert attempts["n"] == 2
    assert not (tmp_path / "failed_pushes.jsonl").exists()  # never recorded — it landed


# ── push_async: /api/generate must never block on the tracker ───────────────

def test_push_async_returns_immediately(tmp_path, monkeypatch):
    """The whole point: even a tracker that hangs for a full second must not
    make push_async's CALLER wait — that second-plus used to sit inside
    every /api/generate response."""
    import time as _time

    def _slow(url, json=None, headers=None, timeout=None):
        _time.sleep(1)
        class _R:
            status_code = 201
            def json(self_):
                return {"status": "auto"}
        return _R()

    monkeypatch.setattr(tracker_push.requests, "post", _slow)
    t0 = _time.time()
    tracker_push.push_async({"mode": "prevod"}, str(tmp_path))
    assert _time.time() - t0 < 0.2, "push_async must return before the network call finishes"


# ── retry_failed: the guarantee David asked for — it really lands ───────────

def test_retry_failed_clears_a_backlog_that_now_succeeds(tmp_path, monkeypatch):
    log = tmp_path / "failed_pushes.jsonl"
    log.write_text(
        json.dumps({"reason": "old timeout", "payload": {"zadost_id": "a", "mode": "prevod"}}) + "\n"
        + json.dumps({"reason": "old timeout", "payload": {"zadost_id": "b", "mode": "zapis"}}) + "\n",
        encoding="utf-8",
    )
    sent = []

    class _Ok:
        status_code = 200
        def json(self):
            return {"status": "duplicate"}  # tracker already has it — still a success

    def _fake(url, json=None, headers=None, timeout=None):
        sent.append(json["zadost_id"])
        return _Ok()

    monkeypatch.setattr(tracker_push.requests, "post", _fake)
    remaining = tracker_push.retry_failed(str(tmp_path))
    assert remaining == 0
    assert sorted(sent) == ["a", "b"]
    assert not log.exists()  # fully cleared


def test_retry_failed_keeps_only_the_ones_still_failing(tmp_path, monkeypatch):
    log = tmp_path / "failed_pushes.jsonl"
    log.write_text(
        json.dumps({"reason": "x", "payload": {"zadost_id": "ok", "mode": "prevod"}}) + "\n"
        + json.dumps({"reason": "x", "payload": {"zadost_id": "still-down", "mode": "zapis"}}) + "\n",
        encoding="utf-8",
    )

    class _Ok:
        status_code = 200
        def json(self):
            return {"status": "auto"}

    def _fake(url, json=None, headers=None, timeout=None):
        if json["zadost_id"] == "ok":
            return _Ok()
        raise ConnectionError("tracker still unreachable")

    monkeypatch.setattr(tracker_push.requests, "post", _fake)
    remaining = tracker_push.retry_failed(str(tmp_path))
    assert remaining == 1
    left = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert [l["payload"]["zadost_id"] for l in left] == ["still-down"]


def test_retry_failed_is_a_noop_with_no_backlog(tmp_path):
    assert tracker_push.retry_failed(str(tmp_path)) == 0


def test_retry_failed_skips_a_corrupt_line_instead_of_dying(tmp_path, monkeypatch):
    log = tmp_path / "failed_pushes.jsonl"
    log.write_text(
        "{not valid json\n"
        + json.dumps({"reason": "x", "payload": {"zadost_id": "ok", "mode": "prevod"}}) + "\n",
        encoding="utf-8",
    )

    class _Ok:
        status_code = 200
        def json(self):
            return {"status": "auto"}

    monkeypatch.setattr(tracker_push.requests, "post", lambda *a, **k: _Ok())
    assert tracker_push.retry_failed(str(tmp_path)) == 0
    assert not log.exists()


# ── start_sweep: idempotent, doesn't block, doesn't crash the process ───────

def test_start_sweep_is_idempotent(tmp_path, monkeypatch):
    """Two calls (e.g. two gunicorn workers importing app.py) must not start
    two loops — that would double-send every retry."""
    starts = []
    monkeypatch.setattr(tracker_push.threading, "Thread",
                        lambda target, daemon: starts.append(target) or type(
                            "T", (), {"start": lambda self: None})())
    monkeypatch.setattr(tracker_push, "_sweep_started", False)
    tracker_push.start_sweep(str(tmp_path), interval_s=9999)
    tracker_push.start_sweep(str(tmp_path), interval_s=9999)
    assert len(starts) == 1
