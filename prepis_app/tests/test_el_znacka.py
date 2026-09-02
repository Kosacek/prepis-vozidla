"""Elektrická značka: „žádám o přidělení EL RZ" → cena 500 a poznámka „EL".

Tabulka na elektromobil je zdarma, platí se jen vyřízení — proto místo běžných
1300 jde do evidence 500. Dělá se to tak ručně a je to jen práce navíc.

Pravidlo je vyčtené z evidence (931 úkonů k 1. 9. 2026):
  * poznámka „EL" má 29 úkonů, z toho 22 typu NOVÉ a nejčastější cena 500 (12×)
  * u DOVOZU vychází EL jinak (1200), tak se tam cena nesahá

A hlavně past, kvůli které se hledá EL jako SAMOSTATNÉ slovo: v evidenci reálně
jsou „Exelero", „Michaela" i „Leasing" — hloupé hledání podřetězce by u nich
srazilo cenu na 500 a připsalo elektrickou značku autu, které není elektrické.

Testy pouštějí JS, který se doopravdy posílá do prohlížeče.
"""
import json
import os
import shutil
import subprocess

import pytest

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")


def _extract_js() -> str:
    with open(TEMPLATE, encoding="utf-8") as fh:
        html = fh.read()
    start = html.index("const EL_SLOVO")
    konec = "function elZkontroluj()"
    return html[start:html.index(konec, start)]


def _uprava(texty, typ, poznamka=""):
    node = shutil.which("node")
    if not node:  # pragma: no cover - závisí na stroji
        pytest.skip("node není nainstalovaný")
    script = (_extract_js()
              + "\nconsole.log(JSON.stringify(elUprava("
              + json.dumps(texty) + ", " + json.dumps(typ) + ", "
              + json.dumps(poznamka) + ")));\n")
    # encoding musí být explicitně utf-8: node píše utf-8, ale Python by na
    # Windows četl v kódování konzole a „Komín" by se rozsypalo.
    res = subprocess.run([node, "-e", script], capture_output=True, text=True,
                         encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


# ── co to má poznat ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "žádám o přidělení EL RZ, typ 801",
    "ŽÁDÁM O PŘIDĚLENÍ ELRZ",
    "EL",
    "Komín, EL",
    "elektrická značka",
])
def test_pozna_elektrickou_znacku(text):
    assert _uprava([text], "NOVÉ") is not None, text


# ── a co poznat NESMÍ ────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "Exelero Czech s.r.o.",          # všechna tři jména jsou reálně v evidenci
    "Michaela Rypalová",
    "Leasing České spořitelny, a.s.",
    "ATELIER RAW s.r.o.",
    "",
])
def test_nezamenit_za_jmeno_ve_kterem_je_el(text):
    assert _uprava([text], "NOVÉ") is None, text


# ── cena ─────────────────────────────────────────────────────────────────────
def test_nove_vozidlo_dostane_500():
    assert _uprava(["žádám o přidělení EL RZ, typ 801"], "NOVÉ")["cena"] == 500


def test_u_dovozu_se_cena_nesaha():
    """V evidenci vychází DOVOZ + EL na 1200 — hádat 500 by bylo horší než nic."""
    assert _uprava(["EL"], "DOVOZ")["cena"] is None


def test_u_prevodu_se_cena_nesaha():
    assert _uprava(["EL"], "PŘEVOD")["cena"] is None


# ── poznámka ─────────────────────────────────────────────────────────────────
def test_prazdna_poznamka_dostane_EL():
    assert _uprava(["EL RZ"], "NOVÉ", "")["poznamka"] == "EL"


def test_k_existujici_poznamce_se_EL_pripoji():
    assert _uprava(["EL RZ"], "NOVÉ", "Komín")["poznamka"] == "Komín, EL"


def test_uz_zapsane_EL_se_neopakuje():
    """Jinak by z toho po pár překreslení bylo „EL, EL, EL"."""
    assert _uprava(["EL RZ"], "NOVÉ", "Komín, EL")["poznamka"] == "Komín, EL"
    assert _uprava(["EL RZ"], "NOVÉ", "EL")["poznamka"] == "EL"
