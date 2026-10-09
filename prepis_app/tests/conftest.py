import pytest
import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

@pytest.fixture(scope="session", autouse=True)
def no_real_http():
    """All tests must mock requests, including legacy localhost failures."""
    def blocked(*args, **kwargs):
        raise requests.ConnectionError("HTTP disabled in tests; mock requests")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(requests.sessions.Session, "request", blocked)
        yield

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
