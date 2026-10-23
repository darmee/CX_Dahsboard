"""
Database tables.

Each class below becomes one table. Django creates the tables for you when
you run `python manage.py migrate`.

    Call        one row per phone call (from getCallHistory)
    AgentOffer  one row each time a call rang an agent (from getAgentOfferedCalls)
    Agent       one row per agent login, with the real staff name you give it (from getAgentList)
    SyncRun     one row each time we pulled data from HoduCC (a log)
"""
from django.conf import settings
from django.db import models


class Call(models.Model):
    class Direction(models.TextChoices):
        INBOUND = "INBOUND", "Inbound"
        OUTBOUND = "OUTBOUND", "Outbound"

    # HoduCC's own ID for the call. unique=True means saving the same call twice
    # updates it instead of creating a duplicate.
    call_id = models.BigIntegerField(unique=True)

    direction = models.CharField(max_length=16, choices=Direction.choices, db_index=True)
    # AGENT = answered by an agent; ABANDONED, DROPPED, ... = see HoduCC guide
    status = models.CharField(max_length=32, db_index=True)

    queue_name = models.CharField(max_length=100, blank=True, db_index=True)
    campaign_name = models.CharField(max_length=100, blank=True)
    agent_username = models.CharField(max_length=100, blank=True, db_index=True)

    # We only keep the last 4 digits of the customer's number (privacy).
    caller_masked = models.CharField(max_length=16, blank=True)

    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    # Durations, in seconds
    wait_seconds = models.PositiveIntegerField(default=0, help_text="Customer's time in the queue (delay)")
    talk_seconds = models.PositiveIntegerField(default=0, help_text="Time talking to an agent")
    hold_seconds = models.PositiveIntegerField(default=0, help_text="Time on hold")
    total_seconds = models.PositiveIntegerField(default=0, help_text="Whole call length")

    hangup_by = models.CharField(max_length=16, blank=True, help_text="Who ended it: AGENT, USER (customer), SYSTEM")
    # Why the call ended, as HoduCC says it, e.g. NORMAL_CLEARING, or "Service Unavailable" for a call out that
    # never connected. It explains "not connected" call by call.
    hangup_reason = models.CharField(max_length=64, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Call {self.call_id} ({self.direction}, {self.status})"

    @property
    def is_answered(self):
        return self.status == "AGENT"

    @property
    def is_unanswered(self):
        return self.status in settings.HODU["UNANSWERED_STATUSES"]


class AgentOffer(models.Model):
    """One ring to one agent. If the agent didn't take it, that's a rejection or a miss."""

    call_id = models.BigIntegerField(db_index=True)
    # As HoduCC writes it, e.g. "Agent 01 (Agent01)"
    agent_name = models.CharField(max_length=150)
    # Just the login, e.g. "Agent01": the same value as Call.agent_username, so the two can be matched
    agent_username = models.CharField(max_length=100, blank=True, db_index=True)
    queue_name = models.CharField(max_length=100, blank=True)
    offered_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ring_seconds = models.PositiveIntegerField(null=True, blank=True)
    hangup_reason = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-offered_at"]
        constraints = [
            # The same ring is never stored twice.
            models.UniqueConstraint(fields=["call_id", "agent_name", "offered_at"], name="unique_offer"),
        ]

    def __str__(self):
        return f"Offer of call {self.call_id} to {self.agent_name}"


class Agent(models.Model):
    """
    One HoduCC agent login, and the member of staff who uses it.

    The HoduCC fields are filled in by the sync (getAgentList). The staff fields are yours:
    fill them in under Admin -> Agents. The sync never changes them.
    HoduCC's agent list also includes each agent's email, phone and personal token; we don't store those.
    """

    # --- From HoduCC ---
    username = models.CharField(max_length=100, unique=True, help_text="The agent's HoduCC login, e.g. Agent01")
    hodu_id = models.PositiveIntegerField(null=True, blank=True, db_index=True, help_text="HoduCC's agt_id")
    hodu_name = models.CharField(max_length=150, blank=True, help_text="First and last name as set in HoduCC")
    is_active = models.BooleanField(default=True, help_text="Still in HoduCC's agent list")

    # --- Yours ---
    staff_name = models.CharField(max_length=150, blank=True, help_text="The real name to show on the dashboard")
    staff_id = models.CharField(max_length=50, blank=True, help_text="Employee number (optional)")
    team = models.CharField(max_length=100, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return f"{self.display_name} ({self.username})"

    @property
    def display_name(self):
        """Your staff name if you gave one, otherwise HoduCC's name, otherwise the login."""
        return self.staff_name or self.hodu_name or self.username


class SyncRun(models.Model):
    """A log entry for each sync, so you can see when data was last pulled and if it failed."""

    day = models.DateField()
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    calls_received = models.PositiveIntegerField(default=0)
    calls_reported_total = models.PositiveIntegerField(
        null=True, blank=True, help_text="The 'total' HoduCC said it had. If bigger than received, data was cut off."
    )
    offers_received = models.PositiveIntegerField(null=True, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Sync {self.day} at {self.started_at:%Y-%m-%d %H:%M} ({'ok' if self.ok else 'failed'})"
