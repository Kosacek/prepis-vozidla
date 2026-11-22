// Náhled kamery u skenu ORV (žádosti 1.37.1): obrys na skutečných rozích karty
// a jeden proužek průběhu od fotky po vyplněný formulář.
//
// - Obrys: rohy z orv_quad.js (8×/s), mezi vzorky se každý roh plynule
//   dotahuje (exponenciální vyhlazení ~70 ms), takže obrys karty živě sleduje
//   a necuká. Když kartu nevidí, obrys zmizí — nic se nepředstírá.
// - Proužek: model sken_prubeh.js, displej nikdy necouvá; 100 % až po zápisu
//   dat do formuláře (dokonceno = promise), chyba = klidně zčervená a zmizí.
// DOM se hledá podle id při každém snímku (novaZadost vyměňuje šablonu).
(function (root) {
  'use strict';
  const OBRYS_TAU = 70, VIDITELNOST_TAU = 90, KONEC_TAU = 60, ZMIZENI_MS = 350;
  const DRZET_PLNY_MS = 140, CHYBA_MS = 1600;

  function create(video, opts) {
    const o = opts || {};
    let cil = null, zobrazene = null, viditelnost = 0, stav = '', posledniQuad = -Infinity, drzet = false;
    let bar = null, raf = 0, minule = 0;
    const ted = () => (root.performance ? root.performance.now() : Date.now());
    const reduce = () => !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
    const krok = (dt, tau) => 1 - Math.exp(-dt / tau);

    function probud() { if (!raf && root.requestAnimationFrame) raf = root.requestAnimationFrame(snimek); }

    function kresliObrys(dt, t) {
      const svg = document.getElementById('orv-obrys');
      if (!svg) return false;
      const vw = video.videoWidth, vh = video.videoHeight;
      if (!vw || !vh) return false;
      const box = `0 0 ${vw} ${vh}`;
      if (svg.getAttribute('viewBox') !== box) svg.setAttribute('viewBox', box);
      if (svg.style.transform !== video.style.transform) svg.style.transform = video.style.transform;
      // Po fotce zůstane obrys sevřený na kartě, dokud sken nedoběhne.
      const vidi = !!cil && (drzet || t - posledniQuad < ZMIZENI_MS);
      if (vidi && (!zobrazene || viditelnost < 0.05 || reduce())) zobrazene = cil.map(c => c.slice());
      else if (vidi) {
        const k = krok(dt, OBRYS_TAU);
        zobrazene = zobrazene.map((c, i) => [c[0] + (cil[i][0] - c[0]) * k, c[1] + (cil[i][1] - c[1]) * k]);
      }
      viditelnost += ((vidi ? 1 : 0) - viditelnost) * (reduce() ? 1 : krok(dt, VIDITELNOST_TAU));
      const poly = svg.querySelector('polygon');
      if (poly && zobrazene) poly.setAttribute('points', zobrazene.map(c => `${(c[0] * vw).toFixed(1)},${(c[1] * vh).toFixed(1)}`).join(' '));
      svg.style.opacity = viditelnost.toFixed(3);
      const s = vidi ? stav : '';
      if (svg.dataset.stav !== s) svg.dataset.stav = s;
      if (!vidi && viditelnost < 0.01) { zobrazene = null; return false; }
      return true;
    }

    function kresliBar(dt, t) {
      const el = document.getElementById('sken-bar');
      if (!bar) return false;
      if (!el) return true;
      const b = bar;
      const model = b.model.hodnota(t);
      if (b.model.hotovy()) {
        b.zobrazeno += (1 - b.zobrazeno) * (reduce() ? 1 : krok(dt, KONEC_TAU));
        if (b.zobrazeno > 0.999) {
          b.zobrazeno = 1;
          if (b.plnyOd == null) b.plnyOd = t;
          if (t - b.plnyOd >= DRZET_PLNY_MS) b.konec();
        }
      } else {
        b.zobrazeno = Math.max(b.zobrazeno, model);
      }
      el.hidden = false;
      if (el.dataset.stav !== b.stav) el.dataset.stav = b.stav;
      const fill = el.firstElementChild;
      if (fill) fill.style.transform = `scaleX(${b.zobrazeno.toFixed(4)})`;
      const procent = String(Math.round(b.zobrazeno * 100));
      if (el.getAttribute('aria-valuenow') !== procent) el.setAttribute('aria-valuenow', procent);
      if (b.stav === 'chyba' && t - b.chybaOd >= CHYBA_MS) { b.konec(); }
      return !!bar;
    }

    function snimek(t) {
      raf = 0;
      const dt = Math.min(100, minule ? t - minule : 16);
      minule = t;
      const dal = kresliObrys(dt, t) | kresliBar(dt, t);
      if (dal) probud(); else minule = 0;
    }

    // Rohy karty (normalizované 0..1, pořadí LH, PH, PD, LD) nebo null.
    function quad(rohy, novyStav) {
      if (drzet) return;
      if (rohy) { cil = rohy; posledniQuad = ted(); stav = novyStav || 'sleduje'; }
      else cil = null;
      probud();
    }
    // Karta se právě vyfotila: obrys se krátce sevře.
    function foto() {
      stav = 'foto';
      drzet = !!cil && ted() - posledniQuad < ZMIZENI_MS;
      probud();
    }

    // Jeden sken: proužek od fotky po vyplněný formulář.
    function prubeh(meta) {
      if (bar) bar.konec(true);
      const historie = (() => {
        try { return JSON.parse(localStorage.getItem(root.SkenPrubeh.KLIC) || '{}') || {}; } catch (_) { return {}; }
      })();
      const model = root.SkenPrubeh.create(historie, ted);
      let hotovo;
      const dokonceno = new Promise(resolve => { hotovo = resolve; });
      const zacatek = ted();
      const b = {
        model, zobrazeno: 0, stav: 'bezi', plnyOd: null, chybaOd: 0,
        konec(tise) {
          if (bar !== b) return;
          bar = null;
          drzet = false;
          cil = null;
          const el = document.getElementById('sken-bar');
          if (el) { el.dataset.stav = 'pryc'; setTimeout(() => { if (!bar && el.dataset.stav === 'pryc') el.hidden = true; }, 260); }
          hotovo(!b.model.chybny());
          if (!tise) zapisCasy();
        },
      };
      function zapisCasy() {
        const casy = model.casy();
        const ok = !model.chybny();
        if (ok) { try { localStorage.setItem(root.SkenPrubeh.KLIC, JSON.stringify(model.novaHistorie())); } catch (_) {} }
        if (o.log) {
          o.log('sken_casy', [`zdroj=${(meta && meta.zdroj) || 'rucne'}`, `qr=${meta && meta.qr ? 1 : 0}`,
            ...root.SkenPrubeh.ETAPY.map(([k]) => `${k}=${casy[k] != null ? casy[k] : '-'}`),
            `celkem=${Math.round(ted() - zacatek)}`, `vysledek=${ok ? 'ok' : (b.duvod || 'chyba')}`].join(' '));
        }
      }
      bar = b;
      probud();
      return {
        hotovo: klic => { model.hotovo(klic); probud(); },
        uploadPodil: podil => model.uploadPodil(podil),
        qr: hodnota => { if (meta) meta.qr = !!hodnota; },
        selhalo: duvod => {
          if (bar !== b || model.chybny()) return;
          model.selhalo();
          b.duvod = String(duvod || 'chyba').replace(/[^a-z_]/g, '').slice(0, 20) || 'chyba';
          b.stav = 'chyba';
          b.chybaOd = ted();
          probud();
        },
        dokonceno,
      };
    }
    return {quad, foto, prubeh};
  }

  const api = {create};
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.OrvNahled = api;
})(typeof window !== 'undefined' ? window : globalThis);
