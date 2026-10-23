# Part 2 · Rebuild it, step by step

Follow these steps in order, in an empty folder, and you end up with this project. Each step names the
files to write; their full text, line by line, is in **Part 3** under the same file name. Type them out
rather than copying: you learn far more that way. After each step, do the **check** before moving on.

Commands are shown for **Windows PowerShell**. On Git Bash use `source .venv/Scripts/activate` to switch the
virtual environment on; on Mac or Linux, `source .venv/bin/activate`, and `python3` instead of `python`.

## Step 0 · What to have ready

- **Python 3.10 or newer** from python.org. On Windows, tick "Add Python to PATH" in the installer.
- **Git** from git-scm.com, and an editor such as **Visual Studio Code**.
- **Microsoft Edge or Google Chrome** (to view the dashboard, and to build this guide's PDF).
- From HoduCC: the **API address**, your **token** and your **tenant ID**.
- **Postman** (or `curl`) to try the API by hand before writing code.

> **Check:** `python --version` prints 3.10 or higher, and `git --version` prints a version.

## Step 1 · Try the API by hand, and save what comes back

Before any code, send one request in Postman: `POST` to `<API address>/getCallHistory` with this JSON body:

```json
{"token": "your token", "tenant_id": "your tenant id",
 "search_on_time": "START", "search_type": "DATE", "date": "05-10-2026"}
```

Save the reply as `sample/callhistory.json`. Read it slowly: field names, how dates and durations are
written, what an empty value looks like. Part 4 lists everything we found. This saved reply lets you build
and test without the network.

> **Check:** you have `sample/callhistory.json` and can see `"code": 200` and a list of calls in it.

## Step 2 · An empty, tidy project folder

```powershell
mkdir callcentre; cd callcentre
git init -b main
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Write `requirements.txt` and `requirements-dev.txt` (Part 3), then:

```powershell
pip install -r requirements-dev.txt
```

Write `.gitignore` and `.gitattributes` **now, before the first commit**, so the secrets file, the database
and the real sample data can never reach Git. Write `pyproject.toml` too: it holds the code checker's rules.

> **Check:** your prompt starts with `(.venv)`, and `pip list` shows Django, requests and ruff.

## Step 3 · The Django skeleton and the settings

```powershell
django-admin startproject config .
python manage.py startapp calls
```

The dot after `config` matters: it puts `manage.py` in this folder instead of a subfolder.
`startproject` creates `manage.py` and the `config` folder (`settings.py`, `urls.py`, `wsgi.py`, `asgi.py`).
`startapp` creates the `calls` folder.

Now replace `config/settings.py` with the version in Part 3. It reads every secret from a `.env` file.
Write `.env.example` (Part 3), copy it to `.env`, and set `HODU_MOCK=1` for now.
Also write `config/urls.py` and `calls/apps.py`.

> **Check:** `python manage.py check` says "System check identified no issues".

## Step 4 · The tables (models)

Write `calls/models.py`: the tables `Call`, `AgentOffer`, `Agent` and `SyncRun`. Then:

```powershell
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

`makemigrations` writes `calls/migrations/0001_initial.py`, the instructions for creating the tables.
`migrate` carries them out and creates `db.sqlite3`. `createsuperuser` makes your first login.

If you are rebuilding this project exactly, write `models.py` without the `Agent` class and the
`agent_username` field of `AgentOffer` first, run the commands above, then follow Step 13. That way
you also learn how a later change to the tables is made.

> **Check:** `python manage.py showmigrations calls` lists `[X] 0001_initial`.

## Step 5 · Talking to HoduCC

Write `calls/client.py`. It is the only file that knows HoduCC's address and token. It has a real client and
a **mock** client that reads your saved replies from `sample/`.

> **Check:** `python manage.py shell -c "from calls.client import get_client; print(get_client().get_call_history(__import__('datetime').date(2026,10,5))[1])"`
> prints the number of calls in your sample.

## Step 6 · Cleaning the raw values, with tests

Write `calls/parsing.py` (dates, durations, masking phone numbers, agent logins), then
`calls/tests/__init__.py` (empty) and `calls/tests/test_parsing.py`.

```powershell
python manage.py test calls.tests.test_parsing
```

> **Check:** all tests pass ("OK").

## Step 7 · Copying calls in (sync)

Write `calls/sync.py`, then the command: create the folders `calls/management/` and
`calls/management/commands/`, each with an empty `__init__.py`, and write `sync_calls.py` inside.

```powershell
python manage.py sync_calls --date 2026-10-05
```

> **Check:** it prints `OK 2026-10-05: 9 calls` (or however many your sample has).

## Step 8 · Working out the numbers

Write `calls/metrics.py`. Every number on the dashboard is worked out here, by the database.

> **Check:** `python manage.py shell -c "from datetime import date; from calls.metrics import compute_metrics; print(compute_metrics(date(2026,10,5), date(2026,10,5))['totals'])"`

## Step 9 · Logins and protection against password guessing

Write `calls/lockout.py`. `config/settings.py` already names it in `AUTHENTICATION_BACKENDS`, and
`calls/apps.py` switches on its failure counting.

## Step 10 · Views and addresses

Write `calls/views.py` and `calls/urls.py`. `config/urls.py` (Step 3) already sends every other address to
`calls/urls.py`.

## Step 11 · The pages

Create `templates/base.html` and `templates/registration/login.html` (project-wide), and
`calls/templates/calls/dashboard.html`.

## Step 12 · Styling, scripts and charts

Create `calls/static/calls/dashboard.css` and the scripts in `calls/static/calls/js/`:
`format.js`, `charts.js`, `fx.js`, one file per page (`overview.js`, `agents.js`, `agent.js`, `activity.js`,
`monthly.js`, `live.js`) and `main.js`.

Download the libraries and the typeface into the project, so the dashboard doesn't depend on another website:

```powershell
mkdir calls\static\calls\vendor, calls\static\calls\fonts
curl.exe -L -o calls\static\calls\vendor\chart.umd.js https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.js
curl.exe -L -o calls\static\calls\vendor\motion.js https://cdn.jsdelivr.net/npm/motion@13.4.0/dist/motion.js
curl.exe -L -o calls\static\calls\vendor\lenis.min.js https://cdn.jsdelivr.net/npm/lenis@1.3.26/dist/lenis.min.js
curl.exe -L -o calls\static\calls\vendor\lenis.css https://cdn.jsdelivr.net/npm/lenis@1.3.26/dist/lenis.css
curl.exe -L -o calls\static\calls\fonts\plus-jakarta-sans-latin.woff2 https://cdn.jsdelivr.net/npm/@fontsource-variable/plus-jakarta-sans@5.3.0/files/plus-jakarta-sans-latin-wght-normal.woff2
```

```powershell
python manage.py runserver
```

> **Check:** open http://127.0.0.1:8000, log in, set both dates to 05/10/2026 and press Update.
> With the sample you see 9 calls in, a 33.3% answer ratio and a 20s average delay.

## Step 13 · Agents and staff names (a change to existing tables)

Add the `Agent` class and `AgentOffer.agent_username` to `models.py` (if you held them back in Step 4), then:

```powershell
python manage.py makemigrations calls --name agents
```

Open the new `calls/migrations/0002_agents.py` and add the `fill_agent_username` function and the
`migrations.RunPython(...)` line, as in Part 3. That fills in the new column for rings saved earlier.

```powershell
python manage.py migrate
```

Write `calls/admin.py`. In the browser, go to **Admin → Agents** and type each agent's real name.

> **Check:** the Agents page shows the names you typed.

## Step 14 · The full test suite and the code checker

Write the remaining test files and `calls/tests/fixtures/` (saved replies with **made-up** phone numbers,
so the tests never need real data).

```powershell
python manage.py test
ruff check .
```

> **Check:** every test passes and ruff says "All checks passed!".

## Step 15 · Switch to the real API

In `.env`: put your real `HODU_TOKEN` and `HODU_TENANT_ID`, set `HODU_MOCK=0`, then load the last month:

```powershell
python manage.py sync_calls --days 30
python manage.py runserver
```

With the dashboard open on today, new calls appear by themselves within about a minute and a half.

## Step 16 · Save your work

```powershell
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git add -A
git commit -m "Call-centre dashboard"
```

Commit after every step from now on. To keep a copy on GitHub, create an empty **private** repository there,
then `git remote add origin <its address>` and `git push -u origin main`. GitHub then runs the tests on every push.
