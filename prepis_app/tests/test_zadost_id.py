"""The evidence tracker dedups on `zadost_id`, so the browser must mint a new one
exactly when the žádost describes a DIFFERENT úkon.

The bug this guards against: the id used to be minted once per page load, so the
real-world flow "generate → print → ← Upravit údaje → change the last two VIN
digits (same firm, next car) → generate again" reused the id and the tracker threw
the second úkon away. Only a full page reload ("Nová žádost") produced a new id.

These tests run the JS that actually ships in templates/index.html through node,
so they fail if the function is edited into something that no longer distinguishes
two different vehicles.
"""
import json
import os
import shutil
import subprocess

import pytest

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")
END_MARKER = "return _zadostSeed + '-' + h.toString(16).padStart(8, '0');\n}"


def _extract_js() -> str:
    with open(TEMPLATE, encoding="utf-8") as fh:
        html = fh.read()
    start = html.index("let _zadostSeed")
    end = html.index(END_MARKER, start) + len(END_MARKER)
    return html[start:end]


def _ids(*payloads, reseed_before=()) -> list:
    """Run the real JS over each payload and return the resulting ids.

    Indexes listed in `reseed_before` get a fresh seed first — that simulates
    "Nová žádost", which reloads the page.
    """
    node = shutil.which("node")
    if not node:  # pragma: no cover - depends on the dev machine
        pytest.skip("node not installed")
    script = (
        "globalThis.window = {};\n"          # no window.crypto -> deterministic fallback branch
        + _extract_js()
        + "\nconst payloads = " + json.dumps(list(payloads)) + ";\n"
        + "const reseed = " + json.dumps(list(reseed_before)) + ";\n"
        + "const out = payloads.map((p, i) => {\n"
        + "  if (reseed.includes(i)) _zadostSeed = 'seed-' + i;\n"
        + "  return zadostIdFor(p);\n"
        + "});\n"
        + "console.log(JSON.stringify(out));\n"
    )
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


BASE = {
    "mode": "prevod",
    "vin": "TMBJJ7NE5J0123456",
    "registracni_znacka": "1AB2345",
    "puvodni_jmeno": "AUTO PROFIT S.R.O.",
    "puvodni_ico": "04156854",
    "novy_jmeno": "JAN NOVAK",
    "novy_ico": "",
    "evidence_firma_id": "5",
    "evidence_typ": "PREVOD",
    "evidence_cena": "1300",
}


def test_unchanged_form_keeps_the_same_id():
    """Hitting Generovat twice on an untouched form must NOT create a second úkon."""
    first, second = _ids(BASE, dict(BASE))
    assert first == second


def test_edited_vin_gets_a_new_id():
    """David's actual flow: same firm, next car, only the VIN tail differs."""
    next_car = dict(BASE, vin="TMBJJ7NE5J0123499")
    first, second = _ids(BASE, next_car)
    assert first != second


@pytest.mark.parametrize("field,value", [
    ("registracni_znacka", "9XY8765"),
    ("novy_ico", "27082440"),
    ("novy_jmeno", "JINA FIRMA S.R.O."),
    ("evidence_firma_id", "7"),
    ("evidence_typ", "KOLA"),
    ("evidence_cena", "1500"),
    ("mode", "zmena"),
])
def test_every_identity_field_forces_a_new_id(field, value):
    first, second = _ids(BASE, dict(BASE, **{field: value}))
    assert first != second, f"changing {field} must create a new úkon"


@pytest.mark.parametrize("field,value", [
    ("poznamky", "NECO NAVIC"),
    ("ppd_castka", "2000"),
    ("evidence_poznamka", "SPECHA TO"),
    ("puvodni_adresa", "JINA ULICE 5"),
])
def test_cosmetic_edits_do_not_split_the_ukon(field, value):
    """Fixing a typo in an address or bumping the PPD amount is the same úkon —
    it must not silently produce a duplicate in evidence."""
    first, second = _ids(BASE, dict(BASE, **{field: value}))
    assert first == second


def test_identity_is_case_and_whitespace_insensitive():
    """Inputs uppercase live as you type; a stray space must not fork the úkon."""
    first, second = _ids(BASE, dict(BASE, vin="  tmbjj7ne5j0123456 "))
    assert first == second


def test_new_page_load_resends_even_an_identical_vehicle():
    """"Nová žádost" reloads the page. The very same vehicle must then reach the
    tracker again — deciding whether that is a real duplicate is the tracker's
    job (it can queue it in Příchozí), not something zadosti may silently drop."""
    first, second = _ids(BASE, dict(BASE), reseed_before=[1])
    assert first != second
