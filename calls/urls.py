"""URLs for the calls app. app_name lets templates write {% url 'calls:dashboard' %}."""
from django.urls import path

from . import views

app_name = "calls"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/metrics/", views.metrics_api, name="metrics_api"),
    path("api/agents/", views.agents_api, name="agents_api"),
    path("api/agent/", views.agent_api, name="agent_api"),
    path("api/monthly/", views.monthly_api, name="monthly_api"),
    path("api/calls/", views.calls_api, name="calls_api"),
    path("api/rings/", views.rings_api, name="rings_api"),
    path("api/live/", views.live_api, name="live_api"),
]
