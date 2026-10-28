"""Sign in with OCI: Oracle Cloud's login page instead of the dashboard's own password.

The usual OpenID Connect "authorization code" steps:

1. oci_start sends the browser to OCI's login page, with a random `state` kept in the session.
2. After login, OCI sends the browser back to oci_callback with a one-time `code` and the same `state`.
3. oci_callback swaps the code for an access token (server to server, with the client secret),
   asks OCI who the person is, and logs in the dashboard account with that email.

Only people who already have an active dashboard account with that email, on the company domain,
get in: OCI proves who someone is, the dashboard's admin still decides who may see it.
Nothing is put in the address bar except OCI's short-lived code; the login itself is Django's
normal session cookie, so the time-outs in settings.py apply.

When something goes wrong, the login page is given a short code (?sso_error=expired), never the message
itself, so nobody can send a link that writes their own text on the login page.
"""
import logging
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth import views as auth_views
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .password_reset import company_address

audit = logging.getLogger("calls.audit")

TIMEOUT = 15  # seconds, for each call to OCI
SESSION_KEY = "oci_sso"

# ?sso_error=<code> -> what the login page says
ERRORS = {
    "unreachable": "OCI login is not reachable right now. Please try again later.",
    "expired": "The OCI sign-in was cancelled or has expired. Please try again.",
    "rejected": "OCI did not accept the sign-in. Please try again.",
    "no_details": "Could not read your details from OCI.",
    "no_access": "Your OCI account has no access to this dashboard. Ask an administrator.",
}


class SsoError(Exception):
    """Something went wrong talking to OCI. Its message is one of the ERRORS codes."""


def enabled():
    """OCI sign-in is on when its issuer URL is set in .env."""
    return bool(settings.OCI_SSO_ISSUER_URL)


def _discover():
    """OCI's own list of its addresses (login page, token, user info). Kept for an hour."""
    endpoints = cache.get("oci-sso-discovery")
    if endpoints is None:
        url = settings.OCI_SSO_ISSUER_URL.rstrip("/") + "/.well-known/openid-configuration"
        try:
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            endpoints = response.json()
        except (requests.RequestException, ValueError) as e:
            raise SsoError("unreachable") from e
        cache.set("oci-sso-discovery", endpoints, 60 * 60)
    return endpoints


def _exchange_code(code):
    """The one-time code from the browser -> an access token. The client secret never leaves the server."""
    try:
        response = requests.post(
            _discover()["token_endpoint"],
            auth=(settings.OCI_SSO_CLIENT_ID, settings.OCI_SSO_CLIENT_SECRET),
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": settings.OCI_SSO_REDIRECT_URI},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["access_token"]
    except (requests.RequestException, ValueError, KeyError) as e:
        raise SsoError("rejected") from e


def _email(access_token):
    """Who OCI says this is: their email address, in small letters."""
    try:
        response = requests.get(
            _discover()["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        info = response.json()
    except (requests.RequestException, ValueError, KeyError) as e:
        raise SsoError("no_details") from e
    return (info.get("email") or info.get("preferred_username") or "").strip().lower()


def _back_to_login(code):
    return redirect(f"{reverse('login')}?{urlencode({'sso_error': code})}")


class LoginView(auth_views.LoginView):
    """Django's login page, plus the "Sign in with OCI" button and OCI's error, when there is one."""

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            oci_sso=enabled(), sso_error=ERRORS.get(self.request.GET.get("sso_error", "")), **kwargs)


def oci_start(request):
    """The "Sign in with OCI" button: off to OCI's login page."""
    if not enabled():
        return redirect("login")
    state = secrets.token_urlsafe(32)
    request.session[SESSION_KEY] = {"state": state, "next": request.GET.get("next", "")}
    try:
        authorize = _discover()["authorization_endpoint"]
    except (SsoError, KeyError):
        return _back_to_login("unreachable")
    params = {
        "client_id": settings.OCI_SSO_CLIENT_ID,
        "redirect_uri": settings.OCI_SSO_REDIRECT_URI,
        "scope": "openid email profile",
        "response_type": "code",
        "state": state,
    }
    return redirect(f"{authorize}?{urlencode(params)}")


def oci_callback(request):
    """Where OCI sends the browser back after login."""
    started = request.session.pop(SESSION_KEY, None)  # one use only
    code, state, error = request.GET.get("code"), request.GET.get("state", ""), request.GET.get("error")

    # The state must be the one this browser was given in oci_start; otherwise the request
    # was not started here (or is old), and is refused.
    if error or not code or not started or not secrets.compare_digest(state, started["state"]):
        audit.warning("OCI sign-in refused: error=%s, state ok=%s", error, bool(started))
        return _back_to_login("expired")

    try:
        email = _email(_exchange_code(code))
    except SsoError as e:
        audit.warning("OCI sign-in failed (%s): %s", e, e.__cause__)
        return _back_to_login(str(e))

    users = get_user_model().objects.filter(email__iexact=email, is_active=True) if email else []
    if not company_address(email) or len(users) != 1:
        audit.warning("OCI sign-in refused for %r: not one active company account", email)
        return _back_to_login("no_access")

    user = users[0]
    # The backend must be one listed in AUTHENTICATION_BACKENDS, or Django forgets the login on the next page.
    login(request, user, backend="calls.lockout.LockoutBackend")
    audit.info("OCI sign-in: %s", user.get_username())

    next_url = started["next"]
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        next_url = reverse(settings.LOGIN_REDIRECT_URL)
    return redirect(next_url)
