/*
 * Chart.js, set up once for the whole dashboard.
 *
 * Chart.js (calls/static/calls/vendor/chart.umd.js) is loaded by a normal <script> tag before
 * our modules, and puts itself in the global variable `Chart`.
 *
 * Every chart on the page is drawn through drawChart(canvasId, build):
 *   - `build(colours)` returns a Chart.js config: { type, data, options }.
 *   - The colours come from the CSS variables at the top of dashboard.css, so charts
 *     match the page in light and dark mode. They were checked with a colour-blindness
 *     validator against the card colour, in both modes: if you change them, check again.
 *   - Bars are drawn the same way everywhere (barStyle): solid, rounded at the data end only,
 *     with a thin gap in the card's colour between stacked pieces. Upright bars get their total
 *     written above them (barLabels); sideways bars at their end (endLabels).
 *   - Ring charts (ringStyle) have rounded pieces with small gaps, the total in the middle
 *     (centreText), and a key beside them with each count and its share (ringLegend).
 *   - drawChart's third argument, `onBarClick`, makes bars and ring pieces clickable (the pointer
 *     shows it): the pages use it to open the calls behind them (js/drill.js).
 *   - The first time a chart is drawn (and each time its page is opened again), its bars grow
 *     one after another; after that, new numbers glide into place.
 *   - Calling drawChart again for the same canvas updates the chart instead of making a new one.
 *   - When the page switches between light and dark mode, every chart is rebuilt.
 */

const charts = new Map(); // canvas id -> { chart, build, onBarClick }

// Read one CSS variable, e.g. css("--good") -> "#0f7a4a"
function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// The dashboard's colours, from dashboard.css.
export function colours() {
  return {
    ink: css("--ink"),
    muted: css("--muted"),
    line: css("--line"),
    card: css("--card"),
    answered: css("--chart-answered"), // calls in answered: blue
    unanswered: css("--chart-unanswered"), // calls in unanswered, and rings missed: amber
    connected: css("--chart-connected"), // calls out the customer picked up: green
    notConnected: css("--chart-not-connected"), // calls out never picked up: grey
    other: css("--chart-other"), // calls in neither answered nor unanswered: pink
    neutral: css("--chart-neutral"), // "none": agents not logged in
  };
}

// Writes the total above each upright bar (each stack, when a chart has two bars side by side), like
// "285" above a month. Skipped when the bars are too thin for a number to fit, and for zeros.
const barLabels = {
  id: "barLabels",
  afterDatasetsDraw(chart) {
    if (chart.config.type !== "bar" || chart.options.indexAxis === "y") return;
    const metas = chart.getSortedVisibleDatasetMetas();
    const { ctx } = chart;
    ctx.save();
    ctx.font = `750 12px ${Chart.defaults.font.family}`;
    ctx.fillStyle = css("--ink");
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    const count = chart.data.labels.length;
    for (let i = 0; i < count; i++) {
      const stacks = new Map(); // stack name -> { total, top, x, width }
      for (const meta of metas) {
        const bar = meta.data[i];
        const value = Number(chart.data.datasets[meta.index].data[i]) || 0;
        if (!bar || !value) continue;
        const key = chart.data.datasets[meta.index].stack ?? "all"; // no stack name: all the pieces make one bar
        const s = stacks.get(key) || { total: 0, top: Infinity, x: bar.x, width: bar.width };
        s.total += value;
        s.top = Math.min(s.top, bar.y);
        stacks.set(key, s);
      }
      for (const s of stacks.values()) {
        const text = s.total.toLocaleString("en-GB");
        if (s.width < 14 || ctx.measureText(text).width > s.width + 18) continue;
        ctx.fillText(text, s.x, s.top - 4);
      }
    }
    ctx.restore();
  },
};

// Writes a number just past the end of each sideways bar (e.g. how many calls), so a ranking reads
// without hovering. The numbers come from the chart's `plugins.endLabels.values`.
const endLabels = {
  id: "endLabels",
  afterDatasetsDraw(chart, _args, options) {
    if (!options.values) return;
    const metas = chart.getSortedVisibleDatasetMetas();
    const { ctx } = chart;
    ctx.save();
    ctx.font = `750 12px ${Chart.defaults.font.family}`;
    ctx.fillStyle = css("--ink");
    ctx.textBaseline = "middle";
    options.values.forEach((value, i) => {
      const bars = metas.map((meta) => meta.data[i]).filter(Boolean);
      if (!bars.length) return;
      const end = Math.max(...bars.map((bar) => bar.x)); // the right-hand end of this row's bars
      ctx.fillText(String(value), end + 6, bars[0].y);
    });
    ctx.restore();
  },
};

// Writes a number and a word in the hole of a ring chart, e.g. "1,307 calls".
// The values come from the chart's `plugins.centreText`.
export const centreText = {
  id: "centreText",
  afterDraw(chart, _args, options) {
    if (chart.config.type !== "doughnut" || options.value === undefined) return;
    const { ctx, chartArea } = chart;
    const x = (chartArea.left + chartArea.right) / 2;
    const y = (chartArea.top + chartArea.bottom) / 2;
    const size = Math.max(16, Math.min(28, (chartArea.right - chartArea.left) / 5.5));
    ctx.save();
    ctx.textAlign = "center";
    ctx.fillStyle = css("--ink");
    ctx.font = `780 ${size}px ${Chart.defaults.font.family}`;
    ctx.fillText(Number(options.value).toLocaleString("en-GB"), x, y + size * 0.2);
    ctx.fillStyle = css("--muted");
    ctx.font = `600 11px ${Chart.defaults.font.family}`;
    ctx.fillText(options.label, x, y + size * 0.2 + 15);
    ctx.restore();
  },
};

// A chart with nothing to show says so, instead of showing an empty grid.
const emptyState = {
  id: "emptyState",
  afterDraw(chart) {
    if (chart.config.type === "doughnut") return; // ring charts have their own note
    const total = chart.data.datasets.reduce((sum, d) => sum + d.data.reduce((s, v) => s + (Number(v) || 0), 0), 0);
    if (total > 0) return;
    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.font = `600 13px ${Chart.defaults.font.family}`;
    ctx.fillStyle = css("--muted");
    ctx.textAlign = "center";
    ctx.fillText("No calls in this period", (chartArea.left + chartArea.right) / 2, (chartArea.top + chartArea.bottom) / 2);
    ctx.restore();
  },
};

// Settings shared by every chart: text colours, grid lines, font, legend, tooltip and animation.
function applyDefaults() {
  const c = colours();
  Chart.defaults.color = c.muted;
  Chart.defaults.borderColor = c.line;
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 12;
  Chart.defaults.font.weight = 600;
  Chart.defaults.maintainAspectRatio = false; // the chart fills its .chart-box, whose height CSS sets
  Chart.defaults.datasets.bar.maxBarThickness = 44; // broad bars, like the reference design...
  Chart.defaults.datasets.bar.categoryPercentage = 0.72; // ...with air between the groups
  Chart.defaults.interaction.mode = "index"; // hovering a bar shows every series for that bar...
  Chart.defaults.interaction.intersect = false; // ...even if the pointer is beside it, not on it

  // Bars grow one after another (left to right, then series by series) when a chart is first drawn.
  // `$grown` is set once that is done, so later refreshes just glide to the new numbers.
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  Chart.defaults.animation.duration = calm ? 0 : 900;
  Chart.defaults.animation.easing = "easeOutQuart";
  Chart.defaults.animation.delay = (ctx) =>
    ctx.type === "data" && ctx.mode === "default" && !ctx.chart.$grown ? ctx.dataIndex * 30 + ctx.datasetIndex * 120 : 0;

  // The key: small rounded squares, at the top left
  const legend = Chart.defaults.plugins.legend;
  Object.assign(legend, { position: "top", align: "start" });
  Object.assign(legend.labels, { usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10, boxHeight: 10, padding: 14, color: c.ink });

  // Tooltips in the text colour, with the card colour as text: dark on a light page, light on a dark one.
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: c.ink, titleColor: c.card, bodyColor: c.card, padding: 12, cornerRadius: 12, caretSize: 6,
    boxPadding: 5, usePointStyle: true, titleFont: { weight: "700" }, bodyFont: { weight: "500" },
  });
}

// Round corners on the end of a bar, unless another piece of the same stack sits on top of it.
function roundedEnd(ctx) {
  const { chart, dataIndex, datasetIndex } = ctx;
  const datasets = chart.data.datasets;
  const stack = datasets[datasetIndex].stack;
  const covered = datasets.some(
    (d, i) => i > datasetIndex && d.stack === stack && chart.isDatasetVisible(i) && d.data[dataIndex] > 0,
  );
  return covered ? 0 : 7;
}

// How every bar is drawn: solid, square at the baseline, rounded at the data end,
// and a 2px gap in the card's colour where pieces of a stack meet.
export function barStyle(c, { horizontal = false } = {}) {
  return {
    borderRadius: roundedEnd,
    borderSkipped: "start",
    borderColor: c.card,
    borderWidth: horizontal ? { right: 2 } : { top: 2 },
    ...(horizontal ? { maxBarThickness: 34 } : {}),
  };
}

// How every ring is drawn: thick, with rounded pieces and small gaps between them.
export function ringStyle() {
  return { borderWidth: 0, borderRadius: 6, spacing: 3, hoverOffset: 6 };
}

// The key beside a ring chart: a dot, the name, the count and its share of the total, per piece
// (like "Answered (in)  412  31.5%"). `items` is [{ label, value, colour }].
export function ringLegend(listId, items) {
  const list = document.getElementById(listId);
  const total = items.reduce((sum, item) => sum + item.value, 0);
  list.replaceChildren();
  for (const { label, value, colour } of items) {
    const li = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = colour;
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = label;
    const number = document.createElement("b");
    number.textContent = value.toLocaleString("en-GB");
    const share = document.createElement("span");
    share.className = "pct";
    share.textContent = total ? `${((value / total) * 100).toFixed(1)}%` : "–";
    li.append(dot, name, number, share);
    list.appendChild(li);
  }
}

// Mark a chart as grown once its first animation has had time to finish.
function settle(chart) {
  chart.$grown = false;
  setTimeout(() => { chart.$grown = true; }, 2500);
}

// Draw (or update) the chart in <canvas id=canvasId>. Returns the Chart, or null if Chart.js didn't load.
// `onBarClick({ datasetIndex, index })`, if given, is called when a bar (or a piece of one) is clicked.
export function drawChart(canvasId, build, onBarClick) {
  if (typeof Chart === "undefined") return null; // the tables still work without charts
  applyDefaults();
  const config = build(colours());
  if (onBarClick) {
    config.options = {
      ...config.options,
      onClick: (_event, bars) => { if (bars.length) onBarClick(bars[0]); },
      onHover: (event, bars) => { event.native.target.style.cursor = bars.length ? "pointer" : "default"; },
    };
  }
  const existing = charts.get(canvasId);

  if (existing && existing.chart.config.type === config.type) {
    existing.chart.data = config.data;
    existing.chart.options = config.options || {};
    existing.chart.update();
    Object.assign(existing, { build, onBarClick });
    return existing.chart;
  }
  if (existing) existing.chart.destroy();
  const plugins = [...(config.plugins || []), barLabels, endLabels, centreText, emptyState];
  const chart = new Chart(document.getElementById(canvasId), { ...config, plugins });
  settle(chart);
  charts.set(canvasId, { chart, build, onBarClick });
  return chart;
}

// After a hidden page is shown, its charts measure their new size and grow again from the baseline.
export function replayCharts(panel) {
  for (const { chart } of charts.values()) {
    chart.resize();
    if (!panel.contains(chart.canvas)) continue;
    settle(chart);
    chart.reset();
    chart.update();
  }
}

// Light/dark switch (the computer's, or the page's own: js/theme.js): rebuild every chart with the new colours.
// (A copy of the list, [...charts], because drawChart adds each rebuilt chart back to `charts`: walking the
// list itself would meet the rebuilt charts again and never finish.)
function rebuildAll() {
  for (const [canvasId, { chart, build, onBarClick }] of [...charts]) {
    chart.destroy();
    charts.delete(canvasId);
    drawChart(canvasId, build, onBarClick);
  }
}
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", rebuildAll);
window.addEventListener("themechange", rebuildAll);

// Bar chart options most charts here share. `horizontal` puts the bars sideways (rankings), with room on
// the right for the end-of-bar numbers; upright bars get room at the top for the totals above them.
// Grid lines are faint dashes; there are no axis lines.
export function stackedBarOptions({ horizontal = false } = {}) {
  const countAxis = { stacked: true, beginAtZero: true, ticks: { precision: 0 }, border: { display: false, dash: [4, 4] } };
  const labelAxis = { stacked: true, grid: { display: false }, border: { display: false } };
  return {
    indexAxis: horizontal ? "y" : "x",
    layout: { padding: horizontal ? { right: 30 } : { top: 18 } },
    scales: horizontal ? { x: countAxis, y: labelAxis } : { x: labelAxis, y: countAxis },
  };
}
