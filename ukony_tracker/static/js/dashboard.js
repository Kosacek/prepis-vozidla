(function () {
  var trend = window.TREND || [], typ = window.TYP || [];
  var MN = ["Led","Úno","Bře","Dub","Kvě","Čvn","Čvc","Srp","Zář","Říj","Lis","Pro"];
  var tctx = document.getElementById("trendChart");
  var metric = "trzby";
  if (tctx) {
    var chart = new Chart(tctx, {
      type: "bar",
      data: { labels: trend.map(function (t) { return MN[t.m - 1]; }),
        datasets: [{ label: "Kč", data: trend.map(function (t) { return t.trzby; }),
          backgroundColor: "#0071e3", borderRadius: 6 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
    });
    var seg = document.getElementById("metric-seg");
    if (seg) seg.addEventListener("click", function (e) {
      var s = e.target.closest("span[data-metric]"); if (!s) return;
      this.querySelectorAll("span").forEach(function (x) { x.classList.remove("on"); });
      s.classList.add("on"); metric = s.dataset.metric;
      chart.data.datasets[0].data = trend.map(function (t) { return t[metric]; });
      chart.data.datasets[0].label = metric === "trzby" ? "Kč" : "Počet";
      chart.update();
    });
  }
  var pctx = document.getElementById("typChart");
  if (pctx && typ.length) new Chart(pctx, {
    type: "doughnut",
    data: { labels: typ.map(function (t) { return t.kod; }),
      datasets: [{ data: typ.map(function (t) { return t.pocet; }),
        backgroundColor: ["#0071e3","#16b8a6","#e0b34f","#8b93a7","#c0506b","#7a6cf0","#d98f4e"] }] },
    options: { plugins: { legend: { position: "right" } } }
  });
})();
