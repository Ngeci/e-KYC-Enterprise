(function () {
  var node = document.getElementById("dash-data");
  var canvas = document.getElementById("trend");
  if (!node || !canvas || typeof Chart === "undefined") { return; }
  var d = JSON.parse(node.textContent);
  var labels = d.labels.map(function (s) { return s.slice(8, 10) + "/" + s.slice(5, 7); });
  new Chart(canvas, {
    data: {
      labels: labels,
      datasets: [
        { type: "bar", label: "Applications", data: d.applications, backgroundColor: "#c9d8d4", yAxisID: "y", order: 2 },
        { type: "bar", label: "Completed registration", data: d.registered, backgroundColor: "#0f6b63", yAxisID: "y", order: 2 },
        { type: "line", label: "Success rate (%)", data: d.rate, borderColor: "#b7791f", backgroundColor: "#b7791f",
          yAxisID: "y1", tension: 0.25, pointRadius: 3, order: 1 }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "Applications" } },
        y1: { position: "right", min: 0, max: 100, grid: { drawOnChartArea: false }, title: { display: true, text: "Success rate (%)" } }
      },
      plugins: { legend: { position: "bottom" } }
    }
  });
})();
