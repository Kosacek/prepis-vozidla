"""Karta dokladu: koš v pravém dolním rohu, částka zarovnaná vpravo (1.36.1).

V 1.36.0 seděl koš ve čtvrtém sloupci mřížky vpravo nahoře a odsouval částku
doleva. Teď je jako v evidenci: absolutně v pravém dolním rohu, 36 × 36 px.
"""
import os
import re

INDEX = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")


def _css() -> str:
    with open(INDEX, encoding="utf-8") as f:
        html = f.read()
    return html[html.index("<style"):html.index("</style>")]


def _pravidlo(css: str, selektor: str) -> str:
    """Tělo prvního (nemediálního) pravidla pro selektor."""
    m = re.search(r"(?m)^\s*" + re.escape(selektor) + r"\s*\{([^}]*)\}", css)
    assert m, f"chybí pravidlo {selektor}"
    return m.group(1)


def test_mrizka_karty_nema_sloupec_pro_kos():
    karta = _pravidlo(_css(), ".dok-card")
    assert "grid-template-columns: 44px minmax(0, 1fr) auto;" in karta
    assert "position: relative" in karta


def test_kos_sedi_vpravo_dole_ve_velikosti_jako_v_evidenci():
    kos = _pravidlo(_css(), ".dok-card .firm-delete")
    for cast in ("position: absolute", "right: 8px", "bottom: 8px", "width: 36px", "height: 36px"):
        assert cast in kos
    assert "padding-right: 40px" in _pravidlo(_css(), ".dok-card .firm-chips")
