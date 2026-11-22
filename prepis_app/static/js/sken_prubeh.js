// Průběh skenu ORV: jeden plynulý proužek od zachycení karty po vyplněný
// formulář (žádosti 1.37.1). 100 % znamená, že data jsou přečtená a zapsaná.
//
// Etapy jsou skutečné milníky, které prohlížeč zná. Mezi milníky se proužek
// blíží stropu další etapy po asymptotě (rychle na začátku, pomalu ke konci),
// časová konstanta je klouzavý medián skutečných trvání (localStorage), takže
// se nikdy viditelně nezastaví a nikdy nedojde na 100 % dřív, než je hotovo.
// Nikdy necouvá. Bez DOM; testy v tests/test_sken_prubeh.cjs.
(function (root) {
  'use strict';
  // [etapa, strop, výchozí odhad trvání v ms] — první dvě krátké = rychlý start.
  const ETAPY = Object.freeze([
    ['foto', 0.10, 200],        // fotka + QR z fotky
    ['upload', 0.28, 600],      // odeslání fotky
    ['ocr', 0.80, 5000],        // čtení ORV (model)
    ['pole', 0.90, 150],        // vyplnění polí, firmy
    ['registr', 1.0, 900],      // registr vozidel (/api/orv)
  ]);
  const KLIC = 'zadosti_sken_casy';
  const HISTORIE = 15;
  const TAU_PODIL = 0.45;       // při mediánu trvání je proužek na ~90 % úseku

  function median(cisla) {
    const s = cisla.filter(n => typeof n === 'number' && isFinite(n) && n >= 0).sort((a, b) => a - b);
    if (!s.length) return null;
    const m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  // historie: {etapa: [ms, …]} (z localStorage), now(): ms
  function create(historie, now) {
    const hist = historie || {};
    let etapa = 0, zacatek = now(), od = 0, upload = 0, konec = null, chyba = false;
    const casy = {};
    const strop = i => ETAPY[i][1];
    const tau = i => Math.max(40, (median(hist[ETAPY[i][0]] || []) || ETAPY[i][2]) * TAU_PODIL);

    // Hodnota modelu v čase t (0..1); displej si ji drží neklesající.
    function hodnota(t) {
      if (konec != null) return konec;
      if (etapa >= ETAPY.length) return 1;
      const cil = strop(etapa);
      const ubehlo = Math.max(0, t - zacatek);
      let v = od + (cil - od) * (1 - Math.exp(-ubehlo / tau(etapa)));
      if (ETAPY[etapa][0] === 'upload') v = Math.max(v, od + (cil - od) * upload * 0.98);
      // Strop etapy se nikdy nedosáhne předem — vždy kousek pod ním.
      return Math.min(v, cil - 0.004);
    }
    // Etapa `klic` je hotová: další etapa pokračuje z aktuální hodnoty (bez skoku).
    function hotovo(klic, t) {
      const i = ETAPY.findIndex(e => e[0] === klic);
      if (i < etapa || konec != null) return;
      const ted = t == null ? now() : t;
      while (etapa <= i) {
        casy[ETAPY[etapa][0]] = Math.round(ted - zacatek);
        od = Math.max(od, hodnota(ted));
        etapa++;
        zacatek = ted;
      }
      upload = 0;
      if (etapa >= ETAPY.length) konec = 1;
    }
    function uploadPodil(podil) {
      if (ETAPY[etapa] && ETAPY[etapa][0] === 'upload') upload = Math.max(upload, Math.min(1, podil || 0));
    }
    function selhalo(t) {
      if (konec != null) return;
      konec = Math.max(od, hodnota(t == null ? now() : t));
      chyba = true;
    }
    // Nová historie po úspěšném skenu (posledních HISTORIE trvání každé etapy).
    function novaHistorie() {
      const out = {};
      for (const [klic] of ETAPY) {
        const stare = Array.isArray(hist[klic]) ? hist[klic] : [];
        out[klic] = (casy[klic] != null ? stare.concat([casy[klic]]) : stare).slice(-HISTORIE);
      }
      return out;
    }
    return {
      hodnota, hotovo, uploadPodil, selhalo, novaHistorie,
      casy: () => Object.assign({}, casy),
      hotovy: () => konec === 1 && !chyba,
      chybny: () => chyba,
    };
  }

  const api = {create, median, ETAPY, KLIC};
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.SkenPrubeh = api;
})(typeof window !== 'undefined' ? window : globalThis);
