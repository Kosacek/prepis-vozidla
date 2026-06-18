"""The žádost print helper (/tisk): shows ONE real, editable PDF (no merge),
with a Vytisknout button that prints then closes — and must NOT auto-fire the
print dialog (that would block editing the form)."""
import app as appmod


def _make_zadost(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json={
        "mode": "prevod", "registracni_znacka": "1AB2345", "vin": "WBA3A5C51DF123456",
        "puvodni_jmeno": "JAN PRODÁVAJÍCÍ", "novy_jmeno": "PETR KUPUJÍCÍ", "ppd_castka": "0",
    })
    return r.get_json()["zmeny"]      # "/download/zmeny_<ts>.pdf"


def test_wrapper_embeds_real_pdf_and_is_manual(client, tmp_path, monkeypatch):
    url = _make_zadost(client, tmp_path, monkeypatch)
    page = client.get("/tisk?src=" + url)
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert f'src="{url}"' in html               # the ACTUAL pdf, embedded directly
    assert "/tisk-pdf" not in html              # no merge → no "list of pdfs"
    assert "doPrint()" in html and "window.close" in html
    # Must NOT auto-open the dialog on load (that blocks editing the form).
    assert "addEventListener('load'" not in html
    assert "setTimeout(function () { window.print" not in html


def test_wrapper_rejects_foreign_or_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    assert client.get("/tisk?src=/etc/passwd").status_code == 400
    assert client.get("/tisk?src=/download/../../app.py").status_code == 400
    assert client.get("/tisk?src=/download/does_not_exist.pdf").status_code == 400
    assert client.get("/tisk").status_code == 400
