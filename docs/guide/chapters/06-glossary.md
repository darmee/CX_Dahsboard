# Glossary

Words used in this guide and in the code, in alphabetical order.

| Word | Meaning |
| --- | --- |
| **Aggregate** | Working out one value from many rows: a count, a sum, an average. In Django: `.aggregate(...)` |
| **Annotate** | Adding a worked-out value to each row or group. With `.values(...)` first, it groups rows (like SQL `GROUP BY`) |
| **Answer ratio** | Calls *in* that were answered ÷ all calls in. Calls out don't count in it; they have the connect rate |
| **API** | A way for one program to ask another for data. HoduCC's API answers requests with JSON |
| **App (Django)** | One part of a Django project with its own models, views and templates. Here: `calls` |
| **`async` / `await`** | JavaScript keywords for waiting on something slow (such as a network request) without freezing the page |
| **Backend (authentication)** | The code Django asks "is this username and password right?". Ours is `LockoutBackend` |
| **Backfill (filling in history)** | Fetching past days the dashboard never fetched: `sync_calls --from 2026-01-01`, or by itself when someone looks at those days (`HODU_AUTO_BACKFILL`) |
| **Cache** | A short-term memory for answers, so the same work isn't repeated. We use Django's in-memory cache |
| **Chart.js** | A JavaScript library that draws charts on a `<canvas>` element. Version 4.5.1 |
| **Commit (Git)** | A saved snapshot of the project, with a message saying what changed |
| **Connect rate** | Calls *out* that the customer picked up ÷ all calls out |
| **Context (template)** | The dictionary of values a view gives a template to fill in |
| **CSRF** | A trick where another website submits a form as you. Django blocks it with a hidden token in each form (`{% csrf_token %}`) |
| **CSS variable** | A named value in CSS, such as `--good: #1f9d55`, used as `var(--good)` |
| **Decorator** | A line starting with `@` above a function that adds behaviour, e.g. `@login_required` |
| **Dictionary (dict)** | Python's set of named values: `{"name": "Ada", "calls": 9}` |
| **DOM** | The web page as objects JavaScript can read and change |
| **Drill-down** | Clicking a number to see what it is made of: here, the panel listing the calls behind a tile, bar or row |
| **Endpoint** | One named request an API offers, such as `getCallHistory` |
| **Environment variable** | A setting given to a program from outside its code. Ours come from `.env` |
| **Event delegation** | One event listener on a container that handles clicks on any of its rows, including rows added later |
| **Exception** | Python's way of signalling an error. `raise` throws one; `try`/`except` catches it |
| **`f`-string** | Python text with values inside braces: `f"{count} calls"` |
| **`fetch`** | The browser's function for requesting a URL from JavaScript |
| **Fixture** | Saved data the tests use instead of the real thing |
| **Foreign key** | A column pointing to a row in another table. (This project matches logins by text instead) |
| **Hangup reason** | HoduCC's word for why a call ended, e.g. `NORMAL_CLEARING`, or `Service Unavailable` for a call out that failed. Shown as "Why it ended" |
| **JSON** | A text format for data: `{"code": 200, "result": [...]}` |
| **Lenis** | A small library that makes scrolling smooth |
| **Lexer / syntax highlighting** | Colouring code by its parts (keywords, text, numbers). Done by Pygments in this guide |
| **Light / dark mode** | Two sets of colours for the same page. The dashboard follows the computer unless the sun/moon switch picks one, which the browser remembers (`localStorage`) |
| **List comprehension** | A one-line way to build a list: `[row["id"] for row in rows]` |
| **localStorage** | A small store in the browser where a page can keep a value between visits; here, the light/dark choice |
| **Lock (thread)** | Something only one thread can hold at a time; the others wait. Used so two background syncs never write to SQLite at once |
| **Logging** | Writing what the program did to the terminal or a file, to find problems later |
| **Management command** | A script run with `python manage.py <name>` that has Django fully loaded |
| **Middleware** | Code that every request passes through, e.g. security headers or sessions |
| **Migration** | A file describing a change to the database tables. `makemigrations` writes it, `migrate` applies it |
| **Mock** | A stand-in for something real (here, for HoduCC) so code can be tried and tested without it |
| **Model** | A Python class that is a database table. Each attribute is a column |
| **Module (JavaScript)** | A `.js` file that shares functions with `export` and uses others' with `import` |
| **Motion** | The animation library the dashboard uses (motion.dev): the plain-JavaScript version of Framer Motion |
| **Not connected** | A call out that the customer never picked up: no answer, busy, switched off, or the line failed. HoduCC's status `DIAL` |
| **ORM** | Writing database queries in Python (`Call.objects.filter(...)`) instead of SQL |
| **Period before** | The stretch of time just before the one shown, as long (yesterday for today), used for the ▲/▼ chips |
| **`Q` object** | A condition you can combine: `Q(status="AGENT") & Q(direction="INBOUND")` |
| **QuerySet** | A query that Django runs only when the results are needed |
| **Regular expression (regex)** | A pattern for matching text, e.g. `\(([^()]+)\)` finds text in brackets |
| **Session** | How Django remembers who is logged in, through a cookie |
| **SQLite** | A database stored in one file (`db.sqlite3`) that needs no server |
| **Static files** | Files sent to the browser unchanged: CSS, JavaScript, images |
| **Template** | An HTML file with gaps (`{{ value }}`) and tags (`{% if %}`) that Django fills in |
| **Thread** | A second line of work inside one program. Live mode syncs in a background thread |
| **Time zone aware** | A date and time that knows its time zone. Django stores them in UTC and shows them in Lagos time |
| **Token** | A secret string that proves who is asking. HoduCC's goes in every request |
| **Transaction** | A group of database changes saved all together, or not at all |
| **Upsert** | "Insert, or update if it's already there". `bulk_create(update_conflicts=True)` |
| **URL pattern** | A rule mapping an address, such as `api/agents/`, to a view |
| **View** | A Python function that receives a web request and returns a page or JSON |
| **Virtual environment** | A folder (`.venv`) holding this project's own Python packages |
| **WhiteNoise** | A package that lets Django serve its CSS, JavaScript and font itself, while developing and on a server |
