// Payer chips for "Nový doklad": the parties of the ticked úkony's žádosti
// (provozovatel, vlastník) plus the firm, and which one to preselect.
(function (root) {
  var MAX_PARTY_CHIPS = 6;
  var ROLE = {provozovatel: 'Provozovatel', vlastnik: 'Vlastník', firma: 'Firma'};

  function squash(s) { return String(s || '').split(/\s+/).filter(Boolean).join(' '); }
  function digits(s) { return String(s || '').replace(/\D/g, ''); }
  // Same party = same IČO; a private person without one = same name.
  function keyOf(p) { return digits(p.ico) || 'n:' + squash(p.jmeno).toLocaleLowerCase('cs'); }

  // The operator of a žádost: the one entered separately, else the owner
  // (žádosti send an operator only when it differs; the address is then in
  // the owner block, hence strana 'vlastnik').
  function operator(z) {
    if (!z) return null;
    if (z.provozovatel) return {person: z.provozovatel, strana: 'provozovatel'};
    return z.vlastnik ? {person: z.vlastnik, strana: 'vlastnik'} : null;
  }
  function owner(z) { return z && z.vlastnik ? {person: z.vlastnik, strana: 'vlastnik'} : null; }

  function shared(ukony, pick) {
    var key = null;
    for (var i = 0; i < ukony.length; i++) {
      var party = pick(ukony[i].zadost);
      if (!party) return null;
      var k = keyOf(party.person);
      if (key !== null && k !== key) return null;
      key = k;
    }
    return key;
  }

  // ukony: the ticked úkony [{id, zadost: {id, provozovatel, vlastnik} | null}];
  // firma: {nazev, zkratka, ico}. Returns {chips, selected} (selected = chip key).
  function choices(ukony, firma) {
    var firmChip = {key: keyOf({jmeno: firma.nazev, ico: firma.ico}), role: 'firma',
      label: ROLE.firma + ' · ' + (firma.zkratka || firma.nazev), jmeno: firma.nazev, ico: digits(firma.ico)};
    var byKey = {}, parties = [];
    function add(role, party, z) {
      if (!party) return;
      var key = keyOf(party.person);
      if (key === firmChip.key) return;
      var known = byKey[key];
      if (known) {
        // Operator anywhere outranks owner: label it Provozovatel.
        if (role === 'provozovatel' && known.role !== role) {
          known.role = role;
          known.label = ROLE[role] + ' · ' + known.jmeno;
        }
        return;
      }
      byKey[key] = {key: key, role: role, label: ROLE[role] + ' · ' + party.person.jmeno,
        jmeno: party.person.jmeno, ico: digits(party.person.ico), zadost_id: z.id, strana: party.strana};
      parties.push(byKey[key]);
    }
    ukony.forEach(function (u) {
      add('provozovatel', operator(u.zadost), u.zadost);
      add('vlastnik', owner(u.zadost), u.zadost);
    });
    var want = ukony.length ? (shared(ukony, operator) || shared(ukony, owner)) : null;
    var ordered = parties.filter(function (c) { return c.role === 'provozovatel'; })
      .concat(parties.filter(function (c) { return c.role === 'vlastnik'; }));
    var kept = ordered.slice(0, MAX_PARTY_CHIPS);
    var hit = byKey[want] || null;
    // The cap never hides the preselected party.
    if (hit && kept.indexOf(hit) < 0) kept = kept.slice(0, MAX_PARTY_CHIPS - 1).concat([hit]);
    return {chips: kept.concat([firmChip]), selected: (hit || firmChip).key};
  }

  // Does "Přijato od" still name this chip's party (not edited since)?
  function names(chip, prijatoOd) { return !!chip && squash(prijatoOd) === squash(chip.jmeno); }

  // Extra fields for the vystavit call: the žádost party, so žádosti can add
  // its address — only while "Přijato od" still names that party.
  function fields(chip, prijatoOd) {
    if (!chip || !chip.zadost_id || !names(chip, prijatoOd)) return {};
    return {zadost_id: chip.zadost_id, strana: chip.strana};
  }

  var api = {choices: choices, fields: fields, names: names, MAX_PARTY_CHIPS: MAX_PARTY_CHIPS};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.DokladPayer = api;
})(typeof window !== 'undefined' ? window : globalThis);
