/*
 * Daily activity page: the tables for one day.
 *   - "Agents": every agent's numbers that day, busiest first (a row opens that agent's calls),
 *   - "Call log": every call that day, newest first: the customer (last 4 digits), in or out, the status,
 *     why it ended (HoduCC's reason), the agent, the queue and the wait, talk and hold times.
 * Asks our server: GET /api/agents/?date=YYYY-MM-DD (the same answer the Agents page draws as charts).
 */
import { wireAgentRows } from "./drill.js";
import {
  agentCell, cell, clock, directionCell, duration, fillTable, getJSON, personCell, reasonText, setStatus, showSyncInfo,
  statusCell,
} from "./format.js";

const panel = document.getElementById("panel-activity");
const form = document.getElementById("activity-filters");

// The day chosen, for the drill-down
const filterParams = () => ({ from: form.elements.date.value, to: form.elements.date.value });

// The agents table sits beside the call log, so it keeps the columns that matter most. Hovering a name
// shows their login and team; hovering the talk time shows the average talk and hold time.
function renderAgents(agents) {
  fillTable("agent-activity", agents, (a) => {
    const person = personCell(a.name, a.agent, { oneLine: true });
    if (a.team) person.querySelector(".person").title = `${a.agent} · ${a.team} team`;
    const talk = cell(duration(a.talk_sec));
    talk.title = `${duration(a.avg_talk_sec)} average talk · ${duration(a.hold_sec)} on hold`;
    return [
      person,
      cell(a.answered_in),
      cell(a.answered_out),
      cell(a.not_connected_out),
      cell(a.missed_rings, a.missed_rings ? "pill unanswered" : undefined),
      talk,
      cell(a.first_call ? `${clock(a.first_call)}–${clock(a.last_call)}` : "–"), // first to last call
    ];
  }, "No agents yet. They appear after the first sync with HoduCC.", { byAgent: true });
}

function renderLog(calls) {
  fillTable("call-log", calls, (c) => [
    cell(clock(c.started_at)),
    cell(c.caller_masked || "–"),
    directionCell(c.direction, { short: true }),
    statusCell(c.status),
    cell(reasonText(c.hangup_reason), "reason"),
    agentCell(c), // "Rang Amina" or "Not answered" when nobody took the call
    cell(duration(c.wait_seconds)),
    cell(duration(c.talk_seconds)),
  ], "No calls that day");
}

export async function load(urls) {
  setStatus(panel, "Loading…");
  try {
    const data = await getJSON(urls.agents, new FormData(form));
    renderAgents(data.agents);
    renderLog(data.recent);
    showSyncInfo(data);
    // If the day had more calls than the log can hold, say the log is only the latest of them
    const shown = data.recent.length < data.calls_total ? `latest ${data.recent.length} of ` : "";
    setStatus(panel, `${shown}${data.calls_total} calls · ${clock(new Date())}`);
  } catch (err) {
    setStatus(panel, `Could not load: ${err.message}`, { error: true });
  }
}

// A row in the agents table opens that agent's calls that day
wireAgentRows(document.getElementById("agent-activity"), filterParams);

export const filters = form;
