from __future__ import annotations

import io
import json
import threading
from datetime import date, datetime

import pytest
from pypdf import PdfReader, PdfWriter

import app as A
import faktura
import faktura_pdf
import hledani
import ppd
import ppd_api
import ppd_push
import sdileni
import storno
import tracker_push
from scripts import ppd_do_evidence
from tests.test_generate_faktura import IBAN, _payload
from tests.test_ppd_api import KLIC, TELO, api

HLAVICKY = {"X-Api-Key": KLIC}


def _vystav(api, monkeypatch, druh="faktura", **navic):
    monkeypatch.setenv("FAKTURA_IBAN", "CZ6508000000192000145399")
    monkeypatch.setenv("FAKTURA_UCET", "19-2000145399/0800")
    telo = {**TELO, "druh": druh, **navic}
    r = api.post("/api/ppd/vystavit", headers=HLAVICKY, json=telo)
    assert r.status_code == 201, r.get_json()
    api.poslano.clear()
    return r.get_json()["doklad"]


def _prihlas(api):
    assert api.post("/login", data={"password": "heslo-jen-pro-test"}).status_code == 302


def _zmen(api, cislo, akce, kdo):
    r = api.post(f"/api/doklady/{cislo}/{akce}", json={"kdo": kdo})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


@pytest.mark.parametrize("druh", ["faktura", "ppd"])
def test_storno_a_obnoveni_dokladu(api, monkeypatch, druh):
    doklad = _vystav(api, monkeypatch, druh, zadost_id="zadost-123")
    cislo = doklad["cislo"]
    dd = str(api.data)
    _prihlas(api)

    faktura_soubory = [api.data / name for name in (faktura.EVIDENCE_NAME, faktura.BACKUP_NAME)]
    puvodni = [path.read_bytes() for path in faktura_soubory] if druh == "faktura" else []
    vysledek = {"success": True, "druh": druh, "cislo": cislo, "storno": True, "zmeneno": True}
    assert _zmen(api, cislo, "odebrat", "  = DÁŠA  ") == vysledek
    assert _zmen(api, cislo, "odebrat", "JANA") == {**vysledek, "zmeneno": False}
    assert api.get("/api/ppd-list").get_json() == []

    cas = storno.stav(dd)[druh, cislo]["storno_cas"]
    assert datetime.fromisoformat(cas).microsecond == 0
    ocekavany_push = {
        "cislo": cislo, "datum": doklad["datum"], "prijato_od": "JE & NE, SPOL. S R.O.",
        "prijato_ico": "44960263", "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB",
        "vozidlo": "3BR9309, 3BR7164", "zadost_id": "", "smazano": True,
        "storno_cas": cas, "storno_kdo": "DÁŠA",
    }
    if druh == "faktura":
        ocekavany_push.update(druh="faktura", splatnost=doklad["splatnost"], zadost_id="zadost-123")
        assert faktura.read_faktura_log(dd) == []
        assert faktura.read_faktura_log(dd, include_stornovane=True)[0]["cislo"] == cislo
        assert [path.read_bytes() for path in faktura_soubory] == puvodni
        dalsi = _vystav_dalsi_fakturu(api)
        assert dalsi == faktura.cislo_z_poradi(date.today().year, 2)
    assert api.get("/api/doklady-stornovane").get_json() == [{
        "druh": druh, "cislo": cislo, "prijato_od": ocekavany_push["prijato_od"],
        "datum": doklad["datum"], "castka": 2600, "vozidlo": "3BR9309, 3BR7164",
        "storno_cas": cas, "storno_kdo": "DÁŠA",
    }]
    assert api.poslano == [ocekavany_push, ocekavany_push]

    assert _zmen(api, cislo, "obnovit", "JANA") == {**vysledek, "storno": False}
    assert _zmen(api, cislo, "obnovit", "DAVID") == {**vysledek, "storno": False, "zmeneno": False}
    assert api.get("/api/doklady-stornovane").get_json() == []
    assert cislo in {r["cislo"] for r in api.get("/api/ppd-list").get_json()}
    obnoveno = {**ocekavany_push, "smazano": False, "storno_cas": "", "storno_kdo": ""}
    assert api.poslano == [ocekavany_push, ocekavany_push, obnoveno, obnoveno]
    assert storno.stav(dd)[druh, cislo]["storno_kdo"] == "JANA"
    udalosti = [json.loads(line) for line in (api.data / storno.LOG_NAME).read_bytes().splitlines()]
    assert [u["akce"] for u in udalosti] == ["storno", "obnoveno"]


def _vystav_dalsi_fakturu(api):
    r = api.post("/api/ppd/vystavit", headers=HLAVICKY,
                 json={**TELO, "druh": "faktura", "request_id": "dalsi"})
    assert r.status_code == 201
    return r.get_json()["cislo"]


@pytest.mark.parametrize("json_data, kdo", [(None, "evidence"), ({"kdo": "  =David  "}, "David")])
def test_evidence_stornuje_fakturu(api, monkeypatch, json_data, kdo):
    n = _vystav(api, monkeypatch)["cislo"]
    url = f"/api/ppd/{n}/smazat"
    assert api.post(url).status_code == 401
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", "")
    assert api.post(url, headers=HLAVICKY).status_code == 503
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", KLIC)
    for removed in (True, False):
        r = api.post(url, headers=HLAVICKY, json=json_data)
        assert r.status_code == 200 and r.get_json() == {"removed": removed}
    assert len(api.poslano) == 2 and api.poslano[0] == api.poslano[1]
    assert api.poslano[0]["storno_kdo"] == kdo and api.poslano[0]["zadost_id"] == ""
    r = api.post("/api/ppd/vystavit", headers=HLAVICKY, json={**TELO, "druh": "faktura"})
    assert r.status_code == 409


@pytest.mark.parametrize("druh", ["faktura", "ppd"])
@pytest.mark.parametrize("akce", ["odebrat", "obnovit"])
def test_storno_bez_ulozeneho_pushe_nezmeni_stav(api, monkeypatch, druh, akce):
    n = _vystav(api, monkeypatch, druh)["cislo"]
    dd = str(api.data)
    _prihlas(api)
    if akce == "obnovit":
        _zmen(api, n, "odebrat", "DAVID")
        api.poslano.clear()
    journal = storno.stav(dd)
    kniha = api.get("/api/ppd-list").get_json()

    def nedostupna_fronta(*args):
        raise OSError("queue write failed")

    monkeypatch.setattr(ppd_push, "enqueue", nedostupna_fronta)
    r = api.post(f"/api/doklady/{n}/{akce}")
    assert r.status_code == 500
    assert r.get_json() == {"success": False, "error": "Storno se nepodařilo uložit."}
    if akce == "odebrat":
        r = api.post(f"/api/ppd/{n}/smazat", headers=HLAVICKY)
        assert r.status_code == 500 and r.get_json() == {"removed": False}
    assert storno.stav(dd) == journal
    assert api.get("/api/ppd-list").get_json() == kniha
    assert api.poslano == []


def _text(pdf):
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def test_pdf_stornovane_faktury_ve_vsech_cestach(api, monkeypatch):
    n = _vystav(api, monkeypatch)["cislo"]
    soubor = f"faktura_{n}.pdf"
    original = (api.data / "output" / soubor).read_bytes()
    assert "QR Platba" in _text(original)
    legacy = sdileni.vytvor_token(str(api.data), [soubor])
    _prihlas(api)
    assert api.get(f"/download/{soubor}").data == original
    _zmen(api, n, "odebrat", "DAVID")
    udalost = storno.stav(str(api.data))["faktura", n]
    datum = datetime.fromisoformat(udalost["storno_cas"]).strftime("%d.%m.%Y")

    def qr(*args):
        pytest.fail("Stornované PDF nesmí vykreslit QR.")

    monkeypatch.setattr(faktura_pdf, "_draw_qr", qr)
    with A.app.test_client() as public:
        kod = sdileni.kod_faktury(n)
        for url in (f"/{n}", f"/{kod}"):
            page = public.get(url)
            assert page.status_code == 200 and "STORNO" in page.get_data(as_text=True)
            assert "nahled/1?storno=1" in page.get_data(as_text=True)
            assert page.headers["Cache-Control"] == "no-store"
        for url in (f"/{kod}/0", f"/{n}/0?stahnout=1", f"/{kod}/vse", f"/s/{legacy}"):
            _over_storno_pdf(public.get(url), original, datum)
        preview = public.get(f"/{n}/0/nahled/1")
        assert preview.status_code == 200 and preview.mimetype == "image/png"
        assert preview.headers["Cache-Control"] == "no-store"
    for url in (f"/download/{soubor}", f"/faktura-print/{n}"):
        _over_storno_pdf(api.get(url), original, datum)

    for telo in (None, {"druh": "faktura"}):
        r = api.post(f"/api/ppd/{n}/sdilet", headers=HLAVICKY, json=telo)
        assert r.status_code == 409 and r.get_json() == {"error": f"Faktura č. {n} je stornovaná."}
    assert api.post("/api/sdilet", json={"soubory": [soubor]}).status_code == 409
    assert (api.data / "output" / soubor).read_bytes() == original


def _over_storno_pdf(r, original, datum):
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    assert "no-store" in r.headers["Cache-Control"]
    assert r.data != original and b"SPD*" not in r.data
    obsah = _text(r.data)
    assert "STORNO" in obsah and f"Stornováno {datum}" in obsah
    for platebni_udaj in ("QR Platba", "IBAN", "Číslo účtu", "Variabilní symbol",
                          "Datum splatnosti", "Forma úhrady", "Celkem k úhradě", "SPD*"):
        assert platebni_udaj not in obsah


@pytest.mark.parametrize("faktura_existuje", [True, False])
def test_indexy_baliku_faktury_a_zadosti_respektuji_existenci_souboru(api, monkeypatch, faktura_existuje):
    n = _vystav(api, monkeypatch)["cislo"]
    dd = str(api.data)
    faktura_pdf = api.data / "output" / f"faktura_{n}.pdf"
    zadost = faktura_pdf.with_name("zmeny_TEST.pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with zadost.open("wb") as f:
        writer.write(f)
    kod = sdileni.vytvor_kod(dd, [faktura_pdf.name, zadost.name])
    if not faktura_existuje:
        faktura_pdf.unlink()
    url = f"/{kod}/{int(faktura_existuje)}"
    _prihlas(api)
    public = A.app.test_client()
    assert public.get(url).data == zadost.read_bytes()
    _zmen(api, n, "odebrat", "DAVID")
    assert public.get(url).data == zadost.read_bytes()
    assert ("STORNO" in public.get(f"/{kod}").get_data(as_text=True)) == faktura_existuje
    if faktura_existuje:
        assert "STORNO" in _text(public.get(f"/{kod}/0").data)
        faktura_pdf.unlink()
        assert public.get(f"/{kod}/0").data == zadost.read_bytes()
    assert public.get(f"/{kod}/1").status_code == 404


def test_stary_ppd_bez_udalosti_a_kompatibilni_cesty(api, monkeypatch):
    n = _vystav(api, monkeypatch, "ppd")["cislo"]
    assert ppd.delete_ppd(str(api.data), n)
    _prihlas(api)
    row, = api.get("/api/doklady-stornovane").get_json()
    assert row["storno_cas"] == row["storno_kdo"] == ""
    assert api.post(f"/api/ppd/{n}/restore").get_json() == {"success": True, "restored": True}
    assert api.delete(f"/api/ppd/{n}").get_json() == {"success": True, "removed": True}
    assert api.get("/api/ppd-deleted").get_json()[0]["cislo"] == n


def test_neprihlaseneho_presmeruje_a_neznamy_doklad_404(api):
    for akce in ("odebrat", "obnovit"):
        r = api.post(f"/api/doklady/1/{akce}", headers=HLAVICKY)
        assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    assert api.get("/api/doklady-stornovane").status_code == 302
    _prihlas(api)
    for akce in ("odebrat", "obnovit"):
        assert api.post(f"/api/doklady/1/{akce}").status_code == 404
    assert api.poslano == []


def test_dve_vlakna_pripoji_udalosti_a_posledni_plati(tmp_path):
    path = tmp_path / storno.LOG_NAME
    path.write_bytes(b"null\n\xff\n{nedokonceno")
    bariera = threading.Barrier(2)

    def zapis(n):
        bariera.wait(timeout=5)
        storno.zapis(str(tmp_path), "faktura", n, "storno", "DAVID")

    vlakna = [threading.Thread(target=zapis, args=(n,)) for n in (20260001, 20260002)]
    for v in vlakna:
        v.start()
    for v in vlakna:
        v.join(timeout=5)
    assert path.read_bytes().startswith(b"null\n\xff\n{nedokonceno\n")
    assert set(storno.stav(str(tmp_path))) == {("faktura", 20260001), ("faktura", 20260002)}
    storno.zapis(str(tmp_path), "faktura", 20260001, "obnoveno")
    assert storno.stav(str(tmp_path))["faktura", 20260001]["storno"] is False


@pytest.mark.parametrize(("kdo", "ocekavano"), [
    ("  ==  =  " + "Ž" * 62 + " ", "Ž" * 60), (", JANA  ", ", JANA"), (["DAVID"], ""), (None, ""),
])
def test_validace_kdo(tmp_path, kdo, ocekavano):
    u = storno.zapis(str(tmp_path), "ppd", 1, "storno", kdo)
    assert u["kdo"] == ocekavano


def test_opozdeny_push_neprepise_storno_ani_obnovu(api, monkeypatch):
    n = _vystav(api, monkeypatch)["cislo"]
    dd = str(api.data)
    _prihlas(api)
    _zmen(api, n, "odebrat", "")
    storno_record, = api.poslano
    _zmen(api, n, "obnovit", "")
    obnoveno = api.poslano[-1]
    sent = []
    monkeypatch.setattr(ppd_push, "_put_once", lambda record: sent.append(record) or {})
    assert ppd_push.push(storno_record, dd) == {}
    assert ppd_push.push(obnoveno, dd) == {}
    assert sent == [obnoveno]
    _zmen(api, n, "odebrat", "")
    queue = api.data / "failed_ppd_pushes.jsonl"
    queue.write_text(json.dumps({"record": obnoveno}) + "\n", encoding="utf-8")
    assert ppd_push.retry_failed(dd) == 0 and not queue.exists()
    assert sent == [obnoveno]


def test_import_starych_ppd_neprepise_cislo_faktury(api, monkeypatch, capsys):
    n = _vystav(api, monkeypatch)["cislo"]
    dd = str(api.data)
    storno.zapis(dd, "faktura", n, "storno")
    monkeypatch.setenv("DATA_DIR", dd)
    monkeypatch.setattr(ppd, "read_backup", lambda _dd: [])
    monkeypatch.setattr(ppd, "read_ppd_log", lambda _dd: [{"cislo": n}])
    assert ppd_do_evidence.main(["--dry-run"]) == 0
    assert "Doklady: 0" in capsys.readouterr().out


def test_kod_faktury_z_wizardu_neprida_pozdejsi_zadost_se_stejnym_id(api, monkeypatch):
    _prihlas(api)
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    telo = _payload(evidence_log=False, zadost_id="stejna-zadost", novy_adresa="PŮVODNÍ 1")
    prvni = api.post("/api/generate", json=telo).get_json()
    oprava = api.post("/api/generate", json={**telo, "novy_adresa": "NOVÁ 2", "ppd_castka": ""}).get_json()
    assert prvni["success"] and oprava["success"]
    assert prvni["zmeny"] != oprava["zmeny"]

    n = prvni["doklad_cislo"]
    dd = str(api.data)
    ulozeny = sdileni.najdi_balik(dd, prvni["sdilet"].lstrip("/"), A._polozky_zadosti)
    assert [p["file"] for p in ulozeny] == [f"faktura_{n}.pdf", prvni["zmeny"].rsplit("/", 1)[-1]]
    assert api.get(prvni["sdilet"] + "/1").data == api.get(prvni["zmeny"]).data
    zaznam = json.loads((api.data / ppd_api.VYSTAVENE).read_bytes())
    assert zaznam["evidence_zadost_id"] == "stejna-zadost"
    assert "zadost_id" not in zaznam["doklad"]
    _zmen(api, n, "odebrat", "DAVID")
    assert api.poslano[-1]["zadost_id"] == "stejna-zadost"


@pytest.mark.parametrize("druh", ["faktura", "ppd"])
def test_stary_doklad_dohleda_id_zadosti_v_indexu(api, monkeypatch, druh):
    n = _vystav(api, monkeypatch, druh)["cislo"]
    dd = str(api.data)
    hledani.zapis_vystup(dd, [f"/download/{druh}_{n}.pdf"], {"zadost_id": "historicka-zadost"})
    _prihlas(api)
    for akce in ("odebrat", "obnovit"):
        _zmen(api, n, akce, "")
    assert [r["zadost_id"] for r in api.poslano] == ["historicka-zadost"] * 2


def test_stara_faktura_z_wizardu_dohleda_id_pres_puvodni_soubory(api, monkeypatch):
    n = _vystav(api, monkeypatch)["cislo"]
    dd = str(api.data)
    puvodni = "zmeny_PUVODNI.pdf"
    hledani.zapis_vystup(dd, [puvodni], {"zadost_id": "puvodni-zadost"})
    sdileni.zapis_fakturu(dd, n, [puvodni])
    hledani.zapis_vystup(dd, ["zmeny_OPRAVENA.pdf"], {"zadost_id": "puvodni-zadost"})
    _prihlas(api)
    _zmen(api, n, "odebrat", "")
    assert api.poslano[-1]["zadost_id"] == "puvodni-zadost"


@pytest.mark.parametrize("jednoznacna", [True, False])
def test_stara_faktura_dohleda_zadost_pres_vyprsely_nahodny_kod(api, monkeypatch, jednoznacna):
    n = _vystav(api, monkeypatch)["cislo"]
    dd = str(api.data)
    faktura_pdf = f"faktura_{n}.pdf"
    hledani.zapis_vystup(dd, ["zmeny_PUVODNI.pdf"], {"zadost_id": "puvodni-zadost"})
    hledani.zapis_vystup(dd, ["zmeny_JINA.pdf"], {"zadost_id": "jina-zadost"})
    sdileni._pripis(dd, "4321", [faktura_pdf, "zmeny_PUVODNI.pdf"], "2026-01-01T00:00:00")
    # Kód se později přidělil znovu. Původní záznam musí být stále dohledatelný.
    sdileni._pripis(dd, "4321", ["zmeny_JINA.pdf"])
    if not jednoznacna:
        sdileni.vytvor_token(dd, [faktura_pdf, "zmeny_JINA.pdf"])
    _prihlas(api)
    _zmen(api, n, "odebrat", "DAVID")
    assert api.poslano[-1]["zadost_id"] == ("puvodni-zadost" if jednoznacna else "")


@pytest.mark.parametrize("pred_upgradem", [False, True])
def test_stornovany_ppd_se_neda_verejne_sdilet(api, monkeypatch, pred_upgradem):
    n = _vystav(api, monkeypatch, "ppd")["cislo"]
    dd = str(api.data)
    soubor = f"ppd_{n}.pdf"
    _prihlas(api)
    kratky = api.post(f"/api/ppd/{n}/sdilet", headers=HLAVICKY).get_json()["sdilet"]
    legacy = sdileni.vytvor_token(dd, [soubor])
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    zadost = api.data / "output" / "zmeny_TEST.pdf"
    with zadost.open("wb") as f:
        writer.write(f)
    smiseny = "/" + sdileni.vytvor_kod(dd, [soubor, zadost.name])
    assert api.get(kratky + "/0/nahled/1").headers["Cache-Control"] == "no-store"

    if pred_upgradem:
        assert ppd.delete_ppd(dd, n)
        assert storno.stav(dd) == {}
    else:
        _zmen(api, n, "odebrat", "")
    for r in (api.post(f"/api/ppd/{n}/sdilet", headers=HLAVICKY),
              api.post("/api/sdilet", json={"soubory": [zadost.name, soubor]})):
        assert r.status_code == 409 and r.get_json() == {"error": f"Doklad č. {n} je stornovaný."}

    A._kod_reset()
    try:
        with A.app.test_client() as public:
            for url in (kratky, kratky + "/vse", kratky + "/0", kratky + "/0/nahled/1", f"/s/{legacy}",
                        smiseny + "/0", smiseny + "/0/nahled/1"):
                assert public.get(url).status_code == 404
            html = public.get(smiseny).get_data(as_text=True)
            assert soubor not in html and f"{smiseny}/1/nahled/1" in html
            assert public.get(smiseny + "/1").data == zadost.read_bytes()
            vse = public.get(smiseny + "/vse")
            assert len(PdfReader(io.BytesIO(vse.data)).pages) == 1
    finally:
        A._kod_reset()
    assert api.get(f"/download/{soubor}").status_code == 200
    assert api.get(f"/ppd-print/{n}").status_code == 200


def test_storno_ppd_plati_i_s_necitelnou_zalohou(api, monkeypatch):
    doklad = _vystav(api, monkeypatch, "ppd")
    n = doklad["cislo"]
    dd = str(api.data)
    soubor = f"ppd_{n}.pdf"
    kod = sdileni.vytvor_kod(dd, [soubor])
    _prihlas(api)
    _zmen(api, n, "odebrat", "DAVID")
    api.poslano.clear()
    (api.data / ppd.BACKUP_NAME).write_bytes(b"unreadable workbook")
    assert ppd.read_backup(dd) == []
    assert ppd.je_stornovany(dd, n)

    with A.app.test_client() as public:
        assert public.get(f"/{kod}/0").status_code == 404
    assert api.post("/api/sdilet", json={"soubory": [soubor]}).status_code == 409
    assert api.post(f"/api/ppd/{n}/sdilet", headers=HLAVICKY).status_code == 409
    assert api.post("/api/ppd/vystavit", headers=HLAVICKY, json=TELO).status_code == 409
    assert api.poslano == []

    ppd_push.enqueue(doklad, dd)
    sent = []
    monkeypatch.setattr(ppd_push, "_put_once", lambda record: sent.append(record) or {})
    assert ppd_push.retry_failed(dd) == 0
    assert [r["smazano"] for r in sent] == [True]


@pytest.mark.parametrize("akce", ["odebrat", "obnovit"])
def test_ppd_opakuje_udalost_po_selhani_zapisu_po_excelu(api, monkeypatch, akce):
    n = _vystav(api, monkeypatch, "ppd")["cislo"]
    dd = str(api.data)
    _prihlas(api)
    smazano = akce == "odebrat"
    if not smazano:
        _zmen(api, n, "odebrat", "DAVID")
        api.poslano.clear()
    puvodni_zapis = storno._zapis

    def chybny_zapis(*args):
        assert any(r["cislo"] == n for r in ppd.read_ppd_log(dd)) != smazano
        assert ppd.je_stornovany(dd, n)
        raise OSError("journal write failed")

    monkeypatch.setitem(A.app.config, "TESTING", True)
    monkeypatch.setattr(storno, "_zapis", chybny_zapis)
    with pytest.raises(OSError, match="journal write failed"):
        api.post(f"/api/doklady/{n}/{akce}", json={"kdo": "DAVID"})
    assert api.poslano == []
    assert bool(storno.stav(dd).get(("ppd", n), {}).get("storno")) != smazano

    monkeypatch.setattr(storno, "_zapis", puvodni_zapis)
    assert _zmen(api, n, akce, "DAVID")["zmeneno"] is True
    assert storno.stav(dd)["ppd", n]["storno"] == smazano
    record, = api.poslano
    assert record["smazano"] == smazano


def test_zmena_se_ulozi_do_fronty_pred_spustenim_vlakna(api, monkeypatch):
    n = _vystav(api, monkeypatch)["cislo"]
    dd = str(api.data)
    queue = api.data / "failed_ppd_pushes.jsonl"
    _prihlas(api)
    snapshots = []
    ulozene_udalosti = []
    zapis = storno._zapis

    def zapis_po_fronta(data_dir, udalost):
        ulozene_udalosti.append(json.loads(queue.read_bytes())["record"]["smazano"])
        return zapis(data_dir, udalost)

    def restart(record, data_dir):
        snapshots.append((record, json.loads(queue.read_bytes())["record"]))
        raise RuntimeError("worker restart")

    monkeypatch.setattr(storno, "_zapis", zapis_po_fronta)
    monkeypatch.setattr(ppd_push, "push_async", restart)
    sent = []
    monkeypatch.setattr(ppd_push, "_put_once", lambda record: sent.append(record) or {})
    for akce in ("odebrat", "obnovit"):
        _zmen(api, n, akce, "DAVID")
        assert ppd_push.retry_failed(dd) == 0 and not queue.exists()
    assert [r["smazano"] for r in sent] == [True, False]
    assert ulozene_udalosti == [True, False]
    assert snapshots == [(r, r) for r in sent]


def test_stary_smazany_ppd_odmitne_replay_vystaveni_i_push(api, monkeypatch):
    doklad = _vystav(api, monkeypatch, "ppd")
    dd = str(api.data)
    n = doklad["cislo"]
    assert ppd.delete_ppd(dd, n) and storno.stav(dd) == {}
    r = api.post("/api/ppd/vystavit", headers=HLAVICKY, json=TELO)
    assert r.status_code == 409 and api.poslano == []
    ppd_push.enqueue(doklad, dd)
    sent = []
    monkeypatch.setattr(ppd_push, "_put_once", lambda record: sent.append(record) or {})
    assert ppd_push.retry_failed(dd) == 0 and sent == []
    r = api.post(f"/api/ppd/{n}/smazat", headers=HLAVICKY)
    assert r.get_json() == {"removed": False}
    assert api.poslano[0]["smazano"] is True


def test_novinky_prebiraji_barvy_aplikace(api):
    _prihlas(api)
    html = api.get("/").get_data(as_text=True)
    assert "prefers-color-scheme: dark" not in html
    assert "--wn-card: var(--card," in html
