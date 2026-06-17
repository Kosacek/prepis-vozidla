(function () {
  // Current month, day by day (1 → today).
  var daily = window.DAILY || [];
  var firmy = window.DAILY_FIRMY || [];
  // Apple system colors — vivid but soft, in the iOS/macOS palette.
  var COLORS = ["#0a84ff", "#34c759", "#ff9f0a", "#bf5af2", "#ff375f",
                "#5ac8fa", "#ffd60a", "#ff6482", "#64d2ff", "#30d158"];

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
            var color = COLORS[i % COLORS.length];
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
})();
