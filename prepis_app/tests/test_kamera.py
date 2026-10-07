"""Kamera se nesmí „ztratit" — po pár žádostech přestala fungovat.

Reálná stížnost 2026-10-07: po několika žádostech kamera přestala jít a
pomohlo jen vytáhnout USB a obnovit stránku. Proudy z kamery se otevíraly a
nezavíraly; každý drží ovladač, a po pár kusech se Windows ovladač zasekne.

Testy pouštějí SKUTEČNÝ kód kamery z templates/index.html v node proti
falešné kameře, která počítá každý otevřený a zastavený proud. Falešné
getUserMedia schválně chvíli trvá — jako USB kamera (0,5–2 s) — protože
právě v tom okně vznikaly osiřelé proudy.
"""
import json
import os
import shutil
import subprocess

import pytest

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")
START = "let cameraStream = null;"
END = "window.addEventListener('pagehide', () => { closeCamera(); });"

# Falešný prohlížeč: jen to, na co kód kamery sahá.
FAKE = r"""
const stav = { otevreno: 0, zastaveno: 0, panel: 1, prodleva: 80, pagehide: null };
const el = () => ({ style: {}, srcObject: null, pause() {}, play() { return Promise.resolve(); } });
const prvky = {};
globalThis.document = {
  getElementById: id => (prvky[id] = prvky[id] || el()),
  addEventListener() {}, body: { addEventListener() {}, removeEventListener() {} },
};
globalThis.window = { addEventListener: (typ, fn) => { if (typ === 'pagehide') stav.pagehide = fn; } };
globalThis.alert = () => {};
// Node má vlastní globální `navigator` jen pro čtení — prosté přiřazení by
// tiše neprošlo, proto defineProperty.
Object.defineProperty(globalThis, 'navigator', { configurable: true, writable: true, value: {
  mediaDevices: { getUserMedia: () => {
    if (stav.selzeSynchronne) throw new TypeError('mediaDevices není k dispozici');
    return new Promise(res => {
      setTimeout(() => {
        stav.otevreno++;
        let zivy = true;
        res({ getTracks: () => [{ stop() { if (zivy) { zivy = false; stav.zastaveno++; } } }] });
      }, stav.prodleva);
    });
  } } } });
globalThis.currentPanel = () => stav.panel;
const pockej = ms => new Promise(r => setTimeout(r, ms));
const zive = () => stav.otevreno - stav.zastaveno;
"""


def _kod_kamery() -> str:
    with open(TEMPLATE, encoding="utf-8") as fh:
        html = fh.read()
    start = html.index(START)
    return html[start:html.index(END, start) + len(END)]


def _spust(scenar: str) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - závisí na stroji
        pytest.skip("node není nainstalovaný")
    script = (FAKE + _kod_kamery()
              + "\n(async () => {\n" + scenar
              + "\nawait pockej(600);\n"
              + "console.log(JSON.stringify({otevreno: stav.otevreno, zastaveno: stav.zastaveno, zive: zive()}));\n"
              + "})();\n")
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_dve_otevreni_naraz_otevrou_jen_jeden_proud():
    """Automatika + klik těsně po sobě: dřív dva proudy, jeden osiřel."""
    s = _spust("tryAutoOpenCamera(); tryAutoOpenCamera();")
    assert s["otevreno"] == 1
    assert s["zive"] == 1


def test_klik_na_kameru_behem_automatickeho_otevirani_nenecha_osirely_proud():
    s = _spust("tryAutoOpenCamera(); await pockej(20); await openCamera();")
    assert s["zive"] == 1, "běží víc kamer najednou — jedna zůstala osiřelá"


def test_odchod_z_kroku_1_behem_otevirani_kameru_pusti():
    """Klik na typ operace dřív, než se kamera stihla otevřít."""
    s = _spust("tryAutoOpenCamera(); await pockej(20); stav.panel = 2; closeCamera();")
    assert s["zive"] == 0, "kamera běží skrytá i po odchodu z kroku 1"


def test_pozde_dorazeny_proud_se_zastavi_i_bez_closeCamera():
    """Pojistka: i kdyby closeCamera nikdo nezavolal, proud z kroku, kde už
    nejsme, se nesmí ujmout."""
    s = _spust("tryAutoOpenCamera(); await pockej(20); stav.panel = 3;")
    assert s["zive"] == 0


def test_nova_zadost_kameru_pusti_pred_obnovenim_stranky():
    """„Nová žádost" obnovuje stránku — dřív s kamerou pořád otevřenou."""
    s = _spust("await tryAutoOpenCamera(); await pockej(150); stav.pagehide();")
    assert s["otevreno"] == 1 and s["zive"] == 0


def test_selhani_kamery_nezablokuje_dalsi_pokusy():
    """Našel to tenhle test: když getUserMedia selže hned (synchronně), stav
    „otevírá se" zůstal viset a kamera už nešla otevřít nikdy."""
    s = _spust("""
      stav.selzeSynchronne = true;
      try { await openCamera(); } catch (_) {}
      stav.selzeSynchronne = false;
      await openCamera();
    """)
    assert s["otevreno"] == 1 and s["zive"] == 1


def test_desitky_cyklu_neustradaji_zadny_proud():
    """Přesně Davidův vzorec: žádost za žádostí, s klikáním a návraty."""
    s = _spust("""
      for (let i = 0; i < 15; i++) {
        stav.panel = 1;
        tryAutoOpenCamera();
        if (i % 3 === 0) { await pockej(10); openCamera(); }
        await pockej(i % 2 ? 30 : 120);
        stav.panel = 2; closeCamera();
        await pockej(20);
      }
    """)
    assert s["zive"] == 0, f"po 15 cyklech pořád běží {s['zive']} proud(ů)"
    assert s["otevreno"] == s["zastaveno"]
