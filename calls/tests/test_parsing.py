"""Tests for parsing.py: does each raw HoduCC value become the right clean value?"""
from django.test import SimpleTestCase

from calls.parsing import call_from_row, mask_number, offer_from_row, parse_datetime, parse_duration


class ParseDatetimeTests(SimpleTestCase):
    def test_day_first_format(self):
        dt = parse_datetime("05-10-2026 09:09:38")
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2026, 10, 5, 9, 9))
        self.assertIsNotNone(dt.tzinfo)

    def test_year_first_format(self):
        self.assertEqual(parse_datetime("2026-10-05 09:09:38"), parse_datetime("05-10-2026 09:09:38"))

    def test_empty_values_become_none(self):
        for value in ["00-00-0000 00:00:00", "", None, "-"]:
            self.assertIsNone(parse_datetime(value))


class ParseDurationTests(SimpleTestCase):
    def test_durations(self):
        self.assertEqual(parse_duration("0:01:16"), 76)
        self.assertEqual(parse_duration("00:30:36"), 1836)
        self.assertEqual(parse_duration("-"), 0)
        self.assertEqual(parse_duration(None), 0)


class CallFromRowTests(SimpleTestCase):
    ROW = {
        "call_id": 10186726, "call_type": "INBOUND", "call_status": "ABANDONED",
        "call_start_time": "05-10-2026 09:09:38", "call_hangup_time": "05-10-2026 09:10:54",
        "queue_wait_time": "0:01:16", "agent_duration": "00:00:00", "hold_duration": "00:00:00",
        "call_duration": "00:01:16", "caller_number": "09061612698", "queue_name": "General",
        "agent_username": None, "hangup_by": "USER",
        # These look like "answered" but are filled even for abandoned calls:
        "call_answer_time": "05-10-2026 09:09:38", "answered_duration": "00:01:16",
    }

    def test_maps_fields(self):
        call = call_from_row(self.ROW)
        self.assertEqual(call["call_id"], 10186726)
        self.assertEqual(call["status"], "ABANDONED")
        self.assertEqual(call["wait_seconds"], 76)
        self.assertEqual(call["agent_username"], "")
        self.assertEqual(call["caller_masked"], "•••2698")

    def test_full_number_is_never_kept(self):
        self.assertNotIn("09061612698", str(call_from_row(self.ROW)))

    def test_rows_without_id_are_skipped(self):
        self.assertIsNone(call_from_row({"call_start_time": "05-10-2026 09:09:38"}))

    def test_mask_number(self):
        self.assertEqual(mask_number(""), "")


class OfferFromRowTests(SimpleTestCase):
    def test_ring_seconds(self):
        offer = offer_from_row({
            "aoc_call_id": 31946, "aoc_agt_id": "Demo3 Demo3 (Demo3) ",
            "aoc_offered_time": "04-11-2024 13:47:53", "aoc_hangup_time": "04-11-2024 13:47:58",
            "aoc_hangup_reason": "NORMAL_CLEARING",
        })
        self.assertEqual(offer["ring_seconds"], 5)
        self.assertEqual(offer["agent_name"], "Demo3 Demo3 (Demo3)")
