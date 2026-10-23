"""
Metrics: turn the calls in our database into dashboard numbers.

All the counting and averaging is done by the database (Django's ORM),
which is fast even with hundreds of thousands of calls.

    numbers = compute_metrics(date(2026, 10, 5), date(2026, 10, 5))
    numbers["totals"]["answer_ratio_pct"]   # 33.3

How each metric is defined:
    Calls in / out    direction = INBOUND / OUTBOUND
    Answered          status = AGENT
    Unanswered        status in HODU_UNANSWERED_STATUSES (ABANDONED, DROPPED)
    Answer ratio      answered inbound / all inbound x 100
    Connect rate      answered outbound (the customer picked up) / all outbound x 100
    Delay             wait_seconds (queue_wait_time) of inbound calls. Averaged separately
                      for answered calls and for calls where the customer gave up.
    Hold              hold_seconds, averaged over calls that were put on hold
    Rejection         rings (AgentOffer) that the agent did not take; time = ring length

    Not connected     outbound calls the customer never picked up (HoduCC's status DIAL: no answer,
                      busy, switched off, or the line failed)
    Period before     the same totals for the period just before, as long (yesterday for today), for
                      the "▲ 12%" chips; while the period includes today, cut at the same time of day

The Monthly tab (monthly) uses the same definitions, month by month.
The drill-down (call_list) lists the calls behind any of these numbers; CALL_KINDS names the lists.

Per agent, over any range (agent_rows), and one agent over a date range (agent_detail):
    Answered in       inbound calls the agent answered          (INBOUND, status AGENT)
    Answered out      outbound calls the customer picked up     (OUTBOUND, status AGENT)
    Not connected     outbound calls that never connected       (OUTBOUND, any other status, e.g. DIAL)
    Made / received   every outbound call they dialled / every inbound call they answered
    Missed rings      rings to the agent that they didn't take  (see Rejection)
"""
from collections import Counter
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.db.models.functions import ExtractHour, Lower, TruncDate, TruncMonth
from django.utils import timezone

from .models import Agent, AgentOffer, Call

ANSWERED = Q(status="AGENT")
INBOUND = Q(direction=Call.Direction.INBOUND)
OUTBOUND = Q(direction=Call.Direction.OUTBOUND)


def _unanswered():
    return Q(status__in=settings.HODU["UNANSWERED_STATUSES"])


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else None


def _round(value):
    return round(value) if value is not None else None


def _between(field, start, end):
    """
    A filter for "between two dates (inclusive), in the display time zone".
    Written as plain time comparisons so the database can use the index on the field.
    """
    first = timezone.make_aware(datetime.combine(start, time.min))
    after_last = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))
    return Q(**{f"{field}__gte": first, f"{field}__lt": after_last})


def _same_login(a, b):
    """Logins match whatever the capitals: "agent01" is "Agent01"."""
    return bool(a) and bool(b) and a.casefold() == b.casefold()


def _login_key(login):
    """A login in small letters, so "agent01" and "Agent01" group as one agent. Matches the database's Lower()."""
    return login.lower()


def agent_names():
    """{login key: name to show} for every agent we know. See Agent.display_name and _login_key."""
    return {_login_key(a.username): a.display_name for a in Agent.objects.all()}


def calls_in_range(start, end, queue=None):
    """Calls that started between two dates (inclusive), in the display time zone."""
    qs = Call.objects.filter(_between("started_at", start, end))
    if queue:
        qs = qs.filter(queue_name=queue)
    return qs


def compute_metrics(start, end, queue=None):
    calls = calls_in_range(start, end, queue)
    unanswered = _unanswered()
    names = agent_names()

    # One query that counts and averages everything at once.
    t = calls.aggregate(
        total=Count("id"),
        inbound=Count("id", filter=INBOUND),
        outbound=Count("id", filter=OUTBOUND),
        answered=Count("id", filter=ANSWERED),
        answered_inbound=Count("id", filter=ANSWERED & INBOUND),
        answered_outbound=Count("id", filter=ANSWERED & OUTBOUND),
        unanswered=Count("id", filter=unanswered),
        unanswered_inbound=Count("id", filter=unanswered & INBOUND),
        abandoned=Count("id", filter=Q(status="ABANDONED")),
        dropped=Count("id", filter=Q(status="DROPPED")),
        # Waiting in the queue only happens to inbound calls; outbound ones would drag the average down.
        avg_wait_answered=Avg("wait_seconds", filter=ANSWERED & INBOUND),
        max_wait_answered=Max("wait_seconds", filter=ANSWERED & INBOUND),
        avg_wait_unanswered=Avg("wait_seconds", filter=unanswered & INBOUND),
        avg_talk=Avg("talk_seconds", filter=ANSWERED),
        avg_hold=Avg("hold_seconds", filter=ANSWERED & Q(hold_seconds__gt=0)),
        held=Count("id", filter=ANSWERED & Q(hold_seconds__gt=0)),
        total_hold=Sum("hold_seconds"),
    )

    return {
        "totals": {
            "calls": t["total"],
            "inbound": t["inbound"],
            "outbound": t["outbound"],
            "answered": t["answered"],
            "answered_inbound": t["answered_inbound"],
            "answered_outbound": t["answered_outbound"],
            "unanswered": t["unanswered"],
            "abandoned": t["abandoned"],
            "dropped": t["dropped"],
            # Inbound calls that are neither answered nor unanswered (IVR only, still in progress, ...).
            # They count in the answer ratio's "all inbound", so the page shows how many there are.
            "other_inbound": t["inbound"] - t["answered_inbound"] - t["unanswered_inbound"],
            "answer_ratio_pct": _pct(t["answered_inbound"], t["inbound"]),
            "unanswered_ratio_pct": _pct(t["unanswered_inbound"], t["inbound"]),
            "connect_ratio_pct": _pct(t["answered_outbound"], t["outbound"]),
        },
        "timing": {
            "avg_wait_answered_sec": _round(t["avg_wait_answered"]),
            "longest_wait_answered_sec": t["max_wait_answered"],
            "avg_wait_before_giving_up_sec": _round(t["avg_wait_unanswered"]),
            "avg_talk_sec": _round(t["avg_talk"]),
            "avg_hold_sec": _round(t["avg_hold"]),
            "calls_put_on_hold": t["held"],
            "total_hold_sec": t["total_hold"] or 0,
        },
        "previous": previous_totals(start, end, queue),
        "rejection": rejection_stats(start, end, queue),
        "hourly": hourly(calls),
        "agents": per_agent(calls, names),
    }


def previous_totals(start, end, queue=None):
    """
    The main totals for the period just before this one, as long as it (e.g. yesterday, for today), so the
    Overview's tiles can show "up 12% on the day before".

    While the period is still going (it includes today), the period before stops at the same time of day,
    so at 9:00 today is compared with yesterday up to 9:00, not with all of yesterday.
    """
    length = end - start + timedelta(days=1)
    first, last = start - length, start - timedelta(days=1)
    calls = calls_in_range(first, last, queue)
    until = None
    now = timezone.localtime()
    if end >= now.date():
        cut = now - length
        calls = calls.filter(started_at__lt=cut)
        until = cut.strftime("%H:%M")
    t = calls.aggregate(
        inbound=Count("id", filter=INBOUND),
        outbound=Count("id", filter=OUTBOUND),
        answered_inbound=Count("id", filter=ANSWERED & INBOUND),
        answered_outbound=Count("id", filter=ANSWERED & OUTBOUND),
        unanswered=Count("id", filter=_unanswered()),
        avg_wait=Avg("wait_seconds", filter=ANSWERED & INBOUND),
        avg_talk=Avg("talk_seconds", filter=ANSWERED),
    )
    return {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "until": until,  # "09:00" when cut at the time of day (see above), else None
        "inbound": t["inbound"],
        "outbound": t["outbound"],
        "unanswered": t["unanswered"],
        "answer_ratio_pct": _pct(t["answered_inbound"], t["inbound"]),
        "connect_ratio_pct": _pct(t["answered_outbound"], t["outbound"]),
        "avg_wait_answered_sec": _round(t["avg_wait"]),
        "avg_talk_sec": _round(t["avg_talk"]),
    }


def hourly(calls):
    """Calls per hour of the day (0-23), in the display time zone."""
    rows = (
        calls.annotate(hour=ExtractHour("started_at"))
        .values("hour")
        .annotate(
            inbound=Count("id", filter=INBOUND),
            outbound=Count("id", filter=OUTBOUND),
            # Inbound only: outbound calls have their own bar on the chart.
            answered=Count("id", filter=ANSWERED & INBOUND),
            unanswered=Count("id", filter=_unanswered() & INBOUND),
        )
    )
    by_hour = {r["hour"]: r for r in rows}
    empty = {"inbound": 0, "outbound": 0, "answered": 0, "unanswered": 0}
    return [{**empty, **by_hour.get(h, {}), "hour": h} for h in range(24)]


def per_agent(calls, names):
    rows = (
        calls.filter(ANSWERED)
        .exclude(agent_username="")
        .values(login=Lower("agent_username"))  # one row per agent, whatever the capitals
        .annotate(
            spelled=Min("agent_username"),
            answered=Count("id"),
            avg_talk=Avg("talk_seconds"),
            avg_hold=Avg("hold_seconds"),
            avg_wait=Avg("wait_seconds"),
        )
        .order_by("-answered")
    )
    return [
        {
            "agent": r["spelled"],
            "name": names.get(r["login"], r["spelled"]),
            "answered": r["answered"],
            "avg_talk_sec": _round(r["avg_talk"]),
            "avg_hold_sec": _round(r["avg_hold"]),
            "avg_wait_sec": _round(r["avg_wait"]),
        }
        for r in rows
    ]


def recent(calls, names, limit=200):
    fields = ["call_id", "started_at", "direction", "status", "queue_name", "agent_username",
              "caller_masked", "wait_seconds", "talk_seconds", "hold_seconds", "hangup_by", "hangup_reason"]
    rows = list(calls.order_by("-started_at").values(*fields)[:limit])
    # A call nobody answered has no agent, but it may have rung some before the caller hung up:
    # `rang` lists them (from the rings, AgentOffer), so the page can say who it went to.
    nobody = [row["call_id"] for row in rows if not row["agent_username"]]
    rang = {}
    for call_id, login in (AgentOffer.objects.filter(call_id__in=nobody).order_by("offered_at")
                           .values_list("call_id", "agent_username")):
        name = names.get(_login_key(login), login)
        if name not in rang.setdefault(call_id, []):
            rang[call_id].append(name)
    for row in rows:
        row["agent_name"] = names.get(_login_key(row["agent_username"]), row["agent_username"])
        row["rang"] = rang.get(row["call_id"], [])
    return rows


def _missed_rings(offers):
    """
    Returns (rings in `offers` that nobody picked up, how many rings there were).
    Each missed ring is a dict with agent_username, ring_seconds and hangup_reason.

    A ring counts as picked up only if it is the last time the call rang the agent
    who ended up answering it. Every other ring is a rejection or a miss.
    """
    answered_by = dict(
        Call.objects.filter(ANSWERED, call_id__in=offers.values("call_id"))
        .values_list("call_id", "agent_username")
    )
    rings = list(
        offers.order_by("offered_at").values("id", "call_id", "agent_username", "offered_at", "ring_seconds",
                                             "hangup_reason")
    )
    # call_id -> the one ring that was picked up. Going through in time order,
    # a later ring to the same agent replaces an earlier one.
    picked_up = {}
    for ring in rings:
        if _same_login(answered_by.get(ring["call_id"]), ring["agent_username"]):
            picked_up[ring["call_id"]] = ring["id"]
    missed = [ring for ring in rings if picked_up.get(ring["call_id"]) != ring["id"]]
    return missed, len(rings)


def rejection_stats(start, end, queue=None):
    """
    Rings that weren't picked up, for the Rejections tile.
    Returns None when we have no offer data at all (endpoint not synced yet).
    """
    if not AgentOffer.objects.exists():
        return None

    offers = AgentOffer.objects.filter(_between("offered_at", start, end))
    if queue:
        offers = offers.filter(call_id__in=calls_in_range(start, end, queue).values("call_id"))

    missed, offered = _missed_rings(offers)
    reasons = {}
    for ring in missed:
        reason = ring["hangup_reason"] or "UNKNOWN"
        reasons[reason] = reasons.get(reason, 0) + 1
    ring_times = [ring["ring_seconds"] for ring in missed if ring["ring_seconds"] is not None]
    return {
        "offered": offered,
        "rejected_or_missed": len(missed),
        "avg_ring_before_reject_sec": round(sum(ring_times) / len(ring_times)) if ring_times else None,
        "reasons": reasons,
    }


def ring_list(start, end, queue=None, agent=None, limit=500):
    """
    The rings behind the Rejections tile and the missed-rings numbers (a drill-down, like call_list):
    rings to an agent that weren't picked up (see _missed_rings), newest first, optionally for one queue and one
    agent. Each comes with the call it belonged to: the customer, how the call ended, and who answered it in the
    end (often someone else). Returns how many there are, the latest `limit`, and the most common reasons.
    """
    offers = AgentOffer.objects.filter(_between("offered_at", start, end))
    if queue:
        offers = offers.filter(call_id__in=calls_in_range(start, end, queue).values("call_id"))
    missed, _ = _missed_rings(offers)
    if agent:
        missed = [ring for ring in missed if _same_login(ring["agent_username"], agent)]
    shown = sorted(missed, key=lambda ring: ring["offered_at"], reverse=True)[:limit]
    calls = {
        c["call_id"]: c for c in Call.objects.filter(call_id__in=[ring["call_id"] for ring in shown])
        .values("call_id", "direction", "status", "agent_username", "caller_masked")
    }
    names = agent_names()
    rows = []
    for ring in shown:
        call = calls.get(ring["call_id"], {})
        taken_by = call.get("agent_username") or ""
        rows.append({
            "call_id": ring["call_id"],
            "offered_at": ring["offered_at"],
            "agent_name": names.get(_login_key(ring["agent_username"]), ring["agent_username"]),
            "ring_seconds": ring["ring_seconds"],
            "hangup_reason": ring["hangup_reason"],
            "caller_masked": call.get("caller_masked", ""),
            "direction": call.get("direction", ""),
            "call_status": call.get("status", ""),
            "answered_by": names.get(_login_key(taken_by), taken_by) if taken_by else "",
        })
    reasons = Counter(ring["hangup_reason"] for ring in missed)
    return {
        "total": len(missed),
        "rings": rows,
        "reasons": [{"reason": reason, "count": n} for reason, n in reasons.most_common(6)],
    }


def agent_rows(start, end, queue=None):
    """
    What each agent did between two dates (inclusive), one dict per agent, busiest first.
    Used by the Agents page (any range), Daily activity (one day) and Monthly (a range of months).

    Every active agent is listed, even with no calls, so you can see who wasn't taking any.
    Logins are matched whatever the capitals, so "agent01" in the rings and "Agent01" in the calls are one row.
    "made" is every outbound call they dialled; "received" is every inbound call they answered.
    """
    calls = calls_in_range(start, end, queue).exclude(agent_username="").annotate(login=Lower("agent_username"))
    known = {_login_key(a.username): a for a in Agent.objects.all()}

    # One query: per login, count and add up everything at once (GROUP BY the login in small letters).
    per_login = {
        r["login"]: r
        for r in calls.values("login").annotate(
            spelled=Min("agent_username"),
            answered_in=Count("id", filter=ANSWERED & INBOUND),
            answered_out=Count("id", filter=ANSWERED & OUTBOUND),
            not_connected_out=Count("id", filter=OUTBOUND & ~ANSWERED),
            talk=Sum("talk_seconds", filter=ANSWERED),
            hold=Sum("hold_seconds", filter=ANSWERED),
            first_call=Min("started_at"),
            last_call=Max("started_at"),
        )
    }

    offers = AgentOffer.objects.filter(_between("offered_at", start, end))
    if queue:
        offers = offers.filter(call_id__in=calls_in_range(start, end, queue).values("call_id"))
    missed_by_login, ring_spelling = {}, {}
    missed, _ = _missed_rings(offers)
    for ring in missed:
        login = _login_key(ring["agent_username"])
        missed_by_login[login] = missed_by_login.get(login, 0) + 1
        ring_spelling.setdefault(login, ring["agent_username"])

    active = {login for login, agent in known.items() if agent.is_active}
    agents = []
    for login in sorted(active | set(per_login) | set(missed_by_login)):
        r = per_login.get(login, {})
        agent = known.get(login)
        # Shown as our agent list spells it; failing that, as the calls or rings do.
        username = agent.username if agent else r.get("spelled") or ring_spelling[login]
        answered_in, answered_out = r.get("answered_in", 0), r.get("answered_out", 0)
        made = answered_out + r.get("not_connected_out", 0)
        handled = answered_in + answered_out
        talk = r.get("talk") or 0
        agents.append({
            "agent": username,
            "name": agent.display_name if agent else username,
            "team": agent.team if agent else "",
            "answered_in": answered_in,
            "answered_out": answered_out,
            "not_connected_out": r.get("not_connected_out", 0),
            "made": made,
            "received": answered_in,
            "connect_ratio_pct": _pct(answered_out, made),
            "handled": handled,
            "missed_rings": missed_by_login.get(login, 0),
            "talk_sec": talk,
            "avg_talk_sec": round(talk / handled) if handled else None,
            "hold_sec": r.get("hold") or 0,
            "first_call": r.get("first_call"),
            "last_call": r.get("last_call"),
        })
    # Busiest first; then most outbound attempts; then by name.
    agents.sort(key=lambda a: (-a["handled"], -a["not_connected_out"], a["name"].casefold()))
    return agents


def agent_activity(start, end=None):
    """
    The Agents and Daily activity pages: every agent's numbers between two dates (one day if `end` is left out),
    and the call log: the latest calls in that time, newest first (at most 1,000; "calls_total" says how many
    there were in all, so the page can say when the log is only the latest of them).
    """
    end = end or start
    calls = calls_in_range(start, end)
    return {
        "agents": agent_rows(start, end),
        "recent": recent(calls, agent_names(), limit=1000),
        "calls_total": calls.count(),
    }


# The three counts the per-agent charts are made of
AGENT_COUNTS = {
    "answered_in": Count("id", filter=ANSWERED & INBOUND),
    "answered_out": Count("id", filter=ANSWERED & OUTBOUND),
    "not_connected_out": Count("id", filter=OUTBOUND & ~ANSWERED),
}


def agent_detail(login, start, end):
    """
    One agent between two dates (inclusive): the Agent detail tab.
    The login is matched whatever the capitals. Returns their totals, their calls on every day
    in the range (days without calls included, as zeros) and their latest calls.
    """
    key = _login_key(login)
    agent = Agent.objects.annotate(login=Lower("username")).filter(login=key).first()
    calls = calls_in_range(start, end).annotate(login=Lower("agent_username")).filter(login=key)

    t = calls.aggregate(
        **AGENT_COUNTS, talk=Sum("talk_seconds", filter=ANSWERED), hold=Sum("hold_seconds", filter=ANSWERED)
    )
    by_day = {r["day"]: r for r in calls.annotate(day=TruncDate("started_at")).values("day").annotate(**AGENT_COUNTS)}
    days = []
    day = start
    while day <= end:
        r = by_day.get(day, {})
        days.append({"date": day.isoformat(), **{name: r.get(name, 0) for name in AGENT_COUNTS}})
        day += timedelta(days=1)

    missed, _ = _missed_rings(AgentOffer.objects.filter(_between("offered_at", start, end)))
    handled = t["answered_in"] + t["answered_out"]
    talk = t["talk"] or 0
    username = agent.username if agent else login
    return {
        "agent": username,
        "name": agent.display_name if agent else username,
        "team": agent.team if agent else "",
        "totals": {
            "answered_in": t["answered_in"],
            "answered_out": t["answered_out"],
            "not_connected_out": t["not_connected_out"],
            "handled": handled,
            "connect_ratio_pct": _pct(t["answered_out"], t["answered_out"] + t["not_connected_out"]),
            "missed_rings": sum(1 for ring in missed if _login_key(ring["agent_username"]) == key),
            "talk_sec": talk,
            "avg_talk_sec": round(talk / handled) if handled else None,
            "hold_sec": t["hold"] or 0,
        },
        "days": days,
        "recent": recent(calls, agent_names(), limit=100),
    }


def add_months(month, n):
    """The 1st of the month `n` months after `month` (n may be negative): add_months(date(2026, 1, 9), -1) -> 1 Dec."""
    index = month.year * 12 + month.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def monthly(first_month, last_month, queue=None):
    """
    Calls per month, from the month of `first_month` to the month of `last_month` (both included; the day
    of the month is ignored): the Monthly tab. Every month in the range is listed, months without calls as zeros.
    """
    start = first_month.replace(day=1)
    end = add_months(last_month, 1) - timedelta(days=1)  # the last day of the last month
    calls = calls_in_range(start, end, queue)
    counts = {
        "inbound": Count("id", filter=INBOUND),
        "outbound": Count("id", filter=OUTBOUND),
        "answered_in": Count("id", filter=ANSWERED & INBOUND),
        "unanswered_in": Count("id", filter=_unanswered() & INBOUND),
        "answered_out": Count("id", filter=ANSWERED & OUTBOUND),
    }
    t = calls.aggregate(**counts, avg_talk=Avg("talk_seconds", filter=ANSWERED))
    # TruncMonth works in the display time zone, so a call at 00:30 on 1 November counts in November.
    rows = calls.annotate(month=TruncMonth("started_at")).values("month").annotate(**counts)
    by_month = {(r["month"].year, r["month"].month): r for r in rows}

    months = []
    month = start
    while month <= end:
        r = by_month.get((month.year, month.month), {})
        months.append({"month": f"{month:%Y-%m}", **{name: r.get(name, 0) for name in counts}})
        month = add_months(month, 1)
    return {
        # Who made and received the most calls over these months (the page ranks them)
        "agents": agent_rows(start, end, queue),
        "totals": {
            "calls": t["inbound"] + t["outbound"],
            "inbound": t["inbound"],
            "outbound": t["outbound"],
            "answered_in": t["answered_in"],
            "answered_out": t["answered_out"],
            "answer_ratio_pct": _pct(t["answered_in"], t["inbound"]),
            "connect_ratio_pct": _pct(t["answered_out"], t["outbound"]),
            "avg_talk_sec": _round(t["avg_talk"]),
        },
        "months": months,
    }


# The lists of calls the dashboard can open from a tile, a bar or an agent (call_list's `kind`).
# The unanswered ones are worked out when asked, because which statuses count comes from the settings.
CALL_KINDS = {
    "all": lambda: Q(),
    "inbound": lambda: INBOUND,
    "outbound": lambda: OUTBOUND,
    "answered": lambda: ANSWERED,
    "answered_in": lambda: ANSWERED & INBOUND,
    "unanswered": _unanswered,
    "unanswered_in": lambda: _unanswered() & INBOUND,
    "connected": lambda: ANSWERED & OUTBOUND,
    "not_connected": lambda: OUTBOUND & ~ANSWERED,
    "held": lambda: ANSWERED & Q(hold_seconds__gt=0),
}


def call_list(start, end, kind="all", queue=None, agent=None, hour=None, limit=500):
    """
    The calls behind a number on the dashboard (a "drill-down"): between two dates, of one `kind`
    (see CALL_KINDS), optionally for one queue, one agent (whatever the capitals) and one hour of the day.
    Returns how many there are, the latest `limit` of them, and why they ended (HoduCC's hangup reason, and
    who hung up), most common first.
    """
    calls = calls_in_range(start, end, queue).filter(CALL_KINDS[kind]())
    if agent:
        calls = calls.annotate(login=Lower("agent_username")).filter(login=_login_key(agent))
    if hour is not None:
        calls = calls.annotate(hour=ExtractHour("started_at")).filter(hour=hour)
    reasons = calls.values("hangup_reason").annotate(n=Count("id")).order_by("-n")[:6]
    ended_by = calls.values("hangup_by").annotate(n=Count("id")).order_by("-n")
    return {
        "total": calls.count(),
        "calls": recent(calls, agent_names(), limit),
        "reasons": [{"reason": r["hangup_reason"], "count": r["n"]} for r in reasons],
        "ended_by": [{"by": r["hangup_by"], "count": r["n"]} for r in ended_by],
    }
