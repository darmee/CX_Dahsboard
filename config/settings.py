"""
Settings for the call-centre dashboard.

Every value that changes between computers (passwords, tokens, debug mode)
is read from the .env file, so this file can be shared safely.
See docs/HOW_IT_WORKS.md, section "Settings", for an explanation.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load values from the .env file in the project folder into os.environ.
load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core Django settings
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

if not DEBUG and SECRET_KEY.startswith("dev-only"):
    raise RuntimeError("Set DJANGO_SECRET_KEY in .env before running with DJANGO_DEBUG=0")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    # WhiteNoise serves the CSS/JS, also under runserver, with headers that make browsers check for a newer
    # copy (instead of mixing an old cached file with new ones after an update).
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "calls",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the CSS/JS (from the app folders while DEBUG is on, from "collectstatic"'s folder when it's off),
    # so gunicorn or waitress is enough on its own.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Project-wide templates (base layout, login page) live in /templates
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SQLite is a single file (db.sqlite3) and needs no setup.
# For a shared server, switch to PostgreSQL later; see docs/HOW_IT_WORKS.md.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# The normal username + password check, plus a pause after repeated wrong passwords.
AUTHENTICATION_BACKENDS = ["calls.lockout.LockoutBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Times are stored in UTC and shown in this time zone.
LANGUAGE_CODE = "en-gb"
TIME_ZONE = env("DISPLAY_TIME_ZONE", "Africa/Lagos")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # used by "collectstatic" when deploying

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Login: anyone not logged in is sent to /accounts/login/
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "calls:dashboard"
LOGOUT_REDIRECT_URL = "login"

# How long a login lasts. Django's default is a cookie kept for 2 weeks, which survives closing the
# browser and shutting down the computer. Instead:
#   - the cookie is dropped when the browser closes;
#   - the login runs out after this many minutes with no requests. An open dashboard keeps asking for
#     data, so it stays logged in; once the tab or computer is off, the clock runs down. This also covers
#     browsers that bring back closed cookies ("continue where you left off" in Chrome/Edge).
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = int(env("DJANGO_SESSION_IDLE_MINUTES", "60")) * 60
SESSION_SAVE_EVERY_REQUEST = True  # each request restarts the clock above

# Where Admin lives. Only superusers can use it (calls/admin.py), and the dashboard has no link to it.
# On a public server, choose an address nobody would guess, e.g. DJANGO_ADMIN_PATH=office-7f3k2/
ADMIN_PATH = env("DJANGO_ADMIN_PATH", "admin/").strip("/") + "/"

# A simple in-memory cache, used so live tiles don't call HoduCC on every refresh.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Extra protection when running for real (DEBUG off, served over HTTPS).
if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    # Send http:// visitors to https://, and tell browsers to always use https for this site.
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", False)
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "0"))

# The site's own https:// address(es), e.g. DJANGO_CSRF_TRUSTED_ORIGINS=https://dashboard.yourcompany.com
# Without this (or DJANGO_BEHIND_PROXY below), logging in through an https proxy is refused.
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Set DJANGO_BEHIND_PROXY=1 only when nginx/IIS/your host sits in front and sets the
# X-Forwarded-Proto header itself; that header is how Django learns the visitor used https.
if env_bool("DJANGO_BEHIND_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "calls": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
        # Crashes while answering a request (500 errors). Django only emails these to ADMINS
        # by default, and none are set, so without this they leave no trace when DEBUG is off.
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}

# ---------------------------------------------------------------------------
# HoduCC settings (our own)
# ---------------------------------------------------------------------------
HODU = {
    "BASE_URL": env("HODU_BASE_URL", "https://hoducc.roitechisl.com/HoduCC_api/v2.1"),
    "TOKEN": env("HODU_TOKEN", ""),
    "TENANT_ID": env("HODU_TENANT_ID", ""),
    # Time zone that HoduCC writes its timestamps in. Confirm with HoduCC.
    "TIME_ZONE": env("HODU_TIME_ZONE", "Africa/Lagos"),
    # MOCK=1 reads sample/*.json instead of calling the real API.
    "MOCK": env_bool("HODU_MOCK", False),
    "SAMPLE_DIR": BASE_DIR / "sample",
    "TIMEOUT_SECONDS": int(env("HODU_TIMEOUT_SECONDS", "30")),
    # Which call_status values count as "customer never answered".
    "UNANSWERED_STATUSES": env_list("HODU_UNANSWERED_STATUSES", "ABANDONED,DROPPED,HANGUP"),
    # How long live tiles are cached, in seconds.
    "LIVE_CACHE_SECONDS": int(env("HODU_LIVE_CACHE_SECONDS", "15")),
    # Live mode: while the dashboard shows today, fetch from HoduCC at most this often,
    # in seconds, so no one has to run sync_calls. 0 switches it off.
    "SYNC_ON_VIEW_SECONDS": int(env("HODU_SYNC_ON_VIEW_SECONDS", "60")),
    # Fill in history by itself: when someone looks at days the dashboard has never fetched, fetch them
    # from HoduCC in the background. 0 switches it off (then use: python manage.py sync_calls --from ...).
    "AUTO_BACKFILL": env_bool("HODU_AUTO_BACKFILL", True),
    # The dashboard warns when the last good sync is older than this, in seconds.
    # Keep it comfortably longer than the gap between syncs.
    "STALE_AFTER_SECONDS": int(env("HODU_STALE_AFTER_SECONDS", "900")),
}


# --- forgot password -----------------------------------------------------------
# A reset link goes only to addresses on this domain, and works once for an hour.
PASSWORD_RESET_EMAIL_DOMAIN = os.getenv("PASSWORD_RESET_EMAIL_DOMAIN", "dash-mfb.com").strip().lstrip("@").lower()
PASSWORD_RESET_TIMEOUT = 60 * 60
# The address people open the dashboard at, e.g. https://calls.dash-mfb.com. Reset links point there, not at
# whatever address the request arrived on (behind IIS that can be 127.0.0.1:8600). Empty: the request's own address.
PUBLIC_URL = os.getenv("DJANGO_PUBLIC_URL", "").strip().rstrip("/")


def _graph(name):
    # MSGRAPH_TENANT_ID or MS_GRAPH_TENANT_ID - either spelling in .env.
    return (os.getenv(f"MSGRAPH_{name}") or os.getenv(f"MS_GRAPH_{name}") or "").strip()


# How the emails go out, in order of preference:
#   1. Microsoft 365, through Microsoft Graph (calls/mail_graph.py), when MSGRAPH_TENANT_ID is set;
#   2. an ordinary mail server (SMTP), when EMAIL_HOST is set;
#   3. otherwise nowhere: Django prints each email in the server's console (fine for trying it out).
MSGRAPH_TENANT_ID = _graph("TENANT_ID")
MSGRAPH_CLIENT_ID = _graph("CLIENT_ID")
MSGRAPH_CLIENT_SECRET = _graph("CLIENT_SECRET")
MSGRAPH_SENDER = _graph("SENDER")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
if MSGRAPH_TENANT_ID:
    EMAIL_PROVIDER = "graph"
    EMAIL_BACKEND = "calls.mail_graph.GraphEmailBackend"
elif EMAIL_HOST:
    EMAIL_PROVIDER = "smtp"
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
    EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False").lower() == "true"
    EMAIL_TIMEOUT = 15
else:
    EMAIL_PROVIDER = ""
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = (os.getenv("DEFAULT_FROM_EMAIL", "") or MSGRAPH_SENDER
                      or os.getenv("EMAIL_HOST_USER", "") or "no-reply@dash-mfb.com")


# --- Sign in with OCI (calls/oci_sso.py) ---------------------------------------
# From the Confidential Application in the OCI identity domain. Empty OCI_SSO_ISSUER_URL: the button is hidden.
OCI_SSO_ISSUER_URL = env("OCI_SSO_ISSUER_URL", "").strip().rstrip("/")
OCI_SSO_CLIENT_ID = env("OCI_SSO_CLIENT_ID", "")
OCI_SSO_CLIENT_SECRET = env("OCI_SSO_CLIENT_SECRET", "")
# Must match the Redirect URL registered in OCI exactly, e.g. https://cxdashboard.dash-mfb.com/oidc/callback/
# The dashboard answers on this address's path (config/urls.py), so changing it here is enough.
OCI_SSO_REDIRECT_URI = env("OCI_SSO_REDIRECT_URI", "")

