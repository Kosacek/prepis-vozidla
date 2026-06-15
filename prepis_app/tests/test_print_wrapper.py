"""The 'Vytisknout žádost' flow: a /tisk wrapper page auto-fires the print
dialog, and /tisk-pdf merges the žádost (+ plné moci) into one print job."""
import io

import app as appmod
from pypdf import PdfReader


def _make_zadost(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    r = client.post("/api/generate", json={
        "mode": "prevod", "registracni_znacka": "1AB2345", "vin": "WBA3A5C51DF123456",
        "puvodni_jmeno": "JAN PRODÁVAJÍCÍ", "novy_jmeno": "PETR KUPUJÍCÍ", "ppd_castka": "0",
    })
    return r.get_json()["zmeny"]      # "/download/zmeny_<ts>.pdf"


def test_wrapper_page_autoprints(client, tmp_path, monkeypatch):
    url = _make_zadost(client, tmp_path, monkeypatch)
    page = client.get("/tisk?files=" + url)
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "/tisk-pdf?files=" in html          # embeds the merged PDF
    assert "print()" in html                   # auto-opens the dialog
    assert "window.close" in html              # closes the tab after


def test_tisk_pdf_returns_pdf(client, tmp_path, monkeypatch):
    url = _make_zadost(client, tmp_path, monkeypatch)
    one = client.get("/tisk-pdf?files=" + url)
    assert one.status_code == 200
    assert one.data[:4] == b"%PDF"
    n_one = len(PdfReader(io.BytesIO(one.data)).pages)
    assert n_one == 3                            # zmeny.pdf is 3 pages
    # Two of the same merge into one job with double the pages.
    two = client.get("/tisk-pdf?files=" + url + "," + url)
    assert len(PdfReader(io.BytesIO(two.data)).pages) == 2 * n_one


def test_tisk_pdf_rejects_foreign_paths(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    # Traversal / non-app URLs resolve to nothing → 404, never a file read.
    assert client.get("/tisk-pdf?files=/etc/passwd").status_code == 404
    assert client.get("/tisk-pdf?files=/download/../../app.py").status_code == 404
    assert client.get("/tisk-pdf?files=").status_code == 404
