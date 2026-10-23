/*
 * Monthly page: history, month by month.
 *
 * Asks our server: GET /api/monthly/?from=2025-11&to=2026-10&queue=..., then draws:
 *   - five tiles for the months chosen (calls, answer ratio, connect rate, average talk, busiest month),
 *   - "Calls per month": two bars per month, calls in (answered, unanswered) and calls out (connected, not),
 *   - "Top agents": who made the most calls, and who received the most, over those months.
 * Clicking a tile, a month's bar or an agent opens the calls behind it (js/drill.js).
 */
import { barStyle, drawChart, stackedBarOptions } from "./charts.js";
import { KIND_TITLES, openDrill, wireAgentRows, wireTiles } from "./drill.js";
import { clock, duration, fillRank, getJSON, monthLabel, setStatus, setText, showSyncInfo } from "./format.js";
import { countTo, growBars, sparkline } from "./fx.js";

const panel = document.getElementById("panel-monthly");
const form = document.getElementById("monthly-filters");
const total = (m) => m.inbound + m.outbound;
let shownMonths = []; // the months on the chart, so a clicked bar knows its month

// "2026-10" -> the first and last day of that month, as "2026-10-01" and "2026-10-31"
function monthDays(month) {
  const [year, number] = month.split("-").map(Number);
  const last = new Date(year, number, 0).getDate(); // day 0 of the next month = the last day of this one
  return { from: `${month}-01`, to: `${month}-${String(last).padStart(2, "0")}` };
}

// The months chosen (first day of the first to last day of the last) and queue, for the drill-down
const filterParams = () => ({
  from: monthDays(form.elements.from.value).from,
  to: monthDays(form.elements.to.value).to,
  queue: form.elements.queue.value,
});

function renderTiles(t, months) {
  const value = (name) => panel.querySelector(`[data-month="${name}"]`);
  const sub = (name, text) => setText(panel, `[data-month-sub="${name}"]`, text);
  countTo(value("calls"), t.calls);
  sub("calls", `${t.inbound} in · ${t.outbound} out`);
  sparkline(panel.querySelector('[data-spark="months"]'), months.map(total));
  countTo(value("answer_ratio"), t.answer_ratio_pct, (n) => `${n.toFixed(1)}%`);
  sub("answer_ratio", t.inbound ? `${t.answered_in} of ${t.inbound} calls in answered` : "no calls in");
  countTo(value("connect"), t.connect_ratio_pct, (n) => `${n.toFixed(1)}%`);
  sub("connect", t.outbound ? `${t.answered_out} of ${t.outbound} calls out picked up` : "no calls out");
  countTo(value("avg_talk"), t.avg_talk_sec, (n) => duration(Math.round(n)));

  // `reduce` walks the months, keeping the one with the most calls so far
  const busiest = months.reduce((best, m) => (total(m) > total(best) ? m : best), months[0]);
  const busy = busiest && total(busiest);
  countTo(value("busiest"), busy ? monthLabel(busiest.month) : "–");
  sub("busiest", busy ? `${total(busiest)} calls` : "no calls yet");
}

// Which list of calls each series opens
const MONTH_KINDS = ["answered_in", "unanswered_in", "connected", "not_connected"];

function renderChart(months) {
  shownMonths = months;
  drawChart("monthly-chart", (c) => ({
    type: "bar",
    data: {
      labels: months.map((m) => monthLabel(m.month)),
      datasets: [
        // Same `stack` name = one bar; so each month has a calls-in bar and a calls-out bar
        { label: "Answered (in)", data: months.map((m) => m.answered_in), backgroundColor: c.answered, stack: "in" },
        { label: "Unanswered (in)", data: months.map((m) => m.unanswered_in), backgroundColor: c.unanswered, stack: "in" },
        { label: "Connected (out)", data: months.map((m) => m.answered_out), backgroundColor: c.connected, stack: "out" },
        { label: "Not connected (out)", data: months.map((m) => m.outbound - m.answered_out), backgroundColor: c.notConnected, stack: "out" },
      ].map((d) => ({ ...d, ...barStyle(c) })),
    },
    options: stackedBarOptions(),
  }), ({ datasetIndex, index }) => {
    const kind = MONTH_KINDS[datasetIndex];
    const month = shownMonths[index].month;
    openDrill({ title: `${KIND_TITLES[kind]} · ${monthLabel(month)}`, params: { ...filterParams(), ...monthDays(month), kind } });
  });
}

function renderAgents(agents) {
  const made = fillRank("monthly-made", agents, {
    value: (a) => a.made,
    hint: (a) => `${a.made} made · ${a.answered_out} connected · click to see their calls`,
    bar: "out",
    emptyText: "No calls made",
  });
  const received = fillRank("monthly-received", agents, {
    value: (a) => a.received,
    hint: (a) => `${a.received} answered · ${a.missed_rings} rings missed · click to see their calls`,
    emptyText: "No calls received",
  });
  if (made) growBars(document.getElementById("monthly-made"));
  if (received) growBars(document.getElementById("monthly-received"));
}

export async function load(urls) {
  setStatus(panel, "Loading…");
  try {
    const data = await getJSON(urls.monthly, new FormData(form));
    renderTiles(data.totals, data.months);
    renderChart(data.months);
    renderAgents(data.agents);
    showSyncInfo(data);
    setStatus(panel, `Updated ${clock(new Date())}`);
  } catch (err) {
    setStatus(panel, `Could not load: ${err.message}`, { error: true });
  }
}

// Tiles and the agents in the two lists open their calls
wireTiles(panel, filterParams);
wireAgentRows(document.getElementById("monthly-made"), filterParams, "outbound");
wireAgentRows(document.getElementById("monthly-received"), filterParams, "answered_in");

export const filters = form;
