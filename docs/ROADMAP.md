# What's next

In order. Each item says why it matters and roughly how big it is.
Tick items off by editing this file and committing.

## Now: before anyone else relies on it

- [ ] **Make the first Git commit, then push to a private GitHub repository.** Until then there is no backup
      and no history. *(10 minutes; commands in the README, "Version control".)*
- [ ] **Give every agent their real name** in **Admin → Agents** (Staff name, and team if useful).
      HoduCC's names are placeholders, so until then the Agents page shows "Agent 01". *(10 minutes.)*
- [ ] **Ask HoduCC these questions**, and note the answers in Part 4 of the guide (`docs/guide/chapters/04-hoducc-api.md`):
  - Does the API token expire, or depend on someone's portal login? If it does, can we have one for system use?
  - Is there a limit on rows per reply for `getCallHistory`, and how do we page through more?
  - How many requests may we make per minute? (Their server dropped the connection after about 75 quick requests.)
  - Can we have the full API guide? It will show what else we could add (agent status, breaks, dispositions).
  - Is there an endpoint for **calls in progress** and for **each agent's live status** (on a call, ready, on a break)?
    We tried about twenty likely names and found none; with one, the Live tab could list them.
- [ ] **Agree the definitions with whoever reads the dashboard.** Write the answers into section 5 of HOW_IT_WORKS.md.
  - Should `ORIGINATOR_CANCEL` count as a rejection? (It usually means the caller hung up while it rang.)
  - Is 80% the right answer-ratio target?
  - Should inbound calls with other statuses count against the answer ratio?
- [ ] **Keep a sync running on a schedule** (Task Scheduler on Windows, every 5 minutes), so days nobody looked at
      are complete. Live mode only fetches while someone is watching today. *(30 minutes.)*

## Next: more useful numbers, no new API calls needed

- [ ] **Service level:** % of inbound calls answered within 20 seconds, the standard call-centre target. *(Small.)*
- [ ] **Average speed of answer** and **wrap-up time** (`disposition_duration`). Needs two new stored fields; follow
      the recipe "Store a new field from HoduCC" in HOW_IT_WORKS.md section 6. *(Small–medium.)*
- [ ] **Download as CSV** for the selected dates, for people who want it in Excel. *(Small.)*
- [ ] **Agent hours:** time between each agent's first and last call, and the share of it spent talking.
      A rough "busy %" until HoduCC's login/break data is available. *(Small.)*

## Later: when more people use it

- [ ] **Put it on a server** following HOW_IT_WORKS.md section 8, with HTTPS. *(Half a day to a day.)*
- [ ] **Back up the database** daily. With SQLite, that is copying `db.sqlite3` somewhere safe. *(Small.)*
- [ ] **Switch to PostgreSQL** once several people use it or you keep years of calls. *(Medium.)*
- [ ] **Decide how long to keep call records**, in line with your company's data-protection rules,
      and delete older ones automatically. *(Small, once decided.)*
- [ ] **Per-team access:** let a supervisor see only their queue. *(Medium.)*
- [ ] **Error alerts:** an email or message when syncing has failed for an hour, instead of waiting for
      someone to see the red banner. *(Small–medium.)*
- [ ] **Faster rejection numbers over long ranges:** work them out in the database instead of in Python. *(Medium.)*

## Done

- [x] Overview, Agents (daily activity per agent, with staff names) and Live (per queue) tabs, with Chart.js charts.
- [x] Six pages in the brand colour, each fitting the screen on a computer: Overview, Agents, Agent detail,
      Daily activity, Monthly (history as a bar chart) and Live. Outbound connect rate alongside the answer ratio.
- [x] Agents ranked over any period (who calls and who receives the most), and per month; a Live badge with
      its update interval and countdown; movement (Motion) and smooth scrolling (Lenis); a page that reloads
      itself when the server's code changes.
- [x] Live mode: today's numbers update by themselves while the dashboard is open.
- [x] History filled in from 22 April 2026.
- [x] Ready for public use: Admin for superusers only, at an address you choose, with no link from the dashboard.
- [x] The layout of the reference design: a slim rail with the logo, filters in the top bar, compact tiles, big
      charts with their values written on them, ring charts with counts and shares.
- [x] Outbound connected vs not connected, and the connect rate, on every page.
- [x] Drill-down: click any tile, bar or agent to see the calls behind it, with why each ended
      (`hangup_reason`, stored since migration 0003) and who hung up.
- [x] ▲/▼ against the period before on the Overview tiles; light and dark mode with a switch; a leaderboard
      that leads the Agents page; one colour per meaning in every chart, checked for colour-blind readers.
- [x] History: `sync_calls --from/--to`, and filling in never-fetched days by itself (`HODU_AUTO_BACKFILL`).
- [x] [CHANGELOG.md](CHANGELOG.md): how the project got here, round by round.
- [x] The PDF guide, rebuilt from the code with `python docs/guide/build_guide.py`.
