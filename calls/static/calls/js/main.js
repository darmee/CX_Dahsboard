/*
 * The page's starting point (loaded with <script type="module"> in dashboard.html).
 *
 * - Switches between the six pages in the sidebar (Overview, Agents, Agent detail, Daily activity,
 *   Monthly, Live): the white pill slides to the open page, the page's name changes at the top, the page
 *   rises into view and its charts grow. The open page is remembered in the address (#monthly).
 * - Loads the open page, then refreshes it every 30 s. While new numbers load, the old ones stay, faded.
 * - The "Live" strip at the top has its own clock: straight from HoduCC every 15 s, on every page.
 * - Nothing refreshes while the browser tab is hidden, and everything refreshes when it comes back.
 * - The sun / moon button switches between light and dark mode (js/theme.js).
 * (Each page's own file makes its tiles, bars and rows open the calls behind them: js/drill.js.)
 *
 * It never talks to HoduCC directly; the token stays on the server.
 */
import * as activity from "./activity.js";
import * as agent from "./agent.js";
import * as agents from "./agents.js";
import { replayCharts } from "./charts.js";
import { closeDrill } from "./drill.js";
import { config, showStatus, wirePresets } from "./format.js";
import { enterPanel, moveIndicator, smoothScrolling, swapTitle } from "./fx.js";
import * as live from "./live.js";
import * as monthly from "./monthly.js";
import * as overview from "./overview.js";
import { wireThemeToggle } from "./theme.js";

const tabs = [...document.querySelectorAll('[role="tab"]')];
const title = document.getElementById("page-title");
const indicator = document.querySelector(".nav-indicator");

// Page name -> how to load it. (The Live page is the strip's own update, with the page filled in too.)
const pages = { overview, agents, agent, activity, monthly };
const loaders = {
  ...Object.fromEntries(Object.entries(pages).map(([name, page]) => [name, () => page.load(config.urls)])),
  live: () => live.load(config.urls, true),
};

let current = null;
let pageTimer = null;
const visible = () => document.visibilityState === "visible";

// Reload the open page. Its old numbers stay, faded, until the new ones arrive.
function refresh() {
  if (!visible()) return;
  const panel = document.getElementById(`panel-${current}`);
  panel.classList.add("is-loading");
  Promise.resolve(loaders[current]()).finally(() => panel.classList.remove("is-loading"));
}

// The Live strip, on its own clock (every 15 s), whatever page is open.
function refreshLive() {
  if (visible()) live.load(config.urls, current === "live");
}

function open(name, { focus = false, first = false } = {}) {
  if (!loaders[name]) name = "overview";
  current = name;
  closeDrill(); // a list of calls belongs to the page it was opened from
  // Only the open page's filters show in the top bar (the Live page has none)
  for (const [pageName, page] of Object.entries(pages)) page.filters.hidden = pageName !== name;
  for (const tab of tabs) {
    const selected = tab.id === `tab-${name}`;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1; // only the open page's button is reachable with Tab; arrows move between them
    const panel = document.getElementById(tab.getAttribute("aria-controls"));
    panel.hidden = !selected;
    if (!selected) continue;
    swapTitle(title, tab.textContent.trim());
    moveIndicator(indicator, tab, { instant: first });
    enterPanel(panel);
    replayCharts(panel); // charts on a hidden page had no size; now they measure and grow again
    showStatus(panel); // its "Updated 14:05" line under the page's name
    if (focus) tab.focus();
  }
  history.replaceState(null, "", `#${name}`);
  refresh();
  clearInterval(pageTimer);
  // Live keeps to the strip's clock; every other page refreshes every 30 s
  if (name !== "live") pageTimer = setInterval(refresh, config.refreshSeconds * 1000);
}

const nameOf = (tab) => tab.id.replace("tab-", "");

for (const tab of tabs) {
  tab.addEventListener("click", () => open(nameOf(tab)));
  // Keyboard: the arrow keys move between the pages (up/down in the sidebar, left/right on a phone)
  tab.addEventListener("keydown", (event) => {
    const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    event.preventDefault(); // don't also scroll the page
    const next = tabs[(tabs.indexOf(tab) + step + tabs.length) % tabs.length];
    open(nameOf(next), { focus: true });
  });
}

// The filters: any change (a date, an agent, a queue) or a quick-date button ("This month") reloads the
// numbers straight away, without reloading the page. There is no Update button to press.
for (const [name, page] of Object.entries(pages)) {
  const reload = () => { if (current === name) refresh(); };
  page.filters.addEventListener("submit", (event) => {
    event.preventDefault(); // Enter in a box: stay on the page
    reload();
  });
  page.filters.addEventListener("change", (event) => {
    if (event.target.matches("input, select")) reload();
  });
  wirePresets(page.filters, reload);
}

// Full screen, for a screen on the wall: the button switches it on and off
document.querySelector("[data-fullscreen]").addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.();
});

// The sidebar folds to icons on narrower screens: put the white pill back under the open page's button.
window.addEventListener("resize", () => {
  const tab = document.getElementById(`tab-${current}`);
  if (tab) moveIndicator(indicator, tab, { instant: true });
});

document.addEventListener("visibilitychange", () => {
  refresh();
  if (current !== "live") refreshLive();
});
// A link or the Back button changing #overview / #monthly / ... opens that page
window.addEventListener("hashchange", () => {
  const name = location.hash.slice(1);
  if (name !== current) open(name);
});

wireThemeToggle(document.querySelector("[data-theme-toggle]"));
smoothScrolling();
open(location.hash.slice(1) || "overview", { first: true });
if (current !== "live") refreshLive();
setInterval(refreshLive, config.liveRefreshSeconds * 1000);
