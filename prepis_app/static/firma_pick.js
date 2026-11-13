/* Výběr firmy s barevnou tečkou — port z evidence (ukony_tracker/static/js/firma_pick.js).
 *
 * Nativní <select> zůstává v DOMu a drží hodnotu (evidence_firma_id se tak
 * posílá beze změny); nad ním vznikne tlačítko s tečkou a seznam s tečkami,
 * název firmy je normální barvou textu. Barva tečky = data-color volby, tedy
 * `barva` z evidence.
 *
 * Klávesnice (žádosti jedou bez myši):
 *   Tab           zaostří tlačítko (skrytý select je z tabulátoru vyřazený)
 *   psaní         zavřený výběr přeskočí na firmu začínající napsaným textem
 *   ↓ ↑ Enter     otevře seznam; šipky listují, Enter vybere, Esc zavře
 *   Home / End    první / poslední firma
 *
 * FirmaPick.attach(select) · sync(select) · refresh(select)
 */
(function (root) {
  'use strict';

  var FALLBACK_COLOR = 'var(--muted)';
  var instances = typeof WeakMap === 'function' ? new WeakMap() : null;
  var openInstances = [];
  var documentHooked = false;
  var uid = 0;
  var TYPE_RESET_MS = 700;

  function doc() { return typeof document !== 'undefined' ? document : null; }
  function hasClass(node, name) {
    return !!node && (' ' + (node.className || '') + ' ').indexOf(' ' + name + ' ') >= 0;
  }
  function optionsOf(select) {
    return select && select.options ? Array.prototype.slice.call(select.options) : [];
  }
  function colorOf(option) {
    var c = option && option.dataset ? option.dataset.color : '';
    return c || FALLBACK_COLOR;
  }
  function labelOf(option) { return option && option.textContent != null ? option.textContent : ''; }
  function valueOf(option) { return option && option.value != null ? String(option.value) : ''; }

  function currentOption(select) {
    var options = optionsOf(select);
    if (!options.length) return null;
    var index = typeof select.selectedIndex === 'number' ? select.selectedIndex : -1;
    if (index >= 0 && options[index]) return options[index];
    return options[0];
  }
  function instanceOf(select) {
    if (!select) return null;
    return instances ? (instances.get(select) || null) : (select.__firmaPick || null);
  }
  function remember(select, inst) {
    if (instances) instances.set(select, inst); else select.__firmaPick = inst;
  }
  function setDot(dot, color) { if (dot && dot.style) dot.style.background = color; }

  function fireChange(select) {
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function renderItems(inst) {
    inst.list.replaceChildren();
    inst.items = [];
    optionsOf(inst.select).forEach(function (option) {
      var item = doc().createElement('button');
      item.type = 'button';
      item.className = 'firma-pick__item';
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', 'false');
      item.dataset.firma = valueOf(option);
      if (option.disabled) item.disabled = true;
      var dot = doc().createElement('span');
      dot.className = 'firma-dot';
      setDot(dot, colorOf(option));
      var label = doc().createElement('span');
      label.textContent = labelOf(option);
      item.append(dot, label);
      item.addEventListener('click', function (e) {
        e.preventDefault();
        if (!option.disabled) choose(inst, option);
      });
      inst.list.append(item);
      inst.items.push({ option: option, item: item });
    });
  }

  function sync(select) {
    var inst = instanceOf(select);
    if (!inst) return null;
    var current = currentOption(select);
    inst.name.textContent = labelOf(current);
    setDot(inst.dot, colorOf(current));
    inst.button.disabled = !!select.disabled;
    inst.items.forEach(function (entry, index) {
      var on = entry.option === current;
      if (on) inst.activeIndex = index;
      entry.item.classList.toggle('on', on);
      entry.item.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    return inst;
  }

  function focusItem(inst, index) {
    var entry = inst.items[index];
    if (!entry) return;
    inst.activeIndex = index;
    entry.item.focus();
    if (entry.item.scrollIntoView) entry.item.scrollIntoView({ block: 'nearest' });
  }
  function focusCurrent(inst) {
    var cur = currentOption(inst.select);
    var index = 0;
    inst.items.forEach(function (e, i) { if (e.option === cur) index = i; });
    focusItem(inst, index);
  }
  function move(inst, delta) {
    if (!inst.items.length) return;
    var next = Math.max(0, Math.min(inst.items.length - 1, (inst.activeIndex || 0) + delta));
    focusItem(inst, next);
  }

  // Seznam se otevře POD tlačítkem; když dole není místo, nad ním (CSS třída).
  function place(inst) {
    var r = inst.button.getBoundingClientRect();
    var h = Math.min(290, inst.list.scrollHeight || 290);
    var below = (window.innerHeight || 0) - r.bottom;
    inst.wrap.classList.toggle('up', below < h + 12 && r.top > below);
  }
  function open(inst) {
    if (inst.open || inst.button.disabled) return;
    inst.open = true;
    inst.list.hidden = false;
    place(inst);
    inst.button.setAttribute('aria-expanded', 'true');
    if (openInstances.indexOf(inst) < 0) openInstances.push(inst);
    focusCurrent(inst);
  }
  function close(inst) {
    if (!inst.open) return;
    inst.open = false;
    inst.list.hidden = true;
    inst.button.setAttribute('aria-expanded', 'false');
    var at = openInstances.indexOf(inst);
    if (at >= 0) openInstances.splice(at, 1);
  }
  function choose(inst, option) {
    inst.select.value = valueOf(option);
    close(inst);
    sync(inst.select);
    inst.button.focus();
    fireChange(inst.select);
  }

  // Psaní písmen: první firma, jejíž název začíná napsaným textem.
  function typeAhead(inst, key) {
    var now = Date.now();
    inst.typed = (now - (inst.typedAt || 0) > TYPE_RESET_MS ? '' : inst.typed || '') + key.toLowerCase();
    inst.typedAt = now;
    var hit = -1;
    inst.items.forEach(function (e, i) {
      if (hit < 0 && valueOf(e.option) !== '' && labelOf(e.option).toLowerCase().indexOf(inst.typed) === 0) hit = i;
    });
    if (hit < 0) return;
    if (inst.open) { focusItem(inst, hit); return; }
    if (inst.select.value === valueOf(inst.items[hit].option)) return;   // beze změny žádný change
    inst.select.value = valueOf(inst.items[hit].option);
    sync(inst.select);
    fireChange(inst.select);
  }
  function isPrintable(e) {
    return e.key && e.key.length === 1 && e.key !== ' ' && !e.ctrlKey && !e.altKey && !e.metaKey;
  }

  function onButtonKey(inst, e) {
    var key = e.key;
    if (key === 'Escape' || key === 'Esc') {
      if (inst.open) { e.preventDefault(); e.stopPropagation(); close(inst); }
      return;
    }
    if (key === 'Enter' || key === ' ') {
      e.preventDefault();
      e.stopPropagation();   // Enter průvodce („další krok") sem nepatří
      if (inst.open) close(inst); else open(inst);
      return;
    }
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      e.preventDefault();
      if (!inst.open) open(inst); else move(inst, key === 'ArrowUp' ? -1 : 1);
      return;
    }
    if (key === 'Home' || key === 'End') {
      e.preventDefault();
      if (!inst.open) open(inst);
      focusItem(inst, key === 'End' ? inst.items.length - 1 : 0);
      return;
    }
    if (isPrintable(e)) { e.preventDefault(); typeAhead(inst, key); }
  }
  function onListKey(inst, e) {
    var key = e.key;
    if (key === 'Escape' || key === 'Esc') {
      e.preventDefault(); e.stopPropagation(); close(inst); inst.button.focus(); return;
    }
    if (key === 'ArrowDown' || key === 'ArrowUp') { e.preventDefault(); move(inst, key === 'ArrowUp' ? -1 : 1); return; }
    if (key === 'Home' || key === 'End') {
      e.preventDefault(); focusItem(inst, key === 'End' ? inst.items.length - 1 : 0); return;
    }
    if (key === 'Tab') { close(inst); return; }
    if (isPrintable(e)) { e.preventDefault(); typeAhead(inst, key); return; }
    // Enter / mezerník: položka je skutečné <button>, prohlížeč spustí click.
    if (key === 'Enter') e.stopPropagation();   // globální Enter průvodce nesmí jít dál
  }

  function hookDocument() {
    if (documentHooked || !doc()) return;
    documentHooked = true;
    doc().addEventListener('click', function (e) {
      openInstances.slice().forEach(function (inst) {
        if (!inst.wrap.contains(e.target)) close(inst);
      });
    });
  }

  function attach(select) {
    if (!select || !doc()) return null;
    var existing = instanceOf(select);
    if (existing) return existing;

    var wrap = select.parentNode;
    if (!hasClass(wrap, 'firma-pick')) {
      wrap = doc().createElement('div');
      wrap.className = 'firma-pick';
      select.parentNode.insertBefore(wrap, select);
      wrap.append(select);
    }
    var listId = 'firma-pick-list-' + (++uid);

    var button = doc().createElement('button');
    button.type = 'button';
    button.className = 'firma-pick__btn';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', listId);
    var dot = doc().createElement('span');
    dot.className = 'firma-dot';
    var name = doc().createElement('span');
    name.className = 'firma-pick__name';
    var chev = doc().createElement('span');
    chev.className = 'firma-pick__chev';
    chev.setAttribute('aria-hidden', 'true');
    button.append(dot, name, chev);

    var list = doc().createElement('div');
    list.className = 'firma-pick__list';
    list.id = listId;
    list.setAttribute('role', 'listbox');
    list.hidden = true;

    wrap.append(button, list);
    wrap.classList.add('js');
    select.tabIndex = -1;            // jediný tabulátorový bod je tlačítko
    select.setAttribute('aria-hidden', 'true');

    var inst = { select: select, wrap: wrap, button: button, list: list, dot: dot, name: name,
                 items: [], activeIndex: 0, open: false };
    remember(select, inst);
    renderItems(inst);

    button.addEventListener('click', function (e) {
      e.preventDefault();
      if (inst.open) close(inst); else open(inst);
    });
    button.addEventListener('keydown', function (e) { onButtonKey(inst, e); });
    list.addEventListener('keydown', function (e) { onListKey(inst, e); });
    select.addEventListener('change', function () { sync(select); });

    hookDocument();
    sync(select);
    return inst;
  }

  function refresh(select) {
    var inst = instanceOf(select);
    if (!inst) return null;
    renderItems(inst);
    sync(select);
    return inst;
  }

  var api = { attach: attach, sync: sync, refresh: refresh };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FirmaPick = api;
})(typeof window !== 'undefined' ? window : globalThis);
