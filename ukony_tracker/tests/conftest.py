import sqlite3, pytest, db


@pytest.fixture(autouse=True)
def clear_ai_environment(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ZEPTEJ_EFFORT", raising=False)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "t.db"
    c = db.connect(str(path))
    db.init_schema(c)
    yield c
    c.close()
