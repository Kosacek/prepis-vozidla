"""'v z.' (v zastoupení) must be pre-filled on the applicant signature line at
the END of each page — as real, EDITABLE AcroForm text fields (deletable in a
PDF viewer), regular weight. The clerk's lines and the rarely-used 'Mezitímní
vlastník' line stay untouched."""
import io
import os

import app as appmod
from pypdf import PdfReader


def _gen(client, tmp_path, monkeypatch, mode, **extra):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    payload = {
        "mode": mode,
        "registracni_znacka": "1AB2345", "vin": "TMBJJ7NE1L0123456",
        "puvodni_jmeno": "PRODAVAJICI s.r.o.", "novy_jmeno": "KUPUJICI s.r.o.",
        "novy_adresa": "Hlavni 5, Brno", "novy_psc": "60200",
        "ppd_castka": "0",
    }
    payload.update(extra)
    r = client.post("/api/generate", json=payload)
    data = r.get_json()
    key = {"prevod": "zmeny", "zapis": "zapis", "zmena": "zmena"}[mode]
    path = os.path.join(str(tmp_path), "output", data[key].split("/")[-1])
    with open(path, "rb") as f:
        return PdfReader(io.BytesIO(f.read()))


def _vz_fields(reader):
    flds = reader.get_fields() or {}
    return {k: v for k, v in flds.items() if k.startswith("vz_podpis_")}


def test_prevod_has_3_editable_vz_fields(client, tmp_path, monkeypatch):
    # End-of-page lines only: p1 bottom, p2 bottom, p3 převzetí dokladů.
    # NOT the mid-page 'Mezitímní vlastník' line.
    rdr = _gen(client, tmp_path, monkeypatch, "prevod")
    vz = _vz_fields(rdr)
    assert len(vz) == 3
    assert all(f.get("/V") == "v z." for f in vz.values())
    assert all(f.get("/FT") == "/Tx" for f in vz.values())   # editable text field


def test_zapis_has_2_editable_vz_fields(client, tmp_path, monkeypatch):
    rdr = _gen(client, tmp_path, monkeypatch, "zapis",
               vin_z="TMBJJ7NE1L0123456", druh_vozidla_z="osobni")
    vz = _vz_fields(rdr)
    assert len(vz) == 2
    assert all(f.get("/V") == "v z." for f in vz.values())


def test_zmena_has_2_editable_vz_fields(client, tmp_path, monkeypatch):
    rdr = _gen(client, tmp_path, monkeypatch, "zmena",
               zadost_zmena="zmena barvy na modrou")
    vz = _vz_fields(rdr)
    assert len(vz) == 2
    assert all(f.get("/V") == "v z." for f in vz.values())


def test_vz_is_field_not_page_content(client, tmp_path, monkeypatch):
    # The old approach drew 'v z.' into the page content (bold, undeletable).
    # Now it must NOT be baked into the content stream.
    rdr = _gen(client, tmp_path, monkeypatch, "prevod")
    assert all("v z." not in (p.extract_text() or "") for p in rdr.pages)