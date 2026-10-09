"""Integration: PPD is generated alongside the žádost via /api/generate.

DATA_DIR is monkeypatched to a tmp dir so the test never touches the real
NAS evidence ledger / counter.
"""
import os
import json
import threading

import pytest

import app as appmod
import ppd_push
import tracker_push

_real_ppd_push_async = ppd_push.push_async


@pytest.fixture(autouse=True)
def evidence_pushes(monkeypatch):
    """Capture both request hooks; ordinary PDF tests never start HTTP threads."""
    calls = {"ppd": [], "tracker": []}
    monkeypatch.setattr(ppd_push, "push_async", lambda body, dd: calls["ppd"].append((body, dd)))
    monkeypatch.setattr(tracker_push, "push_async", lambda data, dd: calls["tracker"].append(
        (tracker_push.build_payload(data), dd)))
    return calls


def _payload(**over):
    base = {
        "mode": "prevod",
        "registracni_znacka": "1AB2345",
        "vin": "WBA3A5C51DF123456",
        "puvodni_jmeno": "JAN PRODÁVAJÍCÍ",
        "novy_jmeno": "PETR KUPUJÍCÍ",
        "ppd_castka": "1300",
        "ppd_prijato_od": "PETR KUPUJÍCÍ",
    }
    base.update(over)
    return base


def test_generate_includes_ppd(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json=_payload())
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert data["ppd"].startswith("/download/ppd_")
    # file written + evidence row created under the tmp DATA_DIR
    fname = data["ppd"].split("/")[-1]
    assert os.path.exists(os.path.join(str(tmp_path), "output", fname))
    assert os.path.exists(os.path.join(str(tmp_path), "ppd_evidence.xlsx"))


def test_generate_pushes_to_evidence_by_default(client, tmp_path, monkeypatch):
    """The 'Zapsat úkon do evidence' box defaults on, so a normal generate fires
    the tracker push (with the žádost data)."""
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    import tracker_push
    calls = []
    monkeypatch.setattr(tracker_push, "push_async", lambda data, dd: calls.append(data))
    r = client.post("/api/generate", json=_payload())     # no evidence_log → default true
    assert r.get_json()["success"] is True
    assert len(calls) == 1


def test_generate_skips_evidence_when_unchecked(client, tmp_path, monkeypatch, evidence_pushes):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    import tracker_push
    calls = []
    monkeypatch.setattr(tracker_push, "push_async", lambda data, dd: calls.append(data))
    r = client.post("/api/generate", json=_payload(evidence_log=False))
    assert r.get_json()["success"] is True
    assert calls == []                                    # box off → no push
    assert len(evidence_pushes["ppd"]) == 1                # every receipt still goes


@pytest.mark.parametrize("zadost_id", [None, "browser-stable-id"])
def test_generate_ppd_and_tracker_share_one_id(client, tmp_path, monkeypatch, evidence_pushes, zadost_id):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    generated = []
    def uuid4():
        generated.append(True)
        return type("UUID", (), {"hex": "generated-once"})()
    monkeypatch.setattr(appmod.uuid, "uuid4", uuid4)
    response = client.post("/api/generate", json=_payload(
        zadost_id=zadost_id, ppd_prijato_ico="01234567", ppd_extra_spz="2CD6789"))
    assert response.status_code == 200
    assert response.get_json()["ppd"]
    body, data_dir = evidence_pushes["ppd"][0]
    payload, tracker_dir = evidence_pushes["tracker"][0]
    assert body["zadost_id"] == payload["zadost_id"] == (zadost_id or "generated-once")
    assert len(generated) == (0 if zadost_id else 1)
    assert data_dir == tracker_dir == str(tmp_path)
    assert body["prijato_ico"] == "01234567"
    assert body["vozidlo"] == "1AB2345, 2CD6789"
    assert body["castka"] == 1300 and type(body["castka"]) is int


def test_generate_returns_receipt_when_evidence_http_raises(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ppd_push, "RETRY_DELAYS", ())
    finished = threading.Event()
    sent = []
    def put(*args, **kwargs):
        sent.append(kwargs["json"])
        raise RuntimeError("evidence unavailable")
    original = ppd_push.push
    def push(*args):
        try:
            return original(*args)
        finally:
            finished.set()
    monkeypatch.setattr(ppd_push.requests, "put", put)
    monkeypatch.setattr(ppd_push, "push", push)
    monkeypatch.setattr(ppd_push, "push_async", _real_ppd_push_async)
    response = client.post("/api/generate", json=_payload(evidence_log=False))
    assert finished.wait(2)  # keep the mock active until the background thread ends
    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert response.get_json()["ppd"].startswith("/download/ppd_")
    queued = json.loads((tmp_path / "failed_ppd_pushes.jsonl").read_text(encoding="utf-8"))
    assert queued["record"] == sent[0]
    assert queued["reason"] == "evidence unavailable"


def test_generate_returns_receipt_when_push_hook_raises(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    def fail(*args, **kwargs):
        raise RuntimeError("thread could not start")
    monkeypatch.setattr(ppd_push, "push_async", fail)
    response = client.post("/api/generate", json=_payload())
    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert response.get_json()["ppd"]


def test_delete_and_restore_push_status_from_backup(client, tmp_path, monkeypatch, evidence_pushes):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    generated = client.post("/api/generate", json=_payload(ppd_prijato_ico="01234567")).get_json()
    number = int(generated["ppd_print"].rsplit("/", 1)[1])
    issued = evidence_pushes["ppd"].pop()[0]
    deleted = client.delete(f"/api/ppd/{number}")
    assert deleted.get_json() == {"success": True, "removed": True}
    restored = client.post(f"/api/ppd/{number}/restore")
    assert restored.get_json() == {"success": True, "restored": True}
    bodies = [body for body, dd in evidence_pushes["ppd"]]
    assert [body["smazano"] for body in bodies] == [True, False]
    for body in bodies:
        assert body["cislo"] == number
        assert body["prijato_ico"] == "01234567"
        assert body["vozidlo"] == issued["vozidlo"]
        assert body["castka"] == issued["castka"]
    # Repeating the restore has no local change and sends no extra push.
    assert client.post(f"/api/ppd/{number}/restore").get_json()["restored"] is False
    assert len(evidence_pushes["ppd"]) == 2


def test_delete_skips_push_without_backup(client, tmp_path, monkeypatch, evidence_pushes):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    number = appmod.ppd.reserve_ppd_number_and_log(str(tmp_path), {
        "date": "08.10.2026", "payer": "Firma", "amount": 1300, "vehicle": "RZ",
    })
    assert client.delete(f"/api/ppd/{number}").get_json()["removed"] is True
    assert evidence_pushes["ppd"] == []
    assert client.delete(f"/api/ppd/{number}").get_json()["removed"] is False
    assert client.post(f"/api/ppd/{number}/restore").status_code == 404
    assert evidence_pushes["ppd"] == []


def test_delete_and_restore_complete_when_push_raises(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    generated = client.post("/api/generate", json=_payload()).get_json()
    number = int(generated["ppd_print"].rsplit("/", 1)[1])
    def fail(*args, **kwargs):
        raise RuntimeError("push failed")
    monkeypatch.setattr(ppd_push, "push_async", fail)
    response = client.delete(f"/api/ppd/{number}")
    assert response.status_code == 200 and response.get_json()["removed"] is True
    response = client.post(f"/api/ppd/{number}/restore")
    assert response.status_code == 200 and response.get_json()["restored"] is True


def test_ppd_payer_is_uppercased(client, tmp_path, monkeypatch):
    """A hand-typed / autofilled payer is stored UPPERCASE on the receipt, like
    the rest of the form. The receipt ledger row reflects it."""
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json=_payload(
        ppd_prijato_od="autodoprava novák s.r.o.", ppd_prijato_adresa="hlavní 5, brno"))
    assert r.get_json()["success"] is True
    import ppd as ppdmod
    log = ppdmod.read_ppd_log(str(tmp_path))
    assert log[0]["prijato_od"] == "AUTODOPRAVA NOVÁK S.R.O."


def test_ppd_print_page_is_a5(client, tmp_path, monkeypatch):
    """The generate response links an HTML print page whose @page rule pre-sets
    A5 paper in the browser's print dialog (the žádosti stay A4 PDFs)."""
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json=_payload())
    data = r.get_json()
    assert data["ppd_print"].startswith("/ppd-print/")
    page = client.get(data["ppd_print"])
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "148mm 210mm" in html                    # @page = explicit A5 paper size
    # Misfeed tolerance: the frame is smaller than the printable area and
    # centered on the paper (~9-12 mm clearance), so a printer that feeds A5 a
    # few mm off can't cut the top border line (bug seen on real hardware).
    assert "width: 130mm" in html
    assert "height: 186mm" in html
    assert "no-store" in page.headers.get("Cache-Control", "")  # always fresh (no stale A4 page)
    assert "PŘÍJMOVÝ POKLADNÍ DOKLAD" in html
    assert "PETR KUPUJÍCÍ" in html
    assert "1AB2345" in html                        # SPZ on the receipt
    assert "window.print()" in html                 # auto-opens the dialog


def test_ppd_print_unknown_number_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    assert client.get("/ppd-print/999").status_code == 404


def test_zero_amount_skips_ppd(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json=_payload(ppd_castka="0"))
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert "ppd" not in data            # opt-out
    assert data.get("zmeny")            # žádosti still produced


# ── víc vozidel na jednom dokladu ────────────────────────────────────────────
# Reálný případ: jeden PPD kryje víc aut najednou. Primární vozidlo je to ze
# žádosti (registracni_znacka); "+ Přidat vozidlo" v UI přidává další SPZ do
# ppd_extra_spz (čárkou oddělené), server je spojí do jednoho řádku.

def test_ppd_joins_extra_spz_from_the_expander(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json=_payload(ppd_extra_spz="2CD6789, 3EF1234"))
    assert r.get_json()["success"] is True

    import openpyxl
    import ppd as ppdmod
    ws = openpyxl.load_workbook(ppdmod._evidence_path(str(tmp_path))).active
    row = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] is not None][0]
    assert row[5] == "1AB2345, 2CD6789, 3EF1234"   # Vozidlo column


def test_ppd_ignores_blank_extra_entries(client, tmp_path, monkeypatch):
    """Trailing commas / empty rows left in the UI must not leave gaps like
    '1AB2345, , 3EF1234'."""
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json=_payload(ppd_extra_spz="2CD6789, , "))
    assert r.get_json()["success"] is True
    import openpyxl
    import ppd as ppdmod
    ws = openpyxl.load_workbook(ppdmod._evidence_path(str(tmp_path))).active
    row = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] is not None][0]
    assert row[5] == "1AB2345, 2CD6789"


def test_ppd_works_with_no_extra_spz(client, tmp_path, monkeypatch):
    """Default case (no expander touched) must be unchanged: just the one plate."""
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json=_payload())
    import openpyxl
    import ppd as ppdmod
    ws = openpyxl.load_workbook(ppdmod._evidence_path(str(tmp_path))).active
    row = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] is not None][0]
    assert row[5] == "1AB2345"


# ── Tisk dokladu s víc auty ──────────────────────────────────────────────────
# Reálná chyba 2026-10-06 (doklad č. 174, 3 auta, 3900 Kč): PDF auta mělo,
# ale tlačítko „Vytisknout PPD" je vynechalo. Tisková stránka se staví ze
# ZÁLOHY a do ní se ukládala jen hlavní SPZ — u Davida prázdná, protože
# všechna tři auta přidal přes „+ Přidat vozidlo". Testy výš hlídaly jen
# ledger, ne to, co se opravdu tiskne.

def _tisk(client, payload):
    data = client.post("/api/generate", json=payload).get_json()
    return client.get(data["ppd_print"]).get_data(as_text=True)


def test_tisk_ukaze_vsechna_auta(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    html = _tisk(client, _payload(ppd_extra_spz="2CD6789, 3EF1234"))
    for spz in ("1AB2345", "2CD6789", "3EF1234"):
        assert spz in html, f"{spz} chybí na tištěném dokladu"


def test_tisk_ukaze_auta_i_bez_hlavni_spz(client, tmp_path, monkeypatch):
    """Přesně Davidův případ: hlavní SPZ prázdná, všechna auta z rozbalovátka."""
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    html = _tisk(client, _payload(registracni_znacka="", vin="",
                                  ppd_extra_spz="1AKB126, 3BP3109, 1AKT148"))
    for spz in ("1AKB126", "3BP3109", "1AKT148"):
        assert spz in html, f"{spz} chybí na tištěném dokladu"


def test_zaloha_nese_vsechna_auta(client, tmp_path, monkeypatch):
    """Záloha je zdroj pravdy pro tisk i pro obnovu smazaného dokladu."""
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    client.post("/api/generate", json=_payload(ppd_extra_spz="2CD6789"))
    import ppd as ppdmod
    assert ppdmod.read_backup(str(tmp_path))[0]["spz"] == "1AB2345, 2CD6789"


def test_tisk_a_pdf_maji_stejna_auta(client, tmp_path, monkeypatch):
    """PDF a tisková stránka jsou dvě různá vykreslení — nesmí se rozejít."""
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    data = client.post("/api/generate", json=_payload(
        registracni_znacka="", ppd_extra_spz="1AKB126, 3BP3109")).get_json()
    from pypdf import PdfReader
    pdf = PdfReader(os.path.join(str(tmp_path), "output", data["ppd"].split("/")[-1]))
    pdf_text = pdf.pages[0].extract_text()
    html = client.get(data["ppd_print"]).get_data(as_text=True)
    for spz in ("1AKB126", "3BP3109"):
        assert spz in pdf_text and spz in html


def test_tisk_starsiho_poskozeneho_zaznamu_vezme_auta_z_ledgeru(client, tmp_path, monkeypatch):
    """Doklady vystavené před opravou mají v záloze SPZ prázdnou. Ledger auta
    má správně — tisk si je má vzít odtud, místo aby nevytiskl nic."""
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    import ppd as ppdmod
    n = ppdmod.reserve_ppd_number_and_log(str(tmp_path), {
        "date": "06.10.2026", "payer": "JE & NE", "amount": 3900,
        "purpose": "Zastupování na MMB", "vehicle": "1AKB126, 3BP3109, 1AKT148"})
    ppdmod.append_backup(str(tmp_path), {
        "cislo": n, "ts": "2026-10-06T10:19:54", "date": "06.10.2026", "payer": "JE & NE",
        "payer_ico": "", "payer_address": "", "amount": 3900,
        "purpose": "Zastupování na MMB", "spz": "", "vin": ""})   # tak to zapsala chyba
    html = client.get(f"/ppd-print/{n}").get_data(as_text=True)
    for spz in ("1AKB126", "3BP3109", "1AKT148"):
        assert spz in html


def test_ppd_slovy_endpoint(client):
    r = client.get("/api/ppd-slovy?castka=1300")
    assert r.status_code == 200
    body = r.get_json()
    assert "tisíc" in body["slovy"].lower()


def test_ppd_slovy_endpoint_zero_and_bad_input(client):
    assert client.get("/api/ppd-slovy?castka=0").get_json()["slovy"]
    r = client.get("/api/ppd-slovy?castka=neplatne")
    assert r.status_code == 400
