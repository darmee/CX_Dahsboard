# Part 5 · Running, testing and going live

## Everyday commands

Run these in the project folder with the virtual environment switched on (`(.venv)` at the start of the prompt).

| Command | What it does |
| --- | --- |
| `python manage.py runserver` | Start the website on http://127.0.0.1:8000. While it shows today, it keeps itself up to date |
| `python manage.py sync_calls` | Fetch today's calls, plus any of the last 3 days not yet finished off, and the agent list |
| `python manage.py sync_calls --date 2026-10-05` | Fetch one day (`05-10-2026` works too) |
| `python manage.py sync_calls --days 30` | Fetch the last 30 days |
| `python manage.py sync_calls --from 2026-01-01` | Fetch every day from a date to today (add `--to 2026-06-30` to stop earlier) |
| `python manage.py sync_calls --loop 300` | Fetch every 300 seconds until Ctrl+C |
| `python manage.py createsuperuser` | Add a login with access to Admin |
| `python manage.py migrate` | Apply changes to the tables after updating the code |
| `python manage.py test` | Run every automatic test |
| `ruff check .` | Check the code for mistakes (`--fix` repairs most) |
| `python docs/guide/build_guide.py` | Rebuild this guide (HTML and PDF) from the code |

Other people get a normal login in **Admin → Users → Add user**. After 5 wrong passwords, a username has to
wait 15 minutes.

## Filling in history

The dashboard only knows the days it has fetched. The routine sync covers today and the 3 days before, so
on its own, history starts the day the dashboard was installed. Two ways to fill in the past:

- **All at once:** `python manage.py sync_calls --from 2026-01-01`. One line per day; a year takes a few
  minutes. Safe to run again: calls are updated, never doubled.
- **By itself:** with `HODU_AUTO_BACKFILL=1` (the default), looking at days that were never fetched, say
  last March on the Monthly page, fetches them from HoduCC in the background. A purple bar shows the
  progress, and the numbers fill in as the days arrive. Set `HODU_AUTO_BACKFILL=0` to switch it off.

Re-fetching a day also fills in details added to the dashboard later, such as why each call ended.

## Admin: for the owner only

Only superusers can open Admin (made with `python manage.py createsuperuser`), and the dashboard has no link to
it: type its address. On a public server, set `DJANGO_ADMIN_PATH` in `.env` to an address nobody would guess,
e.g. `office-7f3k2/`. Give everyone else an ordinary login (Admin → Users → Add user, leaving "Staff status" and
"Superuser status" unticked).

## Naming staff

1. Go to **Admin → Agents**. Every HoduCC login is listed (the sync adds new ones by itself).
2. Type the real name in **Staff name**, and optionally an employee number and team.
3. Press **Save** at the bottom.

The name now appears everywhere on the dashboard. The sync never changes these three fields. If someone takes
over a login, change the name; the earlier calls then show the new name too (the name belongs to the login, not to each call).

## Settings in `.env`

| Setting | Meaning |
| --- | --- |
| `DJANGO_DEBUG` | `1` on your computer, `0` on a server |
| `DJANGO_SECRET_KEY` | A long random secret. Make one with `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_ALLOWED_HOSTS` | The addresses the site answers to |
| `HODU_TOKEN`, `HODU_TENANT_ID` | Your HoduCC API details |
| `HODU_MOCK` | `1` = use the saved replies in `sample/`; `0` = the real API |
| `HODU_UNANSWERED_STATUSES` | Which statuses count as unanswered (default `ABANDONED,DROPPED,HANGUP`) |
| `HODU_SYNC_ON_VIEW_SECONDS` | Live mode: fetch at most this often while someone views today (default 60; 0 = off) |
| `DJANGO_ADMIN_PATH` | Admin's address (default `admin/`); superusers only |
| `HODU_AUTO_BACKFILL` | `1` = looking at never-fetched days fetches them in the background (default); `0` = off |
| `HODU_STALE_AFTER_SECONDS` | Show a red banner when no sync has worked for this long (default 900) |
| `HODU_LIVE_CACHE_SECONDS` | How long a live answer is reused (default 15) |

## Tests

```powershell
python manage.py test
```

171 tests run in a few seconds, in a temporary database; your real data isn't touched and HoduCC is
never called. They use `calls/tests/fixtures/`: saved replies with made-up phone numbers. Run them after
every change, and before updating the server, together with these three checks:

```powershell
ruff check .                                         # "All checks passed!"
python manage.py makemigrations --check --dry-run    # "No changes detected"
python docs/guide/build_guide.py --html              # the guide still matches the code
```

## Rebuilding this guide

```powershell
pip install -r requirements-dev.txt
python docs/guide/build_guide.py
```

The listings come from the code, and every explanation is pinned to a piece of a line's text. If you change
a line so its explanation no longer fits, the build stops with a message such as
`calls/client.py: no line containing 'payload = {' after line 74`. Update the explanation in
`docs/guide/notes/`, then build again.

## Going live on a server

1. In `.env`: `DJANGO_DEBUG=0`, a new `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS=dashboard.yourcompany.com`,
   `DJANGO_CSRF_TRUSTED_ORIGINS=https://dashboard.yourcompany.com`, `HODU_MOCK=0`.
2. `pip install -r requirements.txt`, then `python manage.py migrate` and `python manage.py collectstatic`.
3. Run a production server instead of `runserver`: on Linux `gunicorn config.wsgi`; on Windows
   `waitress-serve --port=8000 config.wsgi:application`.
4. Put HTTPS in front (nginx, IIS, or a host such as Render). Then set `DJANGO_BEHIND_PROXY=1`,
   `DJANGO_SSL_REDIRECT=1` and `DJANGO_HSTS_SECONDS=3600`, and run `python manage.py check --deploy`.
5. Schedule `python manage.py sync_calls` every 5 minutes (Linux cron, or Windows Task Scheduler), so days
   nobody watched are complete too.
6. Back up `db.sqlite3` every day. For many users or years of calls, move to PostgreSQL.

## When something goes wrong

| You see | It means | Do this |
| --- | --- | --- |
| Red banner "Last sync failed: … Token Authentication Failed" | The token is wrong or has expired | Ask HoduCC for a new one; put it in `.env`; restart |
| Yellow note "HoduCC's server was slow to answer" | HoduCC's server or the network was slow for a moment (each request is tried 3 times first) | Nothing; the next sync usually works. Red after 3 failures in a row: check the internet connection, then ask HoduCC |
| Red banner "No sync since …" | Nothing has fetched calls for 15 minutes | Open the dashboard on today, or check the scheduled sync |
| Yellow banner "Fetching the latest calls" | Live mode is catching up | Nothing; it clears on the next refresh |
| Yellow banner "Skipped N row(s) we couldn't read" | HoduCC sent a value in a new format | The message names it; fix the function in `parsing.py` |
| `400 Invalid Date Format` | A date was sent year-first | HoduCC needs `13-10-2026`; see `HODU_DATE` in `client.py` |
| Live tab: "HoduCC's live numbers aren't available" | The realtime request failed | Read the message; usually the token or the network |
| Agents show as "Agent 01" | No staff name entered yet | Admin → Agents |
| No calls before a certain date | Those days were never fetched | Wait for the purple history bar, or `python manage.py sync_calls --from 2026-01-01` |
| "Why it ended" shows "–" | Those calls were fetched before the reason was kept | `python manage.py migrate`, then re-fetch the days with `--from` |
| `no such table: calls_agent` | The tables haven't been updated | `python manage.py migrate` |
| Right password refused | 5 wrong tries locked that username | Wait 15 minutes, or restart the server |
| "CSRF verification failed" on the server | The site's https address isn't trusted | Set `DJANGO_CSRF_TRUSTED_ORIGINS` |
| Page without styling on the server | Static files not collected | `python manage.py collectstatic` |
| Charts missing, tables fine | Chart.js didn't load | Check `calls/static/calls/vendor/chart.umd.js` exists |
| Changes to CSS or JavaScript don't show | The server is still running the old code | Restart it; open dashboards then reload themselves |
| Two `runserver` windows open | Started twice | Close one: both answer on the same port, so requests go to either |
