import pytest
import sys
import os
import threading
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
import tracker_push

_real_tracker_push_async = tracker_push.push_async

@pytest.fixture(scope="session", autouse=True)
def no_real_http():
    """All tests must mock requests, including legacy localhost failures."""
    def blocked(*args, **kwargs):
        raise requests.ConnectionError("HTTP disabled in tests; mock requests")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(requests.sessions.Session, "request", blocked)
        yield

@pytest.fixture
def client(monkeypatch):
    # The HTTP guard rejects every unmocked POST. Ordinary /api/generate tests
    # must not leave retry threads running into another test's HTTP mock.
    monkeypatch.setattr(tracker_push, "push_async", lambda data, data_dir: None)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def pending_tracker_post(monkeypatch):
    """Exercise the real async sender and join it before restoring its POST mock."""
    workers = []
    entered = threading.Event()
    release = threading.Event()

    class Response:
        status_code = 201

        def json(self):
            return {"status": "auto"}

    def post(*args, **kwargs):
        workers.append(threading.current_thread())
        entered.set()
        release.wait(5)
        return Response()

    monkeypatch.setattr(tracker_push, "push_async", _real_tracker_push_async)
    monkeypatch.setattr(tracker_push.requests, "post", post)
    try:
        yield entered
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
            assert not worker.is_alive()
