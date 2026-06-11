(function () {
  var trend = window.TREND || [];
  var MN = ["Led", "Úno", "Bře", "Dub", "Kvě", "Čvn", "Čvc", "Srp", "Zář", "Říj", "Lis", "Pro"];
  var tctx = document.getElementById("trendChart");
  if (!tctx) return;

  var chart = new Chart(tctx, {
    type: "bar",
    data: {
      labels: trend.map(function (t) { return MN[t.m - 1]; }),
      datasets: [{
        label: "Kč",
        data: trend.map(function (t) { return t.trzby; }),
        backgroundColor: "#0071e3",
        borderRadius: 6
      }]
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true } }
    }
  });

  var seg = document.getElementById("metric-seg");
  if (seg) seg.addEventListener("click", function (e) {
    var s = e.target.closest("span[data-metric]");
    if (!s) return;
    this.querySelectorAll("span").forEach(function (x) { x.classList.remove("on"); });
    s.classList.add("on");
    var metric = s.dataset.metric;
    chart.data.datasets[0].data = trend.map(function (t) { return t[metric]; });
    chart.data.datasets[0].label = metric === "trzby" ? "Kč" : "Počet";
    chart.update();
  });
})();
