/* Shared colored firm picker (2.7.2) — one source of truth for a firm
   <select> with the firm's colored dot. Used by the Úkony new form
   (#firma-select), the Doklady "Nový doklad" modal (#dn-firma) and the
   Techničák scan cards (select.orv-card-firma).

   FirmaPick.attach(selectEl, opts)  wraps the native <select>: creates a
                                     .firma-pick wrapper (unless the markup
                                     already has one), hides the select with
                                     the .firma-pick.js pattern, appends the
                                     .firma-pick__btn and .firma-pick__list
                                     (same classes/CSS as the Úkony picker).
   FirmaPick.sync(selectEl)          re-reads the current value → button dot +
                                     label + highlighted item (after
                                     form.reset() or a programmatic change).
   FirmaPick.refresh(selectEl)       re-reads the <option>s (dynamic fill).

   The native select stays in the DOM and keeps working without JS. Picking an
   item sets select.value and fires a bubbling `change`, so existing listeners
   (loadUkony, photo.firmaOverride) keep working unchanged. No dependencies,
   never relies on the element living inside #ukon-form. */
(function (root) {
  'use strict';

  var FALLBACK_COLOR = 'var(--muted)';
  var instances = typeof WeakMap === 'function' ? new WeakMap() : null;
  var openInstances = [];
  var documentHooked = false;
  var uid = 0;

  function doc() {
    return typeof document !== 'undefined' ? document : null;
  }

  function hasClass(node, name) {
    return !!node && (' ' + (node.className || '') + ' ').indexOf(' ' + name + ' ') >= 0;
  }

  function optionsOf(select) {
    if (!select || !select.options) return [];
    return Array.prototype.slice.call(select.options);
  }

  function colorOf(option) {
    var color = option && option.dataset ? option.dataset.color : '';
    return color || FALLBACK_COLOR;
  }

  function labelOf(option) {
    return option && option.textContent != null ? option.textContent : '';
  }

  function valueOf(option) {
    return option && option.value != null ? String(option.value) : '';
  }

  // The option the select is currently on. Falls back to a value match and
  // finally to the first option so a placeholder still has a sensible label.
  function currentOption(select) {
    var options = optionsOf(select);
    if (!options.length) return null;
    var index = typeof select.selectedIndex === 'number' ? select.selectedIndex : -1;
    if (index >= 0 && options[index]) return options[index];
    var value = select.value == null ? '' : String(select.value);
    for (var i = 0; i < options.length; i++) {
      if (valueOf(options[i]) === value) return options[i];
    }
    return options[0];
  }

  function instanceOf(select) {
    if (!select) return null;
    if (instances) return instances.get(select) || null;
    return select.__firmaPick || null;
  }

  function remember(select, instance) {
    if (instances) instances.set(select, instance);
    else select.__firmaPick = instance;  // very old browsers without WeakMap
  }

  function setDot(dot, color) {
    if (dot && dot.style) dot.style.background = color;
  }

  function fireChange(select) {
    var event = null;
    try {
      if (typeof Event === 'function') event = new Event('change', { bubbles: true });
    } catch (_) { event = null; }
    if (!event) {
      var owner = (select && select.ownerDocument) || doc();
      if (owner && owner.createEvent) {
        event = owner.createEvent('Event');
        event.initEvent('change', true, false);
      }
    }
    if (event && select && select.dispatchEvent) select.dispatchEvent(event);
  }

  // Reuse a .firma-pick wrapper already present in the markup (the Úkony form
  // ships one for the no-JS fallback); otherwise create it around the select.
  function ensureWrapper(select) {
    var parent = select.parentNode;
    if (parent && hasClass(parent, 'firma-pick')) return parent;
    var wrap = doc().createElement('div');
    wrap.className = 'firma-pick';
    if (parent) parent.insertBefore(wrap, select);
    wrap.append(select);
    return wrap;
  }

  // A previous inline implementation may have rendered its own button/list into
  // the same wrapper; drop just those nodes (never the select) and rebind.
  function clearRendered(wrap) {
    if (!wrap || !wrap.children) return;
    Array.prototype.slice.call(wrap.children).forEach(function (child) {
      if (hasClass(child, 'firma-pick__btn') || hasClass(child, 'firma-pick__list')) {
        wrap.removeChild(child);
      }
    });
  }

  function renderItems(instance) {
    var select = instance.select;
    var list = instance.list;
    clearRenderedList(instance);
    instance.items = [];
    optionsOf(select).forEach(function (option) {
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
        if (e && e.preventDefault) e.preventDefault();
        if (option.disabled) return;  // a disabled option is shown but not pickable
        choose(instance, option);
      });
      list.append(item);
      instance.items.push({ option: option, item: item });
    });
  }

  function clearRenderedList(instance) {
    var list = instance.list;
    if (!list) return;
    if (list.replaceChildren) list.replaceChildren();
    else if (list.children) {
      Array.prototype.slice.call(list.children).forEach(function (child) { list.removeChild(child); });
    }
  }

  function optionIndex(instance, option) {
    for (var i = 0; i < instance.items.length; i++) {
      if (instance.items[i].option === option) return i;
    }
    return -1;
  }

  function sync(select) {
    var instance = instanceOf(select);
    if (!instance) return null;
    var current = currentOption(select);
    if (instance.name) instance.name.textContent = labelOf(current);
    setDot(instance.dot, colorOf(current));
    if (instance.button) instance.button.disabled = !!select.disabled;
    var active = -1;
    instance.items.forEach(function (entry, index) {
      var on = entry.option === current;
      if (on) active = index;
      if (entry.item.classList) entry.item.classList.toggle('on', on);
      entry.item.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    if (active >= 0) instance.activeIndex = active;
    return instance;
  }

  function focusItem(instance, index) {
    var entry = instance.items[index];
    if (!entry) return;
    instance.activeIndex = index;
    if (entry.item.focus) entry.item.focus();
  }

  function focusCurrent(instance) {
    var index = optionIndex(instance, currentOption(instance.select));
    if (index < 0) index = 0;
    focusItem(instance, index);
  }

  function focusEdge(instance, last) {
    var index = last ? instance.items.length - 1 : 0;
    focusItem(instance, Math.max(0, index));
  }

  function move(instance, delta) {
    if (!instance.items.length) return;
    var from = typeof instance.activeIndex === 'number' ? instance.activeIndex : 0;
    var next = from + delta;
    if (next < 0) next = 0;
    if (next > instance.items.length - 1) next = instance.items.length - 1;
    focusItem(instance, next);
  }

  function open(instance) {
    if (instance.open) return;
    instance.open = true;
    instance.list.hidden = false;
    instance.button.setAttribute('aria-expanded', 'true');
    if (openInstances.indexOf(instance) < 0) openInstances.push(instance);
    focusCurrent(instance);
  }

  function close(instance) {
    if (!instance.open) return;
    instance.open = false;
    instance.list.hidden = true;
    instance.button.setAttribute('aria-expanded', 'false');
    var at = openInstances.indexOf(instance);
    if (at >= 0) openInstances.splice(at, 1);
  }

  function choose(instance, option) {
    var select = instance.select;
    select.value = valueOf(option);  // also moves selectedIndex in the real DOM
    close(instance);
    sync(select);
    if (instance.button.focus) instance.button.focus();
    fireChange(select);
  }

  function focusButton(instance) {
    if (instance.button.focus) instance.button.focus();
  }

  function isSpace(key) {
    return key === ' ' || key === 'Spacebar';
  }

  function onButtonKey(instance, event) {
    if (!event) return;
    var key = event.key;
    if (key === 'Escape' || key === 'Esc') {
      if (instance.open) {
        if (event.preventDefault) event.preventDefault();
        if (event.stopPropagation) event.stopPropagation();
        close(instance);
      }
      return;
    }
    if (key === 'Enter' || isSpace(key)) {
      if (event.preventDefault) event.preventDefault();
      if (instance.open) close(instance); else open(instance);
      return;
    }
    if (key === 'ArrowDown' || key === 'Down' || key === 'ArrowUp' || key === 'Up') {
      if (event.preventDefault) event.preventDefault();
      if (!instance.open) {
        open(instance);
      } else {
        move(instance, (key === 'ArrowUp' || key === 'Up') ? -1 : 1);
      }
      return;
    }
    if (key === 'Home' || key === 'End') {
      if (event.preventDefault) event.preventDefault();
      if (!instance.open) open(instance);
      focusEdge(instance, key === 'End');
    }
  }

  function onListKey(instance, event) {
    if (!event) return;
    var key = event.key;
    if (key === 'Escape' || key === 'Esc') {
      if (event.preventDefault) event.preventDefault();
      if (event.stopPropagation) event.stopPropagation();
      close(instance);
      focusButton(instance);
      return;
    }
    if (key === 'ArrowDown' || key === 'Down') {
      if (event.preventDefault) event.preventDefault();
      move(instance, 1);
      return;
    }
    if (key === 'ArrowUp' || key === 'Up') {
      if (event.preventDefault) event.preventDefault();
      move(instance, -1);
      return;
    }
    if (key === 'Home' || key === 'End') {
      if (event.preventDefault) event.preventDefault();
      focusEdge(instance, key === 'End');
      return;
    }
    if (key === 'Tab') {
      close(instance);  // let focus leave naturally
      return;
    }
    // Enter/Space fall through: the focused item is a real <button>, so the
    // browser fires its click handler and the option gets selected.
  }

  // One document listener closes every open picker on a click outside it.
  function hookDocument() {
    if (documentHooked) return;
    var owner = doc();
    if (!owner || !owner.addEventListener) return;
    documentHooked = true;
    owner.addEventListener('click', function (event) {
      var target = event && event.target;
      openInstances.slice().forEach(function (instance) {
        if (!instance.wrap.contains || !instance.wrap.contains(target)) close(instance);
      });
    });
  }

  function attach(select, opts) {
    if (!select || !doc()) return null;
    var existing = instanceOf(select);
    if (existing) return existing;

    var wrap = ensureWrapper(select);
    clearRendered(wrap);
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
    if (wrap.classList) wrap.classList.add('js');

    var instance = {
      select: select,
      wrap: wrap,
      button: button,
      list: list,
      dot: dot,
      name: name,
      items: [],
      activeIndex: 0,
      open: false,
      opts: opts || {}
    };
    remember(select, instance);
    renderItems(instance);

    button.addEventListener('click', function (event) {
      if (event && event.preventDefault) event.preventDefault();
      if (instance.open) close(instance); else open(instance);
    });
    button.addEventListener('keydown', function (event) { onButtonKey(instance, event); });
    list.addEventListener('keydown', function (event) { onListKey(instance, event); });
    // An external programmatic value + change still updates the picker.
    select.addEventListener('change', function () { sync(select); });

    hookDocument();
    sync(select);
    return instance;
  }

  function refresh(select) {
    var instance = instanceOf(select);
    if (!instance) return null;
    renderItems(instance);
    sync(select);
    if (instance.open) focusCurrent(instance);
    return instance;
  }

  var api = { attach: attach, sync: sync, refresh: refresh };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FirmaPick = api;
})(typeof window !== 'undefined' ? window : globalThis);
