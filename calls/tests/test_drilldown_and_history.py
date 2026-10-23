"""
Tests for the drill-down lists (the calls behind a number), the "vs the period before" totals,
the hangup reason, and filling in history by itself (and with sync_calls --from).
Like the other tests, they never call HoduCC.
"""
from datetime import datetime, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from calls import sync
from calls.metrics import call_list, compute_metrics, ring_list
from calls.models import SyncRun
from calls.parsing import call_from_row
from calls.sync import backfill_in_background, missing_days, sync_day
from calls.tests.test_agents_and_live import make_activity_day
from calls.tests.test_sync_and_metrics import DAY, MOCK_SETTINGS, ListClient, call_row, offer_row


class HangupReasonTests(SimpleTestCase):
    def test_kept_from_the_row(self):
        row = call_row(1, call_type="OUTBOUND", call_status="DIAL", hangup_reason="Service Unavailable")
        fields = call_from_row(row)
        self.assertEqual(fields["hangup_reason"], "Service Unavailable")


@override_settings(HODU=MOCK_SETTINGS)
class CallListTests(TestCase):
    """The made-up day from the Agents tests: one call in, one out connected, two out not connected."""

    @classmethod
    def setUpTestData(cls):
        make_activity_day()

    def total(self, kind="all", **filters):
        return call_list(DAY, DAY, kind, **filters)["total"]

    def test_each_kind(self):
        expected = {"all": 4, "inbound": 1, "outbound": 3, "connected": 1, "not_connected": 2, "answered_in": 1}
        self.assertEqual({kind: self.total(kind) for kind in expected}, expected)
        self.assertEqual(self.total("unanswered"), 0)

    def test_one_agent_whatever_the_capitals_and_one_hour(self):
        self.assertEqual(self.total(agent="agent1"), 3)
        self.assertEqual(self.total(hour=9), 1)  # only the call at 09:10
        self.assertEqual(self.total("outbound", agent="Agent2"), 1)

    def test_calls_carry_the_reason_and_only_the_last_four_digits(self):
        sync_day(DAY, client=ListClient([call_row(9, call_type="OUTBOUND", call_status="DIAL",
                                                  hangup_reason="Service Unavailable", hangup_by="SYSTEM")]))
        data = call_list(DAY, DAY, "not_connected")
        self.assertIn({"reason": "Service Unavailable", "count": 1}, data["reasons"])
        self.assertIn({"by": "SYSTEM", "count": 1}, data["ended_by"])
        call = next(c for c in data["calls"] if c["call_id"] == 9)
        self.assertEqual((call["hangup_reason"], call["caller_masked"]), ("Service Unavailable", "•••0000"))


@override_settings(HODU=MOCK_SETTINGS)
class PreviousPeriodTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        sync_day(DAY, client=ListClient([
            call_row(1),                                                   # 5 Oct: in
            call_row(2, call_start_time="04-10-2026 10:00:00"),            # 4 Oct: in
            call_row(3, call_start_time="04-10-2026 11:00:00", call_type="OUTBOUND"),
            call_row(4, call_start_time="02-10-2026 11:00:00"),            # 2 Oct: in
        ]))

    def test_one_day_compares_with_the_day_before(self):
        before = compute_metrics(DAY, DAY)["previous"]
        self.assertEqual((before["from"], before["to"]), ("2026-10-04", "2026-10-04"))
        self.assertEqual((before["inbound"], before["outbound"]), (1, 1))

    def test_a_range_compares_with_the_same_length_before_it(self):
        before = compute_metrics(DAY - timedelta(days=1), DAY)["previous"]  # 4-5 Oct -> 2-3 Oct
        self.assertEqual((before["from"], before["to"], before["inbound"]), ("2026-10-02", "2026-10-03", 1))
        self.assertIsNone(before["until"])

    def test_today_compares_with_the_day_before_up_to_the_same_time(self):
        # At 10:30 on 5 Oct, 4 Oct counts only up to 10:30: the 10:00 call in, not the 11:00 call out
        half_past_ten = timezone.make_aware(datetime(2026, 10, 5, 10, 30))
        with mock.patch("django.utils.timezone.now", return_value=half_past_ten):
            before = compute_metrics(DAY, DAY)["previous"]
        self.assertEqual((before["until"], before["inbound"], before["outbound"]), ("10:30", 1, 0))


class MissingDaysTests(TestCase):
    def run_for(self, day, ok, after_the_day=True):
        """A sync run for `day`, started after the day was over (or during it)."""
        run = SyncRun.objects.create(day=day, ok=ok, finished_at=timezone.now())
        over = sync._day_over(day)
        started = over + timedelta(hours=1) if after_the_day else over - timedelta(hours=6)
        SyncRun.objects.filter(pk=run.pk).update(started_at=started)

    def test_days_never_synced_are_missing(self):
        three_days = [DAY + timedelta(days=n) for n in range(3)]
        self.assertEqual(missing_days(DAY, three_days[-1]), three_days)

    def test_a_good_sync_after_the_day_ended_completes_it(self):
        self.run_for(DAY, ok=True)
        self.assertEqual(missing_days(DAY, DAY), [])

    def test_a_sync_while_the_day_was_still_going_on_does_not(self):
        self.run_for(DAY, ok=True, after_the_day=False)
        self.assertEqual(missing_days(DAY, DAY), [DAY])

    def test_a_day_that_keeps_failing_is_given_up(self):
        for _ in range(sync.MAX_FINAL_TRIES):
            self.run_for(DAY, ok=False)
        self.assertEqual(missing_days(DAY, DAY), [])

    def test_today_and_later_are_never_missing(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.assertEqual(missing_days(yesterday, yesterday + timedelta(days=6)), [yesterday])


class BackfillTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_one_fill_at_a_time(self):
        with mock.patch("calls.sync.threading.Thread") as thread:
            first = backfill_in_background([DAY, DAY + timedelta(days=1)])
            second = backfill_in_background([DAY])
        self.assertEqual(thread.call_count, 1)
        self.assertEqual(first, {"total": 2, "done": 0})
        self.assertEqual(second, first)  # the second asks how the first is getting on

    def test_nothing_to_fetch(self):
        self.assertIsNone(backfill_in_background([]))

    def test_the_fill_syncs_each_day_and_reports_progress(self):
        cache.add("backfill-running", True)
        with mock.patch("calls.sync.sync_day") as fetch:
            sync._backfill([DAY, DAY + timedelta(days=1)])
        self.assertEqual([c.args[0] for c in fetch.call_args_list], [DAY, DAY + timedelta(days=1)])
        self.assertEqual(cache.get("backfill"), {"total": 2, "done": 2})
        self.assertIsNone(cache.get("backfill-running"))  # free for the next fill


@override_settings(HODU={**MOCK_SETTINGS, "MOCK": False, "AUTO_BACKFILL": True, "SYNC_ON_VIEW_SECONDS": 0})
class ApiFillsHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("manager", password="a-long-test-password")

    def setUp(self):
        self.client.force_login(self.user)

    def test_looking_at_unfetched_days_starts_fetching_them(self):
        progress = {"total": 3, "done": 0}
        with mock.patch("calls.views.backfill_in_background", return_value=progress) as fill:
            data = self.client.get(reverse("calls:metrics_api"), {"from": "2026-09-01", "to": "2026-09-03"}).json()
        fill.assert_called_once()
        self.assertEqual(len(fill.call_args.args[0]), 3)
        self.assertEqual(data["backfill"], progress)

    @override_settings(HODU={**MOCK_SETTINGS, "MOCK": False, "AUTO_BACKFILL": False, "SYNC_ON_VIEW_SECONDS": 0})
    def test_switched_off(self):
        with mock.patch("calls.views.backfill_in_background") as fill:
            data = self.client.get(reverse("calls:metrics_api"), {"from": "2026-09-01"}).json()
        fill.assert_not_called()
        self.assertIsNone(data["backfill"])


@override_settings(HODU=MOCK_SETTINGS)
@override_settings(HODU=MOCK_SETTINGS)
class RingsTests(TestCase):
    """
    Call 1 rang Agent2 (not taken), then Agent1, who answered. Call 2 rang Agent2, and the caller hung up
    while it rang: nobody answered it.
    """

    @classmethod
    def setUpTestData(cls):
        sync_day(DAY, client=ListClient(
            [call_row(1), call_row(2, call_status="ABANDONED", agent_username=None)],
            offers=[
                offer_row(1, "Agent 02 (Agent2)", "10:00:00", "10:00:12"),
                offer_row(1, "Agent 01 (Agent1)", "10:00:13", "10:00:30", reason="NORMAL_CLEARING"),
                offer_row(2, "Agent 02 (Agent2)", "11:00:00", "11:00:09", reason="ORIGINATOR_CANCEL"),
            ],
        ))

    def test_missed_rings_with_their_calls(self):
        data = ring_list(DAY, DAY)
        self.assertEqual(data["total"], 2)  # the ring Agent1 picked up isn't one
        newest, older = data["rings"]
        self.assertEqual((newest["call_id"], newest["ring_seconds"], newest["answered_by"]), (2, 9, ""))
        self.assertEqual((older["call_id"], older["answered_by"], older["call_status"]), (1, "Agent1", "AGENT"))
        self.assertIn({"reason": "ORIGINATOR_CANCEL", "count": 1}, data["reasons"])

    def test_one_agent_whatever_the_capitals(self):
        self.assertEqual(ring_list(DAY, DAY, agent="agent2")["total"], 2)
        self.assertEqual(ring_list(DAY, DAY, agent="Agent1")["total"], 0)

    def test_an_unanswered_call_says_who_it_rang(self):
        calls = {c["call_id"]: c for c in call_list(DAY, DAY)["calls"]}
        self.assertEqual(calls[2]["rang"], ["Agent2"])
        self.assertEqual(calls[1]["rang"], [])  # answered: its agent is known

    def test_the_api(self):
        user = get_user_model().objects.create_user("manager", password="a-long-test-password")
        self.client.force_login(user)
        url = reverse("calls:rings_api")
        self.assertEqual(self.client.get(url, {"from": "2026-10-05"}).json()["total"], 2)
        self.assertEqual(self.client.get(url, {"from": "2026-10-05", "to": "2026-10-01"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"from": "05/10/2026"}).status_code, 400)


class CallsApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("manager", password="a-long-test-password")
        make_activity_day()

    def setUp(self):
        self.client.force_login(self.user)

    def get(self, **params):
        return self.client.get(reverse("calls:calls_api"), {"from": "2026-10-05", **params})

    def test_a_list(self):
        data = self.get(kind="not_connected").json()
        self.assertEqual((data["total"], len(data["calls"]), data["kind"]), (2, 2, "not_connected"))

    def test_bad_requests(self):
        self.assertEqual(self.get(kind="everything").status_code, 400)
        self.assertEqual(self.get(hour="25").status_code, 400)
        self.assertEqual(self.get(to="2026-10-01").status_code, 400)


class SyncCommandRangeTests(TestCase):
    def test_from_and_to(self):
        done = mock.Mock(ok=True, calls_received=0, offers_received=0, message="")
        with mock.patch("calls.management.commands.sync_calls.sync_day", return_value=done) as fetch, \
                mock.patch("calls.management.commands.sync_calls.sync_agents_if_due"):
            call_command("sync_calls", "--from", "2026-10-01", "--to", "2026-10-03", stdout=mock.Mock())
        days = [c.args[0].isoformat() for c in fetch.call_args_list]
        self.assertEqual(days, ["2026-10-01", "2026-10-02", "2026-10-03"])

    def test_to_before_from(self):
        with self.assertRaises(CommandError):
            call_command("sync_calls", "--from", "2026-10-03", "--to", "2026-10-01")
