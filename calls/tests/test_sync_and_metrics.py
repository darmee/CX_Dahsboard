"""
Tests that run the real sync and metrics code against a saved HoduCC reply
(tests/fixtures/callhistory.json: 9 calls on 5 Oct 2026, phone numbers replaced
with made-up ones) and check the numbers.

Run all tests with:  python manage.py test
"""
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from calls.client import UNREACHABLE, HoduError, HoduUnreachable, MockHoduClient
from calls.metrics import compute_metrics
from calls.models import AgentOffer, Call, SyncRun
from calls.sync import (
    CATCHUP_DAYS,
    FINAL_SYNC_GRACE,
    MAX_FINAL_TRIES,
    days_needing_sync,
    sync_day,
    sync_in_background,
)

DAY = date(2026, 10, 5)
FIXTURES = Path(__file__).parent / "fixtures"
# Whatever .env says, the tests never talk to the real HoduCC:
# mock mode reads the fixture, and live mode's background sync and filling in history are off.
MOCK_SETTINGS = {
    **settings.HODU, "MOCK": True, "SAMPLE_DIR": FIXTURES, "SYNC_ON_VIEW_SECONDS": 0, "AUTO_BACKFILL": False,
}
LIVE_SETTINGS = {**MOCK_SETTINGS, "MOCK": False, "STALE_AFTER_SECONDS": 900}


def call_row(call_id, **changes):
    """A made-up getCallHistory row: an inbound call on 5 Oct, answered by Agent1 after a 30s wait."""
    row = {
        "call_id": call_id, "call_type": "INBOUND", "call_status": "AGENT", "queue_name": "General",
        "agent_username": "Agent1", "caller_number": "08030000000",
        "call_start_time": "05-10-2026 10:00:00", "call_hangup_time": "05-10-2026 10:05:00",
        "queue_wait_time": "0:00:30", "agent_duration": "0:02:00", "hold_duration": "0:00:00",
        "call_duration": "0:02:30",
    }
    return {**row, **changes}


def offer_row(call_id, agent, offered, hangup, reason="NO_ANSWER"):
    """A made-up getAgentOfferedCalls row. Times are HH:MM:SS on 5 Oct; hangup=None means still ringing."""
    return {
        "aoc_call_id": call_id, "agt_uname": agent, "aoc_offered_time": f"05-10-2026 {offered}",
        "aoc_hangup_time": f"05-10-2026 {hangup}" if hangup else "00-00-0000 00:00:00",
        "aoc_hangup_reason": reason if hangup else "",
    }


class ListClient:
    """A stand-in for HoduCC that returns exactly the rows it is given."""

    def __init__(self, calls, total=None, offers=()):
        self.calls, self.total, self.offers = calls, total, list(offers)

    def get_call_history(self, day):
        return self.calls, len(self.calls) if self.total is None else self.total

    def get_agent_offered_calls(self, day):
        return self.offers


class FakeOffersClient(MockHoduClient):
    """The sample calls, plus made-up agent offers so rejection maths can be tested."""

    def __init__(self):
        super().__init__(settings.HODU["SAMPLE_DIR"])

    def get_agent_offered_calls(self, day):
        return [
            # Agent02 let call 10189893 ring 12s and didn't take it; Agent01 then answered.
            {"aoc_call_id": 10189893, "agt_uname": "Agent02", "aoc_offered_time": "05-10-2026 12:01:36",
             "aoc_hangup_time": "05-10-2026 12:01:48", "aoc_hangup_reason": "NO_ANSWER"},
            {"aoc_call_id": 10189893, "agt_uname": "Agent01", "aoc_offered_time": "05-10-2026 12:01:48",
             "aoc_hangup_time": "05-10-2026 12:04:10", "aoc_hangup_reason": "NORMAL_CLEARING"},
            # Agent01 rejected an abandoned call after 4s.
            {"aoc_call_id": 10186726, "agt_uname": "Agent01", "aoc_offered_time": "05-10-2026 09:09:40",
             "aoc_hangup_time": "05-10-2026 09:09:44", "aoc_hangup_reason": "CALL_REJECTED"},
        ]


class BrokenClient:
    def get_call_history(self, day):
        raise HoduError("401 Token Authentication Failed.")


class UnreachableClient:
    """HoduCC's server not answering, as the real client reports it after its tries."""

    def get_call_history(self, day):
        raise HoduUnreachable(f"{UNREACHABLE} (getCallHistory): no connection within 10 seconds (tried 3 times).")


@override_settings(HODU=MOCK_SETTINGS)
class SyncTests(TestCase):
    def test_sync_saves_sample_calls(self):
        run = sync_day(DAY, client=MockHoduClient(settings.HODU["SAMPLE_DIR"]))
        self.assertTrue(run.ok)
        self.assertEqual(run.calls_received, 9)
        self.assertEqual(run.calls_reported_total, 9)
        self.assertEqual(Call.objects.count(), 9)

    def test_sync_twice_does_not_duplicate(self):
        client = MockHoduClient(settings.HODU["SAMPLE_DIR"])
        sync_day(DAY, client=client)
        sync_day(DAY, client=client)
        self.assertEqual(Call.objects.count(), 9)

    def test_failed_sync_is_logged_not_crashed(self):
        run = sync_day(DAY, client=BrokenClient())
        self.assertFalse(run.ok)
        self.assertIn("Token Authentication Failed", run.message)
        self.assertEqual(SyncRun.objects.count(), 1)

    def test_cut_off_day_is_saved_but_not_ok(self):
        run = sync_day(DAY, client=ListClient([call_row(1), call_row(2)], total=500))
        self.assertFalse(run.ok)
        self.assertIn("incomplete", run.message)
        self.assertEqual(Call.objects.count(), 2)

    def test_unreadable_row_is_skipped_and_noted(self):
        rows = [call_row(1), call_row(2, call_start_time="2026/10/05 10:00"), call_row(3, queue_wait_time="0:01:16.5")]
        run = sync_day(DAY, client=ListClient(rows))
        self.assertTrue(run.ok)
        self.assertIn("Skipped 2 call row(s)", run.message)
        self.assertEqual(Call.objects.count(), 1)

    def test_unexpected_error_is_logged_not_raised(self):
        class CrashingClient:
            def get_call_history(self, day):
                raise RuntimeError("boom")

        with self.assertLogs("calls.sync", level="ERROR"):
            run = sync_day(DAY, client=CrashingClient())
        self.assertFalse(run.ok)
        self.assertIsNotNone(run.finished_at)
        self.assertIn("RuntimeError", run.message)

    def test_repeated_call_id_keeps_the_last_and_says_so(self):
        rows = [call_row(1, agent_username="Agent1"), call_row(1, agent_username="Agent2")]
        run = sync_day(DAY, client=ListClient(rows))
        self.assertEqual(run.calls_received, 1)
        self.assertIn("repeating a call_id", run.message)
        self.assertEqual(Call.objects.get().agent_username, "Agent2")

    def test_ring_still_ringing_is_completed_by_the_next_sync(self):
        sync_day(DAY, client=ListClient([call_row(1)], offers=[offer_row(1, "Agent2", "10:00:05", None)]))
        self.assertIsNone(AgentOffer.objects.get().ring_seconds)
        sync_day(DAY, client=ListClient([call_row(1)], offers=[offer_row(1, "Agent2", "10:00:05", "10:00:20")]))
        offer = AgentOffer.objects.get()
        self.assertEqual(offer.ring_seconds, 15)
        self.assertEqual(offer.hangup_reason, "NO_ANSWER")


@override_settings(HODU=MOCK_SETTINGS)
class CatchUpTests(TestCase):
    """days_needing_sync: the routine sync also finishes off days that have ended."""

    TODAY = date(2026, 10, 9)
    YESTERDAY = TODAY - timedelta(days=1)

    def run_at(self, day, started_at, ok=True):
        run = SyncRun.objects.create(day=day, ok=ok)
        SyncRun.objects.filter(pk=run.pk).update(started_at=started_at)  # started_at is set automatically otherwise

    def after_midnight(self, minutes):
        return timezone.make_aware(datetime.combine(self.TODAY, time.min)) + timedelta(minutes=minutes)

    def test_with_no_history_it_looks_back(self):
        days = days_needing_sync(self.TODAY)
        self.assertEqual(days, [self.TODAY - timedelta(days=n) for n in range(CATCHUP_DAYS, -1, -1)])

    def test_a_sync_during_the_day_does_not_finish_it(self):
        self.run_at(self.YESTERDAY, self.after_midnight(-5))  # 23:55 the night before
        self.assertIn(self.YESTERDAY, days_needing_sync(self.TODAY))

    def test_a_good_sync_after_the_day_ended_finishes_it(self):
        self.run_at(self.YESTERDAY, self.after_midnight(FINAL_SYNC_GRACE.seconds // 60 + 1))
        days = days_needing_sync(self.TODAY)
        self.assertNotIn(self.YESTERDAY, days)
        self.assertEqual(days[-1], self.TODAY)

    def test_a_day_that_keeps_failing_is_given_up_on(self):
        for attempt in range(MAX_FINAL_TRIES):
            self.assertIn(self.YESTERDAY, days_needing_sync(self.TODAY))
            self.run_at(self.YESTERDAY, self.after_midnight(60 + attempt), ok=False)
        self.assertNotIn(self.YESTERDAY, days_needing_sync(self.TODAY))


@override_settings(HODU=MOCK_SETTINGS)
class CommandTests(TestCase):
    def test_days_must_be_positive(self):
        with self.assertRaisesMessage(CommandError, "--days must be 1 or more"):
            call_command("sync_calls", "--days", "0")

    def test_date_can_be_written_either_way(self):
        from calls.management.commands.sync_calls import Command

        self.assertEqual(Command._parse_date("2026-10-13"), date(2026, 10, 13))
        self.assertEqual(Command._parse_date("13-10-2026"), date(2026, 10, 13))
        with self.assertRaises(CommandError):
            Command._parse_date("13/10/2026")


@override_settings(HODU=MOCK_SETTINGS)
class MetricsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        sync_day(DAY, client=FakeOffersClient())

    def test_totals(self):
        t = compute_metrics(DAY, DAY)["totals"]
        self.assertEqual(t["inbound"], 9)
        self.assertEqual(t["outbound"], 0)
        self.assertEqual(t["answered"], 3)
        self.assertEqual(t["unanswered"], 6)
        self.assertEqual(t["answer_ratio_pct"], 33.3)

    def test_timing(self):
        tm = compute_metrics(DAY, DAY)["timing"]
        self.assertEqual(tm["avg_wait_answered_sec"], 20)  # (18 + 32 + 10) / 3
        self.assertEqual(tm["longest_wait_answered_sec"], 32)
        self.assertEqual(tm["avg_wait_before_giving_up_sec"], 36)  # (76+45+16+27+31+21) / 6
        self.assertIsNone(tm["avg_hold_sec"])  # nobody was put on hold

    def test_hourly_uses_local_time(self):
        hourly = compute_metrics(DAY, DAY)["hourly"]
        self.assertEqual(hourly[9]["unanswered"], 3)  # 09:09, 09:12, 09:20 Lagos time

    def test_per_agent(self):
        agents = {a["agent"]: a for a in compute_metrics(DAY, DAY)["agents"]}
        self.assertEqual(agents["Agent01"]["answered"], 2)
        self.assertEqual(agents["Agent02"]["avg_talk_sec"], 198)

    def test_rejections(self):
        rj = compute_metrics(DAY, DAY)["rejection"]
        self.assertEqual(rj["offered"], 3)
        self.assertEqual(rj["rejected_or_missed"], 2)  # Agent01 taking the call doesn't count
        self.assertEqual(rj["avg_ring_before_reject_sec"], 8)  # (12 + 4) / 2
        self.assertEqual(AgentOffer.objects.count(), 3)

    def test_other_day_is_empty(self):
        self.assertEqual(compute_metrics(date(2026, 10, 6), date(2026, 10, 6))["totals"]["calls"], 0)

    def test_queue_filter(self):
        self.assertEqual(compute_metrics(DAY, DAY, queue="General")["totals"]["calls"], 9)
        self.assertEqual(compute_metrics(DAY, DAY, queue="Nope")["totals"]["calls"], 0)


@override_settings(HODU=MOCK_SETTINGS)
class MixedDayMetricsTests(TestCase):
    """Things the sample doesn't contain: outbound calls, other statuses, awkward rings."""

    def rejection(self, offers, **call_changes):
        sync_day(DAY, client=ListClient([call_row(1, **call_changes)], offers=offers))
        return compute_metrics(DAY, DAY)["rejection"]

    def test_outbound_calls_do_not_change_inbound_numbers(self):
        sync_day(DAY, client=ListClient([
            call_row(1),                                                     # inbound, answered, waited 30s
            call_row(2, call_type="OUTBOUND", queue_wait_time="0:00:00"),    # outbound, answered
            call_row(3, call_status="IVR", agent_username=None),             # inbound, neither
            call_row(4, call_status="ABANDONED", agent_username=None),       # inbound, unanswered
        ]))
        m = compute_metrics(DAY, DAY)
        self.assertEqual(m["timing"]["avg_wait_answered_sec"], 30)
        self.assertEqual(m["totals"]["answered_inbound"], 1)
        self.assertEqual(m["totals"]["other_inbound"], 1)
        self.assertEqual(m["totals"]["answer_ratio_pct"], 33.3)  # 1 of 3 inbound
        hour = m["hourly"][10]
        self.assertEqual((hour["answered"], hour["unanswered"], hour["outbound"]), (1, 1, 1))

    def test_turned_away_calls_count_as_unanswered(self):
        # HANGUP: HoduCC refused the call at once (TENANT_CALLS_LIMIT_REACHED), so the customer never got through.
        hodu = {**settings.HODU, "UNANSWERED_STATUSES": ["ABANDONED", "DROPPED", "HANGUP"]}
        sync_day(DAY, client=ListClient([
            call_row(1),
            call_row(2, call_status="HANGUP", agent_username=None, queue_name=None),
        ]))
        with override_settings(HODU=hodu):
            m = compute_metrics(DAY, DAY)
        self.assertEqual(m["totals"]["unanswered"], 1)
        self.assertEqual(m["totals"]["other_inbound"], 0)

    def test_range_includes_the_whole_last_day(self):
        sync_day(DAY, client=ListClient([
            call_row(1, call_start_time="05-10-2026 00:00:00"),
            call_row(2, call_start_time="05-10-2026 23:59:59"),
            call_row(3, call_start_time="06-10-2026 00:00:00"),
        ]))
        self.assertEqual(compute_metrics(DAY, DAY)["totals"]["calls"], 2)

    def test_similar_agent_name_is_not_the_same_agent(self):
        rj = self.rejection([
            offer_row(1, "Agent10", "10:00:05", "10:00:20"),                 # missed
            offer_row(1, "Agent1", "10:00:20", "10:02:20", "NORMAL_CLEARING"),  # picked up
        ])
        self.assertEqual(rj["rejected_or_missed"], 1)
        self.assertEqual(rj["avg_ring_before_reject_sec"], 15)

    def test_agent_who_misses_then_answers_gets_one_rejection(self):
        rj = self.rejection([
            offer_row(1, "Agent1", "10:00:05", "10:00:20"),
            offer_row(1, "Agent1", "10:00:25", "10:02:20", "NORMAL_CLEARING"),
        ])
        self.assertEqual(rj["rejected_or_missed"], 1)
        self.assertEqual(rj["reasons"], {"NO_ANSWER": 1})

    def test_full_name_with_username_in_brackets_matches(self):
        rj = self.rejection(
            [offer_row(1, "Ada Obi (agent1)", "10:00:20", "10:02:20", "NORMAL_CLEARING")],
            agent_username="Agent1",
        )
        self.assertEqual(rj["rejected_or_missed"], 0)


@override_settings(HODU=MOCK_SETTINGS)
class ViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        sync_day(DAY, client=MockHoduClient(settings.HODU["SAMPLE_DIR"]))
        cls.user = get_user_model().objects.create_user("manager", password="a-long-test-password")

    def test_login_required(self):
        response = self.client.get(reverse("calls:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        # The APIs answer 401 with a message instead, which the page's JavaScript can read.
        for name in ("calls:metrics_api", "calls:agents_api", "calls:agent_api", "calls:monthly_api", "calls:calls_api",
                     "calls:rings_api",
                     "calls:live_api"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 401)
            self.assertIn("log in again", response.json()["error"])

    def test_no_forgotten_password_pages(self):
        # They would try to send email, which isn't set up.
        self.assertEqual(self.client.get("/accounts/password_reset/").status_code, 404)
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_server_errors_are_logged_even_with_debug_off(self):
        # Django's own console handler only prints when DEBUG is on.
        handlers = logging.getLogger("django.request").handlers
        self.assertTrue(any(isinstance(h, logging.StreamHandler) and not h.filters for h in handlers))

    def test_dashboard_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("calls:dashboard"))
        self.assertContains(response, "Calls by hour")
        self.assertContains(response, "General")  # queue filter option

    def test_metrics_api(self):
        self.client.force_login(self.user)
        data = self.client.get(reverse("calls:metrics_api"), {"from": "2026-10-05"}).json()
        self.assertEqual(data["totals"]["inbound"], 9)
        self.assertNotIn("0906", str(data))  # no full phone numbers leave the server

    def test_metrics_api_rejects_bad_dates(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("calls:metrics_api"), {"from": "05/10/2026"}).status_code, 400)
        response = self.client.get(reverse("calls:metrics_api"), {"from": "2026-10-06", "to": "2026-10-05"})
        self.assertEqual(response.status_code, 400)

    @override_settings(HODU={**MOCK_SETTINGS, "SAMPLE_DIR": FIXTURES / "no-such-folder"})
    def test_live_api_without_data(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("calls:live_api")).json()["available"], False)

    def sync_problem(self):
        self.client.force_login(self.user)
        return self.client.get(reverse("calls:metrics_api"), {"from": "2026-10-05"}).json()["sync_problem"]

    def test_no_sync_problem_after_a_good_sync(self):
        self.assertIsNone(self.sync_problem())

    def test_failed_sync_is_reported(self):
        sync_day(DAY, client=BrokenClient())
        problem = self.sync_problem()
        self.assertEqual(problem["level"], "error")
        self.assertIn("Token Authentication Failed", problem["message"])

    def test_a_passing_network_hiccup_is_a_calm_note(self):
        sync_day(DAY, client=UnreachableClient())  # after the good sync in setUpTestData
        problem = self.sync_problem()
        self.assertEqual(problem["level"], "warning")
        self.assertIn("slow to answer", problem["message"])

    def test_three_failures_in_a_row_are_an_error(self):
        for _ in range(3):
            sync_day(DAY, client=UnreachableClient())
        self.assertEqual(self.sync_problem()["level"], "error")

    @override_settings(HODU=LIVE_SETTINGS)
    def test_a_hiccup_with_old_numbers_is_an_error(self):
        SyncRun.objects.update(finished_at=timezone.now() - timedelta(hours=2))
        sync_day(DAY, client=UnreachableClient())
        self.assertEqual(self.sync_problem()["level"], "error")

    def test_sync_in_progress_is_not_reported_as_failed(self):
        SyncRun.objects.create(day=DAY)  # started, not finished
        self.assertIsNone(self.sync_problem())

    def test_warning_from_a_good_sync_is_reported(self):
        sync_day(DAY, client=ListClient([call_row(1), call_row(2, call_start_time="nonsense")]))
        problem = self.sync_problem()
        self.assertEqual(problem["level"], "warning")
        self.assertIn("Skipped 1 call row(s)", problem["message"])

    @override_settings(HODU=LIVE_SETTINGS)
    def test_sync_that_has_stopped_is_reported(self):
        SyncRun.objects.update(finished_at=timezone.now() - timedelta(hours=2))
        problem = self.sync_problem()
        self.assertEqual(problem["level"], "error")
        self.assertIn("No sync since", problem["message"])

    @override_settings(HODU=LIVE_SETTINGS)
    def test_recent_sync_is_not_stale(self):
        self.assertIsNone(self.sync_problem())

    def test_dashboard_page_shows_the_problem(self):
        sync_day(DAY, client=BrokenClient())
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("calls:dashboard")), "Last sync failed")


@override_settings(HODU=MOCK_SETTINGS)
class AdminTests(TestCase):
    def test_synced_data_cannot_be_added_changed_or_deleted(self):
        request = RequestFactory().get("/admin/")
        request.user = get_user_model().objects.create_superuser("root", password="a-long-test-password")
        for model in (Call, AgentOffer, SyncRun):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))


@override_settings(HODU={**LIVE_SETTINGS, "SYNC_ON_VIEW_SECONDS": 60})
class LiveModeTests(TestCase):
    """While someone looks at today, the dashboard fetches from HoduCC by itself."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("manager", password="a-long-test-password")

    def setUp(self):
        self.client.force_login(self.user)

    def get_metrics(self, day):
        # sync_in_background is replaced, so no thread starts and nothing reaches HoduCC.
        with mock.patch("calls.views.sync_in_background", return_value=True) as start:
            response = self.client.get(reverse("calls:metrics_api"), {"from": day.isoformat()})
        return start, response.json()

    def test_viewing_today_starts_a_background_sync(self):
        start, _ = self.get_metrics(timezone.localdate())
        start.assert_called_once_with(60)

    def test_viewing_the_past_does_not(self):
        start, _ = self.get_metrics(DAY)
        start.assert_not_called()

    def test_old_data_being_refreshed_is_a_warning_not_an_error(self):
        run = SyncRun.objects.create(day=DAY, ok=True)
        SyncRun.objects.filter(pk=run.pk).update(finished_at=timezone.now() - timedelta(hours=2))
        _, data = self.get_metrics(timezone.localdate())
        self.assertEqual(data["sync_problem"]["level"], "warning")
        self.assertIn("Fetching the latest calls", data["sync_problem"]["message"])

    @override_settings(HODU={**LIVE_SETTINGS, "SYNC_ON_VIEW_SECONDS": 0})
    def test_can_be_switched_off(self):
        start, _ = self.get_metrics(timezone.localdate())
        start.assert_not_called()


class SyncInBackgroundTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_at_most_one_sync_per_gap(self):
        with mock.patch("calls.sync.threading.Thread") as thread:
            self.assertTrue(sync_in_background(60))
            self.assertFalse(sync_in_background(60))
        thread.return_value.start.assert_called_once()
