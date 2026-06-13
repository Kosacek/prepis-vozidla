(function () {
  // Current month, day by day (1 → today). The chart plots the *cumulative*
  // running total, so the line only ever climbs from the 1st to today.
  var daily = window.DAILY || [];
  var firmy = window.DAILY_FIRMY || [];
  // Apple system colors — vivid but soft, in the iOS/macOS palette.
  var COLORS = ["#0a84ff", "#34c759", "#ff9f0a", "#bf5af2", "#ff375f",
                "#5ac8fa", "#ffd60a", "#ff6482", "#64d2ff", "#30d158"];
  var tctx = document.getElementById("trendChart");
  if (!tctx) return;

  var labels = daily.map(function (t) { return String(t.d); });
  var chart = null;

  // Running total: [a, b, c] -> [a, a+b, a+b+c].
  function cumulative(arr) {
    var out = [], run = 0;
    for (var i = 0; i < arr.length; i++) { run += arr[i] || 0; out.push(run); }
    return out;
  }

  function hexToRgba(hex, a) {
    var n = parseInt(hex.slice(1), 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }

  // Apple-style soft gradient fill under a single climbing line.
  function areaFill(hex) {
    return function (ctx) {
      var ch = ctx.chart, area = ch.chartArea;
      if (!area) return hexToRgba(hex, 0.12);  // first paint, before layout
      var g = ch.ctx.createLinearGradient(0, area.top, 0, area.bottom);
      g.addColorStop(0, hexToRgba(hex, 0.28));
      g.addColorStop(1, hexToRgba(hex, 0.02));
      return g;
    };
  }

  // Shared styling for the smooth, rounded climbing curves.
  function lineStyle(color, extra) {
    var d = {
      borderColor: color,
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
    if (extra) for (var k in extra) d[k] = extra[k];
    return d;
  }

  var baseOptions = {
    interaction: { mode: "index", intersect: false },
    scales: {
      y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "rgba(0,0,0,0.05)" } },
      x: { grid: { display: false } }
    }
  };

  function render(mode) {
    if (chart) chart.destroy();

    if (mode === "firmy") {
      // one climbing line per firm — cumulative úkon count over the month
      chart = new Chart(tctx, {
        type: "line",
        data: {
          labels: labels,
          datasets: firmy.map(function (f, i) {
            var color = COLORS[i % COLORS.length];
            return lineStyle(color, {
              label: f.zkratka,
              data: cumulative(f.pocty),
              backgroundColor: color
            });
          })
        },
        options: Object.assign({}, baseOptions, {
          plugins: {
            legend: {
              position: "bottom",
              labels: { usePointStyle: true, pointStyle: "circle", boxWidth: 8, boxHeight: 8, padding: 16 }
            }
          }
        })
      });
      return;
    }

    // single climbing area-line: cumulative Kč or count over the month
    var color = "#0a84ff";
    chart = new Chart(tctx, {
      type: "line",
      data: {
        labels: labels,
        datasets: [lineStyle(color, {
          label: mode === "trzby" ? "Kč" : "Počet",
          data: cumulative(daily.map(function (t) { return t[mode]; })),
          fill: true,
          backgroundColor: areaFill(color)
        })]
      },
      options: Object.assign({}, baseOptions, {
        plugins: { legend: { display: false } }
      })
    });
  }

  render("trzby");

  var seg = document.getElementById("metric-seg");
  if (seg) seg.addEventListener("click", function (e) {
    var s = e.target.closest("span[data-mode]");
    if (!s) return;
    this.querySelectorAll("span").forEach(function (x) { x.classList.remove("on"); });
    s.classList.add("on");
    render(s.dataset.mode);
  });
})();
