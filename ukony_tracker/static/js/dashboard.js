(function () {
  // Current month, day by day (1 → today).
  var daily = window.DAILY || [];
  var firmy = window.DAILY_FIRMY || [];
  // Apple system colors — vivid but soft, in the iOS/macOS palette.
  var COLORS = ["#0a84ff", "#34c759", "#ff9f0a", "#bf5af2", "#ff375f",
                "#5ac8fa", "#ffd60a", "#ff6482", "#64d2ff", "#30d158"];
  // Canonical firm -> color map (server-provided), shared with the recent list
  // so a firm has the same color in the chart and the table.
  var FIRMA_COLORS = window.FIRMA_COLORS || {};

  // Typy úkonů — revenue share per type (doughnut). Independent of the trend
  // chart, so render it before the trend-chart early-return.
  var pctx = document.getElementById("typChart");
  if (pctx) {
    var per = window.PER_TYP || [];
    new Chart(pctx, {
      type: "doughnut",
      data: {
        labels: per.map(function (t) { return t.kod; }),
        datasets: [{
          data: per.map(function (t) { return t.trzby; }),
          backgroundColor: per.map(function (t, i) { return COLORS[i % COLORS.length]; }),
          borderColor: "#fff",
          borderWidth: 2
        }]
      },
      options: {
        cutout: "58%",
        plugins: {
          legend: {
            position: "right",
            labels: { usePointStyle: true, pointStyle: "circle", boxWidth: 8, boxHeight: 8, padding: 10, font: { size: 11 } }
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var t = per[ctx.dataIndex] || {};
                return t.kod + ": " + Math.round(t.trzby || 0) + " Kč (×" + (t.pocet || 0) + ")";
              }
            }
          }
        }
      }
    });
  }

  var tctx = document.getElementById("trendChart");
  if (!tctx) return;

  var labels = daily.map(function (t) { return String(t.d); });
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
        .then(function (r) { return r.text(); })
        .then(function (html) { if (id === seq) list.innerHTML = html; })
        .catch(function () { /* aborted or offline — ignore */ });
    }
    search.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(runSearch, 180);
    });
  }

  // ── Inline úkon edit modal ──────────────────────────────────────────────────
  // Clicking a recent (or search-result) row opens its edit form in a blurred
  // overlay instead of navigating away. Saving submits normally (full reload to
  // the dashboard, so KPIs/charts reflect the change). Falls back to the plain
  // edit page if the fetch fails or JS is off (the row is still a real link).
  var modal = document.getElementById("ukon-modal");
  var modalBody = document.getElementById("ukon-modal-body");
  var recentList = document.getElementById("recent-list");
  if (modal && modalBody && recentList) {
    var lastFocused = null;

    function openModal(url) {
      fetch(url, { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          modalBody.innerHTML = html;
          lastFocused = document.activeElement;
          modal.hidden = false;
          document.body.classList.add("modal-open");
          requestAnimationFrame(function () {
            modal.classList.add("is-open");
            var first = modalBody.querySelector("input, select, button");
            if (first) first.focus();
          });
        })
        .catch(function () { window.location.href = url.replace(/[?&]modal=1/, ""); });
    }

    function closeModal() {
      modal.classList.remove("is-open");
      document.body.classList.remove("modal-open");
      setTimeout(function () { modal.hidden = true; modalBody.innerHTML = ""; }, 280);
      if (lastFocused && lastFocused.focus) lastFocused.focus();
    }

    // Open — delegated so it also covers rows swapped in by the search box.
    recentList.addEventListener("click", function (e) {
      var row = e.target.closest("a.recent-row");
      if (!row) return;
      var href = row.getAttribute("href");
      if (!href || href.indexOf("/upravit") < 0) return;
      e.preventDefault();
      openModal(href + (href.indexOf("?") >= 0 ? "&" : "?") + "modal=1");
    });

    // Close — backdrop click, the × button, or the form's "Zpět" link.
    modal.addEventListener("click", function (e) {
      if (e.target === modal || e.target.closest("[data-modal-close]")) {
        e.preventDefault();
        closeModal();
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !modal.hidden) closeModal();
    });
  }
})();
