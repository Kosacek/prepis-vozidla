"""Karta dokladu: částka u pravého kraje, Tisk · PDF · Sdílet a koš na jednom řádku.

1.36.0 dal koš do čtvrtého sloupce vpravo nahoře (odsouval částku) a 1.36.1 ho
sice posunul dolů, ale čipy dál žily v úzkém sloupci vedle částky, takže se
„Sdílet" na telefonu zalomilo na další řádek. Od 1.36.2 je text karty přímo
v mřížce (firm-info má display: contents): jméno vedle částky, řádek a čipy
přes celou šířku, koš je poslední položka řádku čipů (vpravo dole, 36 × 36 px
jako v evidenci). Na telefonu jdou čipy i pod číslo dokladu.
"""
import os
import re

INDEX = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")


def _html() -> str:
    with open(INDEX, encoding="utf-8") as f:
        return f.read()


def _css() -> str:
    html = _html()
    return html[html.index("<style"):html.index("</style>")]


def _pravidlo(css: str, selektor: str, od: int = 0) -> str:
    """Tělo prvního pravidla pro selektor (od pozice `od`)."""
    m = re.compile(r"(?m)^\s*" + re.escape(selektor) + r"\s*\{([^}]*)\}").search(css, od)
    assert m, f"chybí pravidlo {selektor}"
    return m.group(1)


def test_mrizka_karty_ma_tri_sloupce_a_text_je_v_ni():
    css = _css()
    assert "grid-template-columns: 44px minmax(0, 1fr) auto;" in _pravidlo(css, ".dok-card")
    assert "display: contents" in _pravidlo(css, ".dok-card .firm-info")
    assert "grid-column: 3" in _pravidlo(css, ".dok-card .dok-castka")
    assert "grid-column: 2 / 4" in _pravidlo(css, ".dok-card .firm-card-sub")
    cipy = _pravidlo(css, ".dok-card .firm-chips")
    assert "grid-column: 2 / 4" in cipy and "flex-wrap: nowrap" in cipy


def test_na_telefonu_maji_cipy_celou_sirku_karty():
    css = _css()
    telefon = css.index("@media (max-width: 600px)")
    assert "grid-column: 1 / 4" in _pravidlo(css, ".dok-card .firm-chips", telefon)


def test_kos_je_posledni_v_radku_cipu_ve_velikosti_jako_v_evidenci():
    html = _html()
    assert ('<div class="firm-chips">${akce}${smazany ? \'\' : `<button type="button" '
            'class="firm-delete"') in html
    kos = _pravidlo(_css(), ".dok-card .firm-delete")
    for cast in ("margin: -2px -4px -2px auto", "width: 36px", "height: 36px"):
        assert cast in kos
    assert "position: absolute" not in kos
