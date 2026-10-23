/*
 * Agent detail page: one agent over a date range.
 *
 * Asks our server: GET /api/agent/?agent=Agent01&from=2026-10-01&to=2026-10-18, then draws:
 *   - six tiles (calls handled, made, received, connect rate, missed rings, average talk),
 *   - "Calls per day": one bar per day, split into answered in / connected out / not connected,
 *   - the agent's latest calls.
 * Clicking a tile or a day's bar opens the agent's calls behind it (js/drill.js).
 */
import { barStyle, drawChart, stackedBarOptions } from "./charts.js";
import { KIND_TITLES, openDrill, wireTiles } from "./drill.js";
import {
  cell, clock, directionCell, duration, fillTable, getJSON, setStatus, setText, shortDateTime, showSyncInfo, statusCell,
} from "./format.js";
import { countTo } from "./fx.js";

const panel = document.getElementById("panel-agent");
const form = document.getElementById("agent-filters");
let shownDays = []; // the days on the chart, so a clicked bar knows its day

// The filters as they are now (agent and dates), for the drill-down
const filterParams = () => ({ from: form.elements.from.value, to: form.elements.to.value, agent: form.elements.agent.value });
const agentName = () => form.elements.agent.selectedOptions[0]?.textContent || "";

function renderTiles(t) {
  const value = (name) => panel.querySelector(`[data-agent="${name}"]`);
  const sub = (name, text) => setText(panel, `[data-agent-sub="${name}"]`, text);
  const made = t.answered_out + t.not_connected_out;
  countTo(value("handled"), t.handled);
  sub("handled", `${t.answered_in} in · ${t.answered_out} out`);
  countTo(value("made"), made);
  sub("made", `${t.answered_out} connected · ${t.not_connected_out} not`);
  countTo(value("answered_in"), t.answered_in);
  countTo(value("connect"), t.connect_ratio_pct, (n) => `${n.toFixed(1)}%`);
  countTo(value("missed_rings"), t.missed_rings);
  countTo(value("avg_talk"), t.avg_talk_sec, (n) => duration(Math.round(n)));
  sub("talk", `${duration(t.talk_sec)} talking in all`);
}

// "2026-10-05" -> "5 Oct"
function dayLabel(iso) {
  return new Date(`${iso}T00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

// Which list of calls each series opens
const DAY_KINDS = ["answered_in", "connected", "not_connected"];

function renderChart(days) {
  shownDays = days;
  drawChart("agent-days-chart", (c) => ({
    type: "bar",
    data: {
      labels: days.map((d) => dayLabel(d.date)),
      datasets: [
        { label: "Answered (in)", data: days.map((d) => d.answered_in), backgroundColor: c.answered },
        { label: "Connected (out)", data: days.map((d) => d.answered_out), backgroundColor: c.connected },
        { label: "Not connected (out)", data: days.map((d) => d.not_connected_out), backgroundColor: c.notConnected },
      ].map((d) => ({ ...d, ...barStyle(c) })),
    },
    options: stackedBarOptions(),
  }), ({ datasetIndex, index }) => {
    const kind = DAY_KINDS[datasetIndex];
    const day = shownDays[index].date;
    openDrill({ title: `${KIND_TITLES[kind]} · ${agentName()}`, params: { ...filterParams(), from: day, to: day, kind } });
  });
}

function renderCalls(calls) {
  fillTable("agent-calls", calls, (c) => [
    cell(shortDateTime(c.started_at)),
    directionCell(c.direction, { short: true }),
    statusCell(c.status),
    cell(duration(c.talk_seconds)),
  ], "No calls in this period");
}

export async function load(urls) {
  const params = new FormData(form);
  if (!params.get("agent")) {
    setStatus(panel, "No agents yet. They appear after the first sync with HoduCC.");
    return;
  }
  setStatus(panel, "Loading…");
  try {
    const data = await getJSON(urls.agent, params);
    renderTiles(data.totals);
    renderChart(data.days);
    renderCalls(data.recent);
    showSyncInfo(data);
    // Just the time: the agent is in the drop-down already, and this row has little room left
    setStatus(panel, `Updated ${clock(new Date())}`);
  } catch (err) {
    setStatus(panel, `Could not load: ${err.message}`, { error: true });
  }
}

// Tiles open this agent's calls
wireTiles(panel, filterParams, { agentFor: () => ({ agent: form.elements.agent.value, name: agentName() }) });

export const filters = form;
