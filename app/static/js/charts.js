(function () {
  var node = document.getElementById("page-charts");
  if (!node || typeof Chart === "undefined") { return; }
  var specs = JSON.parse(node.textContent);
  var registry = [];

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function palette() {
    return { green: css("--green"), ink: css("--chart-ink"), amber: css("--amber"), red: css("--red"),
             grey: css("--chart-grey"), mint: css("--green-soft") };
  }

  function build(id, spec) {
    var canvas = document.getElementById(id);
    if (!canvas) { return; }
    var panel = canvas.closest(".chart-wrap");
    var hasData = spec.labels.length && spec.datasets.some(function (d) { return d.data.some(function (v) { return v !== null; }); });
    if (!hasData) { panel.innerHTML = '<p class="muted">No data for this chart yet.</p>'; return; }

    var c = palette(), isDoughnut = spec.type === "doughnut";
    var cycle = [c.green, c.ink, c.amber, c.red, c.grey, c.mint];
    var datasets = spec.datasets.map(function (d) {
      var color = c[d.color];
      var out = { label: d.label, data: d.data, yAxisID: d.axis || "y" };
      if (d.kind) { out.type = d.kind; }
      if (isDoughnut) {
        out.backgroundColor = spec.labels.map(function (_, i) { return cycle[i % cycle.length]; });
        out.borderColor = css("--panel");
      } else if ((d.kind || spec.type) === "line") {
        out.borderColor = color; out.backgroundColor = color; out.tension = 0.25; out.pointRadius = 3; out.spanGaps = true;
      } else { out.backgroundColor = color; out.borderRadius = 2; }
      return out;
    });

    var grid = css("--line"), text = css("--muted");
    var options = { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom", labels: { color: text, boxWidth: 12 } } } };
    if (!isDoughnut) {
      options.scales = {
        x: { stacked: spec.stacked, grid: { display: false }, ticks: { color: text } },
        y: { stacked: spec.stacked, beginAtZero: true, grid: { color: grid }, ticks: { color: text },
             title: { display: !!spec.yTitle, text: spec.yTitle, color: text } }
      };
      if (spec.y2Title) {
        options.scales.y1 = { position: "right", grid: { drawOnChartArea: false }, ticks: { color: text },
                              title: { display: true, text: spec.y2Title, color: text } };
      }
    } else { options.interaction = { mode: "nearest", intersect: true }; }

    registry.push(new Chart(canvas, { type: spec.type === "doughnut" ? "doughnut" : spec.type,
                                      data: { labels: spec.labels, datasets: datasets }, options: options }));
  }

  function renderAll() {
    registry.forEach(function (ch) { ch.destroy(); });
    registry = [];
    Object.keys(specs).forEach(function (id) { build(id, specs[id]); });
  }
  renderAll();
  document.addEventListener("themechange", renderAll);
})();
