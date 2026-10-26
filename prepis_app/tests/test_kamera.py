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
END = "window.addEventListener('pagehide', () => { closeCamera('pagehide'); });"

# Falešný prohlížeč: jen to, na co kód kamery sahá. getUserMedia umí i
# selhat jako skutečná USB kamera (stav.chyby = fronta názvů chyb pro další
# pokusy, stav.vzdyChyba = selhává pořád) a zapisuje si, kdy ho kdo volal.
FAKE = r"""
const stav = { otevreno: 0, zastaveno: 0, panel: 1, prodleva: 80, pagehide: null,
               volani: [], chyby: [], vzdyChyba: null, dokument: {}, okno: {}, devicechange: null,
               uloziste: {} };
const el = () => ({ style: {}, srcObject: null, hidden: false, textContent: '',
                    pause() {}, play() { return Promise.resolve(); } });
const prvky = {};
globalThis.document = {
  hidden: false,
  getElementById: id => (prvky[id] = prvky[id] || el()),
  addEventListener: (typ, fn) => { stav.dokument[typ] = fn; },
  body: { addEventListener() {}, removeEventListener() {} },
};
globalThis.window = { addEventListener: (typ, fn) => {
  if (typ === 'pagehide') stav.pagehide = fn; else stav.okno[typ] = fn; } };
globalThis.localStorage = {
  getItem: k => (k in stav.uloziste ? stav.uloziste[k] : null),
  setItem: (k, v) => { stav.uloziste[k] = String(v); },
};
globalThis.alert = () => {};
// Node má vlastní globální `navigator` jen pro čtení — prosté přiřazení by
// tiše neprošlo, proto defineProperty.
Object.defineProperty(globalThis, 'navigator', { configurable: true, writable: true, value: {
  mediaDevices: {
    addEventListener: (typ, fn) => { if (typ === 'devicechange') stav.devicechange = fn; },
    getUserMedia: () => {
      stav.volani.push(Date.now());
      if (stav.selzeSynchronne) throw new TypeError('mediaDevices není k dispozici');
      return new Promise((res, rej) => {
        setTimeout(() => {
          const chyba = stav.chyby.length ? stav.chyby.shift() : stav.vzdyChyba;
          if (chyba) { const e = new Error(chyba); e.name = chyba; rej(e); return; }
          stav.otevreno++;
          let zivy = true;
          const stopa = { muted: false, readyState: 'live',
                          stop() { if (zivy) { zivy = false; stav.zastaveno++; } } };
          res({ getTracks: () => [stopa], getVideoTracks: () => [stopa] });
        }, stav.prodleva);
      });
    } } } });
globalThis.currentPanel = () => stav.panel;
const pockej = ms => new Promise(r => setTimeout(r, ms));
const zive = () => stav.otevreno - stav.zastaveno;
const dlazdice = () => ({ chyba: prvky['camera-chyba'] ? (prvky['camera-chyba'].hidden ? '' : prvky['camera-chyba'].textContent) : '',
                          tlacitko: prvky['camera-zapnout-text'] ? prvky['camera-zapnout-text'].textContent : '',
                          nahled: prvky['camera-container'] ? prvky['camera-container'].style.display : null });
"""

KLID = "const KAMERA_KLID_MS = 3000;"
POKUSY = "const KAMERA_POKUSY_MS = [3000, 8000, 20000];"


def _kod_kamery(klid: int = 30, pokusy: str = "[40, 80]") -> str:
    """Kód kamery ze šablony; časy zkrácené, ať testy netrvají minuty."""
    with open(TEMPLATE, encoding="utf-8") as fh:
        html = fh.read()
    start = html.index(START)
    kod = html[start:html.index(END, start) + len(END)]
    assert KLID in kod and POKUSY in kod, "konstanty kamery se přejmenovaly — uprav test"
    return (kod.replace(KLID, f"const KAMERA_KLID_MS = {klid};")
               .replace(POKUSY, f"const KAMERA_POKUSY_MS = {pokusy};"))


def _node(script: str) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - závisí na stroji
        pytest.skip("node není nainstalovaný")
    res = subprocess.run([node, "-e", script], capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _spust(scenar: str, klid: int = 30, pokusy: str = "[40, 80]", konec_ms: int = 600) -> dict:
    return _node(FAKE + _kod_kamery(klid, pokusy)
                 + "\n(async () => {\n" + scenar
                 + f"\nawait pockej({konec_ms});\n"
                 + "console.log(JSON.stringify({otevreno: stav.otevreno, zastaveno: stav.zastaveno,"
                   " zive: zive(), volani: stav.volani, dlazdice: dlazdice(), vystup: globalThis.vystup || null}));\n"
                 + "})();\n")


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


def test_proud_dorazeny_po_odchodu_z_kroku_1_se_ujme_a_je_jen_jeden():
    """Od v1.26.0 kamera běží celou dobu (David, 2026-10-23) — proud, který
    dorazí, až když je uživatel o krok dál, se ujme. Osiřelý ale být nesmí:
    drží ho cameraStream, takže ho closeCamera i pagehide najdou."""
    s = _spust("tryAutoOpenCamera(); await pockej(20); stav.panel = 3; await pockej(150);"
               " tryAutoOpenCamera(); stav.panel = 1; tryAutoOpenCamera();")
    assert s["otevreno"] == 1 and s["zive"] == 1


def test_patnact_zadosti_za_sebou_kamera_se_zapne_jen_jednou():
    """To hlavní z v1.26.0: po ~5 zapnutích a vypnutích USB kamera zamrzla.
    Nová žádost stránku neobnovuje a kroky kameru nevypínají — za celý den
    se tedy zapne jednou."""
    s = _spust("""
      for (let i = 0; i < 15; i++) {
        stav.panel = 1; tryAutoOpenCamera();
        await pockej(i === 0 ? 150 : 10);
        stav.panel = 4; await pockej(10);
        stav.panel = 5; await pockej(10);
      }
      stav.panel = 1; tryAutoOpenCamera();
    """)
    assert s["otevreno"] == 1 and s["zastaveno"] == 0 and s["zive"] == 1


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


# ── Zaseknutá USB kamera (2026-10-26) ────────────────────────────────────────
# kamera_log.jsonl ukázal vzorec u každé mrtvé kamery: puštění a hned nové
# otevření (reload = nová stránka sáhne po kameře za 1 s, restart hlídače za
# 0,8 s) → „Timeout starting video source" → už jen NotReadableError, dokud
# někdo nepřepojil USB. Appka pak potichu zkoušela dál a dlaždice ukazovala
# jen „Zapnout kameru".

def test_po_pusteni_se_kamera_hned_neotevre():
    s = _spust("""
      await tryAutoOpenCamera(); await pockej(120);
      closeCamera('test'); globalThis.vystup = Date.now();
      tryAutoOpenCamera();
    """, klid=300, konec_ms=700)
    assert s["volani"][1] - s["vystup"] >= 290, "kamera se otevřela hned po puštění"
    assert s["zive"] == 1


def test_klid_plati_i_po_obnoveni_stranky():
    """Puštění při pagehide se pamatuje v localStorage — nová stránka počká."""
    kod = _kod_kamery(klid=400)
    s = _node(FAKE + "\nconst stranka = () => { " + kod + "\n return { tryAutoOpenCamera }; };\n"
              + """
(async () => {
  const stara = stranka();
  await stara.tryAutoOpenCamera(); await pockej(150);
  stav.pagehide(); const pusteno = Date.now();
  const nova = stranka();
  nova.tryAutoOpenCamera();
  await pockej(900);
  console.log(JSON.stringify({ cekala: stav.volani[1] - pusteno, zive: zive() }));
})();
""")
    assert s["cekala"] >= 390, "nová stránka sáhla po kameře, kterou stará právě pustila"
    assert s["zive"] == 1


def test_zaseknuta_kamera_se_zkusi_par_krat_a_pak_to_dlazdice_rekne():
    s = _spust("stav.vzdyChyba = 'NotReadableError'; tryAutoOpenCamera();",
               pokusy="[60, 120]", konec_ms=900)
    assert len(s["volani"]) == 3, f"čekal jsem 1 + 2 pokusy, bylo {len(s['volani'])}"
    assert "zasekla" in s["dlazdice"]["chyba"].lower()
    assert s["dlazdice"]["tlacitko"] == "Zkusit znovu"


def test_pokusy_nejsou_tesne_za_sebou():
    s = _spust("stav.vzdyChyba = 'NotReadableError'; tryAutoOpenCamera();",
               klid=150, pokusy="[0, 0]", konec_ms=1200)
    mezery = [b - a for a, b in zip(s["volani"], s["volani"][1:])]
    assert mezery and all(m >= 140 for m in mezery), mezery


def test_bez_povoleni_se_nebusi_a_dlazdice_to_rekne():
    s = _spust("stav.vzdyChyba = 'NotAllowedError'; tryAutoOpenCamera();", konec_ms=500)
    assert len(s["volani"]) == 1
    assert "povolení" in s["dlazdice"]["chyba"]


def test_odpojena_kamera_se_po_zapojeni_zapne_sama():
    """Přepojení USB = devicechange → kamera naskočí bez klikání."""
    s = _spust("""
      stav.vzdyChyba = 'NotFoundError'; tryAutoOpenCamera(); await pockej(400);
      globalThis.vystup = dlazdice().chyba;
      stav.vzdyChyba = null; stav.devicechange();
    """, konec_ms=700)
    assert "připojená" in s["vystup"]
    assert s["zive"] == 1
    assert s["dlazdice"]["chyba"] == "" and s["dlazdice"]["nahled"] == ""


def test_navrat_do_okna_zkusi_mrtvou_kameru_znovu():
    s = _spust("""
      stav.vzdyChyba = 'NotReadableError'; tryAutoOpenCamera(); await pockej(400);
      stav.vzdyChyba = null; document.hidden = false; stav.dokument.visibilitychange();
    """, pokusy="[]", konec_ms=400)
    assert s["zive"] == 1 and s["dlazdice"]["chyba"] == ""


def test_zkusit_znovu_kameru_zapne_a_hlasku_schova():
    s = _spust("""
      stav.vzdyChyba = 'NotReadableError'; tryAutoOpenCamera(); await pockej(400);
      stav.vzdyChyba = null; await openCamera();
    """, pokusy="[]", konec_ms=300)
    assert s["zive"] == 1
    assert s["dlazdice"]["chyba"] == "" and s["dlazdice"]["tlacitko"] == "Zapnout kameru"


def test_zapojeni_navrat_a_klik_naraz_otevrou_jeden_proud():
    s = _spust("""
      stav.vzdyChyba = 'NotFoundError'; tryAutoOpenCamera(); await pockej(400);
      stav.vzdyChyba = null;
      stav.devicechange(); stav.dokument.visibilitychange(); openCamera(); tryAutoOpenCamera();
    """, pokusy="[]", konec_ms=600)
    assert s["otevreno"] == 1 and s["zive"] == 1



def test_zavreni_behem_cekani_na_klid_kameru_neztrati():
    """Našel to test v prohlížeči: zavřít a znovu otevřít, zatímco předchozí
    otevírání ještě čeká na klid → nové se připojilo ke zrušenému a kamera
    už nenaskočila."""
    s = _spust("""
      await tryAutoOpenCamera(); await pockej(120);
      closeCamera('a'); tryAutoOpenCamera(); await pockej(20);
      closeCamera('b'); tryAutoOpenCamera();
    """, klid=200, konec_ms=800)
    assert s["zive"] == 1, "po dvou restartech těsně za sebou kamera neběží"
    assert s["otevreno"] == 2

# ── Hlídač zamrzlého obrazu (static/klavesnice.js) ───────────────────────────
# Dřív každý zamrzlý obraz = kameru pustit a za 0,8 s otevřít znovu, tedy
# přesně to, po čem se USB kamera zasekla. Dokud stopa žije (není „mute"),
# stál jen přehrávač: stačí ho znovu napojit a zařízení zůstane otevřené.

KLAVESNICE = os.path.join(os.path.dirname(__file__), "..", "static", "klavesnice.js")

FAKE_HLIDAC = r"""
const stav = { zavreno: [], otevirano: 0, log: [], cas: 0 };
const video = { srcObject: null, napojeno: 0, play() { this.napojeno++; return Promise.resolve(); } };
let stopa = { muted: MUTED, readyState: 'live' };
let cameraStream = { getVideoTracks: () => [stopa] };
video.srcObject = cameraStream;
globalThis.document = {
  querySelectorAll: () => [], querySelector: () => ({ cloneNode: () => ({}) }),
  getElementById: id => id === 'camera-video' ? video : null,
  addEventListener() {}, body: { dataset: {} },
};
globalThis.window = { addEventListener() {}, crypto: {} };
globalThis.performance = { now: () => stav.cas };
globalThis.fetch = (url, o) => { stav.log.push(JSON.parse(o.body).udalost); return Promise.resolve(); };
globalThis.MutationObserver = class { observe() {} };
globalThis.setInterval = () => 0;
globalThis.localStorage = { getItem: () => null, setItem() {} };
const currentPanel = () => 1;
let appMode = 'prevod', _scanInFlight = false;
const closeCamera = duvod => { stav.zavreno.push(duvod); cameraStream = null; };
const tryAutoOpenCamera = () => { stav.otevirano++; };
"""


def _hlidac(muted: bool, akce: str) -> dict:
    with open(KLAVESNICE, encoding="utf-8") as fh:
        kod = fh.read()
    return _node(FAKE_HLIDAC.replace("MUTED", "true" if muted else "false") + kod + "\n" + akce
                 + "\nsetTimeout(() => console.log(JSON.stringify({zavreno: stav.zavreno,"
                   " otevirano: stav.otevirano, log: stav.log, napojeno: video.napojeno,"
                   " stejny: video.srcObject !== null})), 20);")


def test_zamrzly_obraz_se_nejdriv_ozivi_bez_pusteni_kamery():
    s = _hlidac(False, "stav.cas = 100000; window.kameraZamrzla();")
    assert s["zavreno"] == [] and s["otevirano"] == 0
    assert s["napojeno"] == 1 and s["stejny"]
    assert "oziveni" in s["log"]


def test_kdyz_obraz_zamrzne_znovu_kamera_se_restartuje_hned_bez_cekani_na_timer():
    s = _hlidac(False, "stav.cas = 100000; window.kameraZamrzla(); stav.cas += 6000; window.kameraZamrzla();")
    assert len(s["zavreno"]) == 1 and s["otevirano"] == 1
    assert "restart" in s["log"]


def test_ztichla_stopa_znamena_restart_rovnou():
    s = _hlidac(True, "stav.cas = 100000; window.kameraZamrzla();")
    assert len(s["zavreno"]) == 1 and s["otevirano"] == 1 and s["napojeno"] == 0


# ── Z code review 2026-10-26 ─────────────────────────────────────────────────

def test_nahled_se_ukaze_hned_i_kdyz_prvni_snimek_nedorazi():
    """play() u proudu bez snímků visí — náhled musí být vidět i tak, jinak
    hlídač zamrzlý obraz nikdy nepozná (schovaný náhled snímky nehlásí)."""
    s = _spust("""
      prvky['camera-video'] = Object.assign(el(), { play: () => new Promise(() => {}) });
      tryAutoOpenCamera();
    """, konec_ms=300)
    assert s["zive"] == 1 and s["dlazdice"]["nahled"] == ""


def test_navrat_do_okna_nezkousi_kameru_bez_povoleni():
    """Opakovaná výzva k povolení při každém alt-tabu — Chrome by web zablokoval."""
    s = _spust("""
      stav.vzdyChyba = 'NotAllowedError'; tryAutoOpenCamera(); await pockej(300);
      stav.dokument.visibilitychange(); stav.okno.focus();
    """, konec_ms=300)
    assert len(s["volani"]) == 1


def test_navrat_do_okna_bez_kamery_nebusi_serii_pokusu():
    """PC bez kamery: návrat do okna nespouští novou sérii pokusů a záznamů."""
    s = _spust("""
      stav.vzdyChyba = 'NotFoundError'; tryAutoOpenCamera(); await pockej(500);
      globalThis.vystup = stav.volani.length;
      stav.dokument.visibilitychange();
    """, pokusy="[40, 80]", konec_ms=600)
    assert len(s["volani"]) == s["vystup"], "návrat do okna znovu zkoušel nepřipojenou kameru"


def test_odchod_ze_stranky_behem_otevirani_si_klid_zapamatuje():
    """F5 hned po načtení, zatímco se kamera teprve otevírá: nová stránka
    musí taky počkat — jinak je to přesně puštění a hned otevření."""
    kod = _kod_kamery(klid=400)
    s = _node(FAKE + "\nconst stranka = () => { " + kod + "\n return { tryAutoOpenCamera }; };\n"
              + """
(async () => {
  const stara = stranka();
  stara.tryAutoOpenCamera(); await pockej(20);
  stav.pagehide(); const pusteno = Date.now();
  const nova = stranka();
  nova.tryAutoOpenCamera();
  await pockej(900);
  console.log(JSON.stringify({ cekala: stav.volani[1] - pusteno, zive: zive() }));
})();
""")
    assert s["cekala"] >= 390
    assert s["zive"] == 1
