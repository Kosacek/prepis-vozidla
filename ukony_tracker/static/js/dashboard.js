(function () {
  // Selected period: daily points for a month, monthly points for a whole year.
  var TREND = window.TREND || { labels: [], rows: [], firmy: [] };
  var daily = TREND.rows;
  var firmy = TREND.firmy;
  // Apple system colors — vivid but soft, in the iOS/macOS palette.
  var COLORS = ["#0a84ff", "#34c759", "#ff9f0a", "#bf5af2", "#ff375f",
                "#5ac8fa", "#ffd60a", "#ff6482", "#64d2ff", "#30d158"];
  // Canonical firm -> color map (server-provided), shared with the recent list
  // so a firm has the same color in the chart and the table.
  var FIRMA_COLORS = window.FIRMA_COLORS || {};

  // KPI count-up — the four hero numbers (and their blue Kč figures) animate
  // up from 0 on load instead of just appearing. Server renders the real
  // value into the element up front (so it's correct with JS off or if this
  // throws), and this only takes over once it's confirmed the DOM is ready.
  var REDUCE_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function formatKc(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
  function animateCount(el) {
    var target = parseInt(el.getAttribute("data-count"), 10);
    if (isNaN(target)) return;
    if (REDUCE_MOTION) { el.textContent = formatKc(target); return; }
    var duration = 800, start = null;
    function frame(ts) {
      if (start === null) start = ts;
      var p = Math.min(1, (ts - start) / duration);
      var eased = 1 - Math.pow(1 - p, 3);  // ease-out cubic — fast start, gentle landing
      el.textContent = formatKc(Math.round(target * eased));
      if (p < 1) requestAnimationFrame(frame);
    }
    el.textContent = "0";
    requestAnimationFrame(frame);
  }
  Array.prototype.forEach.call(document.querySelectorAll(".kpis [data-count]"), animateCount);

  // Chart.js keeps the canvas aspect ratio from its width/height attributes
  // (300x110 => ~2.7). On a phone the container is ~300px wide, so the chart
  // collapsed to ~110px tall — with 7+ firm lines it was unreadable. Give the
  // narrow viewport a much taller ratio.
  var MOBILE = window.matchMedia("(max-width: 760px)").matches;
  var TREND_RATIO = MOBILE ? 1.0 : 2.7;

  // ── Kč | Počet toggle, shared by "Podle firmy" and "Typy úkonů" ───────────
  var METRIC_KEY = "dash_metric";
  var metric = "trzby";
  try {
    var saved = localStorage.getItem(METRIC_KEY);
    if (saved === "pocet" || saved === "trzby") metric = saved;
  } catch (e) { /* private mode / blocked storage — default is fine */ }

  var perFirma = window.PER_FIRMA || [];
  var per = window.PER_TYP || [];
  var typChart = null;
  var typRows = [];

  function byMetric(rows) {
    return rows.slice().sort(function (a, b) { return (b[metric] || 0) - (a[metric] || 0); });
  }
  function fmtValue(v) { return metric === "trzby" ? formatKc(Math.round(v || 0)) : String(v || 0); }

  // Bars are built with DOM calls + textContent (firm names come from the DB).
  function renderBars() {
    var box = document.getElementById("firmaBars");
    if (!box) return;
    var rows = byMetric(perFirma);
    var max = rows.length ? (rows[0][metric] || 0) : 0;
    box.replaceChildren();
    if (!rows.length) {
      var empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "Žádná data.";
      box.appendChild(empty);
      return;
    }
    rows.forEach(function (r) {
      var row = document.createElement("div"); row.className = "bar-row";
      var label = document.createElement("span"); label.className = "bar-label"; label.textContent = r.zkratka;
      var track = document.createElement("span"); track.className = "bar-track";
      var fill = document.createElement("span"); fill.className = "bar-fill";
      fill.style.width = (max ? Math.floor(100 * (r[metric] || 0) / max) : 0) + "%";
      track.appendChild(fill);
      var amt = document.createElement("span"); amt.className = "bar-amt"; amt.textContent = fmtValue(r[metric]);
      row.append(label, track, amt);
      box.appendChild(row);
    });
  }

  // Typy úkonů — share per type (doughnut), in Kč or úkon count.
  var pctx = document.getElementById("typChart");
  function updateTyp() {
    if (!typChart) return;
    typRows = byMetric(per);
    typChart.data.labels = typRows.map(function (t) { return t.kod; });
    typChart.data.datasets[0].data = typRows.map(function (t) { return t[metric] || 0; });
    typChart.data.datasets[0].backgroundColor = typRows.map(function (t, i) { return COLORS[i % COLORS.length]; });
    typChart.update();
  }
  if (pctx) {
    typRows = byMetric(per);
    typChart = new Chart(pctx, {
      type: "doughnut",
      data: {
        labels: typRows.map(function (t) { return t.kod; }),
        datasets: [{
          data: typRows.map(function (t) { return t[metric] || 0; }),
          backgroundColor: typRows.map(function (t, i) { return COLORS[i % COLORS.length]; }),
          borderColor: "#fff",
          borderWidth: 2
        }]
      },
      options: {
        cutout: "58%",
        // Chart.js defaults doughnuts to a 1:1 (square) box. Unconstrained by
        // the old grid-stretch, that made the circle balloon to the column's
        // full width — taller than "Podle firmy" next to it. Cap it wider.
        // On a phone the column itself is only ~140px, so a right-side legend
        // has no room — drop it below the circle instead, shrunk to match.
        aspectRatio: MOBILE ? 1.05 : 1.3,
        plugins: {
          legend: {
            position: MOBILE ? "bottom" : "right",
            labels: MOBILE
              ? { usePointStyle: true, pointStyle: "circle", boxWidth: 6, boxHeight: 6, padding: 5, font: { size: 8 } }
              : { usePointStyle: true, pointStyle: "circle", boxWidth: 8, boxHeight: 8, padding: 10, font: { size: 11 } }
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var t = typRows[ctx.dataIndex] || {};
                return t.kod + ": " + formatKc(Math.round(t.trzby || 0)) + " Kč (×" + (t.pocet || 0) + ")";
              }
            }
          }
        }
      }
    });
  }

  function setMetric(m, persist) {
    metric = m;
    if (persist) { try { localStorage.setItem(METRIC_KEY, m); } catch (e) { /* ignore */ } }
    Array.prototype.forEach.call(document.querySelectorAll("[data-metric-toggle] span[data-metric]"), function (x) {
      x.classList.toggle("on", x.dataset.metric === m);
    });
    renderBars();
    updateTyp();
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-metric-toggle]"), function (grp) {
    grp.addEventListener("click", function (e) {
      var s = e.target.closest("span[data-metric]");
      if (s) setMetric(s.dataset.metric, true);
    });
  });
  if (metric !== "trzby") setMetric(metric, false);  // restore the remembered choice

  var tctx = document.getElementById("trendChart");
  if (!tctx) return;

  var labels = TREND.labels;
  var chart = null;

  // Running total: [a, b, c] -> [a, a+b, a+b+c]. Used only by the Firmy lines
  // so each firm's curve climbs over the month.
  function cumulative(arr) {
    var out = [], run = 0;
    for (var i = 0; i < arr.length; i++) { run += arr[i] || 0; out.push(run); }
    return out;
  }

  function render(mode) {
    if (chart) chart.destroy();

    if (mode === "firmy") {
      // one climbing line per firm — cumulative úkon count over the month
      chart = new Chart(tctx, {
        type: "line",
        data: {
          labels: labels,
          datasets: firmy.map(function (f, i) {
            var color = FIRMA_COLORS[f.zkratka] || COLORS[i % COLORS.length];
            return {
              label: f.zkratka,
              data: cumulative(f.pocty),
              borderColor: color,
              backgroundColor: color,
              tension: 0.45,
              cubicInterpolationMode: "monotone",
              borderWidth: 2.5,
              borderCapStyle: "round",
              borderJoinStyle: "round",
              pointRadius: 0,
              pointHoverRadius: 6,
              pointBackgroundColor: color,
              pointBorderColor: "#fff",
              pointBorderWidth: 2,
              pointHoverBorderWidth: 2
            };
          })
        },
        options: {
          aspectRatio: TREND_RATIO,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: {
              position: "bottom",
              labels: { usePointStyle: true, pointStyle: "circle", boxWidth: 8, boxHeight: 8, padding: 16 }
            }
          },
          scales: {
            y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "rgba(0,0,0,0.05)" } },
            x: { grid: { display: false } }
          }
        }
      });
      return;
    }

    // bar: Kč or úkon count per day this month
    chart = new Chart(tctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: mode === "trzby" ? "Kč" : "Počet",
          data: daily.map(function (t) { return t[mode]; }),
          backgroundColor: "#0071e3",
          borderRadius: 6
        }]
      },
      options: {
        aspectRatio: TREND_RATIO,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true } }
      }
    });
  }

  render("firmy");  // Firmy is the default view (most useful at a glance)

  var seg = document.getElementById("metric-seg");
  if (seg) seg.addEventListener("click", function (e) {
    var s = e.target.closest("span[data-mode]");
    if (!s) return;
    this.querySelectorAll("span").forEach(function (x) { x.classList.remove("on"); });
    s.classList.add("on");
    render(s.dataset.mode);
  });

  // ── Recent-list quick search ───────────────────────────────────────────────
  // Server-backed live find across ALL úkony (not just the recent rows). Lets you
  // locate a freshly registered car by a few VIN digits and click straight into
  // its edit page to fill in the new SPZ. Restores the recent list when cleared.
  var search = document.getElementById("recent-search");
  var list = document.getElementById("recent-list");
  if (search && list) {
    var original = list.innerHTML;
    var timer = null, ctrl = null, seq = 0;
    function runSearch() {
      var q = search.value.trim();
      if (!q) { if (ctrl) { ctrl.abort(); ctrl = null; } seq++; list.innerHTML = original; return; }
      if (ctrl) ctrl.abort();
      ctrl = new AbortController();
      var id = ++seq;  // ignore a slow response that lands after a newer query
      fetch("/ukony/hledat?q=" + encodeURIComponent(q), { signal: ctrl.signal })
        .then(function (r) {
          // Non-OK (expired session, server error) would inject an error page
          // into the list — keep the current rows instead.
          if (!r.ok) throw new Error("search " + r.status);
          return r.text();
        })
        .then(function (html) { if (id === seq) list.innerHTML = html; })
        .catch(function () { /* aborted, offline or non-OK — keep current rows */ });
    }
    search.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(runSearch, 180);
    });
  }

  // (The inline úkon-edit modal moved to ukon_modal.js — shared with /ukony.)
})();
