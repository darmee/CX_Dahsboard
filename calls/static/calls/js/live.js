/*
 * The Live page, and the "Live" strip at the top of every page.
 *
 * Asks our server: GET /api/live/. The server asks HoduCC's realtime queue summary, at most once every
 * 15 seconds (HODU_LIVE_CACHE_SECONDS) however many screens are open. It returns:
 *   totals: waiting, on_calls, idle, logged_in, assigned, calls_today, answered_today, ...
 *   queues: the same numbers for each queue
 * HoduCC only gives counts; there is no list of the individual calls in progress.
 *
 * The strip shows a pulsing dot, "every 15 s", and a small ring that empties until the next update.
 */
import { drawChart, ringLegend, ringStyle } from "./charts.js";
import { cell, clock, config, count, duration, fillTable, getJSON, setStatus, setText } from "./format.js";
import { countTo } from "./fx.js";

const panel = document.getElementById("panel-live");
const strip = document.getElementById("live-strip");
const badge = strip.querySelector("[data-live-badge]");
const countdown = strip.querySelector(".countdown");
const every = config.liveRefreshSeconds;

// Restart the little ring: it empties over `every` seconds, until the next update.
function restartCountdown() {
  countdown.classList.remove("running");
  countdown.querySelector(".countdown-fill").style.animationDuration = `${every}s`;
  void countdown.getBoundingClientRect(); // makes the browser notice the restart
  countdown.classList.add("running");
}

function renderStrip(live) {
  strip.hidden = false;
  badge.classList.toggle("paused", !live.available);
  setText(badge, "[data-live-every]", live.available ? `${every} s` : "paused");
  badge.title = live.available
    ? `Live numbers straight from HoduCC, every ${every} seconds. The ring empties until the next update.`
    : `HoduCC's live numbers aren't available${live.error ? `: ${live.error}` : ""}. Trying again every ${every} seconds.`;
  // The numbers on the rail, on every page; "waiting" turns amber and pulses while callers wait
  for (const el of document.querySelectorAll("[data-live]")) countTo(el, live[el.dataset.live]);
  document.querySelector("[data-live-alert]").classList.toggle("alert", (live.waiting_now || 0) > 0);
  restartCountdown();
}

function renderTiles(t) {
  for (const el of panel.querySelectorAll("[data-live-total]")) countTo(el, t[el.dataset.liveTotal]);
  // Anyone waiting is worth noticing
  panel.querySelector('[data-live-total="waiting"]').className = t.waiting ? "value bad" : "value";
  setText(panel, '[data-live-sub="agents_total"]', `of ${t.agents_total} agents`);
  setText(panel, '[data-live-sub="calls_today"]', t.calls_today === null ? "" : `of ${t.calls_today} calls today`);
}

function renderQueues(queues) {
  fillTable("live-queues", queues, (q) => [
    cell(q.name),
    cell(count(q.waiting), q.waiting ? "pill unanswered" : undefined),
    cell(count(q.on_calls)),
    cell(count(q.idle)),
    cell(count(q.logged_in)),
    cell(count(q.assigned)),
    cell(count(q.calls_today)),
    cell(count(q.answered_today)),
    cell(count(q.abandoned_today)),
    cell(duration(q.avg_wait_sec)),
    cell(duration(q.avg_talk_sec)),
  ], "HoduCC reported no queues");
}

function renderAgentsChart(t) {
  // All our agents, split three ways. "Not logged in" = the rest.
  const notLoggedIn = Math.max(t.agents_total - (t.logged_in || 0), 0);
  const nobody = (t.on_calls || 0) + (t.idle || 0) + notLoggedIn === 0;
  panel.querySelector("[data-live-agents-note]").hidden = !nobody;
  drawChart("live-agents-chart", (c) => {
    const items = [
      { label: "On calls", value: t.on_calls || 0, colour: c.connected },
      { label: "Idle", value: t.idle || 0, colour: c.answered },
      { label: "Not logged in", value: notLoggedIn, colour: c.neutral },
    ];
    ringLegend("live-agents-legend", items); // the key beside the ring: each count and its share
    return {
      type: "doughnut",
      data: {
        labels: items.map((i) => i.label),
        datasets: [{ data: items.map((i) => i.value), backgroundColor: items.map((i) => i.colour), ...ringStyle() }],
      },
      options: {
        cutout: "66%",
        plugins: { legend: { display: false }, centreText: { value: t.agents_total, label: "agents" } },
      },
    };
  });
}

// Called on every page every `every` seconds (it fills the strip). `withPanel` also fills the Live page.
export async function load(urls, withPanel) {
  try {
    const live = await getJSON(urls.live);
    renderStrip(live);
    if (!withPanel) return;
    if (!live.available) {
      const why = live.error ? `HoduCC's live numbers aren't available: ${live.error}` : "HoduCC sent no live numbers.";
      setStatus(panel, why, { error: true });
      return;
    }
    renderTiles(live.totals);
    renderQueues(live.queues);
    renderAgentsChart(live.totals);
    setStatus(panel, `As of ${clock(live.as_of)} · from HoduCC every ${every} s`);
  } catch (err) {
    if (withPanel) setStatus(panel, `Could not load: ${err.message}`, { error: true });
  }
}
