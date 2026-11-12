"""POST /api/ppd/<n>/sdilet — evidence „Sdílet kódem" u dokladu."""
import pytest

import app as A
import tracker_push

KLIC = "testovaci-klic-integrace"


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "heslo-jen-pro-test")
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", KLIC)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "ppd_7.pdf").write_bytes(b"%PDF-1.4 test")
    A._login_pokusy.clear()
    with A.app.test_client() as c:
        yield c
    A._login_pokusy.clear()


def _post(c, n=7, klic=KLIC):
    return c.post(f"/api/ppd/{n}/sdilet", headers={} if klic is None else {"X-Api-Key": klic})


def test_platny_klic_vrati_kod(api):
    r = _post(api)
    assert r.status_code == 200
    body = r.get_json()
    assert body["plati_dni"] == 30
    assert body["sdilet"].startswith("/") and body["sdilet"][1:].isalnum()
    # kód otevře doklad bez přihlášení
    assert api.get(body["sdilet"]).status_code == 200


def test_opakovani_vrati_stejny_kod(api):
    assert _post(api).get_json()["sdilet"] == _post(api).get_json()["sdilet"]


@pytest.mark.parametrize("klic", [None, "spatny"])
def test_spatny_klic_401(api, klic):
    assert _post(api, klic=klic).status_code == 401


def test_nezname_cislo_404_s_json_chybou(api):
    r = _post(api, n=999999)
    assert r.status_code == 404
    assert "error" in r.get_json()


def test_bez_nastaveneho_klice_503(api, monkeypatch):
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", "")
    assert _post(api).status_code == 503
