// „Zeptej se" jako konverzace (stejně jako v žádostech). Každá otázka přidá
// kolo pod předchozí; server dostane shrnutí posledních kol, takže „a v září?"
// nebo klik na nabízenou možnost navazuje. Bez JS funguje dál obyčejné
// GET /zeptej?q=… (jedna otázka).
(function () {
  var thread = document.getElementById('ask-thread');
  var form = document.getElementById('ask-form');
  if (!thread || !form) return;
  var input = form.querySelector('input[name="q"]');
  var button = form.querySelector('button');
  var tpl = document.getElementById('ask-thinking-tpl');
  var examples = document.getElementById('ask-examples');
  var nova = document.getElementById('ask-nova');
  var MAX_HISTORIE = 4;
  var seq = 0;

  function historie() {
    return Array.prototype.slice.call(thread.querySelectorAll('.ask-turn[data-shrnuti]'))
      .map(function (t) { return { q: t.dataset.q, a: t.dataset.shrnuti }; })
      .filter(function (k) { return k.q && k.a; })
      .slice(-MAX_HISTORIE);
  }

  // Stejné barvy a styl jako graf „Firmy" na přehledu (dashboard.js).
  var COLORS = ['#0a84ff', '#34c759', '#ff9f0a', '#bf5af2', '#ff375f',
                '#5ac8fa', '#ffd60a', '#ff6482', '#64d2ff', '#30d158'];
  var FIRMA_COLORS = window.FIRMA_COLORS || {};

  function dnyMezi(od, doo) {
    var out = [];
    if (!od || !doo) return out;
    var d = new Date(od + 'T00:00:00Z'), end = new Date(doo + 'T00:00:00Z');
    for (var i = 0; d <= end && i < 400; i++) {
      out.push(d.toISOString().slice(0, 10));
      d.setUTCDate(d.getUTCDate() + 1);
    }
    return out;
  }

  function popisCasu(v, cas) {
    var m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(String(v));
    if (!m) return String(v);
    if (cas === 'mesic' || !m[3]) return (+m[2]) + '/' + m[1];
    return (+m[3]) + '. ' + (+m[2]) + '.';
  }

  // Vývoj v čase = rostoucí čáry průběžného součtu (jedna na firmu), přesně
  // jako „Firmy" na přehledu. Dny bez úkonu se doplní nulou, ať čára roste
  // ve skutečném čase a nepřeskakuje mezery.
  function kumulativniGraf(canvas, rows, info) {
    var ti = Math.max(0, info.skupiny.indexOf(info.cas));
    var si = info.skupiny.length > 1 ? 1 - ti : -1;
    var casy = info.cas === 'den' ? dnyMezi(info.od, info.do) : [];
    if (!casy.length) casy = Array.from(new Set(rows.map(function (r) { return r.skupina[ti]; }))).sort();
    var serie = si < 0 ? [info.kc ? 'Kč' : 'Úkony']
      : Array.from(new Set(rows.map(function (r) { return r.skupina[si]; })));
    var datasets = serie.map(function (name, i) {
      var perCas = {};
      rows.forEach(function (r) {
        if (si >= 0 && r.skupina[si] !== name) return;
        perCas[r.skupina[ti]] = (perCas[r.skupina[ti]] || 0) + (+r.hodnota || 0);
      });
      var run = 0;
      var color = FIRMA_COLORS[name] || COLORS[i % COLORS.length];
      return {
        label: name,
        data: casy.map(function (c) { run += perCas[c] || 0; return run; }),
        borderColor: color, backgroundColor: color,
        tension: 0.45, cubicInterpolationMode: 'monotone',
        borderWidth: 2.5, borderCapStyle: 'round', borderJoinStyle: 'round',
        pointRadius: 0, pointHoverRadius: 6, pointBackgroundColor: color,
        pointBorderColor: '#fff', pointBorderWidth: 2, pointHoverBorderWidth: 2
      };
    });
    new Chart(canvas, {
      type: 'line',
      data: { labels: casy.map(function (c) { return popisCasu(c, info.cas); }), datasets: datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: serie.length > 1, position: 'bottom',
          labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 8, boxHeight: 8, padding: 16 } } },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: 'rgba(0,0,0,0.05)' } },
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } }
        }
      }
    });
  }

  function kresliGrafy(root) {
    if (!window.Chart) return;
    root.querySelectorAll('.ask-chart canvas[data-rows]').forEach(function (canvas) {
      if (canvas.dataset.drawn) return;
      canvas.dataset.drawn = '1';
      var rows = JSON.parse(canvas.dataset.rows || '[]');
      var info = null;
      try { info = JSON.parse(canvas.dataset.graf || 'null'); } catch (e) { info = null; }
      if (info && info.kumulativni && rows.length) { kumulativniGraf(canvas, rows, info); return; }
      var kind = canvas.dataset.kind;
      var two = rows.some(function (r) { return r.skupina.length > 1; });
      var labels, datasets;
      if (two) {
        labels = Array.from(new Set(rows.map(function (r) { return r.skupina[0]; })));
        var groups = Array.from(new Set(rows.map(function (r) { return r.skupina[1]; })));
        datasets = groups.map(function (group, i) {
          return { label: group, data: labels.map(function (label) {
            var row = rows.find(function (r) { return r.skupina[0] === label && r.skupina[1] === group; });
            return row ? row.hodnota : 0;
          }), backgroundColor: 'hsl(' + ((i * 67 + 205) % 360) + ' 65% 55%)',
             borderColor: 'hsl(' + ((i * 67 + 205) % 360) + ' 65% 45%)' };
        });
      } else {
        labels = rows.map(function (r) { return r.skupina.join(' / ') || 'Celkem'; });
        datasets = [{ label: 'Hodnota', data: rows.map(function (r) { return r.hodnota; }),
          backgroundColor: rows.map(function (_, i) { return 'hsl(' + ((i * 37 + 205) % 360) + ' 65% 55%)'; }),
          borderColor: '#2875af' }];
      }
      new Chart(canvas, {
        type: kind === 'cara' ? 'line' : kind === 'kolac' && !two ? 'pie' : 'bar',
        data: { labels: labels, datasets: datasets },
        options: { responsive: true, maintainAspectRatio: false,
          scales: kind === 'kolac' && !two ? {} : { y: { beginAtZero: true } },
          plugins: { legend: { display: two || kind === 'kolac' } } }
      });
    });
  }

  // Nové kolo odroluje přesně pod přišpendlené pole s otázkou (ne pod něj schované).
  function podPole(turn) {
    var bar = form.closest('.ask-bar-card') || form;
    var y = turn.getBoundingClientRect().top + window.scrollY - bar.getBoundingClientRect().bottom - 12;
    window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
  }

  function zeptej(q) {
    q = (q || '').trim();
    if (!q) return;
    var mySeq = ++seq;
    var hist = historie();
    // Nabídnuté možnosti a příklady patří k minulé odpovědi — po nové otázce pryč.
    thread.querySelectorAll('.ask-choices').forEach(function (e) { e.remove(); });
    if (examples) examples.hidden = true;
    if (nova) nova.hidden = false;
    input.value = '';
    input.placeholder = 'Zeptej se dál…';
    button.disabled = true;

    var turn = document.createElement('div');
    turn.className = 'ask-turn';
    turn.dataset.q = q;
    var bubble = document.createElement('div');
    bubble.className = 'ask-q ask-reveal';
    bubble.textContent = q;
    var answer = document.createElement('div');
    answer.className = 'ask-a';
    answer.appendChild(tpl.content.cloneNode(true));
    turn.appendChild(bubble);
    turn.appendChild(answer);
    thread.appendChild(turn);
    podPole(turn);

    var card = answer.querySelector('.ask-thinking');
    var cycle = window.Thinking ? window.Thinking(card, card.querySelector('.ask-verb')) : null;
    if (cycle) cycle.start();

    fetch('/zeptej/kolo', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q: q, historie: hist })
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (data) {
      if (mySeq !== seq) return;
      if (cycle) cycle.stop();
      answer.innerHTML = data.html;
      turn.dataset.shrnuti = data.shrnuti || '';
      kresliGrafy(answer);
    }).catch(function () {
      if (mySeq !== seq) return;
      if (cycle) cycle.stop();
      answer.innerHTML = '<div class="card ask-answer ask-answer--unknown"><div class="ask-headline">Odpověď se nepovedla načíst.</div></div>';
    }).then(function () {
      if (mySeq !== seq) return;
      button.disabled = false;
      input.focus();
    });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    zeptej(input.value);
  });

  // Příklady i nabídnuté možnosti („Myslíš…?") se ptají uvnitř konverzace.
  document.addEventListener('click', function (e) {
    var chip = e.target.closest('a[data-ask]');
    if (!chip || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
    e.preventDefault();
    zeptej(chip.dataset.ask);
  });

  if (nova) nova.addEventListener('click', function () {
    seq++;
    thread.innerHTML = '';
    nova.hidden = true;
    if (examples) examples.hidden = false;
    input.placeholder = 'Zeptej se na úkony nebo PPD';
    button.disabled = false;
    if (location.search) history.replaceState(null, '', '/zeptej');
    input.focus();
  });

  kresliGrafy(thread);
})();
