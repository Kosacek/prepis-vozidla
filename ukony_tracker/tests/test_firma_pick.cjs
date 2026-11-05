/* Tests for the shared colored firm picker (2.7.2, static/js/firma_pick.js):
   the attach flow, data-color → dot mapping with the muted fallback, selecting
   an item (value + bubbling change), sync after a programmatic value/form
   reset, refresh after dynamic options, a disabled placeholder, keyboard and
   click-outside. A minimal fake DOM keeps this dependency-free (no jsdom). */
const { test } = require('node:test');
const assert = require('node:assert/strict');

// -- Minimal fake DOM (createElement, append/insertBefore, classList, events) --
function hasClass(node, name) {
  return (' ' + (node.className || '') + ' ').indexOf(' ' + name + ' ') >= 0;
}

class Node {
  constructor(tag) {
    this.tagName = String(tag || '').toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.className = '';
    this.dataset = {};
    this.attributes = {};
    this.handlers = {};
    this.style = {};
    this.hidden = false;
    this.disabled = false;
    this.focused = false;
    this.type = '';
    this.id = '';
    this._text = '';
    this.classList = {
      add: (...names) => names.forEach(name => {
        if (!hasClass(this, name)) this.className = this.className ? this.className + ' ' + name : name;
      }),
      contains: name => hasClass(this, name),
      toggle: (name, force) => {
        const on = force === undefined ? !hasClass(this, name) : !!force;
        if (on) {
          if (!hasClass(this, name)) this.className = this.className ? this.className + ' ' + name : name;
        } else {
          this.className = String(this.className || '').split(/\s+/)
            .filter(c => c && c !== name).join(' ');
        }
        return on;
      },
    };
  }
  get textContent() {
    return this.children.length ? this.children.map(child => child.textContent).join('') : this._text;
  }
  set textContent(value) {
    this.children = [];
    this._text = value == null ? '' : String(value);
  }
  append(...nodes) {
    nodes.forEach(node => {
      if (node == null) return;
      const list = Array.isArray(node) ? node : [node];
      list.forEach(child => {
        if (child == null) return;
        if (child.parentNode) child.parentNode.removeChild(child);
        child.parentNode = this;
        this.children.push(child);
      });
    });
  }
  appendChild(node) { this.append(node); return node; }
  insertBefore(node, reference) {
    const at = this.children.indexOf(reference);
    if (node.parentNode) node.parentNode.removeChild(node);
    node.parentNode = this;
    if (at < 0) this.children.push(node);
    else this.children.splice(at, 0, node);
    return node;
  }
  removeChild(node) {
    this.children = this.children.filter(child => child !== node);
    if (node.parentNode === this) node.parentNode = null;
    return node;
  }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  addEventListener(name, handler) { (this.handlers[name] ||= []).push(handler); }
  dispatchEvent(event) {
    (this.handlers[event.type] || []).slice().forEach(handler => handler(event));
    return true;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null; }
  contains(node) {
    if (!node) return false;
    for (let at = node; at; at = at.parentNode) if (at === this) return true;
    return false;
  }
  focus() { this.focused = true; }
}

const fakeDocument = {
  handlers: {},
  createElement: tag => new Node(tag),
  addEventListener(name, handler) { (this.handlers[name] ||= []).push(handler); },
};
globalThis.document = fakeDocument;

const FirmaPick = require('../static/js/firma_pick.js');

// -- Helpers ----------------------------------------------------------------
function descendants(node) {
  const out = [];
  node.children.forEach(child => { out.push(child, ...descendants(child)); });
  return out;
}
function classes(node) { return String(node.className || '').split(/\s+/).filter(Boolean); }
function allByClass(root, name) { return descendants(root).filter(node => hasClass(node, name)); }
function oneByClass(root, name) {
  const found = allByClass(root, name)[0];
  assert.ok(found, 'expected a .' + name + ' node');
  return found;
}
function option(value, text, color, extra = {}) {
  const node = new Node('option');
  node.value = String(value);
  node.textContent = text;
  if (color) node.dataset.color = color;
  return Object.assign(node, extra);
}
function makeSelect(options = []) {
  const select = new Node('select');
  select.options = [];
  select._value = '';
  Object.defineProperty(select, 'value', {
    get() { return this._value; },
    set(value) { this._value = value == null ? '' : String(value); },
  });
  Object.defineProperty(select, 'selectedIndex', {
    get() {
      if (!this.options.length) return -1;
      return this.options.findIndex(item => String(item.value) === this._value);
    },
    set(index) { this._value = this.options[index] ? String(this.options[index].value) : ''; },
  });
  options.forEach(item => select.options.push(item));
  return select;
}
// A select inside a plain .field — deliberately NOT inside #ukon-form.
function mount(options) {
  const field = new Node('div');
  field.className = 'field';
  const select = makeSelect(options);
  field.append(select);
  return { field, select };
}
const FIRMS = [option('', '— bez firmy —'), option('1', 'ALB', '#0a84ff'), option('2', 'BS')];
function press(node, key) {
  const event = { key, defaultPrevented: false, propagationStopped: false };
  event.preventDefault = () => { event.defaultPrevented = true; };
  event.stopPropagation = () => { event.propagationStopped = true; };
  (node.handlers.keydown || []).slice().forEach(handler => handler(event));
  return event;
}
function click(node) { (node.handlers.click || []).slice().forEach(handler => handler({ preventDefault() {} })); }
function items(instance) { return allByClass(instance && instance.list ? instance.list : instance, 'firma-pick__item'); }
function selectedFlags(list) {
  return items(list).map(item => item.getAttribute('aria-selected'));
}
function onFlags(list) { return items(list).map(item => classes(item).includes('on')); }
function documentClicks() { return fakeDocument.handlers.click || []; }

// -- attach / mapping -------------------------------------------------------
test('attach wraps the select and maps options + data-color dots (muted fallback)', () => {
  const { field, select } = mount(FIRMS);
  const instance = FirmaPick.attach(select);

  assert.ok(instance);
  assert.equal(instance.select, select);
  assert.equal(instance.wrap.parentNode, field);
  assert.equal(select.parentNode, instance.wrap);
  assert.ok(classes(instance.wrap).includes('firma-pick'));
  assert.ok(classes(instance.wrap).includes('js'));

  // button: dot + name + chevron, ARIA listbox wiring
  assert.equal(instance.button.type, 'button');
  assert.ok(classes(instance.button).includes('firma-pick__btn'));
  assert.equal(instance.button.getAttribute('aria-haspopup'), 'listbox');
  assert.equal(instance.button.getAttribute('aria-expanded'), 'false');
  assert.equal(instance.button.getAttribute('aria-controls'), instance.list.id);
  assert.equal(oneByClass(instance.button, 'firma-dot').tagName, 'SPAN');
  assert.equal(oneByClass(instance.button, 'firma-pick__name').tagName, 'SPAN');
  assert.equal(oneByClass(instance.button, 'firma-pick__chev').getAttribute('aria-hidden'), 'true');

  // listbox: one .firma-pick__item per option, role=option, data-firma=value
  assert.equal(instance.list.getAttribute('role'), 'listbox');
  assert.equal(instance.list.hidden, true);
  assert.deepEqual(items(instance).map(item => item.getAttribute('role')),
    ['option', 'option', 'option']);
  assert.deepEqual(items(instance).map(item => item.dataset.firma), ['', '1', '2']);
  assert.deepEqual(items(instance).map(item => oneByClass(item, 'firma-dot').style.background),
    ['var(--muted)', '#0a84ff', 'var(--muted)']);

  // the placeholder is shown in the button until something is picked
  assert.equal(instance.name.textContent, '— bez firmy —');
  assert.equal(instance.dot.style.background, 'var(--muted)');
  assert.deepEqual(selectedFlags(instance.list), ['true', 'false', 'false']);
  assert.deepEqual(onFlags(instance.list), [true, false, false]);
});

test('attach is idempotent and reuses a .firma-pick wrapper already in the markup', () => {
  const { field, select } = mount(FIRMS);
  const existing = new Node('div');
  existing.className = 'firma-pick';
  field.removeChild(select);
  existing.append(select);
  field.append(existing);
  // stale nodes from the old inline implementation must be replaced, not doubled
  const staleBtn = new Node('button');
  staleBtn.className = 'firma-pick__btn';
  const staleList = new Node('div');
  staleList.className = 'firma-pick__list';
  existing.append(staleBtn, staleList);

  const first = FirmaPick.attach(select);
  const second = FirmaPick.attach(select);
  assert.equal(first, second);
  assert.equal(first.wrap, existing);            // wrapper reused, not nested twice
  assert.equal(existing.parentNode, field);
  assert.equal(allByClass(existing, 'firma-pick__btn').length, 1);
  assert.equal(allByClass(existing, 'firma-pick__list').length, 1);
  assert.equal(select.parentNode, existing);
});

test('attach does not require the select to live in #ukon-form', () => {
  const select = makeSelect(FIRMS);
  const wrapperParent = new Node('div');
  wrapperParent.id = 'some-scan-card';
  wrapperParent.append(select);
  const instance = FirmaPick.attach(select);
  assert.equal(instance.wrap.parentNode, wrapperParent);
  assert.equal(items(instance).length, 3);
});

// -- selection --------------------------------------------------------------
test('picking an item sets select.value, closes the list and fires a bubbling change', () => {
  const { select } = mount(FIRMS);
  const instance = FirmaPick.attach(select);
  const seen = [];
  select.addEventListener('change', event => {
    seen.push({ value: select.value, bubbles: !!event.bubbles });
  });

  click(instance.button);
  assert.equal(instance.list.hidden, false);
  assert.equal(instance.button.getAttribute('aria-expanded'), 'true');

  click(items(instance)[1]);  // ALB (#0a84ff)
  assert.equal(select.value, '1');
  assert.equal(select.selectedIndex, 1);
  assert.deepEqual(seen, [{ value: '1', bubbles: true }]);
  assert.equal(instance.list.hidden, true);
  assert.equal(instance.button.getAttribute('aria-expanded'), 'false');
  assert.equal(instance.name.textContent, 'ALB');
  assert.equal(instance.dot.style.background, '#0a84ff');
  assert.deepEqual(selectedFlags(instance.list), ['false', 'true', 'false']);
  assert.deepEqual(onFlags(instance.list), [false, true, false]);
});

test('a disabled placeholder option is displayed but cannot be picked', () => {
  const disabledPlaceholder = option('', '— vyber firmu —', null, { disabled: true });
  const { select } = mount([disabledPlaceholder, option('1', 'ALB', '#0a84ff')]);
  const instance = FirmaPick.attach(select);
  assert.equal(instance.name.textContent, '— vyber firmu —');
  assert.equal(items(instance)[0].disabled, true);

  const seen = [];
  select.addEventListener('change', () => seen.push(select.value));
  click(items(instance)[0]);
  assert.equal(select.value, '');
  assert.equal(seen.length, 0);
});

// -- sync -------------------------------------------------------------------
test('sync reflects a programmatic value change and a form.reset()', () => {
  const { select } = mount(FIRMS);
  const instance = FirmaPick.attach(select);

  select.value = '2';  // e.g. filter preset / code — no change event
  FirmaPick.sync(select);
  assert.equal(instance.name.textContent, 'BS');
  assert.equal(instance.dot.style.background, 'var(--muted)');
  assert.deepEqual(onFlags(instance.list), [false, false, true]);

  select.value = '';  // what form.reset() does to the native select
  FirmaPick.sync(select);
  assert.equal(instance.name.textContent, '— bez firmy —');
  assert.equal(instance.dot.style.background, 'var(--muted)');
  assert.deepEqual(onFlags(instance.list), [true, false, false]);

  assert.equal(FirmaPick.sync(makeSelect([])), null);  // unattached select: no-op
});

test('an external change on the select keeps the button in sync', () => {
  const { select } = mount(FIRMS);
  const instance = FirmaPick.attach(select);
  select.value = '1';
  select.dispatchEvent(new Event('change', { bubbles: true }));
  assert.equal(instance.name.textContent, 'ALB');
  assert.equal(instance.dot.style.background, '#0a84ff');
});

// -- refresh ----------------------------------------------------------------
test('refresh re-reads dynamically added options and keeps the wrapper', () => {
  const { select } = mount([option('', '— bez firmy —')]);
  const instance = FirmaPick.attach(select);
  assert.equal(items(instance).length, 1);

  select.options.length = 0;
  select.options.push(option('7', 'NOV', '#ff375f'), option('8', 'OLD'));
  select.value = '7';
  const same = FirmaPick.refresh(select);

  assert.equal(same, instance);
  assert.deepEqual(items(instance).map(item => item.textContent), ['NOV', 'OLD']);
  assert.deepEqual(items(instance).map(item => item.dataset.firma), ['7', '8']);
  assert.equal(instance.name.textContent, 'NOV');
  assert.equal(instance.dot.style.background, '#ff375f');
  assert.deepEqual(selectedFlags(instance.list), ['true', 'false']);
  assert.equal(allByClass(instance.wrap, 'firma-pick__btn').length, 1);
  assert.equal(allByClass(instance.wrap, 'firma-pick__list').length, 1);
});

// -- keyboard + click outside ----------------------------------------------
test('keyboard: Enter opens, arrows move the highlight, Esc closes', () => {
  const { select } = mount(FIRMS);
  const instance = FirmaPick.attach(select);

  const enter = press(instance.button, 'Enter');
  assert.equal(enter.defaultPrevented, true);
  assert.equal(instance.list.hidden, false);
  assert.equal(instance.button.getAttribute('aria-expanded'), 'true');
  assert.equal(items(instance)[0].focused, true);  // current option focused

  press(instance.list, 'ArrowDown');
  assert.equal(items(instance)[1].focused, true);
  press(instance.list, 'End');
  assert.equal(items(instance)[2].focused, true);
  press(instance.list, 'Home');
  assert.equal(items(instance)[0].focused, true);

  const escape = press(instance.list, 'Escape');
  assert.equal(escape.propagationStopped, true);  // don't close the whole modal
  assert.equal(instance.list.hidden, true);
  assert.equal(instance.button.getAttribute('aria-expanded'), 'false');
});

test('a click outside closes the open picker, a click inside keeps it open', () => {
  const { select } = mount(FIRMS);
  const instance = FirmaPick.attach(select);
  assert.ok(documentClicks().length >= 1);  // one shared document listener

  click(instance.button);
  assert.equal(instance.list.hidden, false);

  const inside = items(instance)[1];
  documentClicks().forEach(handler => handler({ target: inside }));
  assert.equal(instance.list.hidden, false, 'inside click must not close it');
  assert.equal(select.value, '');

  const outside = new Node('div');
  documentClicks().forEach(handler => handler({ target: outside }));
  assert.equal(instance.list.hidden, true, 'outside click must close it');
});
