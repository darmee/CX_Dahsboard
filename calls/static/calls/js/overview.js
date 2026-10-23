/*
 * Overview page: numbers for a date range and queue.
 *
 * 1. Reads the filters (dates, queue) from the form.
 * 2. Asks our server: GET /api/metrics/?from=...&to=...&queue=...
 * 3. Fills the tiles (numbers count to their new value, with "▲ 12%" against the period before), the answer
 *    ratio's ring, the little trend lines, the hourly chart, the "Call outcomes" ring and the top-agents list.
 * Clicking a tile, a bar, a piece of the ring or an agent opens the calls behind it (js/drill.js).
 * main.js calls load() when the page opens, every 30 seconds while it is open, and when a filter changes.
 */
import { barStyle, drawChart, ringLegend, ringStyle, stackedBarOptions } from "./charts.js";
import { KIND_TITLES, openDrill, wireAgentRows, wireTiles } from "./drill.js";
import { clock, duration, fillRank, getJSON, hourLabel, percent, setStatus, setText, showSyncInfo } from "./format.js";
import { countTo, growBars, setGauge, sparkline } from "./fx.js";

const panel = document.getElementById("panel-overview");
const form = document.getElementById("overview-filters");
const asPercent = (n) => `${n.toFixed(1)}%`;
const asDuration = (n) => duration(Math.round(n));
let shownHours = []; // the hours on the chart, so a clicked bar knows its hour

// The filters as they are now, for the drill-down
const filterParams = () => ({ from: form.elements.from.value, to: form.elements.to.value, queue: form.elements.queue.value });

/*
 * The "▲ 12%" chip beside a number: how it changed on the period before (`before`, from the API's "previous").
 * Counts and times change by a percentage; ratios by percentage points ("▲ 4.2 pts"). `goodWhen` says which
 * way is better ("up", "down", or "" when neither), which colours the chip green or red.
 */
function delta(name, now, before, { points = false, goodWhen = "", label }) {
  const chip = panel.querySelector(`[data-delta="${name}"]`);
  if (now === null || now === undefined || !before) { // nothing to compare with (e.g. no calls the day before)
    chip.hidden = true;
    return;
  }
  const change = points ? now - before : ((now - before) / before) * 100;
  const rounded = Math.round(change * 10) / 10;
  chip.hidden = false;
  chip.textContent = rounded === 0 ? "= same" : `${rounded > 0 ? "▲" : "▼"} ${Math.abs(rounded)}${points ? " pts" : "%"}`;
  const better = goodWhen === "up" ? rounded > 0 : goodWhen === "down" ? rounded < 0 : null;
  chip.className = `delta${rounded === 0 || better === null ? "" : better ? " better" : " worse"}`;
  chip.title = `${label}: ${points ? `${before}%` : before}`;
}

function renderTiles(m) {
  const t = m.totals, tm = m.timing, rj = m.rejection, before = m.previous;
  const value = (name) => panel.querySelector(`[data-metric="${name}"]`);
  const sub = (name, text) => setText(panel, `[data-sub="${name}"]`, text);
  const days = Math.round((new Date(before.to) - new Date(before.from)) / 86400000) + 1;
  // While the period runs into today, the period before stops at the same time of day (before.until)
  const label = `${days === 1 ? "The day before" : `The ${days} days before`}${before.until ? ` up to ${before.until}` : ""}`;

  // The answer ratio = answered calls in ÷ all calls in. Calls out have their own rate (the connect rate).
  const ratio = t.answer_ratio_pct;
  const state = ratio === null ? "" : ratio >= 80 ? "good" : "bad";
  countTo(value("answer_ratio"), ratio, asPercent);
  setGauge(panel.querySelector('[data-gauge="answer_ratio"]'), ratio, state);
  delta("answer_ratio", ratio, before.answer_ratio_pct, { points: true, goodWhen: "up", label });
  // "other" = calls in that were neither answered nor unanswered (IVR only, still in progress, ...)
  const other = t.other_inbound ? ` · ${t.other_inbound} other` : "";
  sub("answer_ratio", t.inbound ? `${t.answered_inbound} answered of ${t.inbound} calls in${other} · target 80%` : "no calls in");

  countTo(value("inbound"), t.inbound);
  delta("inbound", t.inbound, before.inbound, { label });
  sub("inbound", t.inbound ? `${t.answered_inbound} answered · ${t.inbound - t.answered_inbound} not` : "none in this period");
  countTo(value("outbound"), t.outbound);
  delta("outbound", t.outbound, before.outbound, { label });
  sub("outbound", t.outbound
    ? `${t.answered_outbound} connected · ${t.outbound - t.answered_outbound} not · ${percent(t.connect_ratio_pct)}`
    : "none in this period");
  sparkline(panel.querySelector('[data-spark="inbound"]'), m.hourly.map((h) => h.inbound));
  sparkline(panel.querySelector('[data-spark="outbound"]'), m.hourly.map((h) => h.outbound));

  countTo(value("unanswered"), t.unanswered);
  value("unanswered").className = t.unanswered ? "value bad" : "value";
  delta("unanswered", t.unanswered, before.unanswered, { goodWhen: "down", label });
  sub("unanswered", `${t.abandoned} abandoned · ${t.dropped} dropped`);

  countTo(value("delay"), tm.avg_wait_answered_sec, asDuration);
  delta("delay", tm.avg_wait_answered_sec, before.avg_wait_answered_sec, { goodWhen: "down", label });
  sub("delay", `longest ${duration(tm.longest_wait_answered_sec)} · gave up after ${duration(tm.avg_wait_before_giving_up_sec)}`);
  countTo(value("hold"), tm.avg_hold_sec, asDuration);
  sub("hold", `${tm.calls_put_on_hold} calls put on hold`);
  countTo(value("talk"), tm.avg_talk_sec, asDuration);
  delta("talk", tm.avg_talk_sec, before.avg_talk_sec, { label });

  if (rj) {
    countTo(value("rejection"), rj.rejected_or_missed);
    sub("rejection", `of ${rj.offered} rings · avg ${duration(rj.avg_ring_before_reject_sec)} ringing`);
  } else {
    countTo(value("rejection"), "–");
    sub("rejection", "no agent offer data yet");
  }
}

// Which list of calls each series of the hourly chart opens
const HOUR_KINDS = ["answered_in", "unanswered_in", "outbound"];

function renderChart(hourly) {
  // Working hours (8–18), plus any other hour that had calls
  shownHours = hourly.filter((h) => h.inbound + h.outbound > 0 || (h.hour >= 8 && h.hour <= 18));
  const hours = shownHours;
  drawChart("hourly-chart", (c) => ({
    type: "bar",
    data: {
      labels: hours.map((h) => hourLabel(h.hour)),
      datasets: [
        // Same `stack` name = drawn on top of each other in one bar
        { label: "Answered (in)", data: hours.map((h) => h.answered), backgroundColor: c.answered, stack: "in" },
        { label: "Unanswered (in)", data: hours.map((h) => h.unanswered), backgroundColor: c.unanswered, stack: "in" },
        { label: "Calls out", data: hours.map((h) => h.outbound), backgroundColor: c.connected, stack: "out" },
      ].map((d) => ({ ...d, ...barStyle(c) })),
    },
    options: stackedBarOptions(),
  }), ({ datasetIndex, index }) => {
    const kind = HOUR_KINDS[datasetIndex];
    openDrill({ title: KIND_TITLES[kind], params: { ...filterParams(), kind, hour: shownHours[index].hour } });
  });
}

// "Call outcomes": every call in the period, by what happened to it, as a ring with the total in the middle
// and a key with each count and its share. A piece opens those calls; "Other (in)" has no list of its own.
const OUTCOME_KINDS = ["answered_in", "unanswered_in", null, "connected", "not_connected"];

function renderOutcomes(t) {
  const parts = (c) => [
    { label: "Answered in", value: t.answered_inbound, colour: c.answered },
    { label: "Unanswered in", value: t.inbound - t.answered_inbound - t.other_inbound, colour: c.unanswered },
    { label: "Other in", value: t.other_inbound, colour: c.other },
    { label: "Connected out", value: t.answered_outbound, colour: c.connected },
    { label: "Not connected", value: t.outbound - t.answered_outbound, colour: c.notConnected },
  ];
  drawChart("outcome-chart", (c) => {
    const items = parts(c);
    ringLegend("outcome-legend", items.filter((p, i) => p.value > 0 || i !== 2)); // "Other" only when there are some
    return {
      type: "doughnut",
      data: {
        labels: items.map((p) => p.label),
        datasets: [{ data: items.map((p) => p.value), backgroundColor: items.map((p) => p.colour), ...ringStyle() }],
      },
      options: {
        cutout: "66%",
        interaction: { mode: "nearest", intersect: true },
        plugins: { legend: { display: false }, centreText: { value: t.calls, label: "calls" } },
      },
    };
  }, ({ index }) => {
    const kind = OUTCOME_KINDS[index];
    if (kind) openDrill({ title: KIND_TITLES[kind], params: { ...filterParams(), kind } });
  });
}

function renderAgents(agents) {
  const changed = fillRank("overview-rank", agents, {
    value: (a) => a.answered,
    hint: (a) => `${a.answered} answered · ${duration(a.avg_talk_sec)} average talk · click to see their calls`,
    emptyText: "No answered calls in this period",
  });
  if (changed) growBars(document.getElementById("overview-rank"));
}

export async function load(urls) {
  setStatus(panel, "Loading…");
  try {
    const m = await getJSON(urls.metrics, new FormData(form));
    renderTiles(m);
    renderAgents(m.agents);
    renderChart(m.hourly);
    renderOutcomes(m.totals);
    showSyncInfo(m);
    setStatus(panel, `Updated ${clock(new Date())}`);
  } catch (err) {
    setStatus(panel, `Could not load: ${err.message}`, { error: true });
  }
}

// Tiles and the top-agents list open their calls
wireTiles(panel, filterParams);
wireAgentRows(document.getElementById("overview-rank"), filterParams, "answered");

export const filters = form;
