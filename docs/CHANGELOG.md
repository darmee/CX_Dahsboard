# How the dashboard got here

Each round of work, newest first: what was asked, what changed, and why. For *how* the code works, see
[HOW_IT_WORKS.md](HOW_IT_WORKS.md) and the [PDF guide](Call-Centre-Dashboard-Guide.pdf), which explains every
line. For what comes next, see [ROADMAP.md](ROADMAP.md).

---

## Round 12 · Missed rings, turned-away calls, clicking a bar (October 2026)

**Asked:** "Rejections" showed 106 on a day with 33 calls, rings of 0 s "answered by" an agent, and clicking the
Unanswered part of a bar showed nothing.

| Change | Why | Where |
| --- | --- | --- |
| **Rejections is now "Missed rings (agents)"** | It counts rings to agents on calls in, not customers rejecting calls | `dashboard.html`, docs |
| **0-second rings stay in the count** (explained, not removed) | Most missed rings are HoduCC retrying an agent's phone every 2 s when it can't reach it (`NORMAL_UNSPECIFIED`, `UNALLOCATED_NUMBER`): 92 of the 106 that day, from 8 calls. Kept on purpose, to show agents who can't be reached | `HOW_IT_WORKS.md` |
| **`HANGUP` counts as unanswered** | Calls in that HoduCC turned away at once because the account's limit on calls at the same time was reached (`TENANT_CALLS_LIMIT_REACHED`). They were in "Other in", out of every unanswered number | `HODU_UNANSWERED_STATUSES` default, `format.js` |
| **A bar opens the piece you click** | Chart.js passed every series at that position, Answered first, so the Unanswered piece opened the answered calls (often none) | `charts.js` `clickedBar` |

## Round 11 · No GitHub check (October 2026)

**Asked:** delete `.github` and `.ruff_cache`.

`.github/workflows/tests.yml` told GitHub to run the checks and tests on every push; it is gone, so the checks
are now run by hand before updating the server (the four commands are in the README, "Version control"). The
guide's page about that file went with it. `.ruff_cache` was ruff's memory of files it had already checked; it is
safe to delete, but ruff makes it again whenever it runs (`ruff check --no-cache .` doesn't).

## Round 10 · Forgot password: fixing the copied code (October 2026)

**Asked:** the server wouldn't start: `ModuleNotFoundError: No module named 'axes'`.

**Why:** a "Forgot password" feature was copied in from the loan dashboard. It used that project's lockout
package (django-axes) and its app name (`loans`), and had a few bugs of its own. `axes` was only the first to fail.

| Fixed | Where |
| --- | --- |
| The lockout is lifted through this project's own lockout (`unlock`), not django-axes | `calls/lockout.py`, `calls/password_reset.py` |
| The email backend's path (`loans.mail_graph` → `calls.mail_graph`) | `config/settings.py` |
| A second `LOGGING` block replaced the first, silently turning off the sync's logs; removed | `config/settings.py` |
| Microsoft 365 email: two setting names misspelt, the sign-in address (`oauth2`) and scope (`/.default`) wrong, and a misplaced `return` that sent every email without a body | `calls/mail_graph.py` |
| Three templates had no `.html` ending, so Django couldn't find them; the email's file ending didn't match the view's | `templates/registration/` |
| The pages now look like the login page (logo, brand background); the email placeholder shows the company domain; typos and the loan dashboard's name fixed | `templates/registration/`, `dashboard.css` |
| `.env.example` and the README now explain the email settings | `.env.example`, `README.md` |

Checked: 171 tests pass (10 new, for the whole reset flow and the Microsoft 365 email); `ruff` clean; the
pages checked in the browser.

## Round 9 · "Could not reach HoduCC" (October 2026)

**Asked:** "Last sync failed: Could not reach HoduCC (getCallHistory): … ConnectTimeoutError / Read timed out" keeps
showing on the dashboard. Why?

**Why:** HoduCC's server, or the network between this computer and it, is slow now and then. The sync log showed
40 good syncs and 2 failures in two hours (at 10:59 and 11:00 UTC, with the syncs straight after them working);
syncs that normally take 2–3 seconds took 20–50 seconds around then, and a plain connection test to HoduCC took
0.2 s, then 11.4 s, then 0.2 s. The dashboard wasn't at fault, but it gave up on the first timeout and turned the
banner red for a single failure.

| Change | Why | Where |
| --- | --- | --- |
| **Try again before giving up** | A slow moment usually passes within seconds: each request is now tried 3 times (waiting 2 s, then 4 s), with 10 s to connect and 30 s for the reply. The live numbers try once, as they come again in 15 s | `calls/client.py` |
| **Plain words** | "HoduCC's server didn't answer (getCallHistory): no connection within 10 seconds (tried 3 times)" instead of the library's `HTTPSConnectionPool…` text (which still goes to the log) | `client._unreachable` |
| **A calm note for a passing hiccup** | While the numbers are fresh and it hasn't failed 3 times in a row, a network failure shows a yellow note with the time of the numbers shown. Red stays for real problems (a wrong token), 3 failures in a row, or no good sync for 15 minutes | `views._sync_problem` |

Checked: 161 tests pass (6 new: trying again, giving up in plain words, the live numbers trying once, and the three
banner rules); `ruff` clean.

## Round 8 · Live counts on every page, missed rings, Daily activity side by side (October 2026)

**Asked:** what asks HoduCC every 15 seconds, and where? How is the average talk worked out? Who does a "Not
answered" call go to? How does a call know which agent to go to; what are missed rings? What are rejections, and
why can't we drill into them? What does the queue "General" mean? Bring back the live calls and waiting
notification on every page. Daily activity side by side. More space for the leaderboard.

The answers are written up in [HOW_IT_WORKS.md, "Questions people ask"](HOW_IT_WORKS.md#questions-people-ask).

| Change | Why | Where |
| --- | --- | --- |
| **Live counts on the rail, on every page** | Waiting, on calls, idle and logged in, straight from HoduCC every 15 s. They were hidden below 1700px wide; the rail has room for them on every screen. "Waiting" turns amber and pulses while callers wait | `dashboard.html`, `dashboard.css`, `js/live.js` |
| **Who an unanswered call rang** | "Not answered" didn't say whether the call reached anyone. Now the call log and the drill-down say "Rang Amina" when it rang someone before the caller hung up (197 of your 1,060 unanswered calls) | `metrics.recent` (`rang`), `format.agentCell` |
| **Rejections and missed rings open their list** | The drill-down only listed calls; rings are a different table. A new list of missed rings: when, the agent, how long it rang, why it stopped, and who took the call in the end. From the Rejections tile, the missed-rings tiles, and the "Rings missed" bars | `metrics.ring_list`, `/api/rings/`, `js/drill.js` |
| **Daily activity side by side** | The agents and the call log next to each other, with the columns that matter most (the rest on hover). Below 1300px wide they stack | `dashboard.html`, `js/activity.js`, `dashboard.css` |
| **Leaderboard: more space** | The leaderboard now has the left side of the Agents page, the full height, with bigger text; the two charts are stacked on the right. Connected shows the count and the rate together | `dashboard.html`, `dashboard.css`, `js/agents.js` |

Checked: 155 tests pass (4 new, for missed rings and who a call rang); `ruff` clean; every page at 9 desktop sizes,
measured on a day *with* calls this time (an empty day hides wide columns), fits with nothing cut off and no script
errors; phone layout checked.

## Round 7 · Space, the logo, the reference chart style, Admin for the owner only (October 2026)

**Asked:** what database is used? Remove Admin from the dashboard: it will be for public use, and only the
owner should get into Admin. The space still isn't managed. Add the brand logo. Why are some agent places
empty? Make the charts look like the reference picture. Is the answer ratio between calls in and calls out?
On Agents, make the charts bigger and reduce the cards.

| Change | Why | Where |
| --- | --- | --- |
| **The database** (an answer, no change) | SQLite: one file, `db.sqlite3`, beside `manage.py`. It holds 3,306 calls from 22 April 2026 and is fine at this size. For many users on a server, move to PostgreSQL (see "Going live") | `config/settings.py` |
| **Admin: owner only** | The dashboard is going public. Admin now lets in superusers only (not staff, not ordinary logins), the dashboard has no link to it, and its address can be changed to one nobody would guess (`DJANGO_ADMIN_PATH`) | `calls/admin.py`, `config/urls.py`, `config/settings.py` |
| **Space** | Following the reference: the sidebar became a slim rail (icons; names on hover), the filters moved into the top bar (no Update button: a change reloads), the number tiles are compact (a coloured dot, a small-capital name, the number, one line under it), and the charts take the rest of the screen | `dashboard.html`, `dashboard.css`, `js/main.js` |
| **The logo** | At the top of the rail (on a white tile), on the login page, in Admin's header, as the browser-tab icon and as the phone home-screen icon | `static/calls/brand/`, `base.html`, `login.html` |
| **Empty agent places explained** | 1,060 of the 3,306 calls have no agent: callers who hung up before anyone answered (1,032 abandoned, 28 hung up in the menu). HoduCC names no agent for them. The call log and the drill-down now say "Not answered" instead of a blank | `format.agentCell` |
| **Charts like the reference** | Solid bars with rounded tops and their totals written above them; faint dashed grid lines; the key at the top left; ring charts with the total in the middle and a key listing each count and its share. A new "Call outcomes" ring on the Overview. Colours: blue (answered in), amber (unanswered in), green (connected out), grey (not connected), pink (other in). The reference's red-next-to-green failed the colour-blindness check, so unanswered is amber | `js/charts.js`, `js/overview.js`, `js/live.js` |
| **Answer ratio** (an answer) | Not between calls in and calls out: it is answered calls *in* ÷ all calls *in*. The tile now says "Answer ratio (in)"; calls out have the connect rate | `dashboard.html` |
| **Agents page** | The tiles are slimmer, and the two charts take the height that is left (257px instead of 212px on a 1366×768 laptop, 487px on a 1920×1080 screen); the leaderboard is as tall as its rows | `dashboard.css` |
| **Full screen** | A button in the top bar, for a screen on the wall | `js/main.js` |

Checked: 151 tests pass (4 new, for Admin access and the logo); `ruff` clean; every page at 9 desktop sizes fits
with no page scroll, no cut-off columns, no clipped titles and no script errors; screenshots in light, dark and on a phone.

## Round 6 · Drill-down, history, light and dark mode (October 2026)

**Asked:** why are there no calls for September or early October? Let the leaderboard show well. What does
"not connected" mean? A drill-down to the customers behind the numbers. Better chart colours. Hide the
staff-name editing. Light and dark mode. More beautiful. Document everything.

| Change | Why | Where |
| --- | --- | --- |
| **History: `sync_calls --from 2026-01-01`** (and `--to`) | The dashboard only has the days it has fetched. Syncing started on 7 October and the routine sync covers today and the 3 days before, so September was never fetched. One command now fetches any range | `calls/management/commands/sync_calls.py` |
| **History fills in by itself** | Nobody should have to remember the command. Looking at never-fetched days (last March on Monthly, say) fetches them in a background thread, with a purple progress bar. `HODU_AUTO_BACKFILL=0` switches it off | `sync.missing_days`, `sync.backfill_in_background`, `views._fill_history` |
| **Drill-down** | Every number now opens the calls behind it: tiles, chart bars, agents' rows. The panel shows when, the customer (`•••2698`: only the last 4 digits are ever stored), in or out, status, why it ended, agent, wait, talk, hold; plus the most common reasons and who hung up | `metrics.call_list`, `/api/calls/`, `js/drill.js` |
| **Why a call ended** (`hangup_reason`) | To explain "not connected" call by call. Stored from now on (migration 0003); days fetched before show "–" until they are fetched again | `models.py`, `parsing.py`, `migrations/0003_call_hangup_reason.py` |
| **"Not connected" explained** | A call out the customer never picked up: no answer, busy, switched off, or the line failed (HoduCC's status `DIAL`). Said on the Calls out tile, in the drill-down, and in the docs | `dashboard.html`, `js/drill.js` |
| **▲/▼ against the period before** | A number means more next to the one before it. Today is compared with yesterday *up to the same time*, so mornings don't all read "▼ 100%" | `metrics.previous_totals`, `js/overview.js` |
| **New chart colours** | One meaning per colour everywhere: calls in plum (answered) and amber (unanswered); calls out teal (connected) and pale teal (not connected). Checked with a colour-blindness validator in both modes. Bars have a soft gradient | `dashboard.css` (`--chart-*`), `js/charts.js` |
| **Leaderboard first on Agents** | It is the page's main thing: full width, compact rows, small bars for calls made and received. The charts' keys moved into the card headers so the bars get the room | `dashboard.html`, `js/agents.js` |
| **Staff-name editing removed from the dashboard** | Editing belongs in Admin; the dashboard is for reading. Staff still reach it with the Admin button | `dashboard.html` |
| **Light and dark mode** | A sun/moon switch at the top; without a choice, the dashboard follows the computer. The choice is remembered and shared with the admin | `js/theme.js`, `base.html`, `dashboard.css` |
| **Fixed: the page froze when switching light/dark** | Redrawing the charts walked a list it was adding to, and never finished. It now walks a copy | `js/charts.js` (`rebuildAll`) |
| **Phone tidy-ups** | Date and sync note on two lines, status text wraps instead of being cut off | `dashboard.css` |
| **Documentation** | Every new and changed line is explained in the PDF guide; README, HOW_IT_WORKS, the glossary and this changelog updated | `docs/` |

Checked: 147 tests pass; `ruff` clean; no missing migrations; every page at 9 desktop sizes (1024×500 to
2560×1300) fits with no page scroll, no cut-off columns and no script errors; screenshots in light, dark and
on a phone.

## Round 5 · Checking the work

**Asked:** did you go through what you did?

Every page was measured at real laptop and desktop window sizes (including 125% and 150% zoom) for page
scroll, cut-off table columns and clipped text, and screenshots were taken in real time rather than with a
simulated clock, so half-finished animations couldn't hide problems. The problems found were fixed before
moving on.

## Round 4 · Movement, the history error, and the Live badge

**Asked:** use Lenis and Framer Motion; why does history say "Cannot read properties of undefined (reading
'length')"; what is the answer ratio between; no scrolling; a live dot with HoduCC's update interval; more
about agents (who calls and receives most, also monthly); make it stunning.

| Change | Why |
| --- | --- |
| **Motion** (the plain-JavaScript version of Framer Motion, which only works inside React) and **Lenis** | Numbers count up, charts grow, pages rise in, the sidebar's highlight slides, tables scroll smoothly. Switched off for anyone whose computer asks for less motion |
| **The history error** | The browser was running old cached scripts against newer server code (and two servers were running at once). Now static files are always served with "check for a newer copy", every API answer carries a code version, and an open page reloads itself when the code changes |
| **Answer ratio explained** | It is answered calls *in* ÷ all calls *in*. Calls out have their own number, the connect rate |
| **Live badge** | A pulsing dot, "every 15 s", and a ring counting down to the next update from HoduCC |
| **Agents page** | Who calls the most and who receives the most over any period, with a leaderboard; Monthly also ranks agents |

## Round 3 · Six pages that fit the screen

**Asked:** the brand colour must show; daily activity on its own page; no page scrolling on a computer; fix
the cut-off columns; a monthly history tab with bar charts; why is the answer ratio always the same; a tab
for each agent's activity.

- A plum sidebar with six pages: **Overview, Agents, Agent detail, Daily activity, Monthly, Live**.
- On a computer (1000px wide or more) each page fits the screen at any height: tables and lists scroll inside
  their card, charts take the room that is left. Narrower laptops fold the sidebar to icons. Phones scroll.
- **Monthly**: up to 36 months as a bar chart. **Agent detail**: one agent over up to 92 days.
- **Why the answer ratio barely moved**: it counts calls *in* only, and most calls are *out*. The connect rate
  (calls out the customer picked up) was added beside it.

## Round 2 · The brand colour

**Asked:** use #4f1a60 to make it premium.

The brand colour became the base of the page's colours. The feedback that this wasn't good enough led to
the rebuild in round 3.

## Round 1 · Review and fixes

**Asked:** go through the code and check for issues, then fix them.

Among the fixes: the Daily activity call log stopped at 200 calls without saying so (it now holds 1,000 and
says "latest 1,000 of 1,250" when a day has more), and the page could say "Calls sync every 0 s" when live mode
was off.
