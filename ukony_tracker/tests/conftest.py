import sqlite3, pytest, db


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "t.db"
    c = db.connect(str(path))
    db.init_schema(c)
    yield c
    c.close()
