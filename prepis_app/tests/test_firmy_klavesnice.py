"""Keyboard firm picking runs the JavaScript shipped in the template through node."""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

TEMPLATE = pathlib.Path(__file__).resolve().parent.parent / "templates" / "index.html"


def _function(name):
    html = TEMPLATE.read_text(encoding="utf-8")
    start = re.search(r"(?:async )?function " + re.escape(name) + r"\(", html).start()
    return html[start:html.index("\n}", start) + 2]


def _node(script):
    node = shutil.which("node")
    if not node:  # pragma: no cover - depends on the dev machine
        pytest.skip("node not installed")
    result = subprocess.run([node, "-e", script], capture_output=True, text=True,
                            encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _matches(names, query, icos=None):
    firms = [dict(nazev=name, ico=ico) for name, ico in
             zip(names, icos or [str(i) for i in range(len(names))])]
    return _node(_function("najdiFirmy") + "\nconst firms = " + json.dumps(firms)
                 + "; const before = JSON.stringify(firms);\n"
                 + "const matches = najdiFirmy(firms, " + json.dumps(query) + ");\n"
                 + "if (JSON.stringify(firms) !== before) throw Error('mutated firms');\n"
                 + "console.log(JSON.stringify(matches.map(f => f.nazev)));\n")


@pytest.mark.parametrize("query", ["cardion", "ČÁRDIÓN", "ca\u0301rdion"])
def test_case_and_diacritics_are_ignored(query):
    assert _matches(["CARDION", "ČÁRDIÓN", "OTHER"], query) == ["CARDION", "ČÁRDIÓN"]


@pytest.mark.parametrize("query", ["sro", "s.r.o."])
def test_punctuation_is_ignored(query):
    assert _matches(["ORBION S.R.O.", "CARDION SRO"], query) == ["ORBION S.R.O.", "CARDION SRO"]


def test_name_prefix_then_word_prefix_then_substring_keep_tie_order():
    names = ["MYCARSHOP", "ORBION CARS S.R.O.", "CARS FIRST", "OTHER CARS", "CARS SECOND"]
    assert _matches(names, "cars") == ["CARS FIRST", "CARS SECOND", "ORBION CARS S.R.O.",
                                       "OTHER CARS", "MYCARSHOP"]


def test_punctuation_can_also_separate_words():
    assert _matches(["MYCARSHOP", "ORBION-CARS"], "cars") == ["ORBION-CARS", "MYCARSHOP"]


def test_ico_matches_only_a_prefix_and_ranks_after_name_matches():
    names = ["ICO ONLY", "X12X", "FIRM 12", "12 FIRST", "NOT A PREFIX"]
    assert _matches(names, "12", ["12345678", "90", "91", "92", "00123456"]) == [
        "12 FIRST", "FIRM 12", "X12X", "ICO ONLY"]


@pytest.mark.parametrize("query", ["", "   ", " .,- "])
def test_empty_query_returns_no_firms(query):
    assert _matches(["CARDION"], query) == []


# Only the DOM surface touched by the shipped picker and focus helpers.
FAKE = r"""
const state = { next: 0, back: 0, generated: 0, focused: null, preview: 0, ares: null };
const elements = {};
const globalKeys = [];
const classes = initial => {
  const values = new Set(initial.split(/\s+/).filter(Boolean));
  return {
    contains: c => values.has(c), add: c => values.add(c), remove: c => values.delete(c),
    toggle(c, on) { if (on) values.add(c); else values.delete(c); }
  };
};
function field(id, optional = false) {
  return elements[id] = {
    id, value: '', tagName: 'INPUT', type: 'text', offsetParent: {}, tabIndex: 0,
    classList: classes(''), style: { display: 'none' },
    hasAttribute: name => name === 'data-volitelne' && optional,
    closest() { return this.panel || null; },
    focus() { state.focused = id; }, select() {}
  };
}
function dropdown(id) {
  return elements[id] = {
    classList: classes(''), rows: [], scrollTop: 90,
    set innerHTML(html) {
      this.rows = [...html.matchAll(/<div class="firm-option([^\"]*)"([^>]*)>/g)].map(m => {
        const row = { classList: classes('firm-option' + m[1]), dataset: {}, scrolls: 0,
          scrollIntoView(opts) { this.scrolls++; this.scrollBlock = opts.block; },
          closest() { return this.classList.contains('add-new') ? null : this; }
        };
        const ico = m[2].match(/data-ico="([^\"]*)"/);
        if (ico) row.dataset.ico = ico[1];
        return row;
      });
    },
    querySelectorAll() { return this.rows.filter(r => !r.classList.contains('add-new')); },
    contains(row) { return this.rows.includes(row); }
  };
}
function party(prefix) {
  const fields = ['jmeno', 'ico', 'adresa', 'rc_1', 'rc_2', 'psc', 'id']
    .map(suffix => field(prefix + '_' + suffix, suffix === 'id'));
  const panel = { querySelectorAll: () => fields };
  fields.forEach(f => f.panel = panel);
  dropdown(prefix + '-firms'); dropdown(prefix + '-name-firms');
  return panel;
}
globalThis.document = {
  getElementById: id => elements[id],
  addEventListener: (type, fn) => { if (type === 'keydown') globalKeys.push(fn); }
};
const firms = [
  { ico: '12345678', nazev: 'ORBION CARS S.R.O.', adresa: 'PRAHA 1', psc: '11000', id: '42' },
  { ico: '12345679', nazev: 'ORBION SECOND S.R.O.', adresa: 'BRNO 2', psc: '60200', id: '43' }
];
const getSavedFirms = async () => firms;
const navNext = () => state.next++;
const navBack = () => state.back++;
const generatePDFs = () => state.generated++;
const currentPanel = () => 3;
const ppdNahledScheduled = () => state.preview++;
const lookupIco = prefix => state.ares = elements[prefix + '_ico'].value;
let _ppdAresTimer = null;
function key(input, name, modifiers = {}) {
  const ev = { target: input, key: name, prevented: false, stopped: false,
    preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; },
    ...modifiers };
  if (input.onkeydown) input.onkeydown(ev);
  if (!ev.stopped) globalKeys.forEach(fn => fn(ev));
  return { prevented: ev.prevented, stopped: ev.stopped };
}
"""


def _browser(scenario):
    names = ["_jeVyplnitelne", "_chybiPovinne", "dalsiPrazdne", "prvniPrazdne", "_skoc",
             "esc", "_hideDropdowns", "najdiFirmy", "_dropdownKlavesy", "openFirmDropdown",
             "selectFirm", "ppdPayerSuggest", "ppdPayerPick", "icoMistoJmena"]
    html = TEMPLATE.read_text(encoding="utf-8")
    start = html.index("// ── Keyboard")
    global_handler = html[start:html.index("// ── Mode selection", start)]
    script = FAKE + "\n" + "\n".join(_function(name) for name in names) + global_handler
    return _node(script + "\n(async () => {\n" + scenario + "\n})();\n")


@pytest.mark.parametrize("prefix", ["puvodni", "puvodni_prov", "novy", "novy_prov"])
@pytest.mark.parametrize("source", ["name", "ico"])
@pytest.mark.parametrize("key_name", ["Enter", "Tab"])
def test_each_party_input_picks_and_enter_advances_once(prefix, source, key_name):
    result = _browser("const prefix = " + json.dumps(prefix) + ";\n"
        + "const source = " + json.dumps(source) + ";\n"
        + "party(prefix); const inp = elements[prefix + (source === 'name' ? '_jmeno' : '_ico')];\n"
        + "inp.value = source === 'name' ? 'ORBI' : '123'; await openFirmDropdown(prefix, source);\n"
        + "const event = key(inp, " + json.dumps(key_name) + ");\n"
        + "console.log(JSON.stringify({event, next: state.next, values: ['ico', 'jmeno', 'adresa', 'psc', 'id']"
        + ".map(s => elements[prefix + '_' + s].value), open: elements[prefix + '-firms'].classList.contains('open')"
        + " || elements[prefix + '-name-firms'].classList.contains('open')}));")
    assert result["values"] == ["12345678", "ORBION CARS S.R.O.", "PRAHA 1", "11000", "42"]
    assert result["next"] == (1 if key_name == "Enter" else 0)
    assert result["event"] == dict(stopped=True, prevented=key_name == "Enter")
    assert not result["open"]


def test_first_highlight_hover_wrap_scroll_and_add_new_exclusion():
    result = _browser(r"""
      party('novy'); const inp = elements.novy_jmeno, dd = elements['novy-name-firms'];
      inp.value = 'ORBI'; elements.novy_ico.value = '99999999'; await openFirmDropdown('novy', 'name');
      const active = () => dd.rows.findIndex(r => r.classList.contains('active'));
      const indices = [active()]; key(inp, 'ArrowUp'); indices.push(active());
      key(inp, 'ArrowDown'); indices.push(active()); key(inp, 'ArrowDown'); indices.push(active());
      dd.onmouseover({target: {closest: () => dd.rows[0]}}); indices.push(active());
      dd.onmouseover({target: dd.rows[2]}); indices.push(active());
      console.log(JSON.stringify({indices, addActive: dd.rows[2].classList.contains('active'),
        scrolled: dd.rows[1].scrolls, scrollBlock: dd.rows[1].scrollBlock}));
    """)
    assert result == dict(indices=[0, 1, 0, 1, 0, 0], addActive=False,
                          scrolled=2, scrollBlock="nearest")


@pytest.mark.parametrize("key_name", ["Enter", "Tab"])
@pytest.mark.parametrize("empty_before", [False, True])
def test_missing_required_field_is_focused_even_before_current_input(key_name, empty_before):
    result = _browser("""
      const owner = party('puvodni'), operator = party('puvodni_prov');
      const all = [...owner.querySelectorAll(), ...operator.querySelectorAll()];
      const panel = {querySelectorAll: () => all}; all.forEach(f => f.panel = panel);
      all.forEach(f => f.value = 'FILLED');
      const missing = elements.""" + ("puvodni_adresa" if empty_before else "puvodni_prov_adresa") + ";\n"
        + "missing.value = ''; const inp = elements.puvodni_prov_jmeno; inp.value = 'ORBI';\n"
        + "await openFirmDropdown('puvodni_prov', 'name');\n"
        + "// The saved firm itself can have a missing address.\n"
        + ("firms[0].adresa = '';\n" if not empty_before else "")
        + "const event = key(inp, " + json.dumps(key_name) + ");\n"
        + "console.log(JSON.stringify({event, next: state.next, focused: state.focused}));")
    assert result["next"] == 0
    assert result["focused"] == ("puvodni_adresa" if empty_before else "puvodni_prov_adresa")
    assert result["event"] == dict(stopped=True, prevented=True)


def test_escape_closes_only_and_ctrl_enter_still_generates():
    result = _browser(r"""
      party('novy'); const inp = elements.novy_jmeno, dd = elements['novy-name-firms'];
      inp.value = 'ORBI'; await openFirmDropdown('novy', 'name');
      const ctrl = key(inp, 'Enter', {ctrlKey: true});
      const shiftTab = key(inp, 'Tab', {shiftKey: true});
      const escape = key(inp, 'Escape');
      console.log(JSON.stringify({ctrl, shiftTab, escape, generated: state.generated, back: state.back,
        name: inp.value, open: dd.classList.contains('open')}));
    """)
    assert result == dict(ctrl=dict(stopped=False, prevented=True),
                          shiftTab=dict(stopped=False, prevented=False),
                          escape=dict(stopped=True, prevented=True), generated=1, back=0,
                          name="ORBI", open=False)


@pytest.mark.parametrize("only_add_new", [False, True])
def test_closed_or_add_new_only_dropdown_leaves_enter_to_global_handler(only_add_new):
    result = _browser("""
      party('novy'); const inp = elements.novy_jmeno, dd = elements['novy-name-firms'];
      inp.value = 'ORBI'; await openFirmDropdown('novy', 'name');
    """ + ("dd.innerHTML = '<div class=\"firm-option add-new\">SAVE</div>';\n" if only_add_new
            else "dd.classList.remove('open');\n")
        + "const event = key(inp, 'Enter'); console.log(JSON.stringify({event, next: state.next, name: inp.value}));")
    assert result == dict(event=dict(stopped=False, prevented=True), next=1, name="ORBI")


@pytest.mark.parametrize("key_name", ["Enter", "Tab"])
def test_ppd_uses_its_existing_pick_without_advancing(key_name):
    result = _browser("""
      const inp = field('ppd_prijato_od'); field('ppd_prijato_ico'); field('ppd_prijato_adresa');
      const dd = dropdown('ppd-payer-firms'); inp.panel = {querySelectorAll: () => [inp]};
      inp.value = 'ORBI'; await ppdPayerSuggest(); key(inp, 'ArrowDown');
    """ + "const event = key(inp, " + json.dumps(key_name) + ");\n"
        + "console.log(JSON.stringify({event, next: state.next, preview: state.preview,"
        + "values: [inp.value, elements.ppd_prijato_ico.value, elements.ppd_prijato_adresa.value],"
        + "open: dd.classList.contains('open')}));")
    assert result == dict(event=dict(stopped=True, prevented=key_name == "Enter"), next=0,
                          preview=1, values=["ORBION SECOND S.R.O.", "12345679", "BRNO 2"], open=False)


def test_eight_digits_in_name_still_move_to_ico_and_ares():
    result = _browser(r"""
      party('novy'); const inp = elements.novy_jmeno, dd = elements['novy-name-firms'];
      inp.value = 'ORBI'; await openFirmDropdown('novy', 'name');
      inp.value = '1234 5678'; const moved = icoMistoJmena('novy');
      console.log(JSON.stringify({moved, name: inp.value, ico: elements.novy_ico.value,
        ares: state.ares, focused: state.focused, open: dd.classList.contains('open')}));
    """)
    assert result == dict(moved=True, name="", ico="12345678", ares="12345678", focused="novy_ico", open=False)


def test_input_handler_stops_enter_before_global_navigation_and_active_css_exists():
    html = TEMPLATE.read_text(encoding="utf-8")
    handler = _function("_dropdownKlavesy")
    assert "input.onkeydown =" in handler
    assert "dropdown.classList.contains('open')" in handler
    assert "e.preventDefault()" in handler and "e.stopPropagation()" in handler
    assert handler.index("e.stopPropagation()") < handler.index("onPick(rows")
    assert handler.index("e.stopPropagation()") < handler.index("navNext()")
    assert "e.ctrlKey" in handler
    assert "_dropdownKlavesy(input, dropdown" in _function("openFirmDropdown")
    assert "_dropdownKlavesy(inp, dd" in _function("ppdPayerSuggest")
    css = re.search(r"\.firm-option\.active\s*\{([^}]*)\}", html).group(1)
    assert "background: var(--accent)" in css
    assert "inset 3px 0 0 var(--primary)" in css
    # Uppercasing listens to input in capture phase; it cannot swallow keydown.
    assert re.search(r"document.addEventListener\('input', function \(ev\) \{\s*"
                     r"if \(isUcTarget\(ev.target\)\) forceUppercase\(ev.target\);\s*\}, true\)", html)
