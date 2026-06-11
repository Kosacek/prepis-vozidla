"""'v z.' (v zastoupení) must be pre-printed on every APPLICANT signature line
of each generated žádost — Petr signs on behalf of the client. The clerk's
lines (podpis oprávněné úřední osoby) must stay untouched."""
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


def _vz_count(reader):
    return sum(p.extract_text().count("v z.") for p in reader.pages)


def test_prevod_has_vz_on_all_4_signature_lines(client, tmp_path, monkeypatch):
    rdr = _gen(client, tmp_path, monkeypatch, "prevod")
    assert _vz_count(rdr) == 4          # p1: 1, p2: 2 (mezitímní + závěr), p3: 1


def test_zapis_has_vz_on_both_signature_lines(client, tmp_path, monkeypatch):
    rdr = _gen(client, tmp_path, monkeypatch, "zapis",
               vin_z="TMBJJ7NE1L0123456", druh_vozidla_z="osobni")
    assert _vz_count(rdr) == 2


def test_zmena_has_vz_on_both_signature_lines(client, tmp_path, monkeypatch):
    rdr = _gen(client, tmp_path, monkeypatch, "zmena",
               zadost_zmena="zmena barvy na modrou")
    assert _vz_count(rdr) == 2
