"""Žádosti bez myši (v1.26.0, David 2026-10-23).

Celá žádost jen z klávesnice: na kroku 1 Enter vyfotí ORV, číslice vyberou
typ, Ctrl+Enter vygeneruje a otevře všechny dokumenty, zpátky v appce Enter
spustí novou žádost. Testy pouštějí skutečný kód (globální obsluhu klávesnice
z templates/index.html a static/klavesnice.js) v node proti falešné stránce.
"""
import json
import os
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "index.html"
KLAVESNICE = ROOT / "static" / "klavesnice.js"


def _node(script: str, *args: str):
    node = shutil.which("node")
    if not node:  # pragma: no cover - závisí na stroji
        pytest.skip("node není nainstalovaný")
    r = subprocess.run([node, *args, "-e", script] if not args else [node, *args],
                       capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_klavesnice_js_jde_parsovat():
    _node("", "--check", str(KLAVESNICE))


def test_stranka_nacita_klavesnici_az_za_hlavnim_skriptem():
    html = TEMPLATE.read_text(encoding="utf-8")
    tag = '<script src="/static/klavesnice.js?v={{ APP_VERSION }}"></script>'
    assert tag in html
    assert html.index("tryAutoOpenCamera();\n</script>") < html.index(tag)


# ── Globální obsluha klávesnice ──────────────────────────────────────────────

FAKE = r"""
const stav = { dal: 0, zpet: 0, sken: 0, generovano: 0, otevreno: 0, reset: 0, vybrano: null, zustal: null };
const karty = ['prevod', 'zapis', '3rz', 'pm', 'vyvoz', 'zmena'].map(mode => ({
  dataset: { mode }, tagName: 'DIV', classList: { contains: c => c === 'mode-card' }, focus() {},
}));
const prvky = { 'output-card': { style: { display: 'none' } } };
let fokus = null;
globalThis.document = {
  get activeElement() { return fokus; },
  getElementById: id => prvky[id],
  querySelectorAll: sel => sel === '.mode-card' ? karty : [],
  addEventListener: (typ, fn) => { if (typ === 'keydown') globalThis.obsluha = fn; },
};
const FLOWS = { prevod: { panels: [1, 4, 2, 3, 5] }, pm: { panels: [1, 6] } };
let appMode = 'prevod', flowIdx = 0, panel = 1, cameraStream = {}, _otevritPoGenerovani = false;
const currentPanel = () => panel;
const selectMode = (el, zustat) => { appMode = el.dataset.mode; stav.vybrano = appMode; stav.zustal = !!zustat; };
const quickScanOrv = () => stav.sken++;
const navNext = () => stav.dal++;
const navBack = () => stav.zpet++;
const generatePDFs = () => { stav.generovano++; stav.otevritPo = _otevritPoGenerovani; };
const otevriVsechnyDokumenty = () => stav.otevreno++;
const resetForm = () => stav.reset++;
function klavesa(key, extra = {}) {
  const ev = { key, target: extra.target || { tagName: 'BODY', classList: { contains: () => false } },
    shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, preventDefault() { this.zabrano = true; }, ...extra };
  obsluha(ev);
  return ev;
}
"""


def _obsluha(scenar: str) -> dict:
    html = TEMPLATE.read_text(encoding="utf-8")
    start = html.index("// ── Keyboard")
    kod = html[start:html.index("// ── Mode selection", start)]
    out = _node(FAKE + kod + "\n" + scenar + "\nconsole.log(JSON.stringify(stav));")
    return json.loads(out.strip().splitlines()[-1])


def test_enter_na_kroku_1_s_kamerou_skenuje():
    s = _obsluha("klavesa('Enter');")
    assert s["sken"] == 1 and s["dal"] == 0


def test_shift_enter_jde_dal_bez_skenu():
    s = _obsluha("klavesa('Enter', {shiftKey: true});")
    assert s["sken"] == 0 and s["dal"] == 1


def test_bez_kamery_enter_jen_pokracuje():
    s = _obsluha("cameraStream = null; klavesa('Enter');")
    assert s["sken"] == 0 and s["dal"] == 1


def test_cislice_vybere_typ_a_zustane_na_kroku_1():
    """Česká klávesnice: horní řada píše „ř", ale fyzicky je to pětka."""
    s = _obsluha("klavesa('ř', {code: 'Digit5'});")
    assert s["vybrano"] == "vyvoz" and s["zustal"] is True and s["dal"] == 0 and s["sken"] == 0


def test_plna_moc_enterem_neskenuje():
    s = _obsluha("klavesa('4', {code: 'Numpad4'}); klavesa('Enter');")
    assert s["vybrano"] == "pm" and s["sken"] == 0 and s["dal"] == 1


def test_cislice_v_poli_se_pise_normalne():
    s = _obsluha("klavesa('š', {code: 'Digit3', target: {tagName: 'INPUT', classList: {contains: () => false}}});")
    assert s["vybrano"] is None


def test_ctrl_enter_vygeneruje_a_rovnou_otevre():
    s = _obsluha("panel = 3; flowIdx = 3; klavesa('Enter', {ctrlKey: true});")
    assert s["generovano"] == 1 and s["otevritPo"] is True


def test_enter_na_poslednim_kroku_taky_otevre():
    s = _obsluha("panel = 5; flowIdx = 4; klavesa('Enter'); stav.flag = _otevritPoGenerovani;")
    assert s["dal"] == 1 and s["flag"] is True


def test_enter_driv_nez_na_konci_nic_neotevira():
    s = _obsluha("panel = 2; flowIdx = 2; klavesa('Enter'); stav.flag = _otevritPoGenerovani;")
    assert s["dal"] == 1 and s["flag"] is False


def test_po_vygenerovani_enter_spusti_novou_zadost():
    s = _obsluha("panel = 5; flowIdx = 4; prvky['output-card'].style.display = 'block'; klavesa('Enter');")
    assert s["reset"] == 1 and s["dal"] == 0


def test_po_vygenerovani_zamerene_tlacitko_dela_svoje():
    s = _obsluha("panel = 5; prvky['output-card'].style.display = 'block';"
                 " klavesa('Enter', {target: {tagName: 'BUTTON', classList: {contains: () => false}}});")
    assert s["reset"] == 0


def test_po_vygenerovani_ctrl_enter_otevre_znovu():
    s = _obsluha("panel = 5; prvky['output-card'].style.display = 'block'; klavesa('Enter', {ctrlKey: true});")
    assert s["otevreno"] == 1 and s["generovano"] == 0


# ── Pořadí dokumentů ─────────────────────────────────────────────────────────

def _dokumenty(generated: dict, blokovat_od: int = 99) -> dict:
    fake = r"""
    const otevrene = [];
    const hlaska = { hidden: true, textContent: '' };
    globalThis.window = { open: u => otevrene.length >= BLOK ? null : (otevrene.push(u), {}),
                          addEventListener() {}, crypto: {}, scrollTo() {} };
    globalThis.performance = { now: () => 0 };
    globalThis.document = {
      querySelectorAll: () => [], querySelector: () => ({ cloneNode: () => ({}) }),
      getElementById: id => id === 'okna-blokovana' ? hlaska : null,
      addEventListener() {}, body: { dataset: {} },
    };
    globalThis.MutationObserver = class { observe() {} };
    globalThis.setInterval = () => 0;
    const PRIMARNI_PODLE_MODU = { prevod: 'zmeny', zapis: 'zapis', zmena: 'zmena', '3rz': '3rz', vyvoz: 'vyvoz' };
    const currentPanel = () => 1;
    let cameraStream = null, appMode = 'prevod';
    let generatedUrls = GEN;
    """.replace("BLOK", str(blokovat_od)).replace("GEN", json.dumps(generated))
    out = _node(fake + KLAVESNICE.read_text(encoding="utf-8")
                + "\nwindow.otevriVsechnyDokumenty();\n"
                + "console.log(JSON.stringify({poradi: window.dokumentyKTisku(generatedUrls), otevrene, hlaska}));")
    return json.loads(out.strip().splitlines()[-1])


BALIK = {"mode": "prevod", "zmeny": "/download/zmeny_X.pdf", "ppd": "/download/ppd_7.pdf",
         "ppd_print": "/ppd-print/7", "plne_moce": ["/plna-moc/111", "/plna-moc/222"]}


def test_poradi_tisku_doklad_zadost_plne_moci():
    r = _dokumenty(BALIK)
    assert r["poradi"] == ["/ppd-print/7", "/download/zmeny_X.pdf", "/plna-moc/111", "/plna-moc/222"]


def test_otevira_se_od_konce_aby_ctrl_w_slo_poporadu():
    """Chrome po zavření záložky přejde na sourozence vlevo — první dokument
    se proto otevírá poslední (je pak aktivní)."""
    r = _dokumenty(BALIK)
    assert r["otevrene"] == list(reversed(r["poradi"]))
    assert r["hlaska"]["hidden"] is True


def test_prevod_neotevira_zapis_navic():
    r = _dokumenty({**BALIK, "zapis": "/download/zapis_X.pdf"})
    assert "/download/zapis_X.pdf" not in r["poradi"]


def test_zablokovana_okna_appka_rekne():
    r = _dokumenty(BALIK, blokovat_od=1)
    assert r["hlaska"]["hidden"] is False
    assert "1 z 4" in r["hlaska"]["textContent"]


# ── Záznam kamery ────────────────────────────────────────────────────────────

import app as A

HTTPS = {"CF-Visitor": '{"scheme":"https"}'}
WEB = "https://zadosti.spznaklic.cz"


@pytest.fixture
def prod(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "heslo-jen-pro-test")
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    A._login_pokusy.clear()
    with A.app.test_client() as c:
        yield c
    A._login_pokusy.clear()


def _prihlas(c):
    c.post("/login", data={"password": "heslo-jen-pro-test"}, base_url=WEB, headers=HTTPS)


def test_kamera_log_se_zapise(prod, tmp_path):
    _prihlas(prod)
    r = prod.post("/api/kamera-log", json={"udalost": "restart", "detail": "obraz zamrzl"},
                  base_url=WEB, headers=HTTPS)
    assert r.status_code == 200
    radky = (tmp_path / A.KAMERA_LOG).read_text(encoding="utf-8").splitlines()
    zaznam = json.loads(radky[-1])
    assert zaznam["udalost"] == "restart" and zaznam["detail"] == "obraz zamrzl"


@pytest.mark.parametrize("udalost", ["", "DROP TABLE", "x" * 31, "../../etc", None])
def test_kamera_log_odmitne_nesmysl(prod, tmp_path, udalost):
    _prihlas(prod)
    r = prod.post("/api/kamera-log", json={"udalost": udalost}, base_url=WEB, headers=HTTPS)
    assert r.status_code == 400
    assert not (tmp_path / A.KAMERA_LOG).exists()


def test_kamera_log_jen_po_prihlaseni(prod, tmp_path):
    r = A.app.test_client().post("/api/kamera-log", json={"udalost": "zapnuta"}, base_url=WEB, headers=HTTPS)
    assert r.status_code == 302
    assert not (tmp_path / A.KAMERA_LOG).exists()


def test_kamera_log_nenaroste_donekonecna(prod, tmp_path, monkeypatch):
    monkeypatch.setattr(A, "_KAMERA_LOG_MAX", 2000)
    _prihlas(prod)
    for i in range(80):
        prod.post("/api/kamera-log", json={"udalost": "zapnuta", "detail": "x" * 50},
                  base_url=WEB, headers=HTTPS)
    assert os.path.getsize(tmp_path / A.KAMERA_LOG) < 2000 + 600
