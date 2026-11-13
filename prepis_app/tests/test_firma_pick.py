"""Výběr firmy s tečkou (static/firma_pick.js, port z evidence): skutečný JS
v node s malým falešným DOMem. Hlídá: hodnota selectu zůstává zdrojem pravdy
(evidence_firma_id se posílá stejně), tečka bere barvu z data-color, klávesnice
Tab/šipky/Enter/psaní, a Enter výběru nesmí probublat k Enteru průvodce."""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = ROOT / "static" / "firma_pick.js"
INDEX = ROOT / "templates" / "index.html"

FAKE = r"""
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null;
    this.className = ''; this.dataset = {}; this.attrs = {}; this.h = {}; this.style = {};
    this.hidden = false; this.disabled = false; this._t = ''; this.value = ''; }
  get classList() { const s = this; return {
    add: n => { if (!s.className.split(' ').includes(n)) s.className = (s.className + ' ' + n).trim(); },
    toggle: (n, f) => { const l = s.className.split(' ').filter(Boolean); const has = l.includes(n);
      const on = f === undefined ? !has : !!f; s.className = (on ? (has ? l : [...l, n]) : l.filter(x => x !== n)).join(' '); } }; }
  get textContent() { return this.children.length ? this.children.map(c => c.textContent).join('') : this._t; }
  set textContent(v) { this.children = []; this._t = String(v); }
  append(...ns) { ns.forEach(n => { if (n.parentNode) n.parentNode.children = n.parentNode.children.filter(c => c !== n);
    n.parentNode = this; this.children.push(n); }); }
  insertBefore(n, r) { const i = this.children.indexOf(r); n.parentNode = this; this.children.splice(i < 0 ? this.children.length : i, 0, n); }
  replaceChildren(...ns) { this.children = []; this.append(...ns); }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(t, f) { (this.h[t] ||= []).push(f); }
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  getBoundingClientRect() { return { top: 10, bottom: 50, left: 0, right: 100 }; }
  focus() { globalThis.document.active = this; }
  dispatchEvent(e) { e.target = this; for (let x = this; x; x = x.parentNode) { (x.h[e.type] || []).forEach(f => f(e));
    if (e.stopped) break; } return true; }
  scrollIntoView() {}
}
class Sel extends El {
  constructor() { super('select'); this.options = []; this.selectedIndex = 0; }
  get value() { return this.options[this.selectedIndex] ? this.options[this.selectedIndex].value : ''; }
  set value(v) { if (this.options) this.selectedIndex = Math.max(0, this.options.findIndex(o => o.value === v)); }
}
globalThis.Event = class { constructor(t, o) { this.type = t; this.bubbles = !!(o && o.bubbles); } stopPropagation() { this.stopped = true; } preventDefault() { this.prevented = true; } };
globalThis.window = globalThis; window.innerHeight = 800;
const body = new El('body');
globalThis.document = { createElement: t => new El(t), addEventListener() {}, active: null };
function opt(value, text, color) { const o = new El('option'); o.value = value; o.textContent = text; if (color) o.dataset.color = color; return o; }
const wrap = new El('div'); wrap.className = 'firma-pick'; body.append(wrap);
const sel = new Sel(); wrap.append(sel);
sel.options = [opt('', '— vyber firmu —'), opt('1', 'ALSETA', '#0a84ff'), opt('2', 'BAZAR', ''), opt('3', 'ALFA', '#ff3b30')];
const changes = []; sel.addEventListener('change', () => changes.push(sel.value));
function key(el, k) { const e = new Event('keydown', { bubbles: true }); e.key = k; el.dispatchEvent(e); return e; }
"""


def _run(akce: str):
    node = shutil.which("node")
    if not node:  # pragma: no cover
        pytest.skip("node není nainstalovaný")
    script = FAKE + JS.read_text(encoding="utf-8") + "\nconst FirmaPick = module.exports;\n" + akce
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_dot_color_name_and_value_untouched():
    r = _run("""
const i = FirmaPick.attach(sel);
sel.selectedIndex = 1; FirmaPick.sync(sel);
const a = [i.name.textContent, i.dot.style.background, sel.value, sel.tabIndex];
sel.selectedIndex = 2; FirmaPick.sync(sel);
console.log(JSON.stringify({ a, bez: i.dot.style.background, polozek: i.items.length,
  barvy: i.items.map(x => x.item.children[0].style.background) }));""")
    assert r["a"] == ["ALSETA", "#0a84ff", "1", -1]
    assert r["bez"] == "var(--muted)"          # firma bez barvy = šedá tečka
    assert r["polozek"] == 4 and r["barvy"][1] == "#0a84ff"


def test_click_item_sets_select_value_and_fires_change():
    r = _run("""
const i = FirmaPick.attach(sel);
i.button.dispatchEvent(Object.assign(new Event('click', { bubbles: true }), { preventDefault() {} }));
const open = !i.list.hidden;
const it = i.items[3].item; it.dispatchEvent(Object.assign(new Event('click', { bubbles: true }), { preventDefault() {} }));
console.log(JSON.stringify({ open, value: sel.value, changes, closed: i.list.hidden, name: i.name.textContent }));""")
    assert r == {"open": True, "value": "3", "changes": ["3"], "closed": True, "name": "ALFA"}


def test_keyboard_enter_opens_arrows_move_enter_choice_does_not_bubble():
    r = _run("""
const i = FirmaPick.attach(sel);
const e1 = key(i.button, 'Enter');               // otevře
const open = !i.list.hidden;
key(i.list, 'ArrowDown');                        // z prázdné volby na ALSETA
const idx = i.activeIndex;
const e2 = key(i.list, 'Enter');                 // Enter na položce: jen nesmí probublat; click dělá prohlížeč
i.items[idx].item.dispatchEvent(Object.assign(new Event('click', { bubbles: true }), { preventDefault() {} }));
key(i.button, 'Enter'); key(i.list, 'Escape');
console.log(JSON.stringify({ open, idx, stop1: !!e1.stopped, stop2: !!e2.stopped, value: sel.value,
  escClosed: i.list.hidden }));""")
    assert r == {"open": True, "idx": 1, "stop1": True, "stop2": True, "value": "1", "escClosed": True}


def test_typing_selects_matching_firm_when_closed():
    r = _run("""
const i = FirmaPick.attach(sel);
key(i.button, 'b'); const a = sel.value;
key(i.button, 'a'); key(i.button, 'l'); key(i.button, 'f');   // „balf" nic nenajde, zůstane
const b = sel.value;
console.log(JSON.stringify({ a, b, changes }));""")
    assert r["a"] == "2" and r["b"] == "2" and r["changes"] == ["2"]


def test_list_opens_above_when_no_room_below():
    r = _run("""
window.innerHeight = 60;
const i = FirmaPick.attach(sel);
wrap.getBoundingClientRect = () => ({ top: 400, bottom: 440, left: 0, right: 100 });
i.button.getBoundingClientRect = wrap.getBoundingClientRect;
window.innerHeight = 450;
key(i.button, 'ArrowDown');
console.log(JSON.stringify({ up: wrap.className.includes('up') }));""")
    assert r["up"] is True


def test_form_wiring():
    h = INDEX.read_text(encoding="utf-8")
    assert '<select id="evidence_firma"' in h          # stejná hodnota → stejný push
    assert 'class="firma-pick"' in h and "/static/firma_pick.js" in h
    assert "o.dataset.color = barva" in h
    assert "o.style.color" not in h                      # žádné barevné názvy
    assert "classList.contains('firma-pick__btn')" in h        # Enter průvodce výběr nechá
