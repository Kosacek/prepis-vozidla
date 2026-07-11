"""Integration: PPD is generated alongside the žádost via /api/generate.

DATA_DIR is monkeypatched to a tmp dir so the test never touches the real
NAS evidence ledger / counter.
"""
import os

import app as appmod


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
    monkeypatch.setattr(tracker_push, "push", lambda data, dd: calls.append(data))
    r = client.post("/api/generate", json=_payload())     # no evidence_log → default true
    assert r.get_json()["success"] is True
    assert len(calls) == 1


def test_generate_skips_evidence_when_unchecked(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    import tracker_push
    calls = []
    monkeypatch.setattr(tracker_push, "push", lambda data, dd: calls.append(data))
    r = client.post("/api/generate", json=_payload(evidence_log=False))
    assert r.get_json()["success"] is True
    assert calls == []                                    # box off → no push


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
