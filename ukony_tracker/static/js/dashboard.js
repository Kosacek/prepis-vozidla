(function () {
  var trend = window.TREND || [];
  var firmy = window.TREND_FIRMY || [];
  var MN = ["Led", "Úno", "Bře", "Dub", "Kvě", "Čvn", "Čvc", "Srp", "Zář", "Říj", "Lis", "Pro"];
  var COLORS = ["#0071e3", "#16a34a", "#ea580c", "#9333ea", "#dc2626",
                "#0891b2", "#ca8a04", "#db2777", "#475569", "#65a30d"];
  var tctx = document.getElementById("trendChart");
  if (!tctx) return;

  var labels = trend.map(function (t) { return MN[t.m - 1]; });
  var chart = null;

  function render(mode) {
    if (chart) chart.destroy();

    if (mode === "firmy") {
      // one line per firm — compare úkon counts across months
      chart = new Chart(tctx, {
        type: "line",
        data: {
          labels: labels,
          datasets: firmy.map(function (f, i) {
            var color = COLORS[i % COLORS.length];
            return {
              label: f.zkratka,
              data: f.pocty,
              borderColor: color,
              backgroundColor: color,
              tension: 0.3,
              pointRadius: 3,
              borderWidth: 2
            };
          })
        },
        options: {
          interaction: { mode: "index", intersect: false },
          plugins: { legend: { position: "bottom" } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
        }
      });
      return;
    }

    // bar: total Kč or total count per month
    chart = new Chart(tctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: mode === "trzby" ? "Kč" : "Počet",
          data: trend.map(function (t) { return t[mode]; }),
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
