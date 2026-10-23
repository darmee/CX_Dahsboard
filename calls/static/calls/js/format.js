/*
 * Small helpers every page uses: the page's settings, formatting numbers and times, filling tables and
 * ranked lists, the quick-date buttons, and fetching JSON.
 *
 * This is a JavaScript *module*: other files get these functions with
 *   import { duration } from "./format.js";
 * Only the things marked "export" can be imported.
 */

// The settings Django wrote into the page (API addresses, refresh times, today's date, the code version).
export const config = JSON.parse(document.getElementById("dashboard-config").textContent);

// 76 -> "1m 16s", 3725 -> "1h 2m". Missing -> "–".
export function duration(seconds) {
  if (seconds === null || seconds === undefined) return "–";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return m < 60 ? `${m}m ${s}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

// An ISO time -> "14:05", in the viewer's time zone. Missing -> "–".
export function clock(iso) {
  if (!iso) return "–";
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

// The time alone if it was today, otherwise the date too, so an old sync can't look fresh.
export function when(iso) {
  const d = new Date(iso);
  const today = d.toDateString() === new Date().toDateString();
  return today ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); // "18 Oct, 00:45"
}

// 9 -> "09:00"
export function hourLabel(hour) {
  return `${String(hour).padStart(2, "0")}:00`;
}

// A number, or "–" when there isn't one.
export function count(value) {
  return value === null || value === undefined ? "–" : String(value);
}

// 33.3 -> "33.3%". Missing (e.g. no calls to divide by) -> "–".
export function percent(value) {
  return value === null || value === undefined ? "–" : `${value}%`;
}

// An ISO time -> "18 Oct, 17:36", in the viewer's time zone.
export function shortDateTime(iso) {
  return new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

// HoduCC's hangup reason in words: "NORMAL_CLEARING" -> "Normal clearing", "USER_BUSY" -> "User busy".
// Nothing -> "–".
export function reasonText(reason) {
  if (!reason) return "–";
  const words = reason.replace(/_/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// "2026-10" -> "Oct 2026"
export function monthLabel(month) {
  const [year, number] = month.split("-").map(Number);
  return new Date(year, number - 1, 1).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
}

// Put text into the element matching `selector` inside `root`.
// textContent (never innerHTML) means data from the server can never run as code.
// className, if given, replaces the element's classes (used to colour tiles good/bad).
export function setText(root, selector, text, className) {
  const el = root.querySelector(selector);
  if (!el) return;
  el.textContent = text;
  if (el.classList.contains("sub")) el.title = text; // a tile's line is cut to fit: hovering shows all of it
  if (className !== undefined) el.className = className;
}

/*
 * The line under the page's name in the top bar: "Updated 14:05", or why loading failed.
 * Each page keeps its own (in panel.dataset); the line shows the open page's. main.js calls showStatus
 * when a page opens.
 */
export function setStatus(panel, text, { error = false } = {}) {
  panel.dataset.status = text;
  panel.dataset.statusError = error ? "1" : "";
  if (!panel.hidden) showStatus(panel);
}

export function showStatus(panel) {
  const line = document.getElementById("page-status");
  line.textContent = panel.dataset.status || "";
  line.classList.toggle("error", panel.dataset.statusError === "1");
}

// One table cell. With pillClass, the text sits in a coloured pill (e.g. "Answered").
export function cell(text, pillClass) {
  const td = document.createElement("td");
  if (pillClass) {
    const span = document.createElement("span");
    span.className = pillClass;
    span.textContent = text;
    td.appendChild(span);
  } else {
    td.textContent = text;
  }
  return td;
}

// "Ada Okafor" -> "AO", "Agent01" -> "A"
function initials(name) {
  const words = String(name).split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase() || "?";
}

// A round badge with someone's initials.
function avatar(name) {
  const badge = document.createElement("span");
  badge.className = "avatar";
  badge.setAttribute("aria-hidden", "true");
  badge.textContent = initials(name);
  return badge;
}

// A person: a round badge with their initials, their name, and (if it is different) their login under it.
// With oneLine: true, the login shows on hover instead, keeping the row low (the leaderboard).
export function personCell(name, login, { oneLine = false } = {}) {
  const td = document.createElement("td");
  const person = document.createElement("span");
  person.className = "person";
  const text = document.createElement("span");
  text.textContent = name;
  if (login && login !== name && oneLine) {
    person.title = login;
  } else if (login && login !== name) {
    const small = document.createElement("span");
    small.className = "person-login";
    small.textContent = login;
    text.appendChild(small);
  }
  person.append(avatar(name), text);
  td.appendChild(person);
  return td;
}

// "INBOUND" -> a phone icon and "Inbound". With short: true (narrow tables), the icon alone; the word is
// still there for screen readers and on hover.
export function directionCell(direction, { short = false } = {}) {
  const td = document.createElement("td");
  const span = document.createElement("span");
  span.className = "direction";
  const inbound = direction === "INBOUND";
  const word = direction.charAt(0) + direction.slice(1).toLowerCase();
  span.innerHTML = `<svg class="icon" aria-hidden="true"><use href="#i-phone-${inbound ? "in" : "out"}"></use></svg>`; // fixed markup, no data
  const text = document.createElement("span");
  text.textContent = word; // textContent adds text, never HTML
  if (short) {
    text.className = "sr-only";
    span.title = word;
  }
  span.appendChild(text);
  td.appendChild(span);
  return td;
}

// A call's status in a coloured pill: "Answered" (green), abandoned or dropped (red), anything else (grey).
export function statusCell(status) {
  const answered = status === "AGENT";
  const unanswered = status === "ABANDONED" || status === "DROPPED";
  const pill = answered ? "pill answered" : unanswered ? "pill unanswered" : "pill other";
  return cell(answered ? "Answered" : status === "DIAL" ? "Not connected" : status, pill);
}

// A call's agent. A call in that nobody took has none (the caller hung up first, so HoduCC names no agent):
// then who it rang before the caller hung up ("Rang Amina"), or "Not answered" if it never reached an agent.
export function agentCell(call) {
  if (call.agent_name) return cell(call.agent_name);
  const rang = call.rang || [];
  // "Rang Amina", or "Rang Amina +1" when it rang more agents (all of them show on hover), so the column stays narrow
  const who = rang.length > 1 ? `${rang[0]} +${rang.length - 1}` : rang[0];
  const td = cell(rang.length ? `Rang ${who}` : call.direction === "INBOUND" ? "Not answered" : "No agent");
  td.className = "nobody";
  td.title = rang.length
    ? `Nobody answered: it rang ${rang.join(", ")}, and the caller hung up before it was picked up.`
    : "Nobody answered: the caller hung up while waiting in the queue, before it rang any agent.";
  return td;
}

// An answer from the server without the list we need (e.g. the server is still running older code).
function missingData() {
  return new Error("the server's answer was missing data. Reload the page; if it keeps happening, restart the server.");
}

// Mark a table row or list item as one agent's: clicking it (or Enter) opens their calls (js/drill.js).
export function agentRow(element, row) {
  element.dataset.agent = row.agent;
  element.dataset.name = row.name;
  element.tabIndex = 0;
  element.title = `${row.name}: show their calls`;
}

// A number with a small bar under it, as long as its share of `top` (`bar`: "in" plum, "out" teal).
export function cellBar(value, top, bar = "in") {
  const td = document.createElement("td");
  const box = document.createElement("span");
  box.className = "cell-bar";
  const track = document.createElement("span");
  track.className = "bar";
  const fill = document.createElement("i");
  fill.className = bar;
  fill.style.width = `${top ? (value / top) * 100 : 0}%`;
  track.appendChild(fill);
  box.append(value.toLocaleString("en-GB"), track);
  td.appendChild(box);
  return td;
}

// Replace a table body's rows. toCells(row) returns the <td>s for one row.
// With `byAgent: true`, each row is an agent's (row.agent, row.name) and opens their calls when clicked.
export function fillTable(tbodyId, rows, toCells, emptyText, { byAgent = false } = {}) {
  if (!Array.isArray(rows)) throw missingData();
  const tbody = document.getElementById(tbodyId);
  tbody.replaceChildren();
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = cell(emptyText);
    td.colSpan = tbody.closest("table").querySelectorAll("thead th").length;
    td.className = "empty";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    toCells(row).forEach((td) => tr.appendChild(td));
    if (byAgent) agentRow(tr, row);
    tbody.appendChild(tr);
  }
}

// A ranked list (<ol class="rank">): number, initials, name with a bar under it, and the count.
// Only people with a count above 0, biggest first. `value(row)` is the count; `hint(row)` shows on hover;
// `bar` is "in" (plum) or "out" (teal). Each row opens that agent's calls (agentRow).
// Returns true if the list changed (so its bars can grow again).
export function fillRank(listId, rows, { value, hint, bar = "in", emptyText, limit = 50 }) {
  if (!Array.isArray(rows)) throw missingData();
  const list = document.getElementById(listId);
  const items = rows.filter((r) => value(r) > 0).sort((a, b) => value(b) - value(a)).slice(0, limit);
  const key = JSON.stringify(items.map((r) => [r.name, value(r)]));
  if (list._key === key) return false;
  list._key = key;
  list.replaceChildren();
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = emptyText;
    list.appendChild(li);
    return true;
  }
  const top = value(items[0]);
  items.forEach((row, i) => {
    const li = document.createElement("li");
    if (row.agent) agentRow(li, row);
    if (hint) li.title = hint(row);
    const no = document.createElement("span");
    no.className = "no";
    no.textContent = i + 1;
    const who = document.createElement("span");
    who.className = "who";
    const name = document.createElement("b");
    name.textContent = row.name;
    const track = document.createElement("span");
    track.className = "bar";
    const fill = document.createElement("i");
    fill.className = bar;
    fill.style.width = `${(value(row) / top) * 100}%`;
    track.appendChild(fill);
    who.append(name, track);
    const total = document.createElement("span");
    total.className = "count";
    total.textContent = value(row).toLocaleString("en-GB");
    li.append(no, avatar(row.name), who, total);
    list.appendChild(li);
  });
  return true;
}

// The first and last day (or month) of a quick range, as the form's boxes want them: "2026-10-01" or "2026-10".
function presetRange(kind, todayIso) {
  const today = new Date(`${todayIso}T00:00`);
  const y = today.getFullYear(), m = today.getMonth(), d = today.getDate();
  const pad = (n) => String(n).padStart(2, "0");
  const day = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  const month = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}`;
  const ranges = {
    today: [day(today), day(today)],
    yesterday: [day(new Date(y, m, d - 1)), day(new Date(y, m, d - 1))],
    "7d": [day(new Date(y, m, d - 6)), day(today)],
    month: [day(new Date(y, m, 1)), day(today)],
    lastmonth: [day(new Date(y, m - 1, 1)), day(new Date(y, m, 0))], // day 0 of this month = last day of the previous
    "6m": [month(new Date(y, m - 5, 1)), month(today)],
    "12m": [month(new Date(y, m - 11, 1)), month(today)],
    year: [`${y}-01`, month(today)],
  };
  return ranges[kind];
}

// The quick-date buttons in a filter form ("Today", "This month", "12 months", ...): pressing one fills in
// the form's dates and calls `reload`. Typing a date by hand un-highlights them.
export function wirePresets(form, reload) {
  const buttons = [...form.querySelectorAll("[data-range]")];
  for (const button of buttons) {
    button.addEventListener("click", () => {
      const [from, to] = presetRange(button.dataset.range, config.today);
      if (form.elements.date) {
        form.elements.date.value = from; // a one-day form (Daily activity)
      } else {
        form.elements.from.value = from;
        form.elements.to.value = to;
      }
      buttons.forEach((b) => b.classList.toggle("active", b === button));
      reload();
    });
  }
  form.addEventListener("input", (event) => {
    if (event.target.matches("input")) buttons.forEach((b) => b.classList.remove("active"));
  });
}

// GET a URL from our server and return the JSON. Throws an Error with the server's message if it failed.
export async function getJSON(url, params) {
  const query = params ? `?${new URLSearchParams(params)}` : "";
  const response = await fetch(`${url}${query}`, { headers: { Accept: "application/json" } });
  // 401: logged out (e.g. the session ran out). Reloading makes the page itself send them to log in.
  if (response.status === 401) location.reload();
  // A crash on the server sends an HTML error page, not JSON: {} then, and the status below.
  const data = await response.json().catch(() => ({}));
  // The server is running newer code than this page was built with: reload, rather than mix the two.
  if (data.version && data.version !== config.version) {
    location.reload();
    throw new Error("updating to the new version…");
  }
  if (!response.ok) throw new Error(data.error || `server error ${response.status}`);
  return data;
}

// After every refresh: the banner for sync trouble (shown, updated or hidden), the note about filling in
// history, and the note under the page's name saying how often calls are fetched from HoduCC and when that
// last worked.
export function showSyncInfo(data) {
  const banner = document.getElementById("sync-banner");
  const problem = data.sync_problem;
  banner.hidden = !problem;
  banner.textContent = problem ? problem.message : "";
  banner.className = problem ? `banner ${problem.level}` : "banner";

  // Filling in history (sync.backfill_in_background): how far it has got, with a bar
  const fill = document.getElementById("fill-banner");
  const progress = data.backfill;
  fill.hidden = !progress;
  if (progress) {
    fill.replaceChildren(`Fetching history from HoduCC: ${progress.done} of ${progress.total} days so far. `
      + "The numbers fill in as the days arrive; this page updates every 30 seconds.");
    const track = document.createElement("span");
    track.className = "progress";
    const done = document.createElement("i");
    done.style.width = `${(progress.done / progress.total) * 100}%`;
    track.appendChild(done);
    fill.appendChild(track);
  }

  const note = document.querySelector("[data-sync-note]");
  note.textContent = data.last_synced_at ? `Synced ${when(data.last_synced_at)}` : "Not synced yet";
  note.title = config.syncSeconds
    ? `New calls are fetched from HoduCC every ${config.syncSeconds} seconds while the dashboard shows today.`
    : "New calls arrive when sync_calls runs.";
}
