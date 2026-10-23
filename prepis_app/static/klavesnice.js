/* Žádosti bez myši (v1.26.0, David 2026-10-23).
 *
 * Celá žádost od skenu ORV po vytištěné papíry jen z klávesnice:
 *   krok 1      1–6 typ úkonu · Enter vyfotí ORV a sken posune dál
 *   kroky       Enter = vybraný návrh / další krok
 *   konec       Ctrl+Enter vygeneruje a otevře VŠECHNY dokumenty v záložkách,
 *               Ctrl+P / Ctrl+W jimi projdeš, zpátky v appce Enter = nová žádost
 *   kdykoliv    ? ukáže zkratky
 *
 * Tenhle soubor drží to, co v templates/index.html chybělo: nová žádost bez
 * obnovení stránky (kamera tak běží celou dobu), otevírání dokumentů,
 * štítek ↵ u toho, co Enter právě udělá, vypnuté návrhy Chromu, tahák a
 * hlídač kamery se záznamem na server. Sahá na globální proměnné hlavního
 * skriptu (appMode, flowIdx, cameraStream …) — klasické skripty sdílejí
 * jeden globální rozsah, proto se načítá AŽ za ním.
 */
(function () {
  'use strict';

  // ── Návrhy Chromu pryč ─────────────────────────────────────────────────────
  // Chrome přes náš seznam firem a jmen přikrýval svoje „naposledy napsané".
  // Necháváme jen návrhy appky.
  const TEXTOVA = 'input:not([type=checkbox]):not([type=radio]):not([type=hidden])'
    + ':not([type=file]):not([type=button]):not([type=submit]), textarea';
  function bezNavrhuChrome(koren) {
    if (!koren || !koren.querySelectorAll) return;
    const pole = koren.matches && koren.matches(TEXTOVA) ? [koren] : [];
    pole.concat([...koren.querySelectorAll(TEXTOVA)]).forEach(el => {
      if (el.getAttribute('autocomplete') !== 'off') el.setAttribute('autocomplete', 'off');
    });
    koren.querySelectorAll('form').forEach(f => f.setAttribute('autocomplete', 'off'));
  }
  bezNavrhuChrome(document);
  new MutationObserver(zmeny => zmeny.forEach(z => z.addedNodes.forEach(n => {
    if (n.nodeType === 1) bezNavrhuChrome(n);
  }))).observe(document.body, { childList: true, subtree: true });

  // ── Záznam kamery na server ────────────────────────────────────────────────
  // Kamera po pár žádostech zamrzala a na dálku se to nedalo dohledat.
  // Každé zapnutí, vypnutí, chyba a restart jde do DATA_DIR/kamera_log.jsonl.
  function kameraLog(udalost, detail) {
    try {
      fetch('/api/kamera-log', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, keepalive: true,
        body: JSON.stringify({ udalost, detail: String(detail || '').slice(0, 300) }),
      }).catch(() => {});
    } catch (_) { /* záznam je bonus */ }
  }
  window.kameraLog = kameraLog;

  let posledniSnimek = performance.now();
  window.kameraZapnuta = function (proud) {
    posledniSnimek = performance.now();
    const t = proud.getVideoTracks && proud.getVideoTracks()[0];
    if (!t) return;
    let nastaveni = '';
    try { const n = t.getSettings(); nastaveni = ` ${n.width}×${n.height}@${Math.round(n.frameRate || 0)}`; } catch (_) {}
    kameraLog('zapnuta', (t.label || 'kamera') + nastaveni);
    t.addEventListener('ended', () => kameraLog('ended', t.label));
    t.addEventListener('mute', () => kameraLog('mute', t.label));
    t.addEventListener('unmute', () => kameraLog('unmute', t.label));
  };

  // ── Hlídač: zamrzlý obraz → kameru restartovat ─────────────────────────────
  const video0 = document.getElementById('camera-video');
  if (video0 && video0.requestVideoFrameCallback) {
    const snimek = () => { posledniSnimek = performance.now(); video0.requestVideoFrameCallback(snimek); };
    video0.requestVideoFrameCallback(snimek);
  }
  let bylNaKroku1 = false;
  let restarty = [];
  function restartKamery(duvod) {
    const ted = Date.now();
    restarty = restarty.filter(t => ted - t < 120000);
    if (restarty.length >= 3) return;          // nebušit do mrtvé kamery donekonečna
    restarty.push(ted);
    kameraLog('restart', duvod);
    closeCamera('hlídač: ' + duvod);
    setTimeout(() => tryAutoOpenCamera(), 800);
  }
  setInterval(() => {
    const naKroku1 = currentPanel() === 1 && !document.hidden;
    if (naKroku1 && !bylNaKroku1) posledniSnimek = performance.now();  // náhled se teprve ukazuje
    bylNaKroku1 = naKroku1;
    if (!naKroku1 || !cameraStream || _scanInFlight) return;
    const t = cameraStream.getVideoTracks()[0];
    if (!t || t.readyState === 'ended') return restartKamery('stopa skončila');
    if (video0 && video0.requestVideoFrameCallback && performance.now() - posledniSnimek > 4000) {
      restartKamery('obraz zamrzl');
    }
  }, 1500);

  // ── Nová žádost bez obnovení stránky ───────────────────────────────────────
  // Obnovení stránky kameru pokaždé vypnulo a zase zapnulo a po ~5 kolech se
  // USB kamera zasekla. Místo toho se celý průvodce vrátí do stavu po
  // načtení: čistá kopie se udělá teď, než kdokoliv cokoliv napíše
  // (cloneNode bere i hodnoty polí), a živé <video> se do ní jen přesune.
  const cistyPruvodce = document.querySelector('.container').cloneNode(true);

  function vynulujStav() {
    appMode = 'prevod';
    flowIdx = 0;
    generatedUrls = {};
    _otevritPoGenerovani = false;
    _zadostSeed = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
      : ('z' + Date.now() + Math.random().toString(16).slice(2));
    _krokPredIdx = 0;
    _krokAnimace = [];
    _vyvTyp = 'firma';
    _pmZdroj = null; _pmInfo = null; _pmRole = null; _pmRucne = false; _pmAresLast = '';
    _orvLast = '';
    Object.keys(_icoLast).forEach(k => delete _icoLast[k]);
    _sdiletKod = '';
    _evOrv = null;
    // Mohly přibýt firmy a žádosti — načíst znovu, jako po obnovení stránky.
    _firmsCache = null; _prefillCache = null; _prefillNacita = null; _evidenceMeta = null;
    clearTimeout(_ppdAresTimer); clearTimeout(_ppdPreviewTimer); _ppdPreviewSeq++;
  }

  window.novaZadost = function () {
    try {
      _krokStop();
      const stary = document.querySelector('.container');
      const novy = cistyPruvodce.cloneNode(true);
      const video = document.getElementById('camera-video');
      const misto = novy.querySelector('#camera-video');
      if (video && misto) misto.replaceWith(video);
      stary.replaceWith(novy);
      vynulujStav();
      document.getElementById('nav-back').style.display = 'none';
      document.getElementById('nav-back').textContent = 'Zpět';
      const dal = document.getElementById('nav-next');
      dal.style.display = ''; dal.disabled = false;
      _kameraOtoceniUI();
      _kameraUI(!!cameraStream);
      if (cameraStream && video) {
        if (video.srcObject !== cameraStream) video.srcObject = cameraStream;
        video.play().catch(() => {});
      }
      _aktivujPanel(1);        // stepper, popisky, fokus na typ úkonu, kamera
      window.scrollTo({ top: 0 });
      return true;
    } catch (e) {
      kameraLog('nova_zadost_chyba', e && e.message);
      return false;            // resetForm pak obnoví stránku postaru
    }
  };

  // ── Všechny dokumenty naráz ────────────────────────────────────────────────
  // Pořadí tisku: pokladní doklad (A5, sám se vytiskne a zavře), žádost,
  // plné moci. Chrome po Ctrl+W přejde na sousední záložku otevřenou stejnou
  // stránkou, směrem doleva — proto se otevírají od konce: poslední otevřená
  // je aktivní a každé Ctrl+W ukáže další v pořadí.
  function dokumentyKTisku(g) {
    const out = [];
    if (g.ppd) out.push(g.ppd_print || g.ppd);
    const hlavni = PRIMARNI_PODLE_MODU[g.mode];
    if (hlavni && g[hlavni]) out.push(g[hlavni]);
    else ['zmeny', 'zapis', 'zmena', '3rz', 'vyvoz'].forEach(k => { if (g[k]) out.push(g[k]); });
    (g.plne_moce || []).forEach(u => out.push(u));
    return out;
  }
  window.dokumentyKTisku = dokumentyKTisku;

  window.otevriVsechnyDokumenty = function () {
    const docs = dokumentyKTisku(generatedUrls);
    let otevreno = 0;
    docs.slice().reverse().forEach(u => { if (window.open(u, '_blank')) otevreno++; });
    const hlaska = document.getElementById('okna-blokovana');
    if (hlaska) {
      hlaska.hidden = otevreno >= docs.length;
      hlaska.textContent = `Chrome otevřel ${otevreno} z ${docs.length}. Povol vyskakovací okna (ikona vpravo v adresním řádku) a dej Ctrl+Enter.`;
    }
  };

  // ── Co teď udělá Enter: štítek ↵ ───────────────────────────────────────────
  function enterCil() {
    const out = document.getElementById('output-card');
    if (out && out.style.display !== 'none') return 'nova';
    if (currentPanel() === 1) return cameraStream && appMode !== 'pm' ? 'sken' : 'dal';
    if (currentPanel() === 6) return '';
    return 'dal';
  }
  function oznacEnter() {
    const cil = enterCil();
    if (document.body.dataset.enter !== cil) document.body.dataset.enter = cil;
  }
  ['keyup', 'click', 'focusin'].forEach(t => document.addEventListener(t, () => setTimeout(oznacEnter, 0)));
  setInterval(oznacEnter, 700);
  oznacEnter();

  // ── Tahák: ? ───────────────────────────────────────────────────────────────
  const TAHAK = [
    ['Typ úkonu', [['1', '–', '6'], 'vybrat typ'], [['Enter'], 'vyfotit ORV a dál'], [['Shift', '+', 'Enter'], 'dál bez skenu']],
    ['Vyplňování', [['Enter'], 'vzít návrh / další krok'], [['↓', '↑'], 'jiný návrh'], [['Esc'], 'zpět']],
    ['Tisk', [['Ctrl', '+', 'Enter'], 'vygenerovat a otevřít vše'], [['Ctrl', '+', 'P'], 'tisk'], [['Ctrl', '+', 'W'], 'další dokument']],
    ['Hotovo', [['Enter'], 'nová žádost']],
  ];
  function kbd(k) { return ['+', '–'].includes(k) ? `<span class="th-mezi">${k}</span>` : `<kbd>${k}</kbd>`; }
  function tahakHtml() {
    return TAHAK.map(([nadpis, ...radky]) => `<div class="th-blok"><div class="th-nadpis">${nadpis}</div>`
      + radky.map(([klavesy, co]) => `<div class="th-radek"><span class="th-klavesy">${klavesy.map(kbd).join('')}</span><span>${co}</span></div>`).join('')
      + '</div>').join('');
  }
  let tahak = null;
  function prepniTahak(ukaz) {
    if (!tahak) {
      tahak = document.createElement('div');
      tahak.id = 'tahak';
      tahak.className = 'tahak-scrim';
      tahak.innerHTML = `<div class="tahak" role="dialog" aria-modal="true" aria-label="Klávesové zkratky">${tahakHtml()}</div>`;
      tahak.addEventListener('click', e => { if (e.target === tahak) prepniTahak(false); });
      document.body.appendChild(tahak);
    }
    tahak.classList.toggle('open', ukaz);
  }
  window.prepniTahak = prepniTahak;
  document.addEventListener('keydown', e => {
    const otevreny = tahak && tahak.classList.contains('open');
    if (otevreny && (e.key === 'Escape' || e.key === '?')) {
      e.preventDefault(); e.stopImmediatePropagation(); prepniTahak(false); return;
    }
    if (e.key !== '?' || e.ctrlKey || e.altKey || e.metaKey) return;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.target.isContentEditable) return;
    e.preventDefault();
    prepniTahak(!otevreny);
  }, true);
})();
