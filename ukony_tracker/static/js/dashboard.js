(function () {
  var trend = window.TREND || [];
  var firmy = window.TREND_FIRMY || [];
  var MN = ["Led", "Úno", "Bře", "Dub", "Kvě", "Čvn", "Čvc", "Srp", "Zář", "Říj", "Lis", "Pro"];
  // Apple system colors — vivid but soft, in the iOS/macOS palette.
  var COLORS = ["#0a84ff", "#34c759", "#ff9f0a", "#bf5af2", "#ff375f",
                "#5ac8fa", "#ffd60a", "#ff6482", "#64d2ff", "#30d158"];
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
              // soft, rounded Apple-style curves
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
              labels: {
                usePointStyle: true,
                pointStyle: "circle",
                boxWidth: 8,
                boxHeight: 8,
                padding: 16
              }
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
