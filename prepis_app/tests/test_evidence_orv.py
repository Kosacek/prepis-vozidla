"""„Přidat do evidence" ze skenu ORV (evidence_orv.py + /api/evidence/*).

Hledání a doplnění volají endpointy, které evidence teprve dostane (spec v
ukony_tracker/docs/superpowers/specs/2026-10-08-...). Dokud neexistují, musí
appka zůstat použitelná — nabídne jen nový úkon.
"""
import json
from datetime import date

import pytest
import requests

import app as A
import evidence_orv as E
import tracker_push


class _R:
    def __init__(self, status, body=None, html=False):
        self.status_code = status
        self._body = body
        self._html = html
        self.text = "<html>404</html>" if html else json.dumps(body)

    def json(self):
        if self._html:
            raise ValueError("not json")
        return self._body


@pytest.fixture
def evidence(monkeypatch):
    """Podvržená evidence: nastav odpovědi, čti, co se poslalo."""
    st = {"odpoved": _R(200, {}), "volani": []}
    monkeypatch.setattr(tracker_push, "UKONY_API_URL", "http://evidence.test")
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", "tajny-klic")

    def zaznam(metoda):
        def f(url, params=None, json=None, headers=None, timeout=None):
            st["volani"].append({"metoda": metoda, "url": url, "params": params,
                                 "json": json, "headers": headers or {}})
            o = st["odpoved"]
            if isinstance(o, Exception):
                raise o
            return o
        return f
    monkeypatch.setattr(E.requests, "get", zaznam("GET"))
    monkeypatch.setattr(E.requests, "post", zaznam("POST"))
    return st


# ── hledání ──────────────────────────────────────────────────────────────────

def test_dokud_evidence_hledani_neumi_appka_jen_nabidne_novy_ukon(evidence):
    evidence["odpoved"] = _R(404, html=True)          # endpoint ještě neexistuje
    assert E.hledat("TMBEK6NW7M3158470", None) == {"k_dispozici": False, "ukony": []}


def test_nalezene_ukony_se_vrati(evidence):
    evidence["odpoved"] = _R(200, {"ukony": [{"id": 5, "rz": None}]})
    out = E.hledat("tmbek6nw7m3158470", " 1ab 2345 ")
    assert out == {"k_dispozici": True, "ukony": [{"id": 5, "rz": None}]}
    v = evidence["volani"][0]
    assert v["url"] == "http://evidence.test/api/ukony/hledat"
    assert v["params"] == {"vin": "TMBEK6NW7M3158470", "rz": "1AB2345"}
    assert v["headers"]["X-Api-Key"] == "tajny-klic"


def test_bez_vin_i_rz_se_nehleda(evidence):
    with pytest.raises(E.EvidenceError) as e:
        E.hledat("", None)
    assert e.value.status == 400 and evidence["volani"] == []


def test_evidence_mimo_provoz_da_srozumitelnou_chybu(evidence):
    evidence["odpoved"] = requests.ConnectionError("down")
    with pytest.raises(E.EvidenceError, match="neodpovídá"):
        E.hledat("TMBEK6NW7M3158470", None)


# ── doplnění ─────────────────────────────────────────────────────────────────

def test_doplneni_posle_normalizovanou_rz_a_orv(evidence):
    evidence["odpoved"] = _R(200, {"id": 7, "rz": "1AB2345", "orv": "UBE037263", "zmeneno": ["rz", "orv"]})
    out = E.doplnit("7", "1ab-2345", "ube 037263")
    assert out["zmeneno"] == ["rz", "orv"]
    v = evidence["volani"][0]
    assert v["url"] == "http://evidence.test/api/ukony/7/doplnit"
    assert v["json"] == {"rz": "1AB2345", "orv": "UBE037263"}


def test_jina_rz_v_ukonu_se_neprepise_a_uzivatel_vidi_stavajici(evidence):
    evidence["odpoved"] = _R(409, {"error": "RZ už je vyplněná jinak.", "pole": "rz", "stavajici": "9ZZ9999"})
    with pytest.raises(E.EvidenceError) as e:
        E.doplnit(7, "1AB2345")
    assert e.value.status == 409
    assert e.value.data == {"pole": "rz", "stavajici": "9ZZ9999"}


def test_dve_ruzne_404_se_neplety(evidence):
    """Úkon neexistuje (JSON) vs. endpoint ještě neexistuje (holá 404)."""
    evidence["odpoved"] = _R(404, {"error": "Úkon nenalezen."})
    with pytest.raises(E.EvidenceError, match="neexistuje") as e1:
        E.doplnit(7, "1AB2345")
    assert e1.value.status == 404
    evidence["odpoved"] = _R(404, html=True)
    with pytest.raises(E.EvidenceError, match="zatím není") as e2:
        E.doplnit(7, "1AB2345")
    assert e2.value.status == 501


@pytest.mark.parametrize("rz, orv", [("X", None), (None, "12345678"), (None, None)])
def test_spatne_hodnoty_se_do_evidence_vubec_neposlou(evidence, rz, orv):
    with pytest.raises(E.EvidenceError) as e:
        E.doplnit(7, rz, orv)
    assert e.value.status == 400 and evidence["volani"] == []


# ── nový úkon ────────────────────────────────────────────────────────────────

def test_novy_ukon_jde_pres_prichozi_s_vyslovnou_firmou(evidence):
    evidence["odpoved"] = _R(201, {"status": "auto", "ukon_id": 99})
    out = E.zalozit(vin="TMBEK6NW7M3158470", rz="1AB2345", orv="UBE037263",
                    firma_id="3", typ_kod="NOVÉ", celkem="1300", poznamka=" EL ",
                    zaplaceno=True, profil="Roman")
    assert out == {"status": "auto", "ukon_id": 99}
    v = evidence["volani"][0]
    assert v["url"] == "http://evidence.test/api/prichozi"
    p = v["json"]
    assert p["mode"] == "orv" and p["firma_id"] == 3 and p["typ_kod"] == "NOVÉ"
    assert p["celkem"] == 1300.0 and p["zaplaceno"] is True and p["profil"] == "Roman"
    assert p["orv"] == "UBE037263" and p["poznamka"] == "EL"
    assert p["datum"] == date.today().isoformat()
    assert p["zadost_id"].startswith("orv-"), "bez id by dvojklik založil dva úkony"


def test_spatne_prectene_cislo_orv_nezablokuje_ukon(evidence):
    evidence["odpoved"] = _R(201, {"status": "auto", "ukon_id": 1})
    E.zalozit(vin="TMBEK6NW7M3158470", firma_id=1, typ_kod="NOVÉ", orv="U8E03726")
    assert evidence["volani"][0]["json"]["orv"] is None


def test_prazdna_cena_necha_cenu_na_evidenci(evidence):
    evidence["odpoved"] = _R(201, {"status": "auto", "ukon_id": 1})
    E.zalozit(vin="TMBEK6NW7M3158470", firma_id=1, typ_kod="NOVÉ", celkem="")
    assert evidence["volani"][0]["json"]["celkem"] is None


@pytest.mark.parametrize("kw, hlaska", [
    ({"firma_id": None, "typ_kod": "NOVÉ"}, "firmu"),
    ({"firma_id": 1, "typ_kod": ""}, "typ"),
    ({"firma_id": 1, "typ_kod": "NOVÉ", "celkem": "-5"}, "záporná"),
])
def test_neuplny_ukon_se_neodesle(evidence, kw, hlaska):
    with pytest.raises(E.EvidenceError, match=hlaska):
        E.zalozit(vin="TMBEK6NW7M3158470", **kw)
    assert evidence["volani"] == []


# ── trasy ────────────────────────────────────────────────────────────────────

def test_trasa_vrati_chybu_i_s_podrobnostmi(client, evidence):
    evidence["odpoved"] = _R(409, {"error": "RZ už je vyplněná jinak.", "pole": "rz", "stavajici": "9ZZ9999"})
    r = client.post("/api/evidence/doplnit", json={"id": 7, "rz": "1AB2345"})
    assert r.status_code == 409
    assert r.get_json() == {"success": False, "error": "RZ už je vyplněná jinak.",
                            "pole": "rz", "stavajici": "9ZZ9999"}


def test_klic_k_evidenci_se_do_prohlizece_nedostane(client, evidence):
    evidence["odpoved"] = _R(200, {"ukony": []})
    r = client.get("/api/evidence/hledat?vin=TMBEK6NW7M3158470")
    assert r.get_json()["success"] is True
    assert "tajny-klic" not in r.get_data(as_text=True)


def test_trasy_jsou_za_prihlasenim(monkeypatch):
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "heslo")
    cizi = A.app.test_client()
    H = {"CF-Visitor": '{"scheme":"https"}'}
    for metoda, cesta in [("get", "/api/evidence/hledat?vin=X"),
                          ("post", "/api/evidence/doplnit"), ("post", "/api/evidence/zalozit")]:
        r = getattr(cizi, metoda)(cesta, base_url="https://zadosti.spznaklic.cz", headers=H)
        assert r.status_code == 302 and r.headers["Location"] == "/login", cesta
