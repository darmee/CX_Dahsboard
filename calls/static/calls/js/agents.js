/*
 * Agents page: who calls the most, and who receives the most, over any period (a day, a week, a month...).
 *
 * Asks our server: GET /api/agents/?from=...&to=..., then draws:
 *   - five tiles: the top caller, the top receiver, calls made, calls received, missed rings,
 *   - the leaderboard (the main thing on the page): every agent's numbers, most calls handled first,
 *   - "Who calls the most": one sideways bar per agent (connected / not connected), most calls first,
 *   - "Who receives the most": calls in answered, and rings missed, most first.
 * Clicking a tile, a row or a bar opens the calls behind it (js/drill.js).
 * Agents appear under the staff name set in Admin -> Agents (or HoduCC's name until you set one).
 */
import { barStyle, drawChart, stackedBarOptions } from "./charts.js";
import { KIND_TITLES, openDrill, wireAgentRows, wireTiles } from "./drill.js";
import {
  cell, cellBar, clock, duration, fillTable, getJSON, percent, personCell, setStatus, setText, showSyncInfo,
} from "./format.js";
import { countTo } from "./fx.js";

const panel = document.getElementById("panel-agents");
const form = document.getElementById("agents-filters");
let latest = []; // the agents last shown, for the tiles that open one agent's calls

// The filters as they are now, for the drill-down
const filterParams = () => ({ from: form.elements.from.value, to: form.elements.to.value });

function sum(agents, field) {
  return agents.reduce((total, a) => total + a[field], 0);
}

// The agent with the most of `field` (null if nobody has any).
function top(agents, field) {
  const best = [...agents].sort((a, b) => b[field] - a[field])[0];
  return best && best[field] > 0 ? best : null;
}

function renderTiles(agents) {
  const value = (name) => panel.querySelector(`[data-agents="${name}"]`);
  const sub = (name, text) => setText(panel, `[data-agents-sub="${name}"]`, text);

  const caller = top(agents, "made");
  countTo(value("top_caller"), caller ? caller.name : "–");
  value("top_caller").title = caller ? caller.name : "";
  sub("top_caller", caller ? `${caller.made} calls made · ${percent(caller.connect_ratio_pct)} connected` : "no calls made");

  const receiver = top(agents, "received");
  countTo(value("top_receiver"), receiver ? receiver.name : "–");
  value("top_receiver").title = receiver ? receiver.name : "";
  sub("top_receiver", receiver ? `${receiver.received} calls answered` : "no calls received");

  const made = sum(agents, "made"), connected = sum(agents, "answered_out");
  countTo(value("made"), made);
  const rate = made ? percent(Math.round((connected / made) * 1000) / 10) : "";
  sub("made", made ? `${connected} connected · ${made - connected} not · ${rate}` : "none in this period");
  countTo(value("received"), sum(agents, "received"));
  countTo(value("missed_rings"), sum(agents, "missed_rings"));
  const working = agents.filter((a) => a.handled + a.not_connected_out > 0).length;
  sub("working", `${working} of ${agents.length} agents worked`);
}

// The leaderboard: the rank (top three in the brand colour), the agent, and their numbers, with small bars
// for calls made and received so the order shows at a glance. A row opens that agent's calls.
function renderLeaderboard(agents) {
  const mostMade = Math.max(0, ...agents.map((a) => a.made));
  const mostReceived = Math.max(0, ...agents.map((a) => a.received));
  fillTable("leaderboard", agents, (a) => {
    const rank = agents.indexOf(a) + 1;
    const medal = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = rank <= 3 && a.handled ? "medal top" : "medal";
    badge.textContent = rank;
    medal.appendChild(badge);
    return [
      medal,
      personCell(a.name, a.agent, { oneLine: true }),
      cellBar(a.made, mostMade, "out"),
      cell(`${a.answered_out} · ${percent(a.connect_ratio_pct)}`), // connected, and the connect rate
      cellBar(a.received, mostReceived, "in"),
      cell(a.missed_rings, a.missed_rings ? "pill unanswered" : undefined),
      cell(duration(a.talk_sec)),
      cell(duration(a.avg_talk_sec)),
    ];
  }, "No agents yet. They appear after the first sync with HoduCC.", { byAgent: true });
}

// One sideways stacked bar per agent, most first, with a number written at the end of each bar.
// `kinds[datasetIndex]` is the list of calls a click on that piece opens (null: nothing to list).
function rankingChart(canvasId, rows, total, parts, kinds) {
  const labels = rows.map(total);
  // Room on the right for the longest of those numbers (about 7px a character)
  const room = Math.max(30, ...labels.map((l) => String(l).length * 7 + 14));
  drawChart(canvasId, (c) => ({
    type: "bar",
    data: {
      labels: rows.map((a) => a.name),
      datasets: parts(c).map((d) => ({ ...d, ...barStyle(c, { horizontal: true }) })),
    },
    options: {
      ...stackedBarOptions({ horizontal: true }),
      layout: { padding: { right: room } },
      // The key is in the card's header (dashboard.html), so the bars get the room
      plugins: { legend: { display: false }, endLabels: { values: labels } },
    },
  }), ({ datasetIndex, index }) => {
    const kind = kinds[datasetIndex];
    if (!kind) return;
    const agent = rows[index];
    openDrill({ title: `${KIND_TITLES[kind]} · ${agent.name}`, params: { ...filterParams(), kind, agent: agent.agent } });
  });
}

function renderMade(agents) {
  const rows = agents.filter((a) => a.made > 0).sort((a, b) => b.made - a.made);
  rankingChart("made-chart", rows, (a) => a.made, (c) => [
    { label: "Connected", data: rows.map((a) => a.answered_out), backgroundColor: c.connected },
    { label: "Not connected", data: rows.map((a) => a.not_connected_out), backgroundColor: c.notConnected },
  ], ["connected", "not_connected"]);
}

function renderReceived(agents) {
  const rows = agents.filter((a) => a.received + a.missed_rings > 0).sort((a, b) => b.received - a.received);
  // The number at the end of each bar is calls answered, with the rings missed after it
  const label = (a) => (a.missed_rings ? `${a.received} · ${a.missed_rings} missed` : a.received);
  rankingChart("received-chart", rows, label, (c) => [
    { label: "Answered", data: rows.map((a) => a.received), backgroundColor: c.answered },
    { label: "Rings missed", data: rows.map((a) => a.missed_rings), backgroundColor: c.unanswered },
  ], ["answered_in", "rejected"]); // a missed ring opens the rings they didn't take
}

export async function load(urls) {
  setStatus(panel, "Loading…");
  try {
    const data = await getJSON(urls.agents, new FormData(form));
    latest = data.agents;
    renderTiles(data.agents);
    renderLeaderboard(data.agents);
    renderMade(data.agents);
    renderReceived(data.agents);
    showSyncInfo(data);
    setStatus(panel, `Updated ${clock(new Date())}`);
  } catch (err) {
    setStatus(panel, `Could not load: ${err.message}`, { error: true });
  }
}

// Tiles open their calls; "Top caller" and "Top receiver" open that agent's
wireTiles(panel, filterParams, {
  agentFor: (tile) => {
    const field = { top_caller: "made", top_receiver: "received" }[tile.dataset.drillAgent];
    if (!field) return undefined; // a tile about everyone
    const best = top(latest, field);
    return best ? { agent: best.agent, name: best.name } : null;
  },
});
wireAgentRows(document.getElementById("leaderboard"), filterParams);

export const filters = form;
