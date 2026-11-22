// Žádosti: ORV se naskenuje samo, když ho položíš pod kameru (1.37.0).
//
// Rozhodování a QR jsou moduly evidence 2.10.0 beze změny (orv_auto_core.js,
// orv_qr.js, orv_auto.js). Tady je jen to, co je jiné u kamery nad stolem:
// - Jediné živé <video> (novaZadost ho jen přesouvá). Kvůli auto-skenu se
//   kamera nikdy nezavírá ani neotevírá: USB kamera se po rychlém puštění a
//   novém otevření zasekne (KAMERA_KLID_MS). Smyčka se proto spustí jednou a
//   nikdy se nezastaví ani nevynuluje; „Auto" jen zavře bránu sleduje().
// - Hlídá jen tehdy, kdy by Enter skenoval (krok 1, kamera běží, typ není
//   plná moc), nikdy během skenu, nad otevřeným dialogem ani ve skryté kartě.
// - Po každém skenu (sám i Enterem) se další karta vezme sama až když je stůl
//   prázdný nebo je pod kamerou jiný QR. Ten stav přežije novaZadost (není ve
//   vynulujStav) i obnovení stránky (poslední QR), jinak by se karta, která na
//   stole zůstala, naskenovala do další žádosti.
// - Sken je placené čtení: co se jednou odeslalo, se samo znovu neodešle
//   (commit), uvolní se jen to, co se neodeslalo (release).
(function (root) {
  'use strict';
  const KLIC_AUTO = 'zadosti_orv_auto';
  const KLIC_QR = 'zadosti_orv_posledni_qr';
  const KLIC_LADENI = 'zadosti_orv_ladeni';
  const QR_PAMET_MS = 30 * 60 * 1000;   // po obnovení stránky si pamatuje poslední QR kartu
  const VZOREK_MS = 5 * 60 * 1000;      // vzorek čísel do kamera logu (ladění prahů)
  const QR_FOTKA_MS = 1500;             // jak dlouho sken čeká na QR z fotky

  // ── Stráž: kdy smí další auto-sken (bez DOM, testy v tests/test_orv_auto_zadosti.cjs)
  function straz(edgeMin) {
    let cekame = false, posledniQr = null;
    return {
      // Právě se odeslal sken (sám nebo Enterem) karty s tímhle QR (nebo bez).
      poSkenu(qr) { cekame = true; posledniQr = qr || null; },
      // Po obnovení stránky: QR karta, která se skenovala naposled.
      obnov(qr) { if (qr) { cekame = true; posledniQr = qr; } },
      // Stůl je zase prázdný: prázdné hledí, znovu klidné pozadí, nebo nová
      // klidná scéna bez potisku. Vrací true, když se tím stráž uvolnila.
      tick(info) {
        if (!cekame || !info || !info.rearmed) return false;
        if (info.rearmed === 'prazdno' || (info.rearmed === 'nova-scena' && info.edges < edgeMin)) {
          cekame = false;
          posledniQr = null;
          return true;
        }
        return false;
      },
      // Posunutá karta, ruka v záběru nebo stejný QR se znovu nefotí.
      smiFotit(reason, qr) {
        if (!cekame) return true;
        return reason === 'qr' && !!qr && qr !== posledniQr;
      },
      stav: () => ({cekame, posledniQr}),
    };
  }

  const api = {straz};
  if (typeof module === 'object' && module.exports) { module.exports = api; return; }
  root.OrvAutoZadosti = api;

  function cti(klic) { try { return localStorage.getItem(klic); } catch (_) { return null; } }
  function zapis(klic, hodnota) {
    try { if (hodnota == null) localStorage.removeItem(klic); else localStorage.setItem(klic, hodnota); } catch (_) {}
  }
  function log(udalost, detail) { if (root.kameraLog) root.kameraLog(udalost, detail); }
  // Časté události nanejvýš jednou za 30 s (s počtem), ať kamera log
  // (drží jen ~0,5 MB) nevytlačí historii zamrzání kamery.
  const TLUMENI_MS = 30 * 1000;
  const tlumene = {};
  function logTlumene(udalost, detail) {
    const ted = Date.now(), z = tlumene[udalost] || (tlumene[udalost] = {posledni: -Infinity, pocet: 0});
    if (ted - z.posledni < TLUMENI_MS) { z.pocet++; return; }
    log(udalost, detail + (z.pocet ? ' +' + z.pocet + ' dalších' : ''));
    z.posledni = ted;
    z.pocet = 0;
  }
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function spust() {
    const video = document.getElementById('camera-video');
    if (!video || !root.OrvAuto || !root.OrvAutoCore) return;
    let ladeni = cti(KLIC_LADENI) === '1';
    try { ladeni = ladeni || new URLSearchParams(location.search).get('ladeni') === '1'; } catch (_) {}
    let zapnuto = cti(KLIC_AUTO) !== '0';
    let fotka = 0, posledniVzorek = -Infinity;
    const hlidac = straz(root.OrvAutoCore.DEFAULTS.edgeMin);

    function dialogOtevreny() {
      if (document.querySelector('dialog[open], .nv.is-open')) return true;
      return Array.from(document.querySelectorAll('.modal-overlay'))
        .some(m => getComputedStyle(m).display !== 'none');
    }
    // Stejná podmínka jako „Enter skenuje" (klavesnice.js) + nic nesmí rušit.
    function sleduje() {
      try {
        if (!zapnuto || document.hidden || _scanInFlight || !cameraStream) return false;
        if (!(root.enterSkenuje && root.enterSkenuje())) return false;
        if (video.srcObject !== cameraStream || video.offsetParent === null) return false;
        return !dialogOtevreny();
      } catch (_) {
        return false;
      }
    }

    function hledi() { return document.getElementById('orv-hledi'); }
    function ukaz(info) {
      const h = hledi();
      if (!h) return;
      const zamek = info.locked ? 'lock' : '';
      if (h.dataset.auto !== zamek) h.dataset.auto = zamek;
      h.style.setProperty('--orv-hold', String(info.progress || 0));
      const ladici = document.getElementById('orv-ladeni');
      if (ladici) {
        ladici.hidden = !ladeni;
        if (ladeni) {
          ladici.textContent = root.OrvAuto.zachyt(info.armed ? 'ceka' : 'hotovo', info) +
            (info.qr ? ' qr=' + info.qr : '') + ' ' + auto.qrKind() + (hlidac.stav().cekame ? ' straz' : '');
        }
      }
    }
    function blesk() {
      const h = hledi();
      if (!h) return;
      h.classList.remove('is-shot');
      void h.offsetWidth;   // znovu spustit animaci
      h.classList.add('is-shot');
      setTimeout(() => h.classList.remove('is-shot'), 400);
    }
    function onTick(info) {
      ukaz(info);
      if (hlidac.tick(info)) log('auto_prazdno', root.OrvAuto.zachyt(info.rearmed, info));
      else if (info.rearmed) logTlumene('auto_rearm', root.OrvAuto.zachyt(info.rearmed, info));
      if (info.t - posledniVzorek >= VZOREK_MS) {
        posledniVzorek = info.t;
        log('auto_vzorek', root.OrvAuto.zachyt(info.armed ? 'ceka' : 'hotovo', info) + ' ' + auto.qrKind());
      }
    }
    function onFire(info) {
      const qr = info.reason === 'qr' ? info.qr : null;
      const popis = info.zachyt + (qr ? ' qr=' + qr : '');
      if (!hlidac.smiFotit(info.reason, qr)) {
        auto.commit(++fotka);   // karta zůstává „vyfocená", nic se neposílá
        logTlumene('auto_potlaceno', popis);
        return;
      }
      if (!sleduje() || typeof quickScanOrv !== 'function') { auto.release(); return; }
      blesk();
      log('auto_foto', popis);
      Promise.resolve(quickScanOrv({auto: true, zachyt: info.zachyt})).then(
        odeslano => { if (odeslano) auto.commit(++fotka); else auto.release(); },
        () => auto.commit(++fotka));
    }

    const auto = root.OrvAuto.create({
      video,
      crop: () => ({x: 0, y: 0, w: video.videoWidth, h: video.videoHeight}),
      canFire: sleduje,
      onTick,
      onFire,
      jsqrUrl: '/static/vendor/jsQR.js?v=1.4.0',
      debug: ladeni,
    });

    function ukazPrepinac() {
      const b = document.getElementById('orv-auto');
      if (b && b.getAttribute('aria-pressed') !== String(zapnuto)) b.setAttribute('aria-pressed', String(zapnuto));
      const h = hledi();
      if (h && !zapnuto && h.dataset.auto) h.dataset.auto = '';
    }
    root.prepniOrvAuto = function () {
      zapnuto = !zapnuto;
      zapis(KLIC_AUTO, zapnuto ? '1' : '0');
      ukazPrepinac();
      log(zapnuto ? 'auto_zap' : 'auto_vyp', '');
    };

    // Volá _naskenujOrv (index.html) pro každou fotku, Enterem i samo.
    root.orvAuto = {
      async qrZFotky(canvas) {
        try {
          return await Promise.race([auto.verify(canvas, canvas.width, canvas.height), sleep(QR_FOTKA_MS).then(() => null)]);
        } catch (_) {
          return null;
        }
      },
      poOdeslani(qr, jeAuto) {
        hlidac.poSkenu(qr);
        zapis(KLIC_QR, qr ? JSON.stringify({qr, t: Date.now()}) : null);
        if (!jeAuto) auto.manual(++fotka, qr);   // ručně vyfocená karta se sama znovu nefotí
      },
      stav: () => Object.assign({zapnuto, qrKind: auto.qrKind()}, hlidac.stav()),
    };

    try {
      const ulozeny = JSON.parse(cti(KLIC_QR) || 'null');
      if (ulozeny && Date.now() - ulozeny.t < QR_PAMET_MS) hlidac.obnov(root.OrvAutoCore.cleanQr(ulozeny.qr));
    } catch (_) {}
    auto.start();   // jednou za život stránky — viz hlavička
    ukazPrepinac();
    setInterval(ukazPrepinac, 1000);   // novaZadost vymění tlačítko za čistou kopii
    setTimeout(() => log('auto_start', (zapnuto ? 'zap ' : 'vyp ') + auto.qrKind()), 3000);
  }

  try { spust(); } catch (e) { log('auto_chyba', e && e.message); }
})(typeof window !== 'undefined' ? window : globalThis);
