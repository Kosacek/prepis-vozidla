"""Návrhy u poznámek (David 2026-10-26).

v1.26.0 vypnul Chromu návrhy na všech polích, protože přes seznam firem a
jmen přikrýval svoje „naposledy napsané". Spolu s tím ale zmizely i u polí,
kam se pořád píšou stejné věty (jiný doklad, žádost o změnu, poznámky,
poznámka k úkonu). Ta mají data-navrhy: Chrome tam zůstává zapnutý a appka
k tomu nabízí dřív napsané texty, nejčastější nahoře. Testy pouštějí
skutečný static/klavesnice.js v node proti falešné stránce.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "index.html"
KLAVESNICE = ROOT / "static" / "klavesnice.js"

NAVRHY = ["jiny_doklad", "zadost_zmena", "poznamky", "evidence_poznamka"]
BEZ_NAVRHU = ["puvodni_jmeno", "novy_jmeno", "novy_prov_jmeno", "puvodni_prov_jmeno",
              "novy_ico", "novy_adresa", "ppd_prijato_od", "vin", "registracni_znacka"]


def _input_tag(html: str, field_id: str) -> str:
    m = re.search(r'<input[^>]*\bid="%s"[^>]*>' % re.escape(field_id), html)
    assert m, field_id
    return m.group(0)


@pytest.mark.parametrize("field_id", NAVRHY)
def test_poznamky_maji_navrhy(field_id):
    tag = _input_tag(TEMPLATE.read_text(encoding="utf-8"), field_id)
    assert "data-navrhy" in tag
    assert 'autocomplete="off"' not in tag


@pytest.mark.parametrize("field_id", BEZ_NAVRHU)
def test_firmy_a_jmena_navrhy_nemaji(field_id):
    """U firem a jmen zůstávají návrhy Chromu vypnuté — přikrývaly seznam appky."""
    html = TEMPLATE.read_text(encoding="utf-8")
    if f'id="{field_id}"' not in html:
        pytest.skip(f"{field_id} v šabloně není")
    assert "data-navrhy" not in _input_tag(html, field_id)


def test_texty_se_zapamatuji_po_vygenerovani():
    html = TEMPLATE.read_text(encoding="utf-8")
    uspech = html.index("if (result.success) {", html.index("async function generatePDFs"))
    assert "zapamatujNavrhy(data)" in html[uspech:uspech + 200]


# ── Skutečný klavesnice.js v node ────────────────────────────────────────────

FAKE = r"""
const ulozeno = { hodnota: ULOZENO };
globalThis.localStorage = ROZBITE ? {
  getItem() { throw new Error('zakázáno'); }, setItem() { throw new Error('zakázáno'); },
} : {
  getItem: k => k === 'zadosti_navrhy' ? ulozeno.hodnota : null,
  setItem: (k, v) => { if (k === 'zadosti_navrhy') ulozeno.hodnota = v; },
};
function prvek(id, attrs, value) {
  const a = { ...attrs };
  return {
    id, value: value || '', tagName: 'INPUT',
    hasAttribute: n => n in a, getAttribute: n => (n in a ? a[n] : null),
    setAttribute: (n, v) => { a[n] = String(v); }, removeAttribute: n => { delete a[n]; },
    matches: () => true, attrs: a,
  };
}
const pole = POLE.map(([id, attrs, value]) => prvek(id, attrs, value));
const vBody = {};
globalThis.document = {
  querySelectorAll: sel => sel === 'input[data-navrhy]' ? pole.filter(p => p.hasAttribute('data-navrhy'))
    : sel.startsWith('input:not') ? pole : [],
  querySelector: () => ({ cloneNode: () => ({}) }),
  getElementById: id => vBody[id] || null,
  createElement: tag => ({ tagName: tag, children: [], replaceChildren(...d) { this.children = d; } }),
  addEventListener() {},
  body: { dataset: {}, appendChild: el => { vBody[el.id] = el; } },
};
globalThis.window = { addEventListener() {}, crypto: {} };
globalThis.performance = { now: () => 0 };
globalThis.MutationObserver = class { observe() {} };
globalThis.setInterval = () => 0;
const currentPanel = () => 1;
let cameraStream = null, appMode = 'prevod';
"""


def _node(script: str) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - závisí na stroji
        pytest.skip("node není nainstalovaný")
    r = subprocess.run([node, "-e", script], capture_output=True, text=True,
                       encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _stranka(pole, akce="", ulozeno=None, rozbite=False) -> dict:
    fake = (FAKE.replace("ULOZENO", json.dumps(json.dumps(ulozeno) if ulozeno is not None else None))
                .replace("ROZBITE", "true" if rozbite else "false")
                .replace("POLE", json.dumps(pole)))
    return _node(fake + KLAVESNICE.read_text(encoding="utf-8") + "\n" + akce + """
console.log(JSON.stringify({
  pole: Object.fromEntries(pole.map(p => [p.id, p.attrs])),
  seznamy: Object.fromEntries(Object.entries(vBody).filter(([k]) => k.startsWith('navrhy-'))
    .map(([k, v]) => [k, v.children.map(o => o.value)])),
  ulozeno: ulozeno.hodnota ? JSON.parse(ulozeno.hodnota) : null,
}));""")


def test_chrome_zustava_zapnuty_jen_u_poznamek():
    r = _stranka([["poznamky", {"data-navrhy": "", "autocomplete": "off"}, ""],
                  ["novy_jmeno", {}, ""]])
    assert "autocomplete" not in r["pole"]["poznamky"]
    assert r["pole"]["poznamky"]["list"] == "navrhy-poznamky"
    assert r["pole"]["novy_jmeno"]["autocomplete"] == "off"
    assert "list" not in r["pole"]["novy_jmeno"]


def test_nejcastejsi_text_je_nahore():
    ulozeno = {"poznamky": {"ŽÁDÁM O EL RZ TYP 801": [1, 300],
                            "ZÁPIS A50-X": [5, 100],
                            "KOLA": [1, 200]}}
    r = _stranka([["poznamky", {"data-navrhy": ""}, ""]], ulozeno=ulozeno)
    assert r["seznamy"]["navrhy-poznamky"] == ["ZÁPIS A50-X", "ŽÁDÁM O EL RZ TYP 801", "KOLA"]


def test_po_vygenerovani_se_text_pricte_a_seznam_obnovi():
    r = _stranka([["poznamky", {"data-navrhy": ""}, "  kola   a50-x "],
                  ["evidence_poznamka", {"data-navrhy": ""}, ""],
                  ["novy_jmeno", {}, "JAN NOVÁK"]],
                 akce="window.zapamatujNavrhy(); window.zapamatujNavrhy();",
                 ulozeno={"poznamky": {"ZÁPIS A50-X": [1, 1]}})
    assert r["ulozeno"]["poznamky"]["KOLA A50-X"][0] == 2
    assert r["seznamy"]["navrhy-poznamky"] == ["KOLA A50-X", "ZÁPIS A50-X"]
    assert "evidence_poznamka" not in r["ulozeno"]       # prázdné se neukládá
    assert "novy_jmeno" not in r["ulozeno"]              # jména appka nesbírá


def test_seznam_ma_strop_a_vypadne_nejmene_pouzivany():
    ulozeno = {"poznamky": {f"TEXT {i}": [2, i] for i in range(30)}}
    ulozeno["poznamky"]["STARÝ JEDNOU"] = [1, 0]
    r = _stranka([["poznamky", {"data-navrhy": ""}, "NOVÝ"]],
                 akce="window.zapamatujNavrhy();", ulozeno=ulozeno)
    texty = r["ulozeno"]["poznamky"]
    assert len(texty) == 30
    assert "NOVÝ" in texty and "STARÝ JEDNOU" not in texty


def test_bez_uloziste_stranka_nespadne():
    r = _stranka([["poznamky", {"data-navrhy": ""}, "KOLA"]],
                 akce="window.zapamatujNavrhy();", rozbite=True)
    assert r["seznamy"]["navrhy-poznamky"] == []
    assert r["pole"]["poznamky"]["list"] == "navrhy-poznamky"


def test_poskozena_historie_nerozbije_stranku():
    """Rozbitý záznam (jiný formát, ruční zásah) nesmí shodit klavesnice.js
    ani generování — jen se přeskočí."""
    r = _stranka([["poznamky", {"data-navrhy": ""}, "KOLA"]],
                 akce="window.zapamatujNavrhy();",
                 ulozeno={"poznamky": {"ŠPATNĚ": None, "TAKY": "x", "ZÁPIS A50-X": [3, 1]},
                          "jiny_doklad": "nesmysl"})
    assert r["seznamy"]["navrhy-poznamky"][:2] == ["ZÁPIS A50-X", "KOLA"]


def test_uklada_se_to_co_odeslo_ne_schovane_pole():
    """„Žádá o provedení změny" se posílá jen u změny — text, který v poli
    zůstal po přepnutí typu, se do návrhů nepočítá."""
    r = _stranka([["zadost_zmena", {"data-navrhy": ""}, "ZÁPIS A50-X"],
                  ["poznamky", {"data-navrhy": ""}, "KOLA"]],
                 akce="window.zapamatujNavrhy({zadost_zmena: '', poznamky: 'KOLA'});")
    assert "zadost_zmena" not in (r["ulozeno"] or {})
    assert r["ulozeno"]["poznamky"]["KOLA"][0] == 1
