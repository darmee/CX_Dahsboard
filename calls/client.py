"""
HoduCC API client: the only file that talks to HoduCC.

Every HoduCC endpoint is a POST with the token and tenant ID in the JSON body.
This class adds those for you, checks the reply, and turns errors into a
HoduError so the rest of the code can handle them in one way.

    client = get_client()
    calls, total = client.get_call_history(date(2026, 10, 5))
"""
import json
import logging
import re
import time
from datetime import date

import requests
from django.conf import settings

log = logging.getLogger(__name__)

# HoduCC wants dates day-first, like its own timestamps: "13-10-2026".
# "2026-10-13" or "13/10/2026" get "400 Invalid Date Format" (checked against the live API, 13 Oct 2026).
HODU_DATE = "%d-%m-%Y"

# HoduCC replies "Data Not Found!" (with an error code) when there is simply no data.
NO_DATA = re.compile(r"not (be )?found|does not found", re.IGNORECASE)
# ...but "Tenant does not found" or "Token not found" is a real problem, not an empty day.
NOT_AN_EMPTY_DAY = re.compile(
    r"token|tenant|user|auth|api|endpoint|url|method|access|permission|licen[cs]e", re.IGNORECASE
)


def is_no_data(message):
    """True when HoduCC's error message only means "nothing to show"."""
    return bool(NO_DATA.search(message)) and not NOT_AN_EMPTY_DAY.search(message)


class HoduError(Exception):
    """Raised when HoduCC returns an error (bad token, server down, ...)."""


class HoduUnreachable(HoduError):
    """HoduCC's server couldn't be reached, or took too long to reply. It usually passes within a minute."""


# Network trouble (HoduCC's server slow to answer, or the connection dropping) is usually over within seconds,
# so a request tries again before giving up: TRIES tries in all, waiting RETRY_PAUSE seconds, then twice that.
TRIES = 3
RETRY_PAUSE = 2
# How long to wait for the connection itself (the reply gets HODU_TIMEOUT_SECONDS, 30 by default).
CONNECT_TIMEOUT = 10
# Messages about network trouble start with this, so the dashboard can tell a passing hiccup (a yellow note)
# from a real problem such as a wrong token (a red banner). See views._sync_problem.
UNREACHABLE = "HoduCC's server didn't answer"


def _rows(result):
    """
    HoduCC returns lists in two shapes:
        {"0": {...}, "1": {...}, "total": 9}   (getCallHistory)
        [{...}, {...}]                           (most others)
    This returns (list_of_rows, total_or_None).
    """
    if not result:
        return [], 0
    if isinstance(result, list):
        return result, len(result)
    rows = [value for value in result.values() if isinstance(value, dict)]
    total = result.get("total")
    return rows, int(total) if total is not None else None


class HoduClient:
    def __init__(self, base_url, token, tenant_id, timeout=30):
        if not token or not tenant_id:
            raise HoduError("HODU_TOKEN and HODU_TENANT_ID must be set in .env (or set HODU_MOCK=1).")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.tenant_id = tenant_id
        self.timeout = timeout
        self.session = requests.Session()  # reuses the connection between calls

    def post(self, endpoint, tries=TRIES, **body):
        """Call one endpoint. Returns the 'result' or 'data' part of the reply, or None if empty."""
        reply = self.request(endpoint, tries=tries, **body)
        return reply.get("result", reply.get("data")) if reply else None

    def request(self, endpoint, tries=TRIES, **body):
        """
        Call one endpoint. Returns the whole reply (a dict), or None if HoduCC says there's no data.
        If the server doesn't answer, or the connection drops, it tries again (up to `tries` times in all)
        before raising HoduUnreachable. Every endpoint we use only reads, so asking twice does no harm.
        """
        payload = {"token": self.token, "tenant_id": self.tenant_id, **body}
        for attempt in range(1, tries + 1):
            try:
                response = self.session.post(f"{self.base_url}/{endpoint}", json=payload,
                                             timeout=(CONNECT_TIMEOUT, self.timeout))
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == tries:
                    raise HoduUnreachable(self._unreachable(endpoint, exc, tries)) from exc
                log.warning("%s: try %s of %s failed (%s); trying again", endpoint, attempt, tries, type(exc).__name__)
                time.sleep(RETRY_PAUSE * attempt)
            except requests.RequestException as exc:
                raise HoduError(f"Could not reach HoduCC ({endpoint}): {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise HoduError(f"HoduCC sent back something that isn't JSON ({endpoint})") from exc

        if not isinstance(data, dict):
            raise HoduError(f"HoduCC sent back an unexpected reply ({endpoint})")
        # Most endpoints send the code as a number (200), getRealtimeQueueSummary as text ("200").
        if str(data.get("code")) == "200":
            return data
        # An unknown endpoint replies {"message": "Method Failed."} instead of a status_message.
        message = str(data.get("status_message") or data.get("message") or "")
        if is_no_data(message):
            log.info("%s: no data (%s)", endpoint, message)
            return None
        raise HoduError(f"{endpoint}: {data.get('code')} {message}")

    def _unreachable(self, endpoint, exc, tries):
        """Network trouble in plain words, instead of the library's long technical message."""
        times = "once" if tries == 1 else f"{tries} times"
        if isinstance(exc, requests.ConnectTimeout):
            what = f"no connection within {CONNECT_TIMEOUT} seconds"
        elif isinstance(exc, requests.ReadTimeout):
            what = f"it connected, but sent no reply within {self.timeout} seconds"
        else:
            what = "the connection failed"
        log.warning("%s unreachable: %s", endpoint, exc)
        return (f"{UNREACHABLE} ({endpoint}): {what} (tried {times}). Their server or the network was slow; "
                "the next sync tries again.")

    # --- Endpoints we use -------------------------------------------------

    def get_call_history(self, day: date):
        """All calls that started on one day. Returns (rows, total_reported)."""
        result = self.post(
            "getCallHistory",
            search_on_time="START",
            search_type="DATE",
            date=day.strftime(HODU_DATE),
        )
        return _rows(result)

    def get_agent_offered_calls(self, day: date):
        """Every ring to every agent on one day. Returns a list of rows."""
        result = self.post("getAgentOfferedCalls", search_type="DATE", date=day.strftime(HODU_DATE))
        return _rows(result)[0]

    def get_realtime_queue_summary(self):
        # One try: the live numbers are asked for again every 15 seconds anyway, and a page is waiting for them.
        return self.post("getRealtimeQueueSummary", tries=1)

    def get_agent_list(self):
        """Every agent login. This reply keeps its rows under "Agents", not "result"."""
        reply = self.request("getAgentList")
        return (reply or {}).get("Agents") or []


class MockHoduClient:
    """
    Same methods as HoduClient, but reads saved replies from the sample folder.
    Used when HODU_MOCK=1 and in tests. Any day returns the same sample calls.
    """

    def __init__(self, sample_dir):
        self.sample_dir = sample_dir

    def _load(self, filename, key=None):
        """The 'result' (or 'data', or the given key) part of a saved reply; None if the file isn't there."""
        path = self.sample_dir / filename
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if key:
            return data.get(key)
        return data.get("result", data.get("data"))

    def get_call_history(self, day):
        return _rows(self._load("callhistory.json"))

    def get_agent_offered_calls(self, day):
        # No sample/agentofferedcalls.json yet just means no rings to show.
        return _rows(self._load("agentofferedcalls.json"))[0]

    def get_realtime_queue_summary(self):
        return self._load("realtimequeuesummary.json")

    def get_agent_list(self):
        return self._load("agentlist.json", key="Agents") or []


def get_client():
    """Returns the real client, or the mock one if HODU_MOCK=1."""
    cfg = settings.HODU
    if cfg["MOCK"]:
        return MockHoduClient(cfg["SAMPLE_DIR"])
    return HoduClient(cfg["BASE_URL"], cfg["TOKEN"], cfg["TENANT_ID"], cfg["TIMEOUT_SECONDS"])
