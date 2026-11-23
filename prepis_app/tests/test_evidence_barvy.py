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


def test_avatarem_je_logo_nebo_inicialy_a_tecka_patri_firme():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = _html()

    def function(name):
        start = h.index(f"function {name}(")
        return h[start:h.index("\n}", start) + 2]

    js = "\n".join(function(name) for name in (
        "esc", "_firmSearchText", "_firmInitials", "_firmAvatar",
        "evidenceBarva", "evidenceFirma", "firmaDot",
    )) + """
const _firmaLoga = {'01234567': 'svg'};
const _evidenceMeta = {firmy: [
  {id: 1, ico: '01234567', zkratka: 'AV', nazev: 'Auto Vltava', barva: '#0a84ff'},
  {id: 2, ico: '87654321', nazev: 'Auto Morava', barva: '#137200'},
]};
console.log(JSON.stringify([
  _firmAvatar({ico: '01234567', nazev: 'Auto Vltava'}),
  _firmAvatar({ico: '87654321', nazev: 'Auto Morava'}),
  _firmAvatar({ico: '55555555', nazev: 'Nové Auto', id: '1'}),
  firmaDot({nazev: ' AUTO VLTAVA '}),
  firmaDot({zkratka: 'AV'}, true),
  firmaDot({firma_id: 3}, true),
  firmaDot({ico: '99999999', nazev: 'Auto Vltava'}),
  firmaDot({firma_id: 2}, true),
]));
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True,
                            encoding="utf-8", check=True)
    logo, evidence, neutral, jmeno, zkratka, neznamy, jine_ico, ukon = json.loads(result.stdout)
    assert 'src="/firma-logo/01234567"' in logo and 'onerror="this.remove()"' in logo
    assert "background:#0a84ff" in logo and ">AV</span>" in logo
    assert "<img" not in evidence and "background:#137200" in evidence and ">AM</span>" in evidence
    assert "<img" not in neutral and "firma-dot" not in neutral and ">NA</span>" in neutral
    assert "background:#0a84ff" in jmeno and "background:#0a84ff" in zkratka
    assert "background:var(--muted)" in neznamy and jine_ico == ""
    assert "background:#137200" in ukon
