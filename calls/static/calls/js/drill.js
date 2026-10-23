/*
 * The drill-down: the calls behind a number, in a panel that slides in from the right.
 *
 * A tile with data-drill="kind", a bar in a chart, or an agent's row can open it. It asks our server
 *   GET /api/calls/?from=...&to=...&kind=...&queue=...&agent=...&hour=...   (views.calls_api)
 * and lists the calls: when, the customer (only the last 4 digits are ever kept: •••2698), in or out,
 * the status, why the call ended (HoduCC's reason), the agent, and the wait, talk and hold times.
 * Above the list: how many calls there are, the most common reasons, and who hung up.
 * The Rejections tile and the missed-rings numbers open a list of *rings* instead (kind "rejected"):
 *   GET /api/rings/?from=...&to=...&queue=...&agent=...   (views.rings_api)
 * each with the agent it rang, for how long, why it stopped, and how the call ended (and who took it).
 * Close it with the ×, the Esc key, or a click beside it.
 */
import {
  agentCell, cell, clock, config, directionCell, duration, fillTable, getJSON, reasonText, shortDateTime, statusCell,
} from "./format.js";

const motion = window.Motion;
const calm = !motion || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const drawer = document.getElementById("drawer");
const backdrop = document.querySelector(".drawer-backdrop");
const text = (id, value) => { document.getElementById(id).textContent = value; };
let opener = null; // what had the keyboard focus before the panel opened, to give it back afterwards

// What each list is called (the `kind` names come from metrics.CALL_KINDS)
export const KIND_TITLES = {
  all: "All calls",
  inbound: "Calls in",
  outbound: "Calls out",
  answered: "Calls answered",
  answered_in: "Calls in answered",
  unanswered: "Unanswered calls",
  unanswered_in: "Calls in unanswered",
  connected: "Calls out connected",
  not_connected: "Calls out not connected",
  held: "Calls put on hold",
  rejected: "Missed rings", // not calls but rings: see RING_COLUMNS
};

// The table's columns: for calls, and for rings
const CALL_COLUMNS = ["Time", "Customer", "In/Out", "Status", "Why it ended", "Agent", "Wait", "Talk", "Hold"];
const RING_COLUMNS = ["Time", "Agent rung", "Rang for", "Why it stopped", "Customer", "In/Out", "Call ended", "Answered by"];

// A sentence explaining the list, for the lists that need one
const NOTES = {
  not_connected: "Not connected means the customer never picked up: no answer, busy, phone switched off, or the "
    + "line failed. HoduCC records these calls with the status DIAL. “Why it ended” gives HoduCC's reason for each.",
  outbound: "Connected: the customer picked up. Not connected: no answer, busy, switched off or the line failed "
    + "(HoduCC's status DIAL). “Why it ended” gives HoduCC's reason for each call.",
  unanswered: "Calls where the caller gave up waiting (ABANDONED) or the call was cut off (DROPPED) before an agent answered.",
  unanswered_in: "Calls in where the caller gave up waiting (ABANDONED) or the call was cut off (DROPPED) before an agent answered.",
  rejected: "Each line is one time a call rang an agent who didn't pick up: they declined it, didn't answer before "
    + "HoduCC moved it on (RECOVERY_ON_TIMER_EXPIRE, NO_ANSWER), or the caller hung up while it rang "
    + "(ORIGINATOR_CANCEL). “Answered by” shows whether someone else took the call in the end.",
};

// Who hung up, in words
const ENDED_BY = { AGENT: "agent hung up", USER: "customer hung up", SYSTEM: "system or network" };

// "2026-10-18" -> "Sunday 18 October 2026"; a range -> "1 Oct – 18 Oct 2026"
function periodText(from, to) {
  const day = (iso, options) => new Date(`${iso}T00:00`).toLocaleDateString("en-GB", options);
  if (from === to) return day(from, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  return `${day(from, { day: "numeric", month: "short" })} – ${day(to, { day: "numeric", month: "short", year: "numeric" })}`;
}

// The small rounded chips above the list: "Normal clearing 31", "customer hung up 12"
function chips(items) {
  const box = document.getElementById("drawer-reasons");
  box.replaceChildren();
  for (const { label, count } of items) {
    const chip = document.createElement("span");
    chip.className = "chip";
    const number = document.createElement("b");
    number.textContent = count;
    chip.append(label, " ", number);
    box.appendChild(chip);
  }
}

// Put the column titles in the table's header
function setColumns(names) {
  const row = document.getElementById("drawer-columns");
  row.replaceChildren(...names.map((name) => {
    const th = document.createElement("th");
    th.textContent = name;
    return th;
  }));
}

function show() {
  drawer.hidden = false;
  backdrop.hidden = false;
  if (!calm) {
    motion.animate(drawer, { x: ["100%", "0%"] }, { duration: 0.45, ease: [0.22, 1, 0.36, 1] });
    motion.animate(backdrop, { opacity: [0, 1] }, { duration: 0.3 });
  }
  drawer.querySelector("[data-drawer-close]").focus();
}

// Close the panel (also used when another page is opened)
export async function closeDrill() {
  if (drawer.hidden) return;
  if (!calm) {
    motion.animate(backdrop, { opacity: 0 }, { duration: 0.25 });
    await motion.animate(drawer, { x: "100%" }, { duration: 0.3, ease: [0.4, 0, 1, 1] });
  }
  drawer.hidden = true;
  backdrop.hidden = true;
  opener?.focus?.();
}

// Open the panel with the calls matching `params` ({ from, to, kind, queue?, agent?, hour? }).
export async function openDrill({ title, params }) {
  opener = document.activeElement;
  const to = params.to || params.from;
  const hour = params.hour !== undefined ? ` · ${String(params.hour).padStart(2, "0")}:00–${String(params.hour + 1).padStart(2, "0")}:00` : "";
  text("drawer-kicker", `${periodText(params.from, to)}${hour}`);
  text("drawer-title", title);
  text("drawer-sub", "Loading…");
  const note = document.getElementById("drawer-note");
  note.hidden = !NOTES[params.kind];
  note.textContent = NOTES[params.kind] || "";
  chips([]);
  const rings = params.kind === "rejected"; // a list of rings, not calls
  setColumns(rings ? RING_COLUMNS : CALL_COLUMNS);
  document.getElementById("drawer-calls").replaceChildren();
  show();

  // Only the filters that are set go into the address
  const query = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""));
  try {
    const data = await getJSON(rings ? config.urls.rings : config.urls.calls, query);
    const list = rings ? data.rings : data.calls;
    const word = rings ? "missed ring" : "call";
    const many = `${data.total} ${word}${data.total === 1 ? "" : "s"}`;
    text("drawer-sub", list.length < data.total ? `${many} · showing the latest ${list.length}` : many);
    chips([
      ...data.reasons.filter((r) => r.reason).map((r) => ({ label: reasonText(r.reason), count: r.count })),
      ...(data.ended_by || []).filter((e) => ENDED_BY[e.by]).map((e) => ({ label: ENDED_BY[e.by], count: e.count })),
    ]);
    const oneDay = params.from === to;
    const when = (iso) => (oneDay ? clock(iso) : shortDateTime(iso));
    if (rings) {
      fillTable("drawer-calls", data.rings, (r) => [
        cell(when(r.offered_at)),
        cell(r.agent_name),
        cell(duration(r.ring_seconds)),
        cell(reasonText(r.hangup_reason), "reason"),
        cell(r.caller_masked || "–"),
        r.direction ? directionCell(r.direction, { short: true }) : cell("–"),
        r.call_status ? statusCell(r.call_status) : cell("–"),
        r.answered_by ? cell(r.answered_by) : agentCell({ direction: r.direction }),
      ], "No missed rings here");
      return;
    }
    fillTable("drawer-calls", data.calls, (c) => [
      cell(when(c.started_at)),
      cell(c.caller_masked || "–"),
      directionCell(c.direction, { short: true }),
      statusCell(c.status),
      cell(reasonText(c.hangup_reason), "reason"),
      agentCell(c),
      cell(duration(c.wait_seconds)),
      cell(duration(c.talk_seconds)),
      cell(duration(c.hold_seconds)),
    ], "No calls here");
  } catch (err) {
    text("drawer-sub", `Could not load: ${err.message}`);
  }
}

// Make every tile with data-drill in `panel` open its list. `params()` gives the page's current filters;
// `agentFor(tile)`, if given, picks the agent for tiles like "Top caller" ({ agent, name }, or null for none).
export function wireTiles(panel, params, { agentFor } = {}) {
  for (const tile of panel.querySelectorAll("[data-drill]")) {
    tile.tabIndex = 0;
    tile.setAttribute("role", "button");
    tile.setAttribute("aria-label", `${tile.querySelector("h3").textContent}: show the calls`);
    const hint = document.createElement("span");
    hint.className = "drill-hint";
    hint.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-chevron"></use></svg>'; // fixed markup, no data
    tile.appendChild(hint);
    const open = () => {
      const who = agentFor ? agentFor(tile) : undefined;
      if (who === null) return; // e.g. no top caller yet: nothing to list
      const kind = tile.dataset.drill;
      openDrill({
        title: who ? `${KIND_TITLES[kind]} · ${who.name}` : KIND_TITLES[kind],
        params: { ...params(), kind, ...(who ? { agent: who.agent } : {}) },
      });
    };
    tile.addEventListener("click", open);
    tile.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
  }
}

// In `container`, every row marked with data-agent (see format.agentRow) opens that agent's calls of `kind`.
export function wireAgentRows(container, params, kind = "all") {
  const open = (row) => openDrill({
    title: `${KIND_TITLES[kind]} · ${row.dataset.name}`,
    params: { ...params(), kind, agent: row.dataset.agent },
  });
  container.addEventListener("click", (event) => {
    const row = event.target.closest("[data-agent]");
    if (row) open(row);
  });
  container.addEventListener("keydown", (event) => {
    const row = event.target.closest("[data-agent]");
    if (row && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      open(row);
    }
  });
}

for (const closer of document.querySelectorAll("[data-drawer-close]")) closer.addEventListener("click", closeDrill);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrill(); });
