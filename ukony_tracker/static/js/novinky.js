/* "Co umí Evidence" (templates/_novinky.html).
   Phase 1 card -> (3.5 s | any tap/key) -> slides away, sheet underneath.
   data-start: "auto" card then sheet | "hold" card stays (screenshots)
               | "sheet" sheet only, no motion (screenshots).
   data-key present = production: opens once per device (localStorage).
   Absent = preview: always opens. "Verze X ⓘ" = [data-releases-open] opens
   the sheet directly. */
(function () {
  var root = document.getElementById('nv');
  if (!root) return;
  var card = root.querySelector('.nv-card');
  var panel = root.querySelector('.nv-panel');
  var KEY = root.getAttribute('data-key');
  var START = root.getAttribute('data-start') || 'auto';
  var DELAY = 3500;
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var timer = null, opened = false, lockedUntil = 0;

  function seen() { try { return localStorage.getItem(KEY) === '1'; } catch (e) { return true; } }
  function markSeen() { try { localStorage.setItem(KEY, '1'); } catch (e) {} }

  function lockPage(on) { document.documentElement.style.overflow = on ? 'hidden' : ''; }

  // Swallow the click that follows the tap which dismissed the card, so it
  // can't land on "Rozumím" while the sheet is still sliding in.
  root.addEventListener('click', function (e) {
    if (Date.now() < lockedUntil) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  function toSheet() {
    if (!root.classList.contains('is-open') || root.classList.contains('is-sheet')) return;
    clearTimeout(timer);
    lockedUntil = Date.now() + 500;
    root.classList.add('is-sheet');
    setTimeout(function () { if (opened) panel.focus({ preventScroll: true }); }, 60);
  }

  function onKey(e) {
    if (e.key === 'Shift' || e.key === 'Control' || e.key === 'Alt' || e.key === 'Meta') return;
    // The page behind has its own shortcuts (Enter steps the form): keep them out.
    e.stopPropagation();
    if (!root.classList.contains('is-sheet')) { e.preventDefault(); toSheet(); return; }
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'Enter' && !(document.activeElement && document.activeElement.tagName === 'BUTTON')) e.preventDefault();
  }
  function onPointer() { toSheet(); }

  function open(mode) {
    if (opened) return;
    opened = true;
    root.hidden = false;
    lockPage(true);
    var direct = mode === 'sheet' || (mode === 'auto' && reduce);
    if (direct) root.classList.add('nv-direct');
    if (mode === 'still') root.classList.add('nv-still', 'nv-direct');
    if (mode === 'hold') root.classList.add('nv-hold');
    void root.offsetWidth;
    root.classList.add('is-open');
    document.addEventListener('keydown', onKey, true);
    if (direct || mode === 'still') {
      root.classList.add('is-sheet');
      panel.focus({ preventScroll: true });
    } else {
      card.focus({ preventScroll: true });
      document.addEventListener('pointerdown', onPointer, true);
      if (mode !== 'hold') timer = setTimeout(toSheet, DELAY);
    }
  }

  function close() {
    if (!opened) return;
    opened = false;
    clearTimeout(timer);
    root.classList.remove('is-open');
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('pointerdown', onPointer, true);
    setTimeout(function () {
      if (opened) return;
      root.hidden = true;
      root.classList.remove('is-sheet', 'nv-direct', 'nv-still', 'nv-hold');
      lockPage(false);
    }, 450);
  }

  root.querySelector('.nv-ok').addEventListener('click', close);
  // Tap on the dimmed side area of the desktop sheet closes it.
  root.querySelector('.nv-sheet').addEventListener('click', function (e) {
    if (e.target === e.currentTarget) close();
  });

  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-releases-open]')) {
      e.preventDefault();
      if (opened) return;
      open('sheet');
    }
  });

  // Start.
  function autoOpen() {
    if (KEY) {
      if (seen()) return;
      if (document.querySelector('.modal-backdrop:not([hidden]), dialog[open]')) { setTimeout(autoOpen, 2000); return; }
      markSeen();
    }
    open(START === 'sheet-still' ? 'still' : START);
  }
  setTimeout(autoOpen, KEY ? 900 : 150);

  window.novinky = { open: open, close: close };
})();
