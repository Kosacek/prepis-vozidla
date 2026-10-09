"""PPD mapping, best-effort delivery, sweep integration and historical import."""
import json
import threading

import pytest

import ppd_push
import tracker_push
from scripts import ppd_do_evidence as backfill


class Response:
    def __init__(self, status=200, body=None, text="unavailable"):
        self.status_code = status
        self.body = {} if body is None else body
        self.text = text

    def json(self):
        return self.body


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    monkeypatch.setattr(ppd_push, "RETRY_DELAYS", ())


def record(cislo=412):
    return ppd_push.build_record({
        "cislo": cislo, "date": "08.10.2026", "payer": "ALBION S.R.O.",
        "payer_ico": "12345678", "amount": 1300, "purpose": "Zastupování na MMB",
        "vehicle": "1AB2345",
    }, zadost_id="shared-id")


def test_build_record_issue_shape():
    assert record() == {
        "cislo": 412, "datum": "08.10.2026", "prijato_od": "ALBION S.R.O.",
        "prijato_ico": "12345678", "castka": 1300, "ucel": "Zastupování na MMB",
        "vozidlo": "1AB2345", "zadost_id": "shared-id", "smazano": False,
    }


def test_build_record_backup_shape():
    row = {
        "cislo": "413", "datum": "2026-10-08", "prijato_od": "Firma",
        "ico": "01234567", "castka": "1 300,00", "ucel": "MMB",
        "spz": " 1AB2345 ", "vin": "VIN", "adresa": "private address",
    }
    body = ppd_push.build_record(row, smazano=True)
    assert body == {
        "cislo": 413, "datum": "2026-10-08", "prijato_od": "Firma",
        "prijato_ico": "01234567", "castka": 1300, "ucel": "MMB",
        "vozidlo": "1AB2345", "zadost_id": "", "smazano": True,
    }
    assert row["castka"] == "1 300,00"  # does not mutate the backup


@pytest.mark.parametrize("field", ["amount", "castka"])
@pytest.mark.parametrize("amount,expected", [
    ("1 300", 1300), ("1300,00", 1300), ("1\u00a0300,60", 1301),
    (1300.6, 1301), (1300.4, 1300), (1300.5, 1300),
    (None, 0), ("", 0), ("invalid", 0), ("nan", 0), ("inf", 0), (-1, 0),
])
def test_build_record_amount_is_nonnegative_int(field, amount, expected):
    body = ppd_push.build_record({"cislo": 1, field: amount})
    assert type(body["castka"]) is int
    assert body["castka"] == expected


@pytest.mark.parametrize("vehicle_fields,expected", [
    ({"spz": "RZ", "vin": "VIN"}, "RZ"),
    ({"spz": None, "vin": "VIN"}, "VIN"),
    ({"spz": "  ", "vin": " VIN "}, "VIN"),
    ({"vehicle": "RZ, RZ2"}, "RZ, RZ2"),
    ({"vozidlo": "ledger VIN"}, "ledger VIN"),
    ({}, ""),
])
def test_build_record_vehicle_fallback(vehicle_fields, expected):
    assert ppd_push.build_record({"number": 1, **vehicle_fields})["vozidlo"] == expected


@pytest.mark.parametrize("status", [200, 201, 202, 204, 299])
def test_push_success_sends_contract_and_shared_config(tmp_path, monkeypatch, status):
    sent = []
    monkeypatch.setattr(ppd_push, "UKONY_API_URL", "http://evidence.test")
    monkeypatch.setattr(ppd_push, "UKONY_API_KEY", "test-key")
    def put(url, **kwargs):
        sent.append((url, kwargs))
        return Response(status, {"cislo": 412})
    monkeypatch.setattr(ppd_push.requests, "put", put)
    body = record()
    assert ppd_push.push(body, str(tmp_path)) == {"cislo": 412}
    assert sent == [("http://evidence.test/api/ppd/412", {
        "json": body, "headers": {"X-Api-Key": "test-key"}, "timeout": ppd_push.TIMEOUT,
    })]
    assert not (tmp_path / "failed_ppd_pushes.jsonl").exists()


def test_push_queues_response_decoding_exception(tmp_path, monkeypatch):
    class EmptyResponse(Response):
        def json(self):
            raise ValueError("empty body")
    monkeypatch.setattr(ppd_push.requests, "put", lambda *a, **k: EmptyResponse(204))
    body = record()
    assert ppd_push.push(body, str(tmp_path)) is None
    entry = json.loads((tmp_path / "failed_ppd_pushes.jsonl").read_text(encoding="utf-8"))
    assert entry == {"reason": "empty body", "record": body}


@pytest.mark.parametrize("failure", ["exception", 301, 400, 404, 500])
def test_push_failures_are_queued_once_after_retries(tmp_path, monkeypatch, failure):
    calls = []
    delays = []
    monkeypatch.setattr(ppd_push, "RETRY_DELAYS", (1, 4))
    monkeypatch.setattr(ppd_push.time, "sleep", delays.append)
    def put(*args, **kwargs):
        calls.append(kwargs["json"])
        if failure == "exception":
            raise RuntimeError("evidence down")
        return Response(failure)
    monkeypatch.setattr(ppd_push.requests, "put", put)
    body = record()
    assert ppd_push.push(body, str(tmp_path)) is None
    assert calls == [body, body, body]
    assert delays == [1, 4]
    entries = [json.loads(line) for line in (tmp_path / "failed_ppd_pushes.jsonl").read_text(
        encoding="utf-8").splitlines()]
    reason = "evidence down" if failure == "exception" else f"HTTP {failure}: unavailable"
    assert entries == [{"reason": reason, "record": body}]
    assert (tmp_path / "failed_ppd_pushes.jsonl.lock").exists()


def test_push_transient_failure_then_success_does_not_queue(tmp_path, monkeypatch):
    replies = iter([Response(500), Response(201, {"cislo": 412})])
    monkeypatch.setattr(ppd_push, "RETRY_DELAYS", (0,))
    monkeypatch.setattr(ppd_push.requests, "put", lambda *a, **k: next(replies))
    assert ppd_push.push(record(), str(tmp_path)) == {"cislo": 412}
    assert not (tmp_path / "failed_ppd_pushes.jsonl").exists()


def test_push_does_not_raise_if_queue_cannot_be_written(tmp_path, monkeypatch):
    monkeypatch.setattr(ppd_push.requests, "put", lambda *a, **k: Response(404))
    def unavailable(*args):
        raise OSError("unwritable data directory")
    monkeypatch.setattr(ppd_push, "_with_lock", unavailable)
    assert ppd_push.push(record(), str(tmp_path)) is None


def test_push_async_returns_while_http_is_pending(tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    def put(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return Response(201)
    original = ppd_push.push
    def push(*args):
        try:
            return original(*args)
        finally:
            finished.set()
    monkeypatch.setattr(ppd_push.requests, "put", put)
    monkeypatch.setattr(ppd_push, "push", push)
    try:
        ppd_push.push_async(record(), str(tmp_path))
        assert entered.wait(1)
        assert not finished.is_set()
    finally:
        release.set()
        assert finished.wait(2)


def test_retry_failed_resends_all_and_drops_only_successes(tmp_path, monkeypatch):
    log = tmp_path / "failed_ppd_pushes.jsonl"
    bodies = [record(n) for n in (1, 2, 3)]
    log.write_text("".join(json.dumps({"reason": "old", "record": body}) + "\n"
                           for body in bodies), encoding="utf-8")
    sent = []
    def put(url, **kwargs):
        body = kwargs["json"]
        sent.append(body)
        if body["cislo"] == 3:
            raise RuntimeError("still down")
        return Response(201 if body["cislo"] == 1 else 404)
    monkeypatch.setattr(ppd_push.requests, "put", put)
    assert ppd_push.retry_failed(str(tmp_path)) == 2
    assert sent == bodies
    remaining = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [entry["record"]["cislo"] for entry in remaining] == [2, 3]
    assert [entry["reason"] for entry in remaining] == ["HTTP 404: unavailable", "still down"]
    monkeypatch.setattr(ppd_push.requests, "put", lambda *a, **k: Response())
    assert ppd_push.retry_failed(str(tmp_path)) == 0
    assert not log.exists()


def test_retry_failed_no_backlog(tmp_path):
    assert ppd_push.retry_failed(str(tmp_path)) == 0


def test_retry_failed_keeps_corrupt_entries(tmp_path):
    log = tmp_path / "failed_ppd_pushes.jsonl"
    log.write_text("{invalid json\n", encoding="utf-8")
    assert ppd_push.retry_failed(str(tmp_path)) == 1
    assert log.read_text(encoding="utf-8") == "{invalid json\n"


def test_failure_append_and_sweep_use_exclusive_flock(tmp_path, monkeypatch):
    locks = []
    class Flock:
        LOCK_EX = 1
        LOCK_UN = 2
        @staticmethod
        def flock(fd, operation):
            locks.append(operation)
    monkeypatch.setattr(ppd_push, "fcntl", Flock, raising=False)
    monkeypatch.setattr(ppd_push, "_HAVE_FCNTL", True)
    monkeypatch.setattr(ppd_push.requests, "put", lambda *a, **k: Response(404))
    ppd_push.push(record(), str(tmp_path))
    monkeypatch.setattr(ppd_push.requests, "put", lambda *a, **k: Response())
    assert ppd_push.retry_failed(str(tmp_path)) == 0
    assert locks == [Flock.LOCK_EX, Flock.LOCK_UN, Flock.LOCK_EX, Flock.LOCK_UN]


@pytest.mark.parametrize("failing", ["tracker", "ppd", None])
def test_existing_sweep_runs_both_independently(tmp_path, monkeypatch, failing):
    loops = []
    calls = []
    def retry(name):
        def run(data_dir):
            assert data_dir == str(tmp_path)
            calls.append(name)
            if name == failing:
                raise RuntimeError("sweep error")
            return 0
        return run
    class Thread:
        def __init__(self, target, daemon):
            assert daemon is True
            loops.append(target)
        def start(self):
            pass
    class StopLoop(BaseException):
        pass
    def sleep(seconds):
        assert seconds == 123
        raise StopLoop
    monkeypatch.setattr(tracker_push, "_sweep_started", False)
    monkeypatch.setattr(tracker_push, "retry_failed", retry("tracker"))
    monkeypatch.setattr(ppd_push, "retry_failed", retry("ppd"))
    monkeypatch.setattr(tracker_push.threading, "Thread", Thread)
    monkeypatch.setattr(tracker_push.time, "sleep", sleep)
    tracker_push.start_sweep(str(tmp_path), interval_s=123)
    tracker_push.start_sweep(str(tmp_path), interval_s=123)
    assert len(loops) == 1
    with pytest.raises(StopLoop):
        loops[0]()
    assert calls == ["tracker", "ppd"]


def mock_history(monkeypatch, tmp_path, count):
    rows = [{"cislo": n, "datum": "08.10.2026", "prijato_od": "Firma",
             "ico": "01234567", "castka": "1 300,00", "ucel": "MMB",
             "spz": "RZ", "vin": "VIN"} for n in range(1, count + 1)]
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("UKONY_API_URL", "http://evidence.test/")
    monkeypatch.setenv("UKONY_API_KEY", "test-import-key")
    def backup(data_dir):
        assert data_dir == str(tmp_path)
        return rows
    monkeypatch.setattr(backfill.ppd, "read_backup", backup)
    monkeypatch.setattr(backfill.ppd, "read_ppd_log", lambda dd: [{"cislo": 1}])


def test_backfill_dry_run_prints_counts_and_first_three_without_http(tmp_path, monkeypatch, capsys):
    mock_history(monkeypatch, tmp_path, 5)
    monkeypatch.delenv("UKONY_API_KEY")  # dry run needs no credentials
    def no_http(*args, **kwargs):
        pytest.fail("dry run attempted HTTP")
    monkeypatch.setattr(backfill.requests, "post", no_http)
    assert backfill.main(["--dry-run"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Doklady: 5 / zive: 1 / smazane: 4 / chyby: 0"
    bodies = [json.loads(line) for line in lines[1:]]
    assert [body["cislo"] for body in bodies] == [1, 2, 3]
    assert [body["smazano"] for body in bodies] == [False, True, True]
    assert all(type(body["castka"]) is int for body in bodies)


def test_backfill_batches_200_and_reports_totals_and_errors(tmp_path, monkeypatch, capsys):
    mock_history(monkeypatch, tmp_path, 401)
    sent = []
    def post(url, **kwargs):
        assert url == "http://evidence.test/api/ppd/import"
        assert kwargs["headers"] == {"X-Api-Key": "test-import-key"}
        assert kwargs["timeout"] == ppd_push.TIMEOUT
        sent.append(kwargs["json"]["doklady"])
        if len(sent) == 1:
            return Response(body={"vytvoreno": 199, "aktualizovano": 0,
                                  "chyby": [{"cislo": 2, "error": "bad record"}]})
        return Response(body={"vytvoreno": 0, "aktualizovano": len(sent[-1]), "chyby": []})
    monkeypatch.setattr(backfill.requests, "post", post)
    assert backfill.main([]) == 1
    assert [len(batch) for batch in sent] == [200, 200, 1]
    assert [body["cislo"] for batch in sent for body in batch] == list(range(1, 402))
    assert sent[0][0]["smazano"] is False
    assert sent[-1][0]["smazano"] is True
    output = capsys.readouterr().out
    assert "Davka 1/3: vytvoreno=199 / aktualizovano=0 / chyby=1" in output
    assert "Davka 3/3: vytvoreno=0 / aktualizovano=1 / chyby=0" in output
    assert "Celkem: vytvoreno=199 / aktualizovano=201 / chyby=1" in output
    assert '"cislo": 2, "error": "bad record"' in output
    assert "test-import-key" not in output


@pytest.mark.parametrize("failure", ["exception", 404])
def test_backfill_http_failure_is_reported_without_key(tmp_path, monkeypatch, capsys, failure):
    mock_history(monkeypatch, tmp_path, 2)
    def post(*args, **kwargs):
        if failure == "exception":
            raise RuntimeError("transport failure test-import-key")
        return Response(404, text="missing endpoint test-import-key")
    monkeypatch.setattr(backfill.requests, "post", post)
    assert backfill.main([]) == 1
    output = capsys.readouterr().out
    assert "Celkem: vytvoreno=0 / aktualizovano=0 / chyby=2" in output
    assert "test-import-key" not in output
    assert '"cislo": 1' in output and '"cislo": 2' in output


def test_backfill_success(tmp_path, monkeypatch, capsys):
    mock_history(monkeypatch, tmp_path, 1)
    monkeypatch.setattr(backfill.requests, "post", lambda *a, **k: Response(body={
        "vytvoreno": 1, "aktualizovano": 0, "chyby": [],
    }))
    assert backfill.main([]) == 0
    assert "Celkem: vytvoreno=1 / aktualizovano=0 / chyby=0" in capsys.readouterr().out
