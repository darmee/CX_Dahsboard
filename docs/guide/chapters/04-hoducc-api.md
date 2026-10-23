# Part 4 · The HoduCC API: what we learned

HoduCC's API guide isn't public, so everything here was found by sending real requests (October 2026,
API version 2.1). When HoduCC gives you their guide, compare it with this and update both.

## How every request works

- The address is the API base, then the endpoint name:
  `https://hoducc.roitechisl.com/HoduCC_api/v2.1/getCallHistory`.
- Always **POST**, with a **JSON** body containing `token` and `tenant_id`, plus the endpoint's own fields.
- The token is a fixed value, kept in `.env` as `HODU_TOKEN`. There is no login request and no session.
  Whether tokens expire is unknown; if one stops working, every request answers "Token Authentication Failed".

The reply is JSON:

```text
{"code": 200, "status": "OK", "status_message": "Call History selected Successfully.", "result": {...}}
```

| Situation | What comes back | What our code does |
| --- | --- | --- |
| Success | `code` 200. `getRealtimeQueueSummary` sends it as text, `"200"` | `str(code) == "200"` covers both |
| Nothing found | An error code (e.g. 500) and a message such as "Call History does not found." | Treated as "no data" |
| A problem with your account | A message such as "Token Authentication Failed." | Raises `HoduError`, shown in the red banner |
| An endpoint that doesn't exist | HTTP 424 and `{"message": "Method Failed."}` | Raises `HoduError` |
| Too many requests in a row | After about 75 quick requests, the server dropped the connection | We ask at most about twice a minute |

**Dates are day first:** `"13-10-2026"`. `"2026-10-13"` and `"13/10/2026"` are refused with
"400 Invalid Date Format". Times inside replies look like `"13-10-2026 09:09:38"`; an empty time is
`"00-00-0000 00:00:00"`. Durations look like `"0:01:16"` or `"00:01:16"`.

## The endpoints we use

### getCallHistory: every call on a day

| Field sent | Value |
| --- | --- |
| `search_on_time` | `"START"` (search by when the call started). `"END"` is refused |
| `search_type` | `"DATE"` with `date: "DD-MM-YYYY"`, or `"DATETIME"` with `start_datetime` and `end_datetime` (`"DD-MM-YYYY HH:MM:SS"`) |

The result is numbered rows plus a total: `{"0": {...}, "1": {...}, "total": 20}`. We compared whole days with
hour-by-hour requests and found no rows missing. Only **finished** calls are listed.

| Field in each row | Meaning | Stored as |
| --- | --- | --- |
| `call_id` | HoduCC's ID for the call | `Call.call_id` |
| `call_type` | `INBOUND` or `OUTBOUND` | `direction` |
| `call_status` | `AGENT` answered (or, outbound, the customer picked up); `ABANDONED` caller gave up; `DROPPED`; `DIAL` outbound call that never connected | `status` |
| `queue_name`, `campaign_name` | e.g. `General` / `inbound`, `outbound` / `outgoing` | same names |
| `agent_username` | The agent's login, e.g. `Agent01` (empty if nobody answered) | `agent_username` |
| `caller_number`, `phone_number` | The customer's number | Only the last 4 digits: `caller_masked` |
| `call_start_time`, `call_hangup_time` | When the call started and ended | `started_at`, `ended_at` |
| `queue_wait_time` | How long the caller waited in the queue | `wait_seconds` |
| `agent_duration` | Time talking to the agent | `talk_seconds` |
| `hold_duration` | Time on hold | `hold_seconds` |
| `call_duration` | The whole call | `total_seconds` |
| `hangup_by` | `USER`, `AGENT` or `SYSTEM` | `hangup_by` |

Traps: `call_answer_time` and `answered_duration` are filled in **even for abandoned calls**, so they
can't tell you whether a call was answered; only `call_status` can. `agent_wait_time` is the agent's idle
time before the call, not the caller's wait. Other fields we receive but don't store yet:
`hangup_reason`, `disposition_*` (wrap-up), `mute_duration`, `transfer_id`, `callback_type`, `recording_path`.

### getAgentOfferedCalls: every time a call rang an agent

Same `search_type` and `date` as above. Each row:

| Field | Meaning |
| --- | --- |
| `aoc_call_id` | The call that rang |
| `aoc_agt_id` | The agent as `"Agent 01 (Agent01) "`: display name, then the login in brackets |
| `acd_id` | The queue, e.g. `General` |
| `aoc_offered_time`, `aoc_hangup_time` | When it started and stopped ringing |
| `aoc_hangup_reason` | e.g. `NORMAL_CLEARING`, `CALL_REJECTED` (agent declined), `ORIGINATOR_CANCEL` (caller hung up while it rang) |

### getAgentList: every agent login

No extra fields. **The rows are under `"Agents"`, not `"result"`.**

| Field | Stored? |
| --- | --- |
| `agt_id`, `agt_uname`, `agt_fname`, `agt_lname` | Yes: `hodu_id`, `username`, `hodu_name` (first + last) |
| `agt_email`, `agt_phone`, `agt_extension_number` | **No**: contact details we don't need |
| `agent_token` | **Never**: each agent's own secret |

In our HoduCC the names are placeholders ("Agent" "01"). Either correct them in HoduCC (the sync picks the
change up within an hour) or enter real names in **Admin → Agents**, which always win.

### getRealtimeQueueSummary: right now

No extra fields. The result has `agent_total_avg` (the whole call centre) and `agent_queue_details`
(one entry per queue), each with:

| Field | Meaning | Used? |
| --- | --- | --- |
| `live_waiting_calls` | Callers waiting in a queue now | Yes |
| `live_agent_calls` | Agents on a call now | Yes |
| `live_agent` | Agents logged in now | Yes; idle = logged in − on calls |
| `assiged_agent` (sic) | Agents assigned. The overall figure can say 0 while a queue says 3 | Per queue only |
| `total_call`, `total_agent_calls`, `total_abandoned_calls`, `total_failover_calls` | Today's calls, answered, abandoned, failed over | Yes |
| `awt`, `att` | Average wait and talk time (checked: they equal total ÷ calls) | Yes |
| `ttt`, `twt` | Total talk and wait time | No |
| `ltt`, `lwt`, `act`, `aact`, `tdt`, `adt` | Unclear: `lwt` was smaller than `awt`, so it isn't "longest wait" | No, until HoduCC explains them |
| `answered_ratio`, `abandoned_ratio`, `sla_*`, `per_*_within_x_sec` | Percentages; the threshold behind "x sec" is unknown | No |

### getQueueDetails

Exists (see `sample/queueDetails.json`) and gives similar per-queue figures. Not used.

## What the API doesn't seem to have

We tried about twenty likely names (getLiveCalls, getActiveCalls, getAgentStatus, getRealtimeAgentStatus,
getAgentBreakReport, getAgentLoginLogoutReport, and others). All answered "Method Failed". So, as far as we
can tell, there is **no list of the calls in progress** and **no per-agent live status** (on a call, ready,
on a break). The Live tab therefore shows counts. If HoduCC's guide names such endpoints, they can be added.

## Questions to ask HoduCC

1. Does the API token expire, or depend on someone staying logged in to the portal?
2. Is there a limit on rows per reply, and how many requests per minute are allowed?
3. Is there an endpoint for calls in progress, or for each agent's live status and breaks?
4. What do `ltt`, `lwt`, `act`, `aact`, `tdt` and `adt` mean, and what is "x" in `per_answered_within_x_sec`?
5. What are all the possible `call_status` values?
