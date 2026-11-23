"""Auto-sken ORV (1.37.0): node testy modulů z evidence a stráže žádostí.

tests/test_orv_auto.cjs je kopie z evidence (moduly static/js/orv_auto_core.js,
orv_qr.js a orv_auto.js jsou beze změny), tests/test_orv_auto_zadosti.cjs hlídá,
že karta, která po skenu zůstala na stole, se do další žádosti sama nenaskenuje.
"""
import os
import shutil
import subprocess

import pytest

TESTS = os.path.dirname(__file__)
EVIDENCE = os.path.join(TESTS, "..", "..", "ukony_tracker", "static", "js")


@pytest.mark.parametrize("soubor", ["test_orv_auto.cjs", "test_orv_auto_zadosti.cjs",
                                    "test_orv_quad.cjs", "test_sken_prubeh.cjs"])
def test_node(soubor):
    node = shutil.which("node")
    if not node:  # pragma: no cover - závisí na stroji
        pytest.skip("node není nainstalovaný")
    r = subprocess.run([node, "--test", os.path.join(TESTS, soubor)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


@pytest.mark.parametrize("modul", ["orv_auto_core.js", "orv_qr.js", "orv_auto.js"])
def test_moduly_jsou_stejne_jako_v_evidenci(modul):
    """Opravu dělat v evidenci a zkopírovat sem — ať se kód nerozejde."""
    vlastni = os.path.join(TESTS, "..", "static", "js", modul)
    evidence = os.path.join(EVIDENCE, modul)
    if not os.path.exists(evidence):  # pragma: no cover - samostatný checkout žádostí
        pytest.skip("evidence vedle není")
    precti = lambda p: open(p, encoding="utf-8").read().replace("\r\n", "\n")
    assert precti(vlastni) == precti(evidence)


# ── 1.37.1: náhled bez „Auto" pilulky, obrys na rozích karty, proužek průběhu ──

def _sablona():
    return open(os.path.join(TESTS, "..", "templates", "index.html"), encoding="utf-8").read()


def test_zadna_pilulka_ani_stavova_tecka():
    """David: pilulka „Auto" s tečkou je „the most AI slop you can do"."""
    html = _sablona()
    assert '<i aria-hidden="true"></i>Auto' not in html
    assert ".orv-auto i {" not in html and "box-shadow: 0 0 0 3px rgba(52,199,89" not in html
    tlacitko = html[html.index('id="orv-auto"') - 60:html.index('id="orv-auto"') + 1000]
    assert 'class="cam-otocit orv-auto"' in tlacitko and "#i-scan" in tlacitko


def test_prepinac_je_klavesa_a_a_je_v_tahaku():
    html = _sablona()
    assert "e.code === 'KeyA' && window.prepniOrvAuto" in html
    tahak = open(os.path.join(TESTS, "..", "static", "klavesnice.js"), encoding="utf-8").read()
    assert "[['A'], 'sken sám zap/vyp']" in tahak


def test_obrys_a_proužek_jsou_v_náhledu_a_moduly_se_načtou():
    html = _sablona()
    assert 'id="orv-obrys"' in html and 'preserveAspectRatio="xMidYMid meet"' in html
    assert 'id="sken-bar"' in html and 'role="progressbar"' in html
    poradi = [html.index(f"/static/js/{m}") for m in
              ("orv_auto_core.js", "orv_qr.js", "orv_auto.js", "orv_quad.js", "sken_prubeh.js",
               "orv_nahled.js", "orv_auto_zadosti.js")]
    assert poradi == sorted(poradi)


def test_sken_hlasi_milniky_a_ceka_na_registr():
    html = _sablona()
    sken = html[html.index("async function quickScanOrv("):]
    sken = sken[:sken.index("\n}\n")]
    for kus in ("prubeh.hotovo('pole')", "prubeh.hotovo('registr')", "await Promise.race([_orvBezi",
                "prubeh.selhalo("):
        assert kus in sken, kus
    nahrani = html[html.index("async function _naskenujOrv("):][:2600]
    assert "xhr.upload.onprogress" in nahrani and "prubeh.hotovo('ocr')" in nahrani
