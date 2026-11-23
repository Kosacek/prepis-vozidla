// Žádosti: ORV se naskenuje samo, když ho položíš pod kameru (1.37.0).
//
// Rozhodování, QR a obrys jsou sdílené s evidencí. Tady je jen to, co je
// jiné u kamery nad stolem:
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
  const PARAMETRY_STOLU = {steadyMotion: 6, enterMotion: 14};
  const VODITKO = {x: 0.08, y: 0.06, w: 0.84, h: 0.88};

  // ── Stráž: kdy smí další auto-sken (bez DOM, testy v tests/test_orv_auto_zadosti.cjs)
  function straz(edgeMin, rearmMs) {
    let cekame = false, posledniQr = null, prazdnoOd = null;
    return {
      // Právě se odeslal sken (sám nebo Enterem) karty s tímhle QR (nebo bez).
      poSkenu(qr) { cekame = true; posledniQr = qr || null; prazdnoOd = null; },
      // Po obnovení stránky: QR karta, která se skenovala naposled.
      obnov(qr) { if (qr) { cekame = true; posledniQr = qr; } },
      // Chybějící obrys sám nestačí: ruka může zakrýt roh karty.
      // Prázdný stůl potvrzujeme i po tom, co se sdílený detektor už odjistil.
      tick(info) {
        if (!cekame || !info || !info.stable || info.quad || info.edges >= edgeMin) {
          prazdnoOd = null;
          return false;
        }
        if (prazdnoOd == null) prazdnoOd = info.t;
        if (info.t - prazdnoOd < rearmMs) return false;
        cekame = false;
        posledniQr = prazdnoOd = null;
        return true;
      },
      // Posunutá karta, ruka v záběru nebo stejný QR se znovu nefotí.
      smiFotit(reason, qr) {
        if (!cekame) return true;
        return reason === 'qr' && !!qr && qr !== posledniQr;
      },
      stav: () => ({cekame, posledniQr}),
    };
  }

  const api = {straz, PARAMETRY_STOLU};
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
    const {edgeMin, rearmMs} = root.OrvAutoCore.DEFAULTS;
    const hlidac = straz(edgeMin, rearmMs);

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
    const nahled = root.OrvNahled ? root.OrvNahled.create(video, {log}) : null;

    // Obrys pro náhled se počítá z většího snímku než rozhodnutí o skenu.
    const QUAD_W = 256;
    const detektor = root.OrvQuad ? root.OrvQuad.create() : null;
    const qPlatno = document.createElement('canvas');
    const qCtx = qPlatno.getContext('2d', {willReadFrequently: true});
    function obrys(info) {
      if (!detektor || !nahled || !video.videoWidth) return;
      const h = Math.max(1, Math.round(QUAD_W * video.videoHeight / video.videoWidth));
      if (qPlatno.width !== QUAD_W || qPlatno.height !== h) { qPlatno.width = QUAD_W; qPlatno.height = h; }
      qCtx.drawImage(video, 0, 0, QUAD_W, h);
      const g = root.OrvAutoCore.gray(qCtx.getImageData(0, 0, QUAD_W, h).data, QUAD_W, h);
      nahled.quad(detektor.find(g, QUAD_W, h, VODITKO), info.locked ? 'zamek' : 'sleduje');
    }

    function ukaz(info) {
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
      try { obrys(info); } catch (_) { if (nahled) nahled.quad(null); }   // obrys nesmí shodit sken
      if (hlidac.tick(info)) {
        auto.forget(fotka);
        log('auto_prazdno', root.OrvAuto.zachyt('prazdno', info));
      } else if (info.rearmed) logTlumene('auto_rearm', root.OrvAuto.zachyt(info.rearmed, info));
      if (info.t - posledniVzorek >= VZOREK_MS) {
        posledniVzorek = info.t;
        log('auto_vzorek', root.OrvAuto.zachyt(info.armed ? 'ceka' : 'hotovo', info) + ' ' + auto.qrKind());
      }
    }
    // Evidence drží QR celé série, v žádostech hlídáme jen poslední fotku.
    function uzamkni(qr, rucne = false) {
      const predchozi = fotka++;
      if (rucne) auto.manual(fotka, qr);
      else auto.commit(fotka, qr);
      auto.forget(predchozi);
    }

    function onFire(info) {
      if (!sleduje() || typeof quickScanOrv !== 'function') { auto.release(); return; }
      const qr = info.reason === 'qr' ? info.qr : null;
      const popis = info.zachyt + (qr ? ' qr=' + qr : '');
      if (!hlidac.smiFotit(info.reason, qr)) {
        uzamkni(qr);   // karta zůstává „vyfocená", nic se neposílá
        logTlumene('auto_potlaceno', popis);
        return;
      }
      blesk();
      if (nahled) nahled.foto();
      log('auto_foto', popis);
      // PoOdeslani rezervaci potvrdí. Pokud sken skončil už před uploadem,
      // uvolníme ji, aby šlo kartu zkusit znovu.
      Promise.resolve(quickScanOrv({auto: true, zachyt: info.zachyt})).then(auto.release, auto.release);
    }

    const auto = root.OrvAuto.create({
      video,
      crop: () => ({x: 0, y: 0, w: video.videoWidth, h: video.videoHeight}),
      guide: VODITKO,
      params: PARAMETRY_STOLU,
      canFire() {
        const ano = sleduje();
        if (!ano) hlidac.tick(null);
        return ano;
      },
      onTick,
      onFire,
      jsqrUrl: '/static/vendor/jsQR.js?v=1.4.0',
      debug: ladeni,
    });

    function ukazPrepinac() {
      const b = document.getElementById('orv-auto');
      if (b && b.getAttribute('aria-pressed') !== String(zapnuto)) {
        b.setAttribute('aria-pressed', String(zapnuto));
        b.title = zapnuto ? 'Automatický sken je zapnutý (A)' : 'Automatický sken je vypnutý (A)';
      }
      if (!zapnuto && nahled) nahled.quad(null);
    }
    // Proužek průběhu pro každý sken (quickScanOrv v index.html), i ruční.
    root.orvNahled = {
      prubeh: meta => (nahled && root.SkenPrubeh ? nahled.prubeh(meta) : null),
      foto: () => { if (nahled) nahled.foto(); },
    };
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
        uzamkni(qr, !jeAuto);
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
