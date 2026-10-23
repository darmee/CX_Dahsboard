"""
Sync: copy calls from HoduCC into our database.

Why store calls instead of asking HoduCC every time the page loads?
- The dashboard stays fast and works even if HoduCC is slow or down.
- We can show any date range, trends and per-agent numbers with simple queries.
- We call HoduCC a few times an hour instead of every time someone refreshes.

Run it with the management command:  python manage.py sync_calls
"""
import logging
import threading
from collections import Counter
from datetime import date, datetime, time, timedelta

from django.core.cache import cache
from django.db import connections, transaction
from django.utils import timezone

from .client import HoduError, get_client
from .models import Agent, AgentOffer, Call, SyncRun
from .parsing import agent_from_row, call_from_row, offer_from_row

log = logging.getLogger(__name__)

# Fields that get refreshed when a call we already have comes in again
# (for example, a call that was still in progress at the last sync).
CALL_UPDATE_FIELDS = [
    "direction", "status", "queue_name", "campaign_name", "agent_username", "caller_masked",
    "started_at", "ended_at", "wait_seconds", "talk_seconds", "hold_seconds", "total_seconds",
    "hangup_by", "hangup_reason", "synced_at",
]
# The same for a ring that was still ringing at the last sync.
OFFER_UPDATE_FIELDS = ["agent_username", "queue_name", "ended_at", "ring_seconds", "hangup_reason"]

# What can go wrong turning one of HoduCC's rows into clean values (see parsing.py).
BAD_ROW = (ValueError, TypeError, KeyError, IndexError, AttributeError)

# The routine sync also finishes off earlier days: a call made at 23:58, or one still
# in progress at midnight, is only complete once its day is over.
CATCHUP_DAYS = 3                          # how many earlier days to look back at
FINAL_SYNC_GRACE = timedelta(minutes=30)  # a day is "over" this long after midnight
MAX_FINAL_TRIES = 3                       # then stop retrying a day that keeps failing

# The agent list hardly changes, so the live background sync fetches it at most this often.
AGENT_LIST_EVERY_SECONDS = 60 * 60

# SQLite lets one program write at a time, so the background syncs (live mode, and filling in history)
# take turns: each holds this while it saves a day.
_write_lock = threading.Lock()


def _parse_rows(rows, parse, label, notes):
    """
    Clean every row. One row we can't read is skipped and noted;
    it does not stop the rest of the day from being saved.
    """
    parsed, problems = [], []
    for row in rows:
        try:
            fields = parse(row)
        except BAD_ROW as exc:
            problems.append(f"{type(exc).__name__}: {exc}")
            continue
        if fields:
            parsed.append(fields)
    if problems:
        notes.append(f"Skipped {len(problems)} {label} row(s) we couldn't read. First problem: {problems[0]}")
    return parsed


def save_calls(rows, notes):
    """Insert new calls and update existing ones, in one database round trip. Returns how many."""
    now = timezone.now()
    # Keyed by call_id, so if HoduCC sends the same call twice the later row wins.
    calls = {}
    repeats = 0
    for fields in _parse_rows(rows, call_from_row, "call", notes):
        repeats += fields["call_id"] in calls
        calls[fields["call_id"]] = Call(**fields, synced_at=now)
    if repeats:
        notes.append(f"HoduCC sent {repeats} row(s) repeating a call_id already in the reply; kept the last of each.")
    Call.objects.bulk_create(
        calls.values(),
        update_conflicts=True,          # if call_id already exists...
        unique_fields=["call_id"],      # ...match on call_id...
        update_fields=CALL_UPDATE_FIELDS,  # ...and update these fields.
    )
    return len(calls)


def save_offers(rows, notes):
    """Insert agent offers and update ones we already have. Returns how many were received."""
    offers = {}
    for fields in _parse_rows(rows, offer_from_row, "agent offer", notes):
        offers[fields["call_id"], fields["agent_name"], fields["offered_at"]] = AgentOffer(**fields)
    AgentOffer.objects.bulk_create(
        offers.values(),
        update_conflicts=True,
        unique_fields=["call_id", "agent_name", "offered_at"],
        update_fields=OFFER_UPDATE_FIELDS,
    )
    return len(offers)


def sync_day(day: date, client=None) -> SyncRun:
    """
    Pull one day of calls (and agent offers) from HoduCC and save them.
    Always returns a SyncRun log entry; check run.ok to see if it worked.
    """
    run = SyncRun.objects.create(day=day)
    notes = []

    try:
        client = client or get_client()
        rows, reported_total = client.get_call_history(day)
        with transaction.atomic():  # all saved, or nothing saved
            run.calls_received = save_calls(rows, notes)
        run.calls_reported_total = reported_total
        cut_off = reported_total is not None and reported_total > len(rows)
        if cut_off:
            # First in the notes, because this one makes the day's numbers wrong.
            notes.insert(
                0,
                f"HoduCC reported {reported_total} calls but sent {len(rows)}, so this day is incomplete. "
                "Ask HoduCC about paging.",
            )

        # Offers are a bonus: if this endpoint fails, the calls are still saved.
        try:
            offer_rows = client.get_agent_offered_calls(day)
            with transaction.atomic():
                run.offers_received = save_offers(offer_rows, notes)
        except HoduError as exc:
            notes.append(f"Agent offers skipped: {exc}")

        # A cut-off day is not ok: the calls we got are saved, but the totals would be too low.
        run.ok = not cut_off
    except HoduError as exc:
        notes.append(str(exc))
        log.error("Sync for %s failed: %s", day, exc)
    except Exception as exc:  # anything unexpected is logged too, so the next sync still runs
        notes.append(f"Unexpected error ({type(exc).__name__}): {exc}")
        log.exception("Sync for %s crashed", day)

    run.message = "\n".join(notes)
    run.finished_at = timezone.now()
    run.save()
    log.debug("Sync %s: %s calls, %s offers, ok=%s", day, run.calls_received, run.offers_received, run.ok)
    return run


def sync_agents(client=None):
    """
    Bring the Agent table up to date with HoduCC's agent list. Returns how many agents HoduCC listed.

    - A new login gets a new row.
    - HoduCC's name for an existing login is refreshed.
    - The staff fields you filled in (staff_name, staff_id, team) are never touched.
    - A login no longer in HoduCC's list is marked inactive, not deleted, so old calls keep their name.
    - A login seen in our calls but not in the list (e.g. a deleted agent) also gets a row, so you can name it.
    - Logins are matched whatever the capitals: "agent01" and "Agent01" share one row.
    Raises HoduError if HoduCC can't be reached.
    """
    client = client or get_client()
    listed = {}
    for row in client.get_agent_list():
        fields = agent_from_row(row)
        if fields:
            listed[fields["username"]] = fields

    with transaction.atomic():
        rows = {a.username.lower(): a for a in Agent.objects.all()}
        for username, fields in listed.items():
            # Only the HoduCC columns are set, so the staff details stay as you left them.
            agent = rows.setdefault(username.lower(), Agent(username=username))
            agent.hodu_id, agent.hodu_name, agent.is_active = fields["hodu_id"], fields["hodu_name"], True
            agent.save()
        if listed:  # an empty list is more likely a HoduCC hiccup than everyone leaving
            still_listed = [rows[username.lower()].pk for username in listed]
            Agent.objects.exclude(pk__in=still_listed).update(is_active=False)
        seen = Call.objects.exclude(agent_username="").values_list("agent_username", flat=True).distinct()
        unknown = {login.lower(): login for login in seen if login.lower() not in rows}
        Agent.objects.bulk_create([Agent(username=u, is_active=False) for u in sorted(unknown.values())])
    return len(listed)


def sync_agents_if_due(client=None):
    """
    sync_agents, at most once an hour per running program, for the routine and live syncs.
    A failure is logged but doesn't stop the calls being synced.
    """
    if not cache.add("agents-synced", True, AGENT_LIST_EVERY_SECONDS):
        return
    try:
        sync_agents(client)
    except HoduError as exc:
        cache.delete("agents-synced")  # A failed fetch should be retried on the next sync.
        log.warning("Agent list not updated: %s", exc)


def _day_over(day: date):
    """When a day counts as over: half an hour after its midnight (FINAL_SYNC_GRACE)."""
    return timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min)) + FINAL_SYNC_GRACE


def days_needing_sync(today: date):
    """
    The days the routine sync should pull: today, plus any recent day that
    hasn't had a good sync since it ended. Oldest first.
    """
    days = []
    for back in range(CATCHUP_DAYS, 0, -1):
        day = today - timedelta(days=back)
        final_runs = SyncRun.objects.filter(day=day, started_at__gte=_day_over(day))
        if final_runs.filter(ok=True).exists() or final_runs.count() >= MAX_FINAL_TRIES:
            continue
        days.append(day)
    return days + [today]


def missing_days(start: date, end: date):
    """
    The days from `start` to `end` (but not today or later) that the dashboard has never fully synced:
    no good sync since the day ended, and fewer than MAX_FINAL_TRIES failed ones. Oldest first.
    A day synced only while it was still going on counts as missing too: its later calls were never fetched.
    """
    last = min(end, timezone.localdate() - timedelta(days=1))
    if last < start:
        return []
    done, failures = set(), Counter()
    for day, ok, started_at in SyncRun.objects.filter(day__range=(start, last)).values_list("day", "ok", "started_at"):
        if started_at >= _day_over(day):
            if ok:
                done.add(day)
            else:
                failures[day] += 1
    days, day = [], start
    while day <= last:
        if day not in done and failures[day] < MAX_FINAL_TRIES:
            days.append(day)
        day += timedelta(days=1)
    return days


def backfill_in_background(days):
    """
    Used by the dashboard to fill in history by itself: fetch these past days from HoduCC in a background
    thread, oldest first. Only one fill runs at a time (a second request just reports on the first).
    Returns how far the running fill has got, {"total": 31, "done": 4}, or None if none is running.
    """
    status = cache.get("backfill")
    if not days or not cache.add("backfill-running", True, 6 * 60 * 60):
        return status if status and status["done"] < status["total"] else None
    status = {"total": len(days), "done": 0}
    cache.set("backfill", status, 6 * 60 * 60)
    threading.Thread(target=_backfill, args=(days,), name="backfill", daemon=True).start()
    return status


def _backfill(days):
    try:
        for done, day in enumerate(days, start=1):
            with _write_lock:
                sync_day(day)
            cache.set("backfill", {"total": len(days), "done": done}, 6 * 60 * 60)
    except Exception:  # e.g. the database was busy; the next page refresh starts again from what's still missing
        log.exception("Filling in history crashed")
    finally:
        cache.delete("backfill-running")
        connections.close_all()  # this thread opened its own database connection


def sync_in_background(min_gap_seconds):
    """
    Used by the dashboard to stay live without anyone running sync_calls.
    Starts a sync of today (plus any recent day that needs it) in a background thread,
    unless one was started in the last min_gap_seconds. Returns True if it started one.
    The page that asked doesn't wait: its next refresh shows the new calls.
    """
    if not cache.add("sync-in-background", True, min_gap_seconds):
        return False
    threading.Thread(target=_sync_recent_days, name="sync-in-background", daemon=True).start()
    return True


def _sync_recent_days():
    try:
        sync_agents_if_due()
        for day in days_needing_sync(timezone.localdate()):
            with _write_lock:
                sync_day(day)
    except Exception:  # e.g. the database was busy; the next refresh tries again
        log.exception("Background sync crashed")
    finally:
        connections.close_all()  # this thread opened its own database connection
