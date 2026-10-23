# Call Centre Dashboard (Django)

A website that shows HoduCC call statistics on six pages. On a computer each page fits the screen;
on a phone it scrolls.

- **Overview**: calls in/out, unanswered calls, answer ratio (inbound), connect rate (outbound), delay
  (wait time), hold and talk time, agent rejections, calls by hour and the top agents, for any dates and queue.
- **Agents**: who calls the most and who receives the most, for today, a week, this month, last month or
  any range: the top caller and receiver, two ranking charts and a leaderboard, under real staff names.
- **Agent detail**: one agent over a date range: their totals, a bar per day and their latest calls.
- **Daily activity**: one day as tables: every agent's numbers, and every call (the call log).
- **Monthly**: history, month by month, as a bar chart, with the agents who made and received the most
  calls over those months.
- **Live**: right now, per queue: callers waiting, agents on calls, idle and logged in.

**Click any number to see the calls behind it.** Tiles, chart bars and agents' rows open a panel listing
those calls: when, the customer (last 4 digits only), in or out, the status, why it ended (e.g. why a call
out didn't connect), who hung up, and the wait, talk and hold times.

Across the top of every page, a **Live** badge with a pulsing dot shows the numbers straight from HoduCC, how
often they update (every 15 s), and a ring counting down to the next update. Beside it, a **sun/moon switch**
picks light or dark mode (without a choice, the dashboard follows the computer). Overview tiles show
**▲/▼ against the period before** (today against yesterday up to the same time). The pages move: numbers
count up, charts grow, the highlight in the rail slides (Motion, the plain-JavaScript version of Framer
Motion), and tables scroll smoothly (Lenis). A **full-screen** button suits a screen on the wall.

The layout gives the charts the room: a slim rail with the company logo and the pages as icons, the filters
in the top bar (any change reloads the numbers), compact number tiles, and charts with their values written
on them. Calls nobody answered show who they rang (**"Rang Amina"**), or **"Not answered"** if they never
reached anyone. The rail shows the live counts on every page; **"waiting"** turns amber and pulses while
callers wait. The Rejections tile opens the missed rings behind it. Answers to common questions (what asks
HoduCC every 15 seconds, how average talk is worked out, what "General" means) are in
[HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md#questions-people-ask).

**Python + Django** pulls calls from HoduCC, stores them, and works out the numbers; **HTML, CSS,
JavaScript and Chart.js** show them. Login required. The HoduCC token never reaches the browser.

| Read this | To |
| --- | --- |
| **[docs/Call-Centre-Dashboard-Guide.pdf](docs/Call-Centre-Dashboard-Guide.pdf)** | **The full guide:** how it works, rebuilding it step by step, what every line of code does, the HoduCC API, going live |
| **[docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)** | A shorter tour of the files and how each number is worked out |
| **[docs/BUILD_YOUR_OWN.md](docs/BUILD_YOUR_OWN.md)** | Learn to build a project like this from an empty folder, and what makes a project "standard" |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | See what to do next, in order |
| **[docs/CHANGELOG.md](docs/CHANGELOG.md)** | See how the project got here, round by round, and why each change was made |

---

## Quick start (about 10 minutes)

You need **Python 3.10 or newer** (https://python.org; on Windows tick "Add Python to PATH").
Open a terminal in this folder, then run the commands below in order.

### 1. Create a virtual environment

A virtual environment keeps this project's packages separate from the rest of your computer.

```bash
python -m venv .venv
```

Then switch it on. **Do this every time you open a new terminal.**

| Windows (PowerShell) | Windows (Git Bash, MSYS2) | Mac / Linux |
| --- | --- | --- |
| `.venv\Scripts\Activate.ps1` | `source .venv/Scripts/activate` | `source .venv/bin/activate` |

Your prompt now starts with `(.venv)`.

### 2. Install the packages

```bash
pip install -r requirements-dev.txt
```

That installs what the dashboard needs (`requirements.txt`) plus the developer tools: `ruff`
(the code checker), and Markdown and Pygments (for building the guide).
On a server, `pip install -r requirements.txt` is enough.

### 3. Create your settings file

Copy `.env.example` to a new file called `.env` (same folder). Leave `HODU_MOCK=1` for now,
which uses the saved sample instead of the real API.

| Windows | Mac / Linux |
| --- | --- |
| `copy .env.example .env` | `cp .env.example .env` |

### 4. Create the database and your login

```bash
python manage.py migrate
python manage.py createsuperuser
```

`migrate` creates the database file (`db.sqlite3`). `createsuperuser` asks for a username and password; this is your login.

### 5. Load some calls

```bash
python manage.py sync_calls --date 2026-10-05
```

### 6. Start the website

```bash
python manage.py runserver
```

Open http://127.0.0.1:8000, log in, and set both dates to **05/10/2026**.
You should see 9 calls in, 6 unanswered, a 33.3% answer ratio and a 20s average delay.

Stop the server with **Ctrl + C**.

---

## Switching to real HoduCC data

1. In `.env`: put your real `HODU_TOKEN` and `HODU_TENANT_ID`, and set `HODU_MOCK=0`.
2. Load the history you want, e.g. everything since 1 January: `python manage.py sync_calls --from 2026-01-01`
   (add `--to 2026-06-30` to stop earlier). It prints one line per day; a year takes a few minutes.
3. Start the website: `python manage.py runserver`. That's all.

   **History fills in by itself too.** The dashboard only has the days it has fetched. When someone looks
   at days it never fetched (say, last March on the Monthly page), it fetches them from HoduCC in the
   background and shows a purple progress bar; the numbers fill in as the days arrive. This is on unless
   `.env` says `HODU_AUTO_BACKFILL=0`. Step 2 just does it all at once, up front.

   **The dashboard is live by itself.** While it shows today, the server fetches new calls from
   HoduCC in the background (at most once a minute), and the page refreshes every 30 seconds.
   So new calls appear within about a minute and a half, with no sync to run.
   The "Right now" strip (waiting, on calls) is fresher still: 15–45 seconds.

4. Optional on your computer, recommended on a server: also sync on a schedule, so days nobody
   looked at are complete too. Either leave `python manage.py sync_calls --loop 300` running in a
   second terminal, or schedule `python manage.py sync_calls` (see "Going live" in the docs).

5. Give agents their real names: **Admin → Agents**, type each name in **Staff name**, press **Save**.
   HoduCC's own names are placeholders ("Agent 01"); the sync never changes the names you type.

If a sync fails, or no sync has worked for 15 minutes, the terminal says why and a red banner
shows on the dashboard, even on a screen that has been left open. A yellow banner means the sync
worked but had something to report. The full log is under **Admin → Sync runs**.

---

## Everyday commands

| Command | What it does |
| --- | --- |
| `python manage.py runserver` | Start the website on http://127.0.0.1:8000 |
| `python manage.py sync_calls` | Pull today's calls from HoduCC, plus any of the last 3 days not yet finished off |
| `python manage.py sync_calls --date 2026-10-05` | Pull one day (`05-10-2026` works too) |
| `python manage.py sync_calls --days 30` | Pull the last 30 days |
| `python manage.py sync_calls --from 2026-01-01` | Pull every day from a date to today (`--to 2026-06-30` to stop earlier) |
| `python manage.py sync_calls --loop 300` | Do the first command every 300 seconds until you press Ctrl+C |
| `python manage.py migrate` | Update the database tables after getting new code |
| `python manage.py test` | Run the 171 automatic checks (never calls HoduCC) |
| `ruff check .` | Check the code for mistakes and style problems (`--fix` repairs most) |
| `python manage.py createsuperuser` | Add another admin login |
| `python docs/guide/build_guide.py` | Rebuild the PDF guide from the code (needs Edge or Chrome) |

Other people can get a normal (non-admin) login: go to **Admin → Users → Add user**.
After 5 wrong passwords, a username has to wait 15 minutes before it can log in.

## Forgot password

The login page has a **Forgot password?** link. Someone types their work email; if it belongs to an account,
they get a link that works once, for an hour, to set a new password (which also lifts a lockout from wrong
passwords). Only **@dash-mfb.com** addresses are accepted (`PASSWORD_RESET_EMAIL_DOMAIN`), at most 3 requests
an hour per address, and the page never says whether an address has an account.

For it to work:

1. **Each person's account needs their email address**: Admin → Users → the person → Email address.
2. **Email must be set up in `.env`**, one of:
   - Microsoft 365: `MSGRAPH_TENANT_ID`, `MSGRAPH_CLIENT_ID`, `MSGRAPH_CLIENT_SECRET` (an app registered in Azure
     with the **Mail.Send** application permission) and `MSGRAPH_SENDER` (the mailbox it sends from);
   - or an ordinary mail server: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`.

   Until then, the email is printed in the terminal running the server, so you can try the whole flow.
3. On a server, set `DJANGO_PUBLIC_URL` (e.g. `https://calls.dash-mfb.com`) so the link points there.

## Admin (for the site's owner only)

Admin is where staff names are typed and the sync log is kept. **Only superusers can use it** (logins made
with `python manage.py createsuperuser`; yours is the only one), and the dashboard has no link to it. Open it by
typing its address: http://127.0.0.1:8000/admin/ on your computer. On a public server, give it an address
nobody would guess, in `.env`: `DJANGO_ADMIN_PATH=office-7f3k2/` (then it is at `/office-7f3k2/`).
Everyone else gets an ordinary login (made in Admin → Users → Add user, without "Staff status" or
"Superuser status"): they see the dashboard and nothing else.

---

## Project layout

```
callcentre/
├── manage.py                  Django's command runner
├── requirements.txt           Python packages the dashboard needs (exact versions)
├── requirements-dev.txt       ...plus tools for working on the code (ruff)
├── pyproject.toml             Project details and the code checker's rules
├── .env.example               Settings template (copy to .env)
├── .gitignore                 Files Git must never store (.env, database, real sample data)
├── .gitattributes             Keeps line endings the same on every computer
├── config/                    Project-wide setup
│   ├── settings.py            All settings; secrets come from .env
│   └── urls.py                Top-level address map
├── calls/                     The app that does the work
│   ├── models.py              Database tables: Call, AgentOffer, Agent, SyncRun
│   ├── client.py              Talks to the HoduCC API (and a mock for testing)
│   ├── parsing.py             Cleans HoduCC's raw values (dates, durations, phone numbers)
│   ├── sync.py                Copies calls from HoduCC into the database
│   ├── metrics.py             Works out every dashboard number
│   ├── views.py               Answers web requests (page + JSON)
│   ├── urls.py                Addresses for the views
│   ├── admin.py               Back-office screens at /admin
│   ├── lockout.py             Pauses logins after repeated wrong passwords
│   ├── management/commands/sync_calls.py   The sync_calls command
│   ├── migrations/            Changes to the tables, in order (0002 added staff names, 0003 why a call ended)
│   ├── templates/calls/dashboard.html      The dashboard page: a rail, a top bar and six pages
│   ├── static/calls/brand/    The company logo, the browser-tab icon and the phone home-screen icon
│   ├── static/calls/dashboard.css          Its styling
│   ├── static/calls/js/       The page's JavaScript: main.js (switching pages, refreshing), one file
│   │                          per page (overview, agents, agent, activity, monthly, live),
│   │                          charts.js (Chart.js set-up), fx.js (movement), format.js (helpers),
│   │                          drill.js (the calls behind a number), theme.js (light/dark switch)
│   ├── static/calls/vendor/   Chart.js 4.5.1, Motion 13.4.0, Lenis 1.3.26 (see README.txt there)
│   ├── static/calls/fonts/    The Plus Jakarta Sans typeface, with its licence
│   └── tests/                 Automatic checks
│       └── fixtures/          Saved HoduCC replies with made-up values, for the tests
├── templates/                 Shared page layout and the login page
├── sample/                    Your real saved replies (used when HODU_MOCK=1; not in Git)
└── docs/
    ├── Call-Centre-Dashboard-Guide.pdf   The full guide (built from the code)
    ├── guide/                 What the PDF is built from: build_guide.py, chapters/, notes/, images/
    ├── HOW_IT_WORKS.md        A shorter tour of the files
    ├── BUILD_YOUR_OWN.md      How to build a project like this, and what "standard" means
    ├── CHANGELOG.md           How the project got here, round by round, and why
    └── ROADMAP.md             What to do next
```

---

## Before other people use it

`runserver` is for your own computer only. To put this on a server for your team,
follow "Going live" in the guide (Part 5) or [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

**Privacy:** `sample/callhistory.json` contains real customer phone numbers. The database only ever
stores the last 4 digits, and `.gitignore` keeps the `sample/` folder out of Git, but delete or
anonymise that sample before sharing this folder any other way (zip, USB, shared drive).
The tests don't need it (they use `calls/tests/fixtures/`); only `HODU_MOCK=1` does.

---

## Version control (Git)

This folder is a Git repository: Git keeps every saved version of the code, so you can see what
changed, when, and undo mistakes. Nothing has been saved into it yet. To make the first save
(a "commit"), once:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git commit -m "First version of the call-centre dashboard"
```

After each piece of work: `git add -A` then `git commit -m "What you changed"`.
To put it on GitHub (privately): create an empty **private** repository there, then
`git remote add origin <its URL>` and `git push -u origin main`.

**Before you update the server**, run these four checks and make sure each one passes:

```powershell
python manage.py test                                # every test passes
ruff check .                                         # "All checks passed!"
python manage.py makemigrations --check --dry-run    # "No changes detected"
python docs/guide/build_guide.py --html              # the guide still matches the code
```
