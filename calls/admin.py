"""
Django admin (/admin): a ready-made back office to look through calls,
agent offers and the sync log. Data comes from HoduCC, so it is read-only here.

The one thing you edit here is Agents: give each HoduCC login the real staff name
(and, if you like, employee number and team). The dashboard shows that name everywhere.
"""
from django.contrib import admin
from django.db import models
from django.forms import TextInput

from .models import Agent, AgentOffer, Call, SyncRun


def superusers_only(request):
    """
    Who may use Admin: only superusers (made with `python manage.py createsuperuser`). Staff logins and
    everyone else get the admin's login page instead, even if they are logged in to the dashboard.
    """
    return request.user.is_active and request.user.is_superuser


admin.site.has_permission = superusers_only


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Call)
class CallAdmin(ReadOnlyAdmin):
    list_display = ("call_id", "started_at", "direction", "status", "queue_name", "agent_username",
                    "caller_masked", "wait_seconds", "talk_seconds", "hold_seconds")
    list_filter = ("direction", "status", "queue_name", "agent_username")
    search_fields = ("call_id", "caller_masked", "agent_username")
    date_hierarchy = "started_at"


@admin.register(AgentOffer)
class AgentOfferAdmin(ReadOnlyAdmin):
    list_display = ("call_id", "agent_name", "agent_username", "offered_at", "ring_seconds", "hangup_reason")
    list_filter = ("hangup_reason",)
    search_fields = ("call_id", "agent_name", "agent_username")
    date_hierarchy = "offered_at"


@admin.register(SyncRun)
class SyncRunAdmin(ReadOnlyAdmin):
    list_display = ("started_at", "day", "ok", "calls_received", "calls_reported_total", "offers_received", "message")
    list_filter = ("ok",)


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    """
    Map each HoduCC login to a member of staff. The list itself is editable:
    type the names into the Staff name column and press Save at the bottom.
    Rows are created by the sync from HoduCC's agent list, so there is no Add or Delete.
    """

    list_display = ("username", "hodu_name", "staff_name", "staff_id", "team", "is_active")
    list_editable = ("staff_name", "staff_id", "team")
    # Narrower boxes, so every column fits on the screen
    formfield_overrides = {models.CharField: {"widget": TextInput(attrs={"size": 14})}}
    list_filter = ("is_active", "team")
    search_fields = ("username", "hodu_name", "staff_name", "staff_id")
    readonly_fields = ("username", "hodu_id", "hodu_name", "is_active", "updated_at")
    fieldsets = (
        ("From HoduCC (updated by the sync)", {"fields": ("username", "hodu_id", "hodu_name", "is_active")}),
        ("Your staff details", {"fields": ("staff_name", "staff_id", "team")}),
        (None, {"fields": ("updated_at",)}),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
