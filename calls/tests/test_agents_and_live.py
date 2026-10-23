"""
Tests for the Agents and Live tabs: staff names, the agent list sync, daily activity, live numbers.
Like the other tests, they never call HoduCC: replies come from tests/fixtures/ or are made up here.
"""
import importlib
import json
from datetime import date, timedelta
from unittest import mock

from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from calls.client import HoduError, MockHoduClient
from calls.metrics import add_months, agent_activity, agent_detail, compute_metrics, monthly
from calls.models import Agent, AgentOffer
from calls.parsing import agent_from_row, agent_login, offer_from_row
from calls.sync import sync_agents, sync_agents_if_due, sync_day
from calls.tests.test_sync_and_metrics import DAY, FIXTURES, MOCK_SETTINGS, ListClient, call_row, offer_row


class AgentListClient(ListClient):
    """ListClient that also answers getAgentList."""

    def __init__(self, agents=(), **kwargs):
        super().__init__(kwargs.pop("calls", []), **kwargs)
        self.agents = list(agents)

    def get_agent_list(self):
        return self.agents


def listed(username, first="Agent", last=""):
    return {"agt_id": 1, "agt_uname": username, "agt_fname": first, "agt_lname": last}


class AgentParsingTests(SimpleTestCase):
    def test_login_from_display_name(self):
        self.assertEqual(agent_login("Agent 01 (Agent01) "), "Agent01")
        self.assertEqual(agent_login("Agent01"), "Agent01")
        self.assertEqual(agent_login(None), "")

    def test_offer_keeps_the_login(self):
        offer = offer_from_row({"aoc_call_id": 5, "aoc_agt_id": "Agent 01 (Agent01) ",
                                "aoc_offered_time": "15-10-2026 12:12:38", "aoc_hangup_time": "15-10-2026 12:13:00"})
        self.assertEqual(offer["agent_name"], "Agent 01 (Agent01)")
        self.assertEqual(offer["agent_username"], "Agent01")

    def test_agent_row_leaves_out_contact_details_and_token(self):
        row = json.loads((FIXTURES / "agentlist.json").read_text())["Agents"][0]
        fields = agent_from_row(row)
        self.assertEqual(fields, {"username": "Agent01", "hodu_id": 191, "hodu_name": "Agent 01"})

    def test_row_without_login_is_skipped(self):
        self.assertIsNone(agent_from_row({"agt_id": 9}))


@override_settings(HODU=MOCK_SETTINGS)
class AgentSyncTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_agents_come_from_hoducc(self):
        self.assertEqual(sync_agents(MockHoduClient(FIXTURES)), 3)
        agent = Agent.objects.get(username="Agent01")
        self.assertEqual((agent.hodu_id, agent.hodu_name, agent.is_active), (191, "Agent 01", True))
        self.assertEqual(agent.display_name, "Agent 01")

    def test_token_email_and_phone_are_never_stored(self):
        sync_agents(MockHoduClient(FIXTURES))
        stored = str(list(Agent.objects.values()))
        for secret in ("made-up-token", "@example.com", "0800000000"):
            self.assertNotIn(secret, stored)

    def test_your_staff_details_survive_a_resync(self):
        sync_agents(AgentListClient([listed("Agent01", "Agent", "01")]))
        Agent.objects.filter(username="Agent01").update(staff_name="Ada Example", staff_id="E-1", team="Inbound")
        sync_agents(AgentListClient([listed("Agent01", "Renamed", "In HoduCC")]))
        agent = Agent.objects.get(username="Agent01")
        self.assertEqual((agent.staff_name, agent.staff_id, agent.team), ("Ada Example", "E-1", "Inbound"))
        self.assertEqual(agent.hodu_name, "Renamed In HoduCC")
        self.assertEqual(agent.display_name, "Ada Example")

    def test_agent_who_left_is_kept_but_inactive(self):
        sync_agents(AgentListClient([listed("Agent01"), listed("Agent02")]))
        sync_agents(AgentListClient([listed("Agent01")]))
        self.assertFalse(Agent.objects.get(username="Agent02").is_active)

    def test_an_empty_list_does_not_deactivate_everyone(self):
        sync_agents(AgentListClient([listed("Agent01")]))
        sync_agents(AgentListClient([]))
        self.assertTrue(Agent.objects.get(username="Agent01").is_active)

    def test_logins_seen_only_in_calls_get_a_row_to_name(self):
        sync_day(DAY, client=ListClient([call_row(1, agent_username="OldAgent")]))
        sync_agents(AgentListClient([listed("Agent01")]))
        self.assertFalse(Agent.objects.get(username="OldAgent").is_active)

    def test_logins_match_whatever_the_capitals(self):
        sync_day(DAY, client=ListClient([call_row(1, agent_username="agent01")]))
        sync_agents(AgentListClient([listed("Agent02")]))  # agent01 gets an inactive row from the calls
        sync_agents(AgentListClient([listed("Agent01"), listed("Agent02")]))
        sync_day(DAY, client=ListClient([call_row(2, agent_username="AGENT01")]))
        sync_agents(AgentListClient([listed("Agent01"), listed("Agent02")]))
        rows = Agent.objects.filter(username__iexact="agent01")
        self.assertEqual(len(rows), 1)  # no second row for the other spellings
        self.assertTrue(rows[0].is_active)

    def test_routine_sync_fetches_the_list_at_most_once_an_hour(self):
        client = AgentListClient([listed("Agent01")])
        with mock.patch.object(client, "get_agent_list", wraps=client.get_agent_list) as fetch:
            sync_agents_if_due(client)
            sync_agents_if_due(client)
        self.assertEqual(fetch.call_count, 1)

    def test_routine_sync_carries_on_if_the_list_fails(self):
        class Broken:
            def get_agent_list(self):
                raise HoduError("down")

        with self.assertLogs("calls.sync", level="WARNING"):
            sync_agents_if_due(Broken())  # no exception

    def test_failed_routine_sync_retries_on_the_next_call(self):
        client = AgentListClient([listed("Agent01")])
        with mock.patch("calls.sync.sync_agents", side_effect=[HoduError("down"), 1]) as sync:
            with self.assertLogs("calls.sync", level="WARNING"):
                sync_agents_if_due(client)
            sync_agents_if_due(client)
        self.assertEqual(sync.call_count, 2)


class MigrationTests(TestCase):
    def test_existing_rings_get_their_login(self):
        offer = AgentOffer.objects.create(call_id=1, agent_name="Agent 02 (Agent02)", offered_at=timezone.now())
        migration = importlib.import_module("calls.migrations.0002_agents")
        migration.fill_agent_username(apps, None)
        offer.refresh_from_db()
        self.assertEqual(offer.agent_username, "Agent02")


def make_activity_day():
    """One made-up day: Agent1 takes calls in and out, Agent2 only dials, Agent3 does nothing."""
    sync_day(DAY, client=ListClient(
        [
            call_row(1, call_start_time="05-10-2026 09:10:00", agent_duration="0:02:00"),  # in, answered
            call_row(2, call_type="OUTBOUND", call_start_time="05-10-2026 10:00:00",
                     agent_duration="0:01:00"),                                              # out, answered
            call_row(3, call_type="OUTBOUND", call_status="DIAL", agent_duration="0:00:00",
                     call_start_time="05-10-2026 10:05:00"),                                 # out, not connected
            call_row(4, call_type="OUTBOUND", call_status="DIAL", agent_username="Agent2",
                     agent_duration="0:00:00"),                                              # out, not connected
        ],
        offers=[
            offer_row(1, "Agent 02 (Agent2)", "09:09:50", "09:09:58"),                   # Agent2 missed it
            offer_row(1, "Agent 01 (Agent1)", "09:09:58", "09:12:00", "NORMAL_CLEARING"),  # Agent1 took it
        ],
    ))
    Agent.objects.create(username="Agent1", hodu_name="Agent 01", staff_name="Ada Example", team="Inbound")
    Agent.objects.create(username="Agent2", hodu_name="Agent 02")
    Agent.objects.create(username="Agent3", hodu_name="Agent 03")
    Agent.objects.create(username="Gone", hodu_name="Left Us", is_active=False)


@override_settings(HODU=MOCK_SETTINGS)
class AgentActivityTests(TestCase):
    """One made-up day: Agent1 takes calls in and out, Agent2 only dials, Agent3 does nothing."""

    @classmethod
    def setUpTestData(cls):
        make_activity_day()

    def by_login(self):
        return {a["agent"]: a for a in agent_activity(DAY)["agents"]}

    def test_counts_per_agent(self):
        ada = self.by_login()["Agent1"]
        self.assertEqual((ada["answered_in"], ada["answered_out"], ada["not_connected_out"]), (1, 1, 1))
        self.assertEqual(ada["handled"], 2)
        self.assertEqual(ada["talk_sec"], 180)
        self.assertEqual(ada["avg_talk_sec"], 90)
        self.assertEqual(ada["missed_rings"], 0)

    def test_staff_name_and_team_are_shown(self):
        ada = self.by_login()["Agent1"]
        self.assertEqual((ada["name"], ada["team"]), ("Ada Example", "Inbound"))
        self.assertEqual(self.by_login()["Agent2"]["name"], "Agent 02")  # no staff name yet: HoduCC's name

    def test_missed_rings_are_counted_per_agent(self):
        self.assertEqual(self.by_login()["Agent2"]["missed_rings"], 1)

    def test_active_agents_with_no_calls_are_listed(self):
        agents = self.by_login()
        self.assertEqual(agents["Agent3"]["handled"], 0)
        self.assertNotIn("Gone", agents)

    def test_busiest_first(self):
        self.assertEqual([a["agent"] for a in agent_activity(DAY)["agents"]], ["Agent1", "Agent2", "Agent3"])

    def test_calls_made_and_received(self):
        agents = self.by_login()
        ada, agent2 = agents["Agent1"], agents["Agent2"]
        self.assertEqual((ada["made"], ada["received"], ada["connect_ratio_pct"]), (2, 1, 50.0))
        self.assertEqual((agent2["made"], agent2["received"], agent2["connect_ratio_pct"]), (1, 0, 0.0))
        self.assertIsNone(agents["Agent3"]["connect_ratio_pct"])  # dialled nothing: no rate

    def test_a_range_of_days(self):
        week = {a["agent"]: a for a in agent_activity(DAY - timedelta(days=3), DAY + timedelta(days=3))["agents"]}
        self.assertEqual(week["Agent1"]["made"], 2)
        later = {a["agent"]: a for a in agent_activity(DAY + timedelta(days=1), DAY + timedelta(days=3))["agents"]}
        self.assertEqual(later["Agent1"]["made"], 0)

    def test_overview_uses_staff_names_too(self):
        m = compute_metrics(DAY, DAY)
        self.assertEqual(m["agents"][0]["name"], "Ada Example")

    def test_call_log_lists_the_days_calls_with_staff_names(self):
        day = agent_activity(DAY)
        log = day["recent"]
        self.assertEqual((len(log), day["calls_total"]), (4, 4))
        self.assertIn("Ada Example", {c["agent_name"] for c in log})

    def test_connect_rate_is_answered_outbound_over_all_outbound(self):
        t = compute_metrics(DAY, DAY)["totals"]
        self.assertEqual((t["answered_outbound"], t["outbound"]), (1, 3))
        self.assertEqual(t["connect_ratio_pct"], 33.3)

    def test_logins_match_whatever_the_capitals(self):
        sync_day(DAY, client=ListClient(
            [call_row(5, agent_username="agent1", call_start_time="05-10-2026 09:30:00")],  # in, answered
            offers=[offer_row(5, "Agent 03 (AGENT3)", "09:29:50", "09:29:58")],             # Agent3 missed it
        ))
        agents = self.by_login()
        self.assertEqual(set(agents), {"Agent1", "Agent2", "Agent3"})  # no extra rows for agent1 or AGENT3
        self.assertEqual((agents["Agent1"]["answered_in"], agents["Agent1"]["name"]), (2, "Ada Example"))
        self.assertEqual(agents["Agent3"]["missed_rings"], 1)
        m = compute_metrics(DAY, DAY)
        self.assertEqual([(a["name"], a["answered"]) for a in m["agents"]], [("Ada Example", 3)])
        log = agent_activity(DAY)["recent"]
        self.assertEqual({c["agent_name"] for c in log if c["call_id"] == 5}, {"Ada Example"})


@override_settings(HODU=MOCK_SETTINGS)
class AgentDetailTests(TestCase):
    """The same made-up day as AgentActivityTests, seen one agent at a time over three days."""

    @classmethod
    def setUpTestData(cls):
        make_activity_day()

    def detail(self, login="Agent1"):
        return agent_detail(login, DAY, DAY + timedelta(days=2))

    def test_totals(self):
        t = self.detail()["totals"]
        self.assertEqual((t["answered_in"], t["answered_out"], t["not_connected_out"]), (1, 1, 1))
        self.assertEqual((t["handled"], t["talk_sec"], t["avg_talk_sec"]), (2, 180, 90))
        self.assertEqual(t["connect_ratio_pct"], 50.0)  # 1 of 2 outbound calls connected

    def test_every_day_in_the_range_is_listed(self):
        days = self.detail()["days"]
        self.assertEqual([d["date"] for d in days], ["2026-10-05", "2026-10-06", "2026-10-07"])
        self.assertEqual((days[0]["answered_in"], days[1]["answered_in"]), (1, 0))

    def test_name_missed_rings_and_calls(self):
        ada = self.detail()
        self.assertEqual((ada["name"], ada["team"]), ("Ada Example", "Inbound"))
        self.assertEqual(len(ada["recent"]), 3)
        self.assertEqual(self.detail("Agent2")["totals"]["missed_rings"], 1)

    def test_login_whatever_the_capitals(self):
        self.assertEqual(self.detail("agent1")["agent"], "Agent1")
        self.assertEqual(self.detail("agent1")["totals"]["handled"], 2)

    def test_agent_with_no_calls(self):
        nobody = self.detail("Agent3")
        self.assertEqual((nobody["totals"]["handled"], nobody["totals"]["avg_talk_sec"]), (0, None))


@override_settings(HODU=MOCK_SETTINGS)
class MonthlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        sync_day(DAY, client=ListClient([
            call_row(1),                                                          # Oct: in, answered
            call_row(2, call_status="ABANDONED", agent_username=""),              # Oct: in, unanswered
            call_row(3, call_type="OUTBOUND", call_start_time="12-09-2026 10:00:00"),  # Sep: out, connected
            call_row(4, call_type="OUTBOUND", call_status="DIAL",
                     call_start_time="01-11-2026 00:30:00"),                      # Nov (00:30 local time)
        ]))

    def test_months_in_order_with_empty_ones_as_zeros(self):
        months = monthly(date(2026, 8, 1), date(2026, 11, 30))["months"]
        self.assertEqual([m["month"] for m in months], ["2026-08", "2026-09", "2026-10", "2026-11"])
        self.assertEqual(months[0]["inbound"] + months[0]["outbound"], 0)
        self.assertEqual((months[1]["outbound"], months[1]["answered_out"]), (1, 1))
        self.assertEqual((months[2]["answered_in"], months[2]["unanswered_in"]), (1, 1))

    def test_a_call_just_after_midnight_counts_in_the_new_month(self):
        months = {m["month"]: m for m in monthly(date(2026, 10, 1), date(2026, 11, 1))["months"]}
        self.assertEqual((months["2026-10"]["outbound"], months["2026-11"]["outbound"]), (0, 1))

    def test_totals(self):
        t = monthly(date(2026, 9, 1), date(2026, 11, 1))["totals"]
        self.assertEqual((t["calls"], t["answer_ratio_pct"], t["connect_ratio_pct"]), (4, 50.0, 50.0))

    def test_agents_ranked_over_the_months(self):
        agents = {a["agent"]: a for a in monthly(date(2026, 9, 1), date(2026, 11, 1))["agents"]}
        self.assertEqual((agents["Agent1"]["made"], agents["Agent1"]["received"]), (2, 1))
        self.assertEqual(monthly(date(2026, 9, 1), date(2026, 9, 1))["agents"][0]["made"], 1)  # September only

    def test_add_months(self):
        self.assertEqual(add_months(date(2026, 1, 9), -1), date(2025, 12, 1))
        self.assertEqual(add_months(date(2026, 11, 30), 2), date(2027, 1, 1))


@override_settings(HODU=MOCK_SETTINGS)
class AgentAndMonthlyApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("manager", password="a-long-test-password")
        sync_day(DAY, client=ListClient([call_row(1)]))

    def setUp(self):
        self.client.force_login(self.user)

    def get(self, name, **params):
        return self.client.get(reverse(name), params)

    def test_agent(self):
        data = self.get("calls:agent_api", agent="Agent1", **{"from": "2026-10-01", "to": "2026-10-31"}).json()
        self.assertEqual((data["totals"]["answered_in"], len(data["days"])), (1, 31))
        self.assertIn("sync_problem", data)

    def test_agent_needs_an_agent_and_a_sensible_range(self):
        self.assertEqual(self.get("calls:agent_api").status_code, 400)
        self.assertEqual(self.get("calls:agent_api", agent="Agent1", **{"from": "2026-01-01"}).status_code, 400)
        self.assertEqual(self.get("calls:agent_api", agent="Agent1", **{"from": "05/10/2026"}).status_code, 400)

    def test_monthly(self):
        data = self.get("calls:monthly_api", **{"from": "2026-09", "to": "2026-10"}).json()
        self.assertEqual([m["month"] for m in data["months"]], ["2026-09", "2026-10"])
        self.assertEqual(data["totals"]["inbound"], 1)

    def test_monthly_defaults_to_the_last_twelve_months(self):
        self.assertEqual(len(self.get("calls:monthly_api").json()["months"]), 12)

    def test_monthly_rejects_bad_ranges(self):
        self.assertEqual(self.get("calls:monthly_api", to="October").status_code, 400)
        self.assertEqual(self.get("calls:monthly_api", **{"from": "2026-10", "to": "2026-09"}).status_code, 400)
        self.assertEqual(self.get("calls:monthly_api", **{"from": "2020-01", "to": "2026-10"}).status_code, 400)


@override_settings(HODU=MOCK_SETTINGS)
class AgentsApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("manager", password="a-long-test-password")
        sync_day(DAY, client=ListClient([call_row(1)]))
        Agent.objects.create(username="Agent1", staff_name="Ada Example")

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("calls:agents_api")).status_code, 401)

    def test_one_day(self):
        self.client.force_login(self.user)
        data = self.client.get(reverse("calls:agents_api"), {"date": "2026-10-05"}).json()
        self.assertEqual((data["from"], data["to"]), ("2026-10-05", "2026-10-05"))
        self.assertEqual(data["agents"][0]["name"], "Ada Example")
        self.assertIn("sync_problem", data)

    def test_a_range(self):
        self.client.force_login(self.user)
        data = self.client.get(reverse("calls:agents_api"), {"from": "2026-10-01", "to": "2026-10-31"}).json()
        self.assertEqual(data["agents"][0]["received"], 1)
        bad = self.client.get(reverse("calls:agents_api"), {"from": "2026-10-31", "to": "2026-10-01"})
        self.assertEqual(bad.status_code, 400)

    def test_bad_date(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("calls:agents_api"), {"date": "05/10/2026"}).status_code, 400)

    @override_settings(HODU={**MOCK_SETTINGS, "MOCK": False, "SYNC_ON_VIEW_SECONDS": 60})
    def test_today_keeps_live(self):
        self.client.force_login(self.user)
        with mock.patch("calls.views.sync_in_background", return_value=True) as start:
            self.client.get(reverse("calls:agents_api"))
        start.assert_called_once_with(60)


@override_settings(HODU=MOCK_SETTINGS)
class LiveApiTests(TestCase):
    """The fixture: 3 logged in, 1 on a call, 2 waiting; queues General and outbound."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("manager", password="a-long-test-password")
        for login in ("Agent01", "Agent02", "Agent03"):
            Agent.objects.create(username=login)

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.force_login(self.user)

    def get_live(self):
        return self.client.get(reverse("calls:live_api")).json()

    def test_totals(self):
        t = self.get_live()["totals"]
        self.assertEqual((t["waiting"], t["on_calls"], t["logged_in"], t["idle"]), (2, 1, 3, 2))
        self.assertEqual((t["calls_today"], t["answered_today"], t["abandoned_today"]), (12, 9, 3))
        self.assertEqual((t["avg_wait_sec"], t["avg_talk_sec"]), (30, 90))
        self.assertEqual(t["agents_total"], 3)

    def test_one_row_per_queue(self):
        queues = {q["name"]: q for q in self.get_live()["queues"]}
        self.assertEqual(set(queues), {"General", "outbound"})
        self.assertEqual((queues["General"]["idle"], queues["General"]["assigned"]), (1, 3))

    def test_strip_numbers(self):
        live = self.get_live()
        self.assertTrue(live["available"])
        self.assertEqual((live["waiting_now"], live["agents_idle"]), (2, 2))

    def test_hoducc_down(self):
        with mock.patch("calls.views.get_client", side_effect=HoduError("down")):
            live = self.get_live()
        self.assertEqual((live["available"], live["error"]), (False, "down"))

    def reply(self, summary):
        """/api/live/ when HoduCC's realtime summary is `summary`."""
        client = mock.Mock()
        client.get_realtime_queue_summary.return_value = summary
        with mock.patch("calls.views.get_client", return_value=client):
            return self.get_live()

    def test_a_value_that_isnt_a_duration_is_left_blank(self):
        t = self.reply({"agent_total_avg": {"live_agent": "3", "awt": "N/A", "att": "0:01:30"}})["totals"]
        self.assertEqual((t["logged_in"], t["avg_wait_sec"], t["avg_talk_sec"]), (3, None, 90))

    def test_a_reply_in_an_unexpected_shape_is_not_a_crash(self):
        with self.assertLogs("calls.views", level="ERROR"):
            live = self.reply(["not", "the", "usual", "dictionary"])
        self.assertFalse(live["available"])
        self.assertIn("can't read", live["error"])

    def test_answers_come_from_the_cache_for_a_few_seconds(self):
        self.get_live()
        with mock.patch("calls.views.get_client") as client:
            self.get_live()
        client.assert_not_called()


@override_settings(HODU=MOCK_SETTINGS)
class DashboardPageTests(TestCase):
    def test_page_has_three_tabs_and_the_settings_for_the_javascript(self):
        user = get_user_model().objects.create_user("manager", password="a-long-test-password")
        self.client.force_login(user)
        response = self.client.get(reverse("calls:dashboard"))
        for tab in ("tab-overview", "tab-agents", "tab-live"):
            self.assertContains(response, f'id="{tab}"')
        config = json.loads(response.content.decode().split('id="dashboard-config" type="application/json">')[1]
                            .split("</script>")[0])
        self.assertEqual(config["urls"]["agents"], reverse("calls:agents_api"))
        self.assertNotContains(response, "{#")  # no template comment leaks onto the page
        # The page and the APIs carry the same code version, so an open page can tell when the code changed
        api = self.client.get(reverse("calls:agents_api")).json()
        self.assertEqual(api["version"], config["version"])
        self.assertTrue(config["version"])

    def test_page_has_the_logo_and_no_link_to_admin(self):
        user = get_user_model().objects.create_superuser("owner", password="a-long-test-password")
        self.client.force_login(user)
        response = self.client.get(reverse("calls:dashboard"))
        self.assertContains(response, "calls/brand/logo.png")
        self.assertNotContains(response, reverse("admin:index"))  # not even for the owner


class AdminAccessTests(TestCase):
    """Admin is for superusers only: staff logins and ordinary users are turned away."""

    def get_admin(self, **flags):
        user = get_user_model().objects.create_user("someone", password="a-long-test-password", **flags)
        self.client.force_login(user)
        return self.client.get(reverse("admin:index"))

    def test_ordinary_user_is_turned_away(self):
        self.assertRedirects(self.get_admin(), f"{reverse('admin:login')}?next={reverse('admin:index')}")

    def test_staff_user_is_turned_away(self):
        self.assertEqual(self.get_admin(is_staff=True).status_code, 302)

    def test_superuser_gets_in(self):
        self.assertEqual(self.get_admin(is_staff=True, is_superuser=True).status_code, 200)


class AgentAdminTests(TestCase):
    def test_staff_details_editable_but_rows_come_from_hoducc(self):
        request = RequestFactory().get("/admin/")
        request.user = get_user_model().objects.create_superuser("root", password="a-long-test-password")
        agent_admin = admin.site._registry[Agent]
        self.assertTrue(agent_admin.has_change_permission(request))
        self.assertFalse(agent_admin.has_add_permission(request))
        self.assertFalse(agent_admin.has_delete_permission(request))
        self.assertEqual(agent_admin.list_editable, ("staff_name", "staff_id", "team"))
        self.assertIn("hodu_name", agent_admin.readonly_fields)


class AgentDisplayNameTests(SimpleTestCase):
    def test_falls_back_from_staff_name_to_hoducc_name_to_login(self):
        self.assertEqual(Agent(username="a1", hodu_name="Agent 01", staff_name="Ada").display_name, "Ada")
        self.assertEqual(Agent(username="a1", hodu_name="Agent 01").display_name, "Agent 01")
        self.assertEqual(Agent(username="a1").display_name, "a1")

