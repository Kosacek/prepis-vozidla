"""Výběr firmy v kartě „Evidence úkonu" nese barvu firmy z evidence (`barva`).

Spouští skutečný JS z templates/index.html přes node. Barva se nikdy nevymýšlí
v žádostech a do stylu smí jen #hex."""
import json
import os
import shutil
import subprocess

import pytest

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")


def _html() -> str:
    with open(TEMPLATE, encoding="utf-8") as fh:
        return fh.read()


def _barva(firma) -> str:
    node = shutil.which("node")
    if not node:  # pragma: no cover
        pytest.skip("node not installed")
    h = _html()
    start = h.index("function evidenceBarva")
    end = h.index("async function loadEvidenceMeta", start)
    js = h[start:end] + f"\nprocess.stdout.write(JSON.stringify(evidenceBarva({json.dumps(firma)})));"
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_barva_z_evidence_projde():
    assert _barva({"id": 1, "barva": "#0a84ff"}) == "#0a84ff"


@pytest.mark.parametrize("firma", [
    {"id": 1}, {"id": 1, "barva": ""}, {"id": 1, "barva": "red"},
    {"id": 1, "barva": "#fff; background:url(x)"}, {"id": 1, "barva": 5}, None,
])
def test_bez_platne_barvy_zadna_barva(firma):
    assert _barva(firma) == ""


def test_picker_pouziva_barvu_a_zustava_nativni_select():
    h = _html()
    assert "o.dataset.color = barva" in h              # tečku kreslí firma_pick.js z data-color
    assert '<select id="evidence_firma"' in h   # klávesnice (klavesnice.js) počítá s selectem


def test_zadna_vlastni_paleta():
    # barvy jen z evidence: v kartě se nesmí objevit pevný seznam hex barev firem
    h = _html()
    start = h.index("function evidenceBarva")
    assert "PALETTE" not in h[start:start + 1500]
