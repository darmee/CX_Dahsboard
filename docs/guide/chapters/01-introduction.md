# Part 1 · Introduction

## What the dashboard does

The call centre runs on **HoduCC**, a hosted call-centre system. HoduCC records every call, but its own
screens don't answer the questions managers ask every day. This dashboard does:

- How many calls came in and went out today, last week, or for one queue?
- How many callers gave up before anyone answered, and how long had they waited?
- What share of inbound calls did we answer (the **answer ratio**)?
- How long do calls last, and how long are callers put on hold?
- How often does a call ring an agent who doesn't pick up (**rejections**)?
- What did each agent do today: calls taken, calls made, calls that didn't connect, missed rings?
- What is happening **right now**: callers waiting, agents on calls, agents idle?
- Which calls exactly are behind a number, and why did each one end?

It is a website. People log in with a username and password and see six pages, chosen from a slim rail in
the brand colour with the company logo at the top. Each page's filters sit in the top bar, its numbers in
compact tiles, and the rest of the screen goes to the charts. On a computer each page fits the screen without
scrolling; on a phone it scrolls.

On every page:

- **Click a number to see the calls behind it.** Tiles, bars in the charts and agents' rows open a panel that
  slides in from the right with those calls: when, the customer (only the last 4 digits are ever kept), in or
  out, the status, why it ended, the agent, and the wait, talk and hold times. Above the list: the most
  common reasons the calls ended, and who hung up (the agent, the customer, or the system).
- **Live** at the top: a pulsing dot, how often HoduCC's live numbers update (every 15 s), and a ring
  counting down to the next update.
- **Light or dark**: the sun/moon button switches; without a choice, the dashboard follows the computer.
- **History fills in by itself**: looking at days the dashboard never fetched starts fetching them from
  HoduCC in the background, with a progress bar.

![A drill-down: the calls out behind a tile, with who hung up. (“Why it ended” fills in once a day is synced with this version; the customer digits in this picture are made up.)](images/drill.png)

The Missed rings (agents) tile (and every missed-rings number) opens the rings behind it: each time a call rang an agent who didn't pick up, why, and who took the call in the end.

![Missed rings: the rings behind the Missed rings (agents) tile](images/rings.png)

### Overview

Numbers for any range of dates and any queue: calls in and out, unanswered calls, the answer ratio
(inbound calls answered) and the connect rate (outbound calls the customer picked up), average delay, hold
and talk time, rejections, a chart of calls by hour, and the top agents. Each tile shows how it changed
on the period before (▲ 12%): today against yesterday up to the same time of day, a week against the week
before. Green is better, red worse.

**Not connected** means a call out that the customer never picked up: no answer, busy, phone switched off, or
the line failed (HoduCC's status `DIAL`). The **answer ratio** is answered calls *in* ÷ all calls *in*; calls
out have their own number, the **connect rate**.

![The Overview page](images/overview.png)

### Agents

Who calls the most and who receives the most, for today, the last 7 days, this month, last month or any
range, under the **real staff name** you give each HoduCC login: the top caller and receiver, a
leaderboard across the page with every agent's calls made, connected, connect rate, received, missed rings
and talk time, and under it a ranking chart for calls made and one for calls received.

![The Agents page](images/agents.png)

### Agent detail

One agent over any range of up to 92 days: calls handled, answered in and out, connect rate, missed rings
and talk time, a bar for each day, and their latest calls.

![The Agent detail page](images/agent.png)

### Daily activity

One day as tables: every agent's numbers, and the call log, every call that day with each caller's number
shown as `•••` plus the last 4 digits.

![The Daily activity page](images/activity.png)

### Monthly

History, month by month: calls, answer ratio, connect rate, average talk and the busiest month, and a bar
chart with an inbound and an outbound bar for each month. Choose any range of up to 36 months, and a queue.

![The Monthly page](images/monthly.png)

### Live

What is happening now, refreshed every 15 seconds: callers waiting, agents on calls, agents logged in but
idle, and the same for each queue.

![The Live page](images/live.png)

Staff names are entered once, in the back office (**Admin → Agents**). Admin is for the site's owner only:
superusers get in, nobody else does, and the dashboard has no link to it.

![Naming staff in Admin](images/admin-agents.png)

## How it fits together

There are two jobs. One copies calls from HoduCC into our own database (the **sync**). The other is the
**website**, which reads only from our database. The one exception is the Live tab, which asks HoduCC directly
because it is about this very moment.

```text
   HoduCC (the call system, on the internet)
      │  getCallHistory, getAgentOfferedCalls, getAgentList        getRealtimeQueueSummary
      ▼                                                                      │
   client.py ──► parsing.py ──► sync.py ──► database (db.sqlite3)            │
   (talks to      (cleans the     (saves      Call, AgentOffer,               │
    HoduCC)        raw values)     them)       Agent, SyncRun                 │
                                                  │                          │
                                                  ▼                          ▼
                                             metrics.py ──► views.py ◄───────┘
                                             (counts and    (answers the browser:
                                              averages)      a page, or numbers as JSON)
                                                                 │
                                                                 ▼
                                    Browser: dashboard.html + dashboard.css + js/*.js + Chart.js
```

Why keep a copy of the calls instead of asking HoduCC every time?

- **Speed.** Our database answers in milliseconds; HoduCC takes seconds.
- **Any date range.** HoduCC's live figures only cover today. With every call stored, you can look at any period.
- **Being polite.** However many people watch the dashboard, HoduCC is asked at most once a minute.
- **It keeps working.** If HoduCC is down, everything up to the last sync is still there.

**Why can't the web page talk to HoduCC itself?** Every request to HoduCC carries the secret token.
Anything a web page has, anyone can read with "View source". So only the Python code on the server ever holds the token.

## How the numbers stay fresh

HoduCC never tells us about new calls; we have to ask. So "live" here means "about a minute behind":

| What | How fresh | How |
| --- | --- | --- |
| The Live page, and the Live badge on every page | Every 15 seconds | The server asks HoduCC's realtime summary, at most every 15 seconds; the badge's ring counts down to the next update |
| Everything else, while someone views today | About 1–1½ minutes | Each page refresh (every 30 s) lets the server start a background sync, at most once a minute ("live mode") |
| Days nobody looked at | When the next scheduled sync runs | `python manage.py sync_calls` on a timer (Part 5) |

## How to read this guide

- **Part 2** rebuilds the project from an empty folder, step by step, with every command.
- **Part 3** shows **every file**, in the order you would write them, with **every line numbered** and a table
  saying what each line does. Lines that only close a bracket, or are blank, are not explained.
- **Part 4** is what we learned about HoduCC's API by trying it, because its documentation isn't public.
- **Part 5** is everyday use, testing, putting it on a server, and fixing common problems.
- **The glossary** at the end explains every technical word used. If a word is new, look it up there.

The guide is built from the code itself (Part 5 shows how), so the listings always match the code in the folder.

## What you need to know first

Nothing beyond using a computer, but these help:

- **Python basics**: variables, `if`, `for`, functions, lists and dictionaries. The free official
  tutorial at docs.python.org covers them in an afternoon.
- **HTML and CSS basics**: what a tag and a style rule are.
- **The Django tutorial** (docs.djangoproject.com, "Writing your first Django app", parts 1–4). This project
  uses the same ideas: models, views, URLs and templates.
