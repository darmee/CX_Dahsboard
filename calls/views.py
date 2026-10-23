"""
Views: functions that answer a web request.

    dashboard     -> the HTML page (the browser loads this once). It has six pages: Overview, Agents,
                     Agent detail, Daily activity, Monthly and Live; the JavaScript fills each from an API below.
    metrics_api   -> JSON numbers for a date range (Overview tab)
    agents_api    -> JSON: what each agent did on one day (Agents and Daily activity tabs)
    agent_api     -> JSON: one agent over a date range (Agent detail tab)
    monthly_api   -> JSON: calls per month (Monthly tab)
    calls_api     -> JSON: the calls behind a number, for the drill-down panel
    rings_api     -> JSON: the missed rings behind the Rejections tile (the drill-down panel too)
    live_api      -> JSON: what is happening right now, straight from HoduCC (Live tab and the top strip)

The Overview, Agents, Agent detail and Monthly APIs also keep the data live: when they are asked about today,
they start a background sync now and then (see _keep_live).

@login_required means only logged-in users get an answer; others go to the login page.
The APIs use @api_login_required instead, which answers 401 so the JavaScript can send them there.
"""
import hashlib
import logging
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .client import UNREACHABLE, HoduError, get_client
from .metrics import (
    CALL_KINDS,
    add_months,
    agent_activity,
    agent_detail,
    call_list,
    compute_metrics,
    monthly,
    ring_list,
)
from .models import Agent, Call, SyncRun
from .parsing import parse_duration
from .sync import backfill_in_background, missing_days, sync_in_background

log = logging.getLogger(__name__)

MAX_RANGE_DAYS = 366
MAX_AGENT_DAYS = 92  # the Agent detail chart has one bar per day
MAX_MONTHS = 36
MAX_LIST_DAYS = 1100  # the drill-down can list calls from a Monthly range of up to 36 months


def _code_version():
    """
    A short fingerprint of the dashboard's code: every Python, template, CSS and JavaScript file's name and
    time of last change. The page and every API answer carry it; when they differ (the server was restarted
    with new code while a dashboard was open), the page reloads itself instead of mixing old and new code.
    """
    app = Path(__file__).resolve().parent
    files = [*app.rglob("*.py"), *app.rglob("*.html"), *app.rglob("*.css"), *app.rglob("*.js"),
             *(settings.BASE_DIR / "templates").rglob("*.html")]
    digest = hashlib.sha1()
    for f in sorted(files):
        digest.update(f"{f.relative_to(settings.BASE_DIR)}:{f.stat().st_mtime_ns}".encode())
    return digest.hexdigest()[:12]


CODE_VERSION = _code_version()


def _json(data, status=200):
    """A JSON answer for the dashboard, with the code version added (see _code_version)."""
    return JsonResponse({**data, "version": CODE_VERSION}, status=status)


def api_login_required(view):
    """
    @login_required for the JSON APIs. Someone not logged in (e.g. their session ran out) gets a 401
    with a message, rather than the login page's HTML, which the JavaScript couldn't read.
    The JavaScript reloads the page on a 401, and the page itself sends them to log in.
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _json({"error": "You have been logged out. Please log in again."}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


def _sync_problem(syncing_now=False):
    """
    Anything the viewer should know about syncing, as {"level": "error" or "warning", "message": ...},
    or None when all is well. Sent with every metrics refresh, so a screen left open still finds out.
    syncing_now: a sync is running at this moment, so old data is about to be refreshed.
    """
    finished = SyncRun.objects.exclude(finished_at=None)
    latest = finished.first()  # newest finished run, ok or not
    last_ok = SyncRun.objects.filter(ok=True).first()
    stale_after = timedelta(seconds=settings.HODU["STALE_AFTER_SECONDS"])
    if latest and not latest.ok:
        # HoduCC's server being slow for a moment is common and passes by itself: while the numbers are still
        # fresh and it hasn't failed 3 times in a row, say so calmly. Anything else (a wrong token, say) is red.
        hiccup = UNREACHABLE in latest.message
        fresh = last_ok is not None and timezone.now() - last_ok.finished_at <= stale_after
        three_in_a_row = len(recent := list(finished[:3])) == 3 and not any(run.ok for run in recent)
        if hiccup and fresh and not three_in_a_row:
            at = timezone.localtime(latest.started_at)
            good = timezone.localtime(last_ok.finished_at)
            return {
                "level": "warning",
                "message": f"HoduCC's server was slow to answer at {at:%H:%M}; the next sync tries again. "
                           f"The numbers are from the last good sync, at {good:%H:%M}.",
            }
        return {"level": "error", "message": f"Last sync failed: {latest.message[:200]}"}

    # Syncs that have stopped altogether leave no failed run behind, so also check the clock.
    if last_ok and not settings.HODU["MOCK"] and timezone.now() - last_ok.finished_at > stale_after:
        since = timezone.localtime(last_ok.finished_at)
        if syncing_now:
            return {
                "level": "warning",
                "message": f"Fetching the latest calls from HoduCC (last sync {since:%d %b %Y %H:%M}). "
                           "The numbers will update in a moment.",
            }
        return {
            "level": "error",
            "message": f"No sync since {since:%d %b %Y %H:%M}, so these numbers may be out of date. "
                       "Check that sync_calls is still running.",
        }

    if latest and latest.message:
        return {"level": "warning", "message": f"Last sync finished with a warning: {latest.message[:200]}"}
    return None


@login_required
@require_GET
def dashboard(request):
    queues = Call.objects.exclude(queue_name="").values_list("queue_name", flat=True).distinct()
    today = timezone.localdate()
    context = {
        "queues": queues.order_by("queue_name"),
        # For the Agent detail tab's drop-down: agents still working first, then by login
        "agents": Agent.objects.order_by("-is_active", "username"),
        "last_sync": SyncRun.objects.filter(ok=True).first(),
        "sync_problem": _sync_problem(),
        "today": today.isoformat(),
        "month_start": today.replace(day=1).isoformat(),  # Agent detail starts at the 1st of this month
        "this_month": f"{today:%Y-%m}",  # Monthly shows the last 12 months, up to this one
        "year_ago_month": f"{add_months(today, -11):%Y-%m}",
        "mock": settings.HODU["MOCK"],
        # Read by js/main.js. The URLs come from urls.py, so the JavaScript never hard-codes them.
        "dashboard_config": {
            "urls": {
                "metrics": reverse("calls:metrics_api"),
                "agents": reverse("calls:agents_api"),
                "agent": reverse("calls:agent_api"),
                "monthly": reverse("calls:monthly_api"),
                "calls": reverse("calls:calls_api"),
                "rings": reverse("calls:rings_api"),
                "live": reverse("calls:live_api"),
            },
            "today": today.isoformat(),  # for the quick-date buttons ("This month", "Yesterday", ...)
            "refreshSeconds": 30,
            # How often the "Live" numbers come from HoduCC, and how often new calls are fetched (0 = off)
            "liveRefreshSeconds": settings.HODU["LIVE_CACHE_SECONDS"],
            "syncSeconds": 0 if settings.HODU["MOCK"] else settings.HODU["SYNC_ON_VIEW_SECONDS"],
            "version": CODE_VERSION,
        },
    }
    return render(request, "calls/dashboard.html", context)


def _parse_range(request):
    """Reads ?from=YYYY-MM-DD&to=YYYY-MM-DD. Defaults to today. Raises ValueError if invalid."""
    today = timezone.localdate()
    start = date.fromisoformat(request.GET.get("from") or today.isoformat())
    end = date.fromisoformat(request.GET.get("to") or start.isoformat())
    if end < start:
        raise ValueError("'to' must be on or after 'from'")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError(f"Choose {MAX_RANGE_DAYS} days or fewer")
    return start, end


def _fill_history(start, end):
    """
    Filling in history by itself: if the range asked about has days the dashboard never fetched, start
    fetching them from HoduCC in the background (sync.backfill_in_background). Returns how far a running
    fill has got, {"total": 31, "done": 4}, or None. Off in mock mode, or with HODU_AUTO_BACKFILL=0.
    """
    if settings.HODU["MOCK"] or not settings.HODU["AUTO_BACKFILL"]:
        return None
    return backfill_in_background(missing_days(start, end))


def _keep_live(end, start=None):
    """
    Live mode: while someone is looking at a range that includes today, start a background
    sync now and then (at most every HODU_SYNC_ON_VIEW_SECONDS). If `start` is given, also fill in any
    days of the range never fetched (_fill_history). Returns the sync details every API reply carries:
    when data last arrived, any problem to show, and how far filling in history has got.
    """
    gap = settings.HODU["SYNC_ON_VIEW_SECONDS"]
    started = bool(gap) and not settings.HODU["MOCK"] and end >= timezone.localdate() and sync_in_background(gap)
    running = SyncRun.objects.filter(finished_at=None, started_at__gte=timezone.now() - timedelta(minutes=2)).exists()
    last = SyncRun.objects.filter(ok=True).first()
    return {
        "last_synced_at": last.finished_at.isoformat() if last and last.finished_at else None,
        "sync_problem": _sync_problem(syncing_now=started or running),
        "backfill": _fill_history(start, end) if start else None,
    }


@api_login_required
@require_GET
def metrics_api(request):
    """GET /api/metrics/?from=2026-10-05&to=2026-10-05&queue=General"""
    try:
        start, end = _parse_range(request)
    except ValueError as exc:
        return _json({"error": str(exc)}, status=400)

    sync_info = _keep_live(end, start)  # first, so a sync can start while we count
    data = compute_metrics(start, end, queue=request.GET.get("queue") or None)
    data.update({"from": start.isoformat(), "to": end.isoformat(), **sync_info})
    return _json(data)


@api_login_required
@require_GET
def agents_api(request):
    """
    GET /api/agents/?from=2026-10-01&to=2026-10-18 -> what each agent did in that time (default: today).
    ?date=2026-10-15 is short for one day (from and to the same).
    """
    try:
        if request.GET.get("date"):
            start = end = date.fromisoformat(request.GET["date"])
        else:
            start, end = _parse_range(request)
    except ValueError as exc:
        return _json({"error": str(exc)}, status=400)

    sync_info = _keep_live(end, start)
    data = agent_activity(start, end)
    data.update({"from": start.isoformat(), "to": end.isoformat(), **sync_info})
    return _json(data)


@api_login_required
@require_GET
def agent_api(request):
    """GET /api/agent/?agent=Agent01&from=2026-10-01&to=2026-10-18 -> one agent's activity (default: this month)."""
    login = (request.GET.get("agent") or "").strip()
    if not login:
        return _json({"error": "Choose an agent"}, status=400)
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.GET.get("from") or today.replace(day=1).isoformat())
        end = date.fromisoformat(request.GET.get("to") or today.isoformat())
    except ValueError:
        return _json({"error": "Dates must look like 2026-10-15"}, status=400)
    if end < start:
        return _json({"error": "'to' must be on or after 'from'"}, status=400)
    if (end - start).days >= MAX_AGENT_DAYS:
        return _json({"error": f"Choose {MAX_AGENT_DAYS} days or fewer"}, status=400)

    sync_info = _keep_live(end, start)
    data = agent_detail(login, start, end)
    data.update({"from": start.isoformat(), "to": end.isoformat(), **sync_info})
    return _json(data)


def _parse_month(text, default):
    """'2026-10' -> date(2026, 10, 1); nothing -> default. Raises ValueError for anything else."""
    if not text:
        return default
    return date.fromisoformat(f"{text}-01")


@api_login_required
@require_GET
def monthly_api(request):
    """GET /api/monthly/?from=2025-11&to=2026-10&queue=General -> calls per month (default: the last 12 months)."""
    this_month = timezone.localdate().replace(day=1)
    try:
        last = _parse_month(request.GET.get("to"), this_month)
        first = _parse_month(request.GET.get("from"), add_months(last, -11))
    except ValueError:
        return _json({"error": "Months must look like 2026-10"}, status=400)
    if last < first:
        return _json({"error": "'to' must be on or after 'from'"}, status=400)
    if add_months(first, MAX_MONTHS) <= last:
        return _json({"error": f"Choose {MAX_MONTHS} months or fewer"}, status=400)

    sync_info = _keep_live(add_months(last, 1) - timedelta(days=1), first)
    data = monthly(first, last, queue=request.GET.get("queue") or None)
    data.update({"from": f"{first:%Y-%m}", "to": f"{last:%Y-%m}", **sync_info})
    return _json(data)


@api_login_required
@require_GET
def calls_api(request):
    """
    GET /api/calls/?from=2026-10-01&to=2026-10-18&kind=unanswered&queue=&agent=Agent01&hour=14
    -> the calls behind a number on the dashboard, for the drill-down panel. `kind` is one of CALL_KINDS.
    """
    kind = request.GET.get("kind") or "all"
    if kind not in CALL_KINDS:
        return _json({"error": f"kind must be one of: {', '.join(CALL_KINDS)}"}, status=400)
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.GET.get("from") or today.isoformat())
        end = date.fromisoformat(request.GET.get("to") or start.isoformat())
        hour = int(request.GET["hour"]) if request.GET.get("hour") else None
    except ValueError:
        return _json({"error": "Dates must look like 2026-10-15, and hour must be 0 to 23"}, status=400)
    if end < start or (end - start).days >= MAX_LIST_DAYS or not (hour is None or 0 <= hour <= 23):
        return _json({"error": "Choose a shorter range that ends on or after it starts, and an hour 0-23"}, status=400)

    data = call_list(start, end, kind, queue=request.GET.get("queue") or None,
                     agent=(request.GET.get("agent") or "").strip() or None, hour=hour)
    data.update({"from": start.isoformat(), "to": end.isoformat(), "kind": kind})
    return _json(data)


@api_login_required
@require_GET
def rings_api(request):
    """
    GET /api/rings/?from=2026-10-01&to=2026-10-18&queue=&agent=Agent01
    -> the missed rings behind the Rejections tile and the missed-rings numbers, for the drill-down panel.
    """
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.GET.get("from") or today.isoformat())
        end = date.fromisoformat(request.GET.get("to") or start.isoformat())
    except ValueError:
        return _json({"error": "Dates must look like 2026-10-15"}, status=400)
    if end < start or (end - start).days >= MAX_LIST_DAYS:
        return _json({"error": "Choose a shorter range that ends on or after it starts"}, status=400)

    data = ring_list(start, end, queue=request.GET.get("queue") or None,
                     agent=(request.GET.get("agent") or "").strip() or None)
    data.update({"from": start.isoformat(), "to": end.isoformat()})
    return _json(data)


def _number(value):
    """HoduCC sends some counts as text ("3"). -> 3, or None if it isn't a number."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _seconds(value):
    """HoduCC's "00:00:53" -> 53, or None if it is missing or isn't a duration."""
    try:
        return parse_duration(value) if value else None
    except (TypeError, ValueError):
        return None


def _live_row(raw):
    """
    One row of HoduCC's realtime queue summary -> the numbers the Live tab shows.

    Only fields whose meaning we have checked are used: awt and att are the average wait
    and talk time (they equal total wait / calls and total talk / calls).
    "Idle" = logged in but not on a call. HoduCC doesn't say whether those agents are on a break.
    """
    logged_in = _number(raw.get("live_agent"))
    on_calls = _number(raw.get("live_agent_calls"))
    idle = max(logged_in - on_calls, 0) if logged_in is not None and on_calls is not None else None
    return {
        "name": raw.get("name") or "",
        "waiting": _number(raw.get("live_waiting_calls")),
        "on_calls": on_calls,
        "logged_in": logged_in,
        "idle": idle,
        "assigned": _number(raw.get("assiged_agent")),  # sic: HoduCC's spelling
        "calls_today": _number(raw.get("total_call")),
        "answered_today": _number(raw.get("total_agent_calls")),
        "abandoned_today": _number(raw.get("total_abandoned_calls")),
        "failover_today": _number(raw.get("total_failover_calls")),
        "avg_wait_sec": _seconds(raw.get("awt")),
        "avg_talk_sec": _seconds(raw.get("att")),
    }


@api_login_required
@require_GET
def live_api(request):
    """
    GET /api/live/ -> what is happening right now, from HoduCC's realtime queue summary:
    totals for the whole call centre, and one row per queue.
    Cached for a few seconds so ten open screens make one call to HoduCC, not ten.

    HoduCC's API has no list of the individual calls in progress, so this is counts only.
    """
    data = cache.get("live")
    if data is None:
        try:
            summary = get_client().get_realtime_queue_summary() or {}
            raw_totals = summary.get("agent_total_avg") or {}
            totals = _live_row(raw_totals)
            # HoduCC's own total of assigned agents can say 0 while a queue says 3,
            # so "how many agents are there" comes from our agent list instead.
            totals["agents_total"] = Agent.objects.filter(is_active=True).count()
            data = {
                "available": bool(raw_totals),
                "as_of": timezone.now().isoformat(),
                "totals": totals,
                "queues": [_live_row(q) for q in summary.get("agent_queue_details") or []],
                # Short names for the strip at the top of the page
                "waiting_now": totals["waiting"],
                "on_calls_now": totals["on_calls"],
                "agents_logged_in": totals["logged_in"],
                "agents_idle": totals["idle"],
                "agents_assigned": totals["assigned"],
            }
        except HoduError as exc:
            data = {"available": False, "error": str(exc)}
        except (AttributeError, TypeError):  # e.g. a list where we expect a dict: a reply unlike any we've seen
            log.exception("Couldn't read HoduCC's realtime queue summary")
            data = {"available": False, "error": "HoduCC sent live numbers in a form we can't read."}
        cache.set("live", data, settings.HODU["LIVE_CACHE_SECONDS"])
    return _json(data)
