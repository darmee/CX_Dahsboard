# How the dashboard works

> **The full guide is [Call-Centre-Dashboard-Guide.pdf](Call-Centre-Dashboard-Guide.pdf)**: every file, line by
> line, a step-by-step rebuild, and what we learned about HoduCC's API. This page is the shorter tour.

This explains the project from the top down. Read it once from start to end,
then use it as a reference. Each section names the file to open alongside it.

1. [The big picture](#1-the-big-picture)
2. [Django in five ideas](#2-django-in-five-ideas)
3. [Following one request through the code](#3-following-one-request-through-the-code)
4. [File by file](#4-file-by-file)
5. [How each number is worked out](#5-how-each-number-is-worked-out)
6. [Changing things: recipes](#6-changing-things-recipes)
7. [Tests](#7-tests)
8. [Going live](#8-going-live)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. The big picture

There are two jobs: fetching calls from HoduCC into our database (sync), and showing them (website).

```
 JOB 1: SYNC                                               JOB 2: WEBSITE  (python manage.py runserver)
 (by itself while the dashboard shows today,
  or python manage.py sync_calls)
 ─────────────────────────────────────────                 ───────────────────────────────────────────

   HoduCC API                                                  Browser (dashboard.html + js/*.js)     
       │  getCallHistory, getAgentOfferedCalls                       │  GET /api/metrics/?from=..&to=..
       ▼                                                             ▼
   client.py   ── raw JSON ──►  parsing.py  ── clean values ──►  views.py ──► metrics.py
                                                    │                              │
                                                    ▼                              │
                                              sync.py saves                        │ reads
                                                    │                              │
                                                    ▼                              ▼
                                          ┌───────────────── database (db.sqlite3) ───────────┐
                                          │  Call      AgentOffer      SyncRun                │
                                          └───────────────────────────────────────────────────┘
```

**Why two jobs, with a database in the middle?**

- **Speed.** The page reads from your own database, which answers in milliseconds.
  HoduCC can take seconds.
- **Any date range.** HoduCC's realtime endpoints only know about *today*. With every call stored,
  you can look at last week, last month, or one queue.
- **Being polite to HoduCC.** HoduCC is asked at most once a minute, however many
  people have the dashboard open.
- **It keeps working.** If HoduCC is down, the dashboard still shows everything up to the last sync.

**How does it stay live?** HoduCC doesn't announce new calls; we have to ask for them. So:

| | How fresh | How |
| --- | --- | --- |
| "Right now" strip (waiting, on calls, agents logged in) | 15–45 seconds | Asked of HoduCC directly (`getRealtimeQueueSummary`) on each page refresh, cached 15 s |
| Everything else, while someone views **today** | About 1–1½ minutes | **Live mode.** Each page refresh (every 30 s) asks the server for numbers. If the last fetch was over a minute ago (`HODU_SYNC_ON_VIEW_SECONDS`), the server starts one in the background. The refresh after that shows the new calls |
| Everything else, when nobody is looking | Whenever the next sync runs | `sync_calls` on a schedule (see section 8). Optional on your own computer; recommended on a server, so reports are complete even on days nobody opened the page |

You never *have* to run `sync_calls` by hand any more.

**What about the past?** The database only has the days that were fetched: the routine sync covers today and
the 3 days before, so on its own the dashboard's history starts the day it was installed. Two ways to fill it in:

| | How |
| --- | --- |
| **All at once** | `python manage.py sync_calls --from 2026-01-01` (add `--to 2026-06-30` to stop earlier). One line per day; a year takes a few minutes. Running it again is safe: calls are updated, never doubled |
| **By itself** | When someone looks at days that were never fetched (last March on the Monthly page, say), the server fetches them from HoduCC in a background thread, oldest first, and the page shows a purple progress bar. On unless `.env` says `HODU_AUTO_BACKFILL=0`. See `missing_days` and `backfill_in_background` in `sync.py` |

**Why can't the browser call HoduCC directly?** The token goes inside every request.
Anything the browser has, anyone can see with "View source". So only Python ever holds the token.

---

## 2. Django in five ideas

Django is a Python framework for websites. You only need five ideas to follow this project.

| Idea | What it is | In this project |
| --- | --- | --- |
| **Model** | A Python class that *is* a database table. Each attribute is a column. | `calls/models.py` → tables `Call`, `AgentOffer`, `SyncRun` |
| **Migration** | A file describing how to create or change tables. `makemigrations` writes it; `migrate` applies it. | `calls/migrations/0001_initial.py` |
| **View** | A Python function that receives a web request and returns a response (a page or JSON). | `calls/views.py` |
| **URL** | A map from an address like `/api/metrics/` to a view. | `config/urls.py`, `calls/urls.py` |
| **Template** | An HTML file with gaps `{{ like_this }}` and tags `{% like_this %}` that Django fills in. | `calls/templates/calls/dashboard.html` |

Two more words you'll see:

- **Project vs app.** `config/` is the *project*: settings and the top-level URL map. `calls/` is an *app*:
  one self-contained feature. Big sites have many apps; we have one.
- **ORM** (Object-Relational Mapper). Instead of writing SQL, you write Python:
  `Call.objects.filter(status="AGENT").count()` becomes `SELECT COUNT(*) FROM calls_call WHERE status = 'AGENT'`.

---

## 3. Following one request through the code

What happens when you click **Update** on the dashboard:

1. **Browser → `js/main.js` and `js/overview.js`**. The form's submit is caught (`form.addEventListener("submit", ...)`).
   The script reads the dates and queue and calls
   `fetch("/api/metrics/?from=2026-10-05&to=2026-10-05&queue=")`.

2. **Django → `config/urls.py`**. The address doesn't start with `admin/` or `accounts/`,
   so it's handed to `calls/urls.py`, which matches `api/metrics/` to `views.metrics_api`.

3. **`views.metrics_api`**.
   - `@api_login_required` checks you're logged in; if not, it answers 401 ("log in first"), and the page
     reloads itself, which takes you to the login page.
   - `_parse_range()` reads `from` and `to` and rejects nonsense (bad format, end before start).
   - It calls `compute_metrics(start, end, queue)`.

4. **`metrics.compute_metrics`**. Asks the database for all the counts and averages in one query
   (see section 5), then the hourly and per-agent lists. Returns a Python dict.

5. **Back in the view**. `_json(data)` turns the dict into JSON, adds the code version (see below) and
   sends it back.

6. **Back in `js/overview.js`**. `renderTiles`, `renderAgents` and `renderChart` put the numbers
   on the page; the numbers count up to their new values. `setInterval` repeats the whole thing every 30 seconds.

**The code version.** The page and every API answer carry a short fingerprint of the code (`CODE_VERSION` in
`views.py`). If the server is restarted with new code while a dashboard is open, the page sees a different
version on its next refresh and reloads itself, so it never mixes old and new code.

And the first time you open the page, it's simpler: `/` → `views.dashboard` → renders
`dashboard.html` with the list of queues and the last sync time. The page then runs `js/main.js`, and step 1 starts.

---

## 4. File by file

### `config/settings.py`: settings

Everything Django needs to know: which apps are installed, where templates are, the database, time zone, login rules.

The important pattern: **secrets and machine-specific values are read from `.env`**, not written in this file.

```python
load_dotenv(BASE_DIR / ".env")             # read .env into environment variables
SECRET_KEY = env("DJANGO_SECRET_KEY", ...) # then pick them up
```

So you can share the code without sharing your token. `.env` is listed in `.gitignore` so Git never uploads it.

Our own settings are grouped in the `HODU` dictionary at the bottom (token, mock mode,
which statuses count as unanswered, ...). Other files read them with `settings.HODU["TOKEN"]`.

`TIME_ZONE = "Africa/Lagos"` with `USE_TZ = True` means Django stores times in UTC
and converts to Lagos time for display and for "which day/hour was this call in".

### `calls/models.py`: the database tables

```python
class Call(models.Model):
    call_id = models.BigIntegerField(unique=True)
    status = models.CharField(max_length=32, db_index=True)
    wait_seconds = models.PositiveIntegerField(default=0)
    ...
```

- `unique=True` on `call_id`: the same call can't be stored twice. When the sync sees it again, it updates it.
- `db_index=True`: tells the database to keep a lookup index on that column, so filters like
  "status = ABANDONED" stay fast with lots of rows.
- Durations are stored as **whole seconds**, which makes averages simple.
- We store `caller_masked` (`•••2698`), never the full phone number.

`AgentOffer` stores each time a call rang an agent (for rejections). `SyncRun` is a log: one row per sync, with how many calls arrived and any error.

**If you change a model**, run `python manage.py makemigrations` then `python manage.py migrate`.

### `calls/client.py`: talking to HoduCC

The **only** file that knows HoduCC's address and token.

```python
client = get_client()                       # real client, or mock if HODU_MOCK=1
rows, total = client.get_call_history(date(2026, 10, 5))
```

`HoduClient.post()` does what every HoduCC call needs:
1. Adds `token` and `tenant_id` to the body.
2. Sends the POST.
3. If `code` is 200, returns the `result`/`data` part.
4. If the message says "Not Found", returns `None`. HoduCC uses an error code for "no data", which isn't really an error.
   The exception is a "not found" about your account (token, tenant, user, API): that is a real error, so step 5 applies.
5. Anything else raises `HoduError` with HoduCC's message, e.g. `"getCallHistory: 400 Token Authentication Failed."`.

Dates are sent day-first, `"13-10-2026"`, because HoduCC answers `"2026-10-13"` with `400 Invalid Date Format`.
(The `sync_calls --date` option accepts either way of writing it.)

`_rows()` handles HoduCC's odd list shape: `{"0": {...}, "1": {...}, "total": 9}` → a normal list, plus the total.

`MockHoduClient` has the same methods but reads `sample/*.json`. Because both classes look the same from outside,
the rest of the code doesn't care which one it gets. That is what makes mock mode and the tests possible.

### `calls/parsing.py`: cleaning raw values

Turns one raw HoduCC row into the fields of a `Call`. All of HoduCC's quirks live here:

| HoduCC gives | We store | Function |
| --- | --- | --- |
| `"05-10-2026 09:09:38"` (day first) | a proper date-time in Lagos time | `parse_datetime` |
| `"00-00-0000 00:00:00"` | nothing (`None`) | `parse_datetime` |
| `"0:01:16"` | `76` (seconds) | `parse_duration` |
| `"09061612698"` | `"•••2698"` | `mask_number` |

The comment at the top lists the traps found in your real data. For example, `call_answer_time` is filled even
for abandoned calls, so "answered" is decided by `call_status == "AGENT"` only.

If HoduCC ever renames a field, this is the one file to change.

### `calls/sync.py`: copying calls into the database

`sync_day(day)`:

1. Creates a `SyncRun` log row.
2. Gets the day's calls from the client.
3. `save_calls()` turns each row into a `Call` and saves them all with **one** database command:

   ```python
   Call.objects.bulk_create(calls, update_conflicts=True, unique_fields=["call_id"], update_fields=[...])
   ```

   That means "insert these; if a `call_id` already exists, update it instead". This is called an *upsert*.
   So running the sync twice never creates duplicates, and a call still in progress at the last sync gets its final numbers.
   A row we can't read (say, a date in a new format) is skipped and noted; the rest of the day is still saved.

4. Checks HoduCC's `total` against the rows received. If HoduCC said 500 but sent 200, the results were cut off.
   The 200 are saved, but the sync is marked **failed**, because that day's totals would be too low.
5. Tries agent offers, saved the same way (so a ring still ringing at the last sync gets its final length).
   If that endpoint fails, the calls are still saved and the problem is noted.
6. Any error is caught and written to the log, so a bad token gives a clear message instead of a crash,
   and one bad sync never stops the next one.

`transaction.atomic()` means "save all of these, or none of them". You never get half a reply saved.

`days_needing_sync(today)` answers "which days should the routine sync pull?": today, plus any of the last 3 days
that hasn't had a good sync **since it ended** (30 minutes after midnight). Without this, a call at 23:58, or one still
in progress at midnight, would never be completed, because the next sync would only ask for the new day.
A day that keeps failing is given up on after 3 tries.

`missing_days(start, end)` answers "which past days in this range were never properly fetched?" by the same
rule: a day is done once a good sync started after it ended. `backfill_in_background(days)` fetches them in a
background thread, one at a time, recording its progress in Django's cache (`{"total": 31, "done": 4}`) for the
progress bar. Only one fill runs at a time. Both background jobs (live mode and the fill) take turns writing
(`_write_lock`), because SQLite lets one program write at a time.

### `calls/management/commands/sync_calls.py`: the command

Any file in `management/commands/` becomes a `python manage.py <filename>` command, with Django fully loaded.
`add_arguments` defines `--date`, `--days`, `--from`/`--to` and `--loop`; `handle` runs. It just loops over days
and calls `sync_day`. With no options (and with `--loop`), the days come from `days_needing_sync`.

`sync_in_background(gap)` is live mode's half of `sync.py`: it starts the same "today plus any day still needing it"
sync in a background **thread** (a second line of work inside the web server), so the page that asked doesn't wait.
Django's cache remembers that a sync started, so a second request within `gap` seconds doesn't start another.

### `calls/metrics.py`: working out the numbers

The heart of the dashboard. The key trick is **conditional aggregation**: counting several things in one query.

```python
calls.aggregate(
    inbound=Count("id", filter=Q(direction="INBOUND")),
    answered=Count("id", filter=Q(status="AGENT")),
    avg_wait_answered=Avg("wait_seconds", filter=Q(status="AGENT")),
    ...
)
```

`Q(...)` is a condition. `Count("id", filter=Q(...))` means "count the calls that match this condition".
All of these run as a single `SELECT`, so it stays fast as the data grows.

- `hourly()` groups by `ExtractHour("started_at")`, so you get calls per hour in Lagos time.
- `per_agent()` groups by `agent_username` with `.values(...).annotate(...)`. That's the ORM's "GROUP BY".
- `rejection_stats()` is explained in section 5.
- `previous_totals()` works out the same totals for the period before, for the ▲/▼ chips (section 5).
- `call_list()` is the drill-down: the calls behind a number. `CALL_KINDS` names each list (`inbound`,
  `not_connected`, `held`, ...) and the condition that picks its calls.

### `calls/views.py` and `calls/urls.py`: answering requests

| Address | View | Returns |
| --- | --- | --- |
| `/` | `dashboard` | The HTML page |
| `/api/metrics/?from=&to=&queue=` | `metrics_api` | JSON: the Overview page's numbers for that range |
| `/api/agents/?from=&to=` (or `?date=`) | `agents_api` | JSON: what each agent did in that time (calls made, received, connect rate, missed rings, talk), and the call log (Agents and Daily activity pages) |
| `/api/agent/?agent=&from=&to=` | `agent_api` | JSON: one agent over up to 92 days (Agent detail page) |
| `/api/monthly/?from=&to=&queue=` | `monthly_api` | JSON: calls per month, up to 36 months, e.g. `from=2025-11&to=2026-10` (Monthly page) |
| `/api/calls/?from=&to=&kind=&queue=&agent=&hour=` | `calls_api` | JSON: the calls behind a number (the drill-down panel): the latest 500, how many in all, the most common hangup reasons and who hung up |
| `/api/live/` | `live_api` | JSON: the Live page, totals and one row per queue, straight from HoduCC |

All seven need you to be logged in: the page with `@login_required`, which sends you to the login page,
and the six APIs with `@api_login_required`, which answers 401 so the JavaScript can do that. `live_api` uses Django's cache for 15 seconds, so ten open screens make
one request to HoduCC, not ten.

The Overview, Agents, Agent detail and Monthly APIs also go through `_keep_live()`: it starts live mode's
background sync when the range includes today, starts filling in any never-fetched days (`_fill_history`),
and adds the sync details to the reply.

`_sync_problem()` decides whether the page shows a banner. It is sent with every one of those replies, so a screen
left open all day still finds out:

| Banner | When |
| --- | --- |
| Red: "Last sync failed" | The newest finished sync failed (bad token, HoduCC down, results cut off) |
| Red: "No sync since ..." | No sync has worked for `HODU_STALE_AFTER_SECONDS` (15 minutes). Usually `sync_calls` has stopped. Not shown in mock mode |
| Yellow: "finished with a warning" | The sync worked but noted something (rows skipped, agent offers unavailable) |

`calls/urls.py` sets `app_name = "calls"`, so elsewhere you can write `{% url 'calls:metrics_api' %}`
instead of typing the address. If you ever change an address, nothing else breaks.

### Templates: `templates/base.html` and `calls/templates/calls/dashboard.html`

`base.html` is the shared frame: the `<head>` (typeface, stylesheets, the icons) and empty **blocks**:

```html
<body class="{% block body_class %}{% endblock %}">
  {% block body %}{% endblock %}
  {% block scripts %}{% endblock %}
```

`dashboard.html` and `login.html` start with `{% extends "base.html" %}` and fill those blocks, so the `<head>`
is written once. A one-line script in `base.html` applies a stored light/dark choice before the styles load,
so the page never flashes the wrong colours.

Things to notice in `dashboard.html`:
- A slim plum rail with the company logo and six page buttons as icons (`role="tab"`), and six panels
  (`role="tabpanel"`): Overview, Agents, Agent detail, Daily activity, Monthly, Live.
- A top bar with the page's name, then every page's filter form (only the open page's shows; a change to any
  box reloads the numbers, so there is no Update button), then Live, full screen and the light/dark switch.
- `{% for q in queues %}<option>{{ q }}</option>{% endfor %}` builds the queue dropdown from the database.
- Each tile has `data-metric="inbound"` (or `data-agents`, `data-live-total`, ...). That's how the JavaScript finds
  where to put each number. Tiles with `data-drill="kind"` open the calls behind them.
- At the end, the drill-down panel (`#drawer`), hidden until a number is clicked.
- `{{ dashboard_config|json_script:"dashboard-config" }}` passes the API addresses (from
  `reverse()` in the view) to the JavaScript, so it has nothing hard-coded.
- `{% csrf_token %}` on the log-out form is Django's protection against other sites submitting forms as you.
- There is no link to Admin at all: the dashboard can be shown to anyone, and Admin is for the site's
  owner (see `calls/admin.py` below).

`templates/registration/login.html` is the login page. Django's built-in login view looks for exactly that file name.

### Static files: `dashboard.css` and `js/*.js`

Plain CSS and plain JavaScript with no build step. Edit and refresh.

- **CSS.** Colours are variables at the top: the brand colour `--brand` (#4f1a60) and its steps, then `--good`, `--bad`, ...
  Change them there. On a computer (1000px wide or more) every page fits the screen, however short the window:
  tables scroll inside their card and charts fill what is left; on short screens everything tightens and the
  tiles go into one row. On tablets and phones the rail becomes a bar at the top and the page scrolls.
  Dark mode is the same variables with dark values: used when the computer is set to dark, or when someone picks
  dark with the sun/moon switch (`<html data-theme="dark">`). The charts read the same variables, so they follow.
- **JS.** Small *modules* that `import` from each other:

  | File | Job |
  | --- | --- |
  | `main.js` | The starting point: switches between the six pages (remembered in the address, e.g. `#monthly`), refreshes the open one every 30 s (Live: 15 s), pauses while the browser tab is hidden |
  | `overview.js`, `agents.js`, `agent.js`, `activity.js`, `monthly.js`, `live.js` | One per page: fetch that page's API and fill it in |
  | `fx.js` | Movement: pages rising in, numbers counting, the sliding pill in the rail, the answer-ratio ring, trend lines; smooth scrolling. Uses Motion and Lenis, and does nothing if the computer asks for less motion |
  | `charts.js` | Chart.js set up once: colours from the CSS, light/dark mode, update instead of redraw, clickable bars |
  | `drill.js` | The drill-down: the panel that slides in with the calls behind a tile, a bar or an agent's row |
  | `theme.js` | The light/dark switch: remembers the choice in the browser and tells the charts to redraw |
  | `format.js` | Helpers: durations, times, filling tables, fetching JSON, the sync and history banners |

  Text goes in with `textContent`, never `innerHTML`. That way, if HoduCC ever sent a name containing `<script>`,
  it would show as text instead of running.

### `calls/admin.py`: the back office

`@admin.register(Call)` adds a Calls screen to `/admin` with filters (status, queue, agent),
search and a date drill-down. It's read-only (no add, change or delete) because the data belongs to HoduCC.
The **Sync runs** screen is where you check whether syncing is healthy.

**Agents** is the one editable screen: type each login's real **staff name** (and, optionally, employee number
and team) straight into the list and press Save. HoduCC's own names are placeholders ("Agent 01"). The sync adds
new logins by itself (from `getAgentList`, at most hourly) and never changes what you typed.

**Only superusers can use Admin** (`superusers_only` replaces the admin's usual "any staff member" rule), and the
dashboard has no link to it. Its address is `admin/` unless `.env` sets `DJANGO_ADMIN_PATH`; on a public server,
choose one nobody would guess.

### `calls/lockout.py`: stopping password guessing

After 5 wrong passwords for one username, logins for that username are refused for 15 minutes, on both
`/accounts/login/` and `/admin/login/`. `settings.py` switches it on with `AUTHENTICATION_BACKENDS`.
The counts are kept in Django's cache, which lives in the server's memory: restarting the server clears them,
and a server running several worker processes counts separately in each.

---

## 5. How each number is worked out

All from `calls/metrics.py`, for the date range and queue you pick.

| Tile | Calculation | Field from HoduCC |
| --- | --- | --- |
| **Calls in** | count where direction = INBOUND | `call_type` |
| **Calls out** | count where direction = OUTBOUND | `call_type` |
| **Unanswered** | count where status is ABANDONED or DROPPED (set by `HODU_UNANSWERED_STATUSES`) | `call_status` |
| **Answer ratio** | answered inbound ÷ all inbound × 100. Below it: "3 of 9 inbound", plus "· 2 other" if some inbound calls were neither answered nor unanswered. Outbound calls are not in it, so on a mostly-outbound day it rests on a handful of calls | `call_status`, `call_type` |
| **Connect rate** | outbound calls the customer picked up (status `AGENT`) ÷ all outbound × 100. Shown under Calls out, and on Agents, Agent detail and Monthly | `call_status`, `call_type` |
| **Not connected** | outbound calls the customer never picked up: any status other than `AGENT`, in practice `DIAL`. That means no answer, busy, phone switched off, or the line failed; the drill-down's "Why it ended" column gives HoduCC's reason for each | `call_status`, `hangup_reason` |
| **Avg delay** | average wait of answered inbound calls. Below it: the longest wait, and the average wait before callers gave up | `queue_wait_time` |
| **Avg hold** | average hold time, only over calls that were put on hold | `hold_duration` |
| **Avg talk** | average talk time of answered calls, inbound and outbound | `agent_duration` |
| **Rejections** | rings to an agent that the agent didn't take, and how long they rang | `getAgentOfferedCalls` |

**"Other" inbound calls.** A call whose status is neither `AGENT` nor one of `HODU_UNANSWERED_STATUSES`
(for example one that ended in the IVR menu, or one still in progress) counts in "all inbound", so it lowers the
answer ratio. The tile tells you how many there are. If they shouldn't count against you, that is a choice about
the definition: change `answer_ratio_pct` in `metrics.py`.

**Why the answer ratio can look stuck.** It is answered calls *in* ÷ all calls *in*. On a mostly-outbound
day it rests on a handful of inbound calls, so it barely moves even when lots of calls are made. Calls out
have their own number, the connect rate.

**The colours.** One meaning per colour, on every page: calls in answered are blue, calls in unanswered (and
rings missed) amber, calls out connected green, calls out not connected grey, other calls in pink. (Red next to
green, as in many dashboards, can't be told apart by colour-blind readers, so unanswered is amber.) Bars carry
their totals above them, and rings list each count and its share beside them. They were checked with a
colour-blindness validator in both light and dark mode.

**▲/▼ against the period before.** Each Overview tile shows how it changed on the period just before, as long:
yesterday for today, the previous 7 days for a week. While the period includes today, the period before stops
at the same time of day, so at 9:00 today is compared with yesterday up to 9:00 (otherwise every morning would
read "▼ 100%"). Green means better, red worse, grey neither (more calls is not good or bad in itself).
Hover over a chip to see the number it is compared with.

**The drill-down.** Click a tile, a bar or an agent and a panel lists the calls behind the number (up to the
latest 500), with how many there are in all, the most common reasons they ended, and who hung up (agent,
customer, or system). Customers appear as `•••2698`: the full number is never stored. "Why it ended" comes from
HoduCC's `hangup_reason`, stored since migration 0003; calls synced before then show "–" until their day is
synced again (`sync_calls --from ...`).

**Rejections in detail.** Every time a call rings an agent, HoduCC records an "offer". Say call 123 rings
Agent02 for 12 seconds (not taken), then Agent01, who answers. That's 2 offers, 1 rejection,
and an average of 12 seconds ringing before the reject. The code counts one offer per answered call as *taken*:
the last ring to the agent who answered it. Every other offer is a rejection or a miss, including an earlier ring
to that same agent. Agents are matched by exact username (`Agent1` is not `Agent10`). The `reasons` field shows HoduCC's
`aoc_hangup_reason` for each, so you can see which mean "rejected" and which mean "didn't pick up".
Check this against real data once offers are syncing.

**Agents and Daily activity.** Per agent: *answered in* (inbound, status AGENT), *answered out* (outbound, the
customer picked up), *not connected* (outbound, any other status, e.g. DIAL), *missed rings* (see rejections),
talk and hold time, first and last call. *Calls made* = every outbound call they dialled, connected or not;
*calls received* = every inbound call they answered. Every active agent is listed, even with no calls.

**Live tab.** From HoduCC's realtime summary: waiting, on calls, logged in, and *idle* = logged in − on calls
(HoduCC doesn't say whether idle agents are on a break). HoduCC's API has no list of individual calls in
progress, so this tab shows counts.

### Questions people ask

**What makes the dashboard ask HoduCC every 15 seconds, and where is that?** Two clocks, both in the browser,
and the server decides what actually reaches HoduCC:

| What | The clock | What the server does | Where |
| --- | --- | --- | --- |
| Live numbers (waiting, on calls, idle, logged in) | Every 15 s, `setInterval(refreshLive, ...)` | `live_api` asks HoduCC's `getRealtimeQueueSummary`, unless it already did in the last 15 s (`cache`, `HODU_LIVE_CACHE_SECONDS`): ten open screens make one request | `js/main.js` (last lines), `js/live.js` `load`, `views.live_api` |
| New calls (every other number) | Every 30 s, the open page reloads (`refreshSeconds`) | If the page shows today and the last fetch was over 60 s ago (`HODU_SYNC_ON_VIEW_SECONDS`), starts `sync_in_background`: `getCallHistory` and `getAgentOfferedCalls` for today | `js/main.js` `open`, `views._keep_live`, `sync.sync_in_background` |

Nothing reaches HoduCC while no dashboard is open (except a scheduled `sync_calls`, if you set one up), and the
browser never talks to HoduCC itself: only the server holds the token.

**How is the average talk worked out?** HoduCC records each call's talk time as `agent_duration` (the time the
agent and the customer were connected; `parsing.py` turns `0:01:16` into 76 seconds and stores it as
`talk_seconds`). The average is the mean of `talk_seconds` over the *answered* calls in the period, in and out
(`avg_talk=Avg("talk_seconds", filter=ANSWERED)` in `metrics.compute_metrics`). Unanswered calls are left out,
because their talk time is 0 and would pull the average down. Per agent: their total talk ÷ the calls they handled.

**A call in says "Not answered". Who did it go to?** Nobody took it: the caller hung up first. A call in waits in a
queue until HoduCC rings an available agent. If the caller hangs up while waiting, it never rang anyone: "Not
answered". If it rang someone who didn't pick up in time, the log now says who: "Rang Amina". In your data, 197 of
the 1,060 unanswered calls rang an agent before the caller hung up.

**How does a call know which agent to go to?** The dashboard doesn't decide that: HoduCC does. A call in enters a
queue (e.g. General); HoduCC's queue rings the agents logged in to that queue, by the order and rules set in
HoduCC, until one picks up or the caller hangs up. Each of those rings is recorded (`getAgentOfferedCalls`), and the
dashboard reads them after the call has ended. It only sees a call once the sync fetches it, a minute or so later;
right now, HoduCC only gives counts (waiting, on calls), not a list of calls in progress. A call out is simply dialled
by the agent.

**What are missed rings and rejections?** Every time a call rings an agent, HoduCC records a ring. A ring the agent
didn't pick up is a *missed ring*: they declined it (`CALL_REJECTED`), didn't answer before HoduCC moved the call on
(`RECOVERY_ON_TIMER_EXPIRE`, `NO_ANSWER`), or the caller hung up while it rang (`ORIGINATOR_CANCEL`). The Overview's
**Rejections** tile counts them all; the Agents page counts each agent's. Click either to see the rings: when, the
agent, how long it rang, why it stopped, and who took the call in the end. (They couldn't be clicked before because
the drill-down only listed calls; rings now have their own list, `/api/rings/`.)

**What does the queue "General" mean?** It is the name of the queue set up in HoduCC that calls in arrive in.
In your data: 1,263 calls in came through General (and 39 calls out were made from it); calls out made directly are
in a queue HoduCC calls "outbound"; 28 calls in have no queue (they ended in the phone menu, before reaching one).
More queues (e.g. Sales, Support) would show up here, and in the Queue drop-down, as soon as HoduCC uses them.

**Checking with the sample (5 Oct 2026).** 9 inbound calls; 3 answered (Agent01 ×2, Agent02 ×1), 6 abandoned.
Answer ratio 3 ÷ 9 = 33.3%. Answered waits 18, 32 and 10 seconds → average 20s. Abandoned waits
76, 45, 16, 27, 31 and 21 → callers gave up after 36s on average.

---

## 6. Changing things: recipes

### Change colours or spacing
Edit the variables at the top of `calls/static/calls/dashboard.css`. Refresh the page (Ctrl+F5 if it doesn't change).

### Change the "good" answer-ratio target (currently 80%)
In `calls/static/calls/js/overview.js`, find `ratio >= 80` and change the number.

### Count only ABANDONED as unanswered (not DROPPED)
In `.env`: `HODU_UNANSWERED_STATUSES=ABANDONED`, then restart `runserver`. No code change needed.

### Add a new tile, e.g. "Calls handled by the system"
1. **metrics.py**: inside `calls.aggregate(...)`, add a line:
   `system=Count("id", filter=Q(status="IVR")),`
   then add it to the returned `"totals"`: `"system": t["system"],`
2. **dashboard.html**: copy a tile and give it `data-metric="system"`.
3. **js/overview.js**: in `renderTiles`, add `countTo(value("system"), t.system);`
4. **tests**: add an assertion in `test_sync_and_metrics.py`.
5. **The guide**: run `python docs/guide/build_guide.py`. If a changed line had an explanation, the build says
   which; update it in `docs/guide/notes/`.

### Store a new field from HoduCC, e.g. `disposition_name`
1. **models.py**: add `disposition = models.CharField(max_length=100, blank=True)` to `Call`.
2. Run `python manage.py makemigrations` and `python manage.py migrate`.
3. **parsing.py**: in `call_from_row`, add `"disposition": row.get("disposition_name") or "",`
4. **sync.py**: add `"disposition"` to `CALL_UPDATE_FIELDS`.
5. Re-sync the days you want it for: `python manage.py sync_calls --from 2026-01-01`. (This is exactly how
   `hangup_reason` was added: migration 0003.)

### Test rejections in mock mode
Run `getAgentOfferedCalls` once in Postman and save the reply as `sample/agentofferedcalls.json`.

---

## 7. Tests

```bash
python manage.py test
```

171 automatic checks, in a temporary database (your real data isn't touched). They never call HoduCC, whatever
`.env` says: they use `calls/tests/fixtures/callhistory.json`, a copy of a real reply with the phone numbers
replaced by made-up ones, plus made-up calls written in the tests. So they also run on a fresh copy of the
project. Nothing runs them for you: run them after every change, and before updating the server (the README's
"Version control" section lists the four checks).

Before handing over a change, also run `ruff check .`. It finds mistakes like an unused import, a misspelt
name or imports out of order (`ruff check --fix .` repairs most of them). Its rules are in `pyproject.toml`.

| File | What it checks |
| --- | --- |
| `tests/test_parsing.py` | Dates, durations, masking. Full numbers are never stored. |
| `tests/test_client.py` | The token and tenant are sent; "Not Found" means empty, unless it's about your account; real errors raise. Uses fake replies, no network. |
| `tests/test_sync_and_metrics.py` | Sync saves 9 calls and never duplicates; cut-off, unreadable and repeated rows; finishing off earlier days; every dashboard number for 5 Oct is right; outbound and "other" calls; rejections; the sync banners; live mode starts only for today and at most once a minute; login is required; no full numbers leave the server; admin is read-only. |
| `tests/test_agents_and_live.py` | The agent list sync; staff names; per-agent numbers, missed rings and the leaderboard order; Agent detail; Monthly; the Live page's numbers, including odd or failed replies from HoduCC. |
| `tests/test_drilldown_and_history.py` | Each drill-down list picks the right calls (and only the last 4 digits); the period before, including "up to the same time" today; which days are missing; filling in history (one fill at a time, switched off by `HODU_AUTO_BACKFILL=0`); `sync_calls --from --to`. |
| `tests/test_lockout.py` | 5 wrong passwords lock a username on both login pages; other usernames are unaffected. |

Run them after every change. If one fails, it names what's wrong.

---

## 8. Going live

`runserver` is only for your own computer. For your team, on a server:

1. In `.env`:
   - `DJANGO_DEBUG=0`. With debug on, error pages show your settings to anyone.
   - A new `DJANGO_SECRET_KEY`: run `python -c "import secrets; print(secrets.token_urlsafe(50))"` and paste the result.
   - `DJANGO_ALLOWED_HOSTS=dashboard.yourcompany.com`
   - `DJANGO_CSRF_TRUSTED_ORIGINS=https://dashboard.yourcompany.com`. Without it, the login form is refused ("CSRF verification failed").
   - `HODU_MOCK=0`
2. `python manage.py collectstatic` copies CSS/JS into `staticfiles/`. Run it again whenever you change the CSS or JS.
   With `DJANGO_DEBUG=0`, Django serves that folder itself (using the WhiteNoise package), so there is nothing else to set up.
3. Run Django with a production server instead of `runserver`:
   - Linux: `pip install gunicorn` then `gunicorn config.wsgi`
   - Windows: `pip install waitress` then `waitress-serve --port=8000 config.wsgi:application`
4. Put it behind HTTPS (for example nginx or IIS in front, or a host like Render or Railway). Then, in `.env`:
   - `DJANGO_BEHIND_PROXY=1`, so Django knows visitors used https. Only set this when something really is in front
     and sets the `X-Forwarded-Proto` header itself (nginx: `proxy_set_header X-Forwarded-Proto $scheme;`).
   - `DJANGO_SSL_REDIRECT=1` to send `http://` visitors to `https://`. Set it after `DJANGO_BEHIND_PROXY`, or the site
     redirects forever.
   - `DJANGO_HSTS_SECONDS=3600` to tell browsers to use https only. Raise it (e.g. `31536000`, a year) once all is well.
   - Check your work with `python manage.py check --deploy`.
5. Live mode keeps today fresh while someone is watching. Also run the sync on a schedule, so days nobody
   watched are complete too (use this instead of `--loop`):
   - Linux cron, every 5 minutes: `*/5 * * * * cd /path/to/callcentre && .venv/bin/python manage.py sync_calls`
   - Windows: Task Scheduler running `.venv\Scripts\python.exe manage.py sync_calls` every 5 minutes.
6. Optional: switch from SQLite to PostgreSQL if many people use it or you keep years of calls.
   Change `DATABASES` in `settings.py` and `pip install "psycopg[binary]"`.

---

## 9. Troubleshooting

| You see | It means | Fix |
| --- | --- | --- |
| `HODU_TOKEN and HODU_TENANT_ID must be set` | `.env` is missing or still has the placeholder | Check `.env` is in the same folder as `manage.py` |
| `Token Authentication Failed` | Wrong or expired token | Ask HoduCC for a new one |
| `You cannot access this APIs` | Your token doesn't have API access | Ask HoduCC to enable it |
| Dashboard shows 0 calls for past days | Those days were never fetched | Wait for the purple "Fetching history" bar to finish, or run `python manage.py sync_calls --from YYYY-MM-DD` |
| "Not answered" in the agent column | Nobody took that call in: the caller hung up first (ABANDONED, or HANGUP in the menu), so HoduCC names no agent | Nothing; it is how those calls are |
| "Why it ended" shows "–" | The call was synced before the reason was stored (migration 0003) | Run `python manage.py migrate`, then re-sync those days with `--from` |
| "reported N calls but sent M, so this day is incomplete" | HoduCC cut the results off. The M calls are saved, but the sync counts as failed | Ask HoduCC about paging or limits |
| Yellow note "HoduCC's server was slow to answer at 12:00" (before: red "Could not reach HoduCC … ConnectTimeout / Read timed out") | HoduCC's server, or the network to it, was slow for a moment. Each request is tried 3 times (waiting 2 s, then 4 s) before the sync gives up | Nothing: the next sync, within a minute, usually works. If it turns red (3 failures in a row, or no good sync for 15 minutes), check this computer's internet connection, then ask HoduCC whether their server is down |
| Red banner "No sync since ..." | No sync has worked for 15 minutes | Check the terminal or scheduled task running `sync_calls`. If you sync less often on purpose, raise `HODU_STALE_AFTER_SECONDS` |
| Yellow banner "Skipped N row(s) we couldn't read" | HoduCC sent a value in a new format | The message names the problem; fix the matching function in `parsing.py` |
| Yellow banner "repeating a call_id" | HoduCC sent the same call more than once in one reply (perhaps one row per transfer) | Look at the raw reply; only the last row of each is kept |
| Yellow banner "Fetching the latest calls" | Live mode is catching up after a quiet spell | Nothing; it goes on the next refresh |
| `400 Invalid Date Format` | A date was sent as 2026-10-13 | HoduCC needs 13-10-2026; `client.py` does this via `HODU_DATE` |
| Right password is refused | 5 wrong tries locked that username | Wait 15 minutes, or restart the server |
| "CSRF verification failed" when logging in on the server | Django doesn't know the site's https address | Set `DJANGO_CSRF_TRUSTED_ORIGINS` (section 8) |
| Page has no styling on the server | `collectstatic` hasn't been run | `python manage.py collectstatic` |
| `no such table: calls_call` | Database not created | `python manage.py migrate` |
| CSS changes don't show | Browser cache | Ctrl+F5 |
| `'python' is not recognized` (Windows) | Python not on PATH | Reinstall Python and tick "Add to PATH", or use `py` instead of `python` |
| Hours look 1 hour off | HoduCC uses a different time zone | Ask HoduCC, then set `HODU_TIME_ZONE` in `.env` |
