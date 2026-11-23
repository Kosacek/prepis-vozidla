import pytest

import app as zadosti


@pytest.fixture
def loga(tmp_path, monkeypatch):
    monkeypatch.setattr(zadosti, "DATA_DIR", str(tmp_path))
    return tmp_path / "loga"


def test_chybejici_adresar_i_soubor(client, loga):
    assert client.get("/api/firma-loga").json == {}
    assert client.get("/firma-logo/01234567").status_code == 404
    loga.mkdir()
    assert client.get("/firma-logo/01234567").status_code == 404


@pytest.mark.parametrize("ico", [
    "1234567", "123456789", "abcdefgh", "１２３４５６７８", "01234567.svg",
    "01234567%0A", "..%2F01234567", "..%5C01234567", "01234567%2F..",
])
def test_odmitne_neplatne_ico_a_pruchod_cestou(client, loga, ico):
    loga.mkdir()
    (loga / "01234567.svg").write_text("<svg/>", encoding="utf-8")
    (loga.parent / "01234567.svg").write_text("outside", encoding="utf-8")
    assert client.get(f"/firma-logo/{ico}").status_code == 404


def test_mapa_a_hlavicky_log(client, loga):
    loga.mkdir()
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    png = b"\x89PNG\r\n\x1a\n"
    for name, data in {
        "01234567.svg": svg, "01234567.png": png, "12345678.png": png,
        "abc.svg": svg, "12345678.gif": b"GIF", "１２３４５６７８.svg": svg,
    }.items():
        (loga / name).write_bytes(data)
    (loga / "87654321.svg").mkdir()
    assert client.get("/api/firma-loga").json == {"01234567": "svg", "12345678": "png"}

    with client.get("/firma-logo/01234567") as response:
        assert response.status_code == 200 and response.data == svg
        assert response.mimetype == "image/svg+xml"
        assert response.headers["Content-Security-Policy"] == "default-src 'none'; style-src 'unsafe-inline'"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.cache_control.max_age == 86400
        assert response.cache_control.private and not response.cache_control.public
    with client.get("/firma-logo/12345678") as response:
        assert response.status_code == 200 and response.data == png
        assert response.mimetype == "image/png"


def test_loga_vyzaduji_prihlaseni(client, loga, monkeypatch):
    monkeypatch.setattr(zadosti, "ADMIN_PASSWORD", "test-only")
    for path in ("/api/firma-loga", "/firma-logo/01234567"):
        response = client.get(path)
        assert response.status_code == 302 and response.location == "/login"
    with client.session_transaction() as session:
        session["authed"] = True
    assert client.get("/api/firma-loga").status_code == 200
