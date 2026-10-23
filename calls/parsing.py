"""
Turns HoduCC's raw rows into clean values for our database.

Kept separate from the API client and the database code so it is easy to
test and easy to fix when HoduCC changes a field.

Things we learned from real responses (5 Oct 2026 sample):
- Dates are day-first: "05-10-2026 09:09:38". Empty dates are "00-00-0000 00:00:00".
- Durations look like "0:01:16" or "00:01:16".
- call_answer_time and answered_duration are filled in even for ABANDONED calls,
  so we never use them to decide if a call was answered. We use call_status == "AGENT".
- agent_wait_time is the agent's idle time, not the customer's wait. We use queue_wait_time.
- Outbound calls (13 Oct 2026, live API): call_status AGENT = the customer picked up,
  DIAL = never connected (hangup_reason e.g. "Service Unavailable"). Their queue_name is "outbound".
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings

EMPTY_DATES = ("00-00-0000", "0000-00-00")
# The login at the end of "Agent 01 (Agent01)"
LOGIN_IN_BRACKETS = re.compile(r"\(([^()]+)\)\s*$")


def parse_datetime(value):
    """'05-10-2026 09:09:38' or '2026-10-05 09:09:38' -> time-zone-aware datetime, or None."""
    if not value or value == "-" or str(value).startswith(EMPTY_DATES):
        return None
    value = str(value).strip()
    fmt = "%Y-%m-%d %H:%M:%S" if value[4:5] == "-" else "%d-%m-%Y %H:%M:%S"
    naive = datetime.strptime(value, fmt)
    return naive.replace(tzinfo=ZoneInfo(settings.HODU["TIME_ZONE"]))


def parse_duration(value):
    """'0:01:16' -> 76 seconds. Missing or '-' -> 0. Never negative."""
    if not value or value == "-":
        return 0
    seconds = 0
    for part in str(value).split(":"):
        seconds = seconds * 60 + int(part)
    return max(seconds, 0)


def mask_number(number):
    """'09061612698' -> '•••2698'. We never store full customer numbers."""
    number = str(number or "").strip()
    return f"•••{number[-4:]}" if number else ""


def agent_login(text):
    """'Agent 01 (Agent01)' -> 'Agent01'. Text without brackets is taken to be the login already."""
    text = str(text or "").strip()
    match = LOGIN_IN_BRACKETS.search(text)
    return (match.group(1) if match else text).strip()


def call_from_row(row):
    """
    One getCallHistory row -> a dict of Call fields.
    Returns None if the row has no ID or start time (we skip those).
    """
    call_id = row.get("call_id")
    started_at = parse_datetime(row.get("call_start_time"))
    if not call_id or not started_at:
        return None

    return {
        "call_id": int(call_id),
        "direction": (row.get("call_type") or "").upper(),
        "status": (row.get("call_status") or "").upper(),
        "queue_name": row.get("queue_name") or "",
        "campaign_name": row.get("campaign_name") or "",
        "agent_username": row.get("agent_username") or "",
        "caller_masked": mask_number(row.get("caller_number") or row.get("phone_number")),
        "started_at": started_at,
        "ended_at": parse_datetime(row.get("call_hangup_time")),
        "wait_seconds": parse_duration(row.get("queue_wait_time")),
        "talk_seconds": parse_duration(row.get("agent_duration")),
        "hold_seconds": parse_duration(row.get("hold_duration")),
        "total_seconds": parse_duration(row.get("call_duration")),
        "hangup_by": row.get("hangup_by") or "",
        "hangup_reason": str(row.get("hangup_reason") or "")[:64],
    }


def offer_from_row(row):
    """One getAgentOfferedCalls row -> a dict of AgentOffer fields, or None."""
    offered_at = parse_datetime(row.get("aoc_offered_time"))
    if not row.get("aoc_call_id") or not offered_at:
        return None
    ended_at = parse_datetime(row.get("aoc_hangup_time"))
    ring = int((ended_at - offered_at).total_seconds()) if ended_at else None
    # This endpoint gives the agent as "Name Surname (username)" in aoc_agt_id
    agent_name = str(row.get("agt_uname") or row.get("aoc_agt_id") or "").strip()
    return {
        "call_id": int(row["aoc_call_id"]),
        "agent_name": agent_name,
        "agent_username": agent_login(agent_name),
        "queue_name": str(row.get("acd_id") or ""),
        "offered_at": offered_at,
        "ended_at": ended_at,
        "ring_seconds": max(ring, 0) if ring is not None else None,
        "hangup_reason": row.get("aoc_hangup_reason") or "",
    }


def agent_from_row(row):
    """
    One getAgentList row -> a dict of Agent fields, or None.
    The row also holds the agent's email, phone and personal token. They are left out on purpose:
    we only need to know who a login belongs to.
    """
    username = str(row.get("agt_uname") or "").strip()
    if not username:
        return None
    first, last = str(row.get("agt_fname") or "").strip(), str(row.get("agt_lname") or "").strip()
    agt_id = row.get("agt_id")
    return {
        "username": username,
        "hodu_id": int(agt_id) if agt_id not in (None, "") else None,
        "hodu_name": f"{first} {last}".strip(),
    }
