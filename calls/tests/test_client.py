"""Tests for the real HoduClient, with the network replaced by fake replies (no real calls made)."""
from datetime import date
from unittest import mock

import requests
from django.test import SimpleTestCase

from calls.client import UNREACHABLE, HoduClient, HoduError, HoduUnreachable


def fake_reply(payload):
    response = mock.Mock()
    response.json.return_value = payload
    return response


class HoduClientTests(SimpleTestCase):
    def setUp(self):
        self.client_ = HoduClient("https://example.test/api", token="t0ken", tenant_id="1005")

    def test_sends_token_and_tenant_in_body(self):
        reply = fake_reply({"code": 200, "result": {"total": 0}})
        with mock.patch.object(self.client_.session, "post", return_value=reply) as post:
            self.client_.get_call_history(date(2026, 10, 5))
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["token"], "t0ken")
        self.assertEqual(body["tenant_id"], "1005")
        self.assertEqual(body["date"], "05-10-2026")  # HoduCC rejects 2026-10-05
        self.assertEqual(post.call_args.args[0], "https://example.test/api/getCallHistory")

    def test_turns_numbered_result_into_list(self):
        reply = {"code": 200, "result": {"0": {"call_id": 1}, "1": {"call_id": 2}, "total": 2}}
        with mock.patch.object(self.client_.session, "post", return_value=fake_reply(reply)):
            rows, total = self.client_.get_call_history(date(2026, 10, 5))
        self.assertEqual([r["call_id"] for r in rows], [1, 2])
        self.assertEqual(total, 2)

    def test_no_data_is_empty_not_error(self):
        reply = {"code": 400, "status_message": "Realtime Queue Summary Data Not Found!"}
        with mock.patch.object(self.client_.session, "post", return_value=fake_reply(reply)):
            self.assertIsNone(self.client_.get_realtime_queue_summary())

    def test_not_found_about_the_account_is_an_error(self):
        for message in ["Tenant does not found", "Token not found", "User not found."]:
            reply = {"code": 400, "status_message": message}
            with mock.patch.object(self.client_.session, "post", return_value=fake_reply(reply)):
                with self.assertRaisesMessage(HoduError, message):
                    self.client_.get_call_history(date(2026, 10, 5))

    def test_success_code_sent_as_text_is_success(self):
        # getRealtimeQueueSummary really does send "200" as text
        reply = {"code": "200", "status_message": "Realtime Queue Summary Data Selected Successfully.",
                 "result": {"agent_total_avg": {"live_agent": "2"}}}
        with mock.patch.object(self.client_.session, "post", return_value=fake_reply(reply)):
            self.assertEqual(self.client_.get_realtime_queue_summary(), reply["result"])

    def test_agent_list_comes_from_the_agents_key(self):
        reply = {"code": 200, "Agents": [{"agt_uname": "Agent01"}], "total": 1}
        with mock.patch.object(self.client_.session, "post", return_value=fake_reply(reply)) as post:
            self.assertEqual(self.client_.get_agent_list(), [{"agt_uname": "Agent01"}])
        self.assertEqual(post.call_args.args[0], "https://example.test/api/getAgentList")

    def test_unknown_endpoint_message_is_shown(self):
        reply = {"message": "Method Failed."}
        with mock.patch.object(self.client_.session, "post", return_value=fake_reply(reply)):
            with self.assertRaisesMessage(HoduError, "Method Failed."):
                self.client_.request("getNoSuchThing")

    def test_reply_that_is_not_an_object_is_an_error(self):
        with mock.patch.object(self.client_.session, "post", return_value=fake_reply(["oops"])):
            with self.assertRaises(HoduError):
                self.client_.get_call_history(date(2026, 10, 5))

    def test_real_errors_raise(self):
        reply = {"code": 400, "status_message": "Token Authentication Failed."}
        with mock.patch.object(self.client_.session, "post", return_value=fake_reply(reply)):
            with self.assertRaisesMessage(HoduError, "Token Authentication Failed"):
                self.client_.get_call_history(date(2026, 10, 5))

    def test_missing_token_is_a_clear_error(self):
        with self.assertRaisesMessage(HoduError, "HODU_TOKEN"):
            HoduClient("https://example.test", token="", tenant_id="")


@mock.patch("calls.client.time.sleep")  # no real waiting between tries
class NetworkTroubleTests(SimpleTestCase):
    """HoduCC's server being slow or the connection dropping: try again, then give up with a plain message."""

    def setUp(self):
        self.client_ = HoduClient("https://example.test/api", token="t0ken", tenant_id="1005")

    def test_tries_again_after_a_timeout(self, sleep):
        replies = [requests.ConnectTimeout("slow"), fake_reply({"code": 200, "result": {"total": 0}})]
        with mock.patch.object(self.client_.session, "post", side_effect=replies) as post:
            self.assertEqual(self.client_.get_call_history(date(2026, 10, 5)), ([], 0))
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once()

    def test_gives_up_after_three_tries_in_plain_words(self, sleep):
        with mock.patch.object(self.client_.session, "post", side_effect=requests.ReadTimeout("slow")) as post:
            with self.assertRaises(HoduUnreachable) as caught:
                self.client_.get_call_history(date(2026, 10, 5))
        self.assertEqual(post.call_count, 3)
        message = str(caught.exception)
        self.assertTrue(message.startswith(UNREACHABLE))
        self.assertIn("no reply within 30 seconds (tried 3 times)", message)
        self.assertNotIn("HTTPSConnectionPool", message)

    def test_live_numbers_try_once(self, sleep):
        with mock.patch.object(self.client_.session, "post", side_effect=requests.ConnectionError("down")) as post:
            with self.assertRaises(HoduUnreachable):
                self.client_.get_realtime_queue_summary()
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()
