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


@pytest.mark.parametrize("soubor", ["test_orv_auto.cjs", "test_orv_auto_zadosti.cjs"])
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
