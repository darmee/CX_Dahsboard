"""
Email through Microsoft 365 (Microsoft Graph), for the "Forgot password" links.

Used when MSGRAPH_TENANT_ID is set in .env (see config/settings.py). It signs in as the app registered in
Azure (MSGRAPH_CLIENT_ID and MSGRAPH_CLIENT_SECRET, with the Mail.Send application permission), keeps the
sign-in token until shortly before it expires, and sends each email from MSGRAPH_SENDER's mailbox.
"""
import json
import threading
import time
from email.utils import parseaddr
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend

TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
SCOPE = "https://graph.microsoft.com/.default"

TIMEOUT = 10  #seconds, per request
EARLY = 120  #seconds, before token expires

_token = {"value": None, "expires": 0.0}
_token_lock = threading.Lock()

class GraphError(Exception):
    """Graph or the sign-in flow returned an error. The message is the JSON response from Graph."""

def _call(request):
    """make a request; return(status, parsed JSON body or {})"""
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
            return response.status, (json.loads(body) if body else {})
    except HTTPError as err:
        body = err.read()
        try:
            detail = json.loads(body) if body else {}
        except ValueError:
            detail = {}
        return err.code, detail
    except URLError as err:
        raise GraphError(f"Could not reach Microsoft: {err.reason}") from err

def _reason(detail):
    """Reasons for error response """
    error = detail.get("error")
    if isinstance(error, dict):
        return f"{error.get('code', '')}: {error.get('message', '')}".strip(": ")
    return detail.get("error_description") or error or "no reason given"

class GraphEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.tenant = settings.MSGRAPH_TENANT_ID
        self.client_id = settings.MSGRAPH_CLIENT_ID
        self.secret = settings.MSGRAPH_CLIENT_SECRET
        self.sender = settings.MSGRAPH_SENDER
        missing = [name for name, value in (
            ("MSGRAPH_TENANT_ID", self.tenant),
            ("MSGRAPH_CLIENT_ID", self.client_id),
            ("MSGRAPH_CLIENT_SECRET", self.secret),
            ("MSGRAPH_SENDER", self.sender),
        ) if not value]
        if missing:
            raise ImproperlyConfigured(f"Missing Microsoft Graph email needs: {', '.join(missing)} in .env")

    # signin ------------------------------------------------------
    def _access_token(self, renew=False):
        """Get a valid access token, renewing if necessary. Thread-safe."""
        with _token_lock:
            if not renew and _token["value"] and time.time() < _token["expires"] - EARLY:
                return _token["value"]
            form = urlencode({
                "client_id": self.client_id, "client_secret": self.secret,
                "scope": SCOPE, "grant_type": "client_credentials",
            }).encode()
            status, detail = _call(Request(
                TOKEN_URL.format(tenant=quote(self.tenant)), data=form, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ))
            if status != 200 or "access_token" not in detail:
                raise GraphError(f"Microsoft signin failed ({status}): {_reason(detail)}")
            _token["value"] = detail["access_token"]
            _token["expires"] = time.time() + int(detail.get("expires_in", 360))
            return _token["value"]

    # sending ------------------------------------------------------
    @staticmethod
    def _payload(message):
        html = next((content for content, kind in getattr(message, "alternatives", []) if kind == "text/html"), None)

        def people(addresses):
            return [{"emailAddress": {"address": parseaddr(a)[1]}} for a in addresses]

        body = {
            "subject": message.subject,
            "body": {"contentType": "HTML" if html else "Text", "content": html or message.body},
            "toRecipients": people(message.to),
        }
        if message.cc:
            body["ccRecipients"] = people(message.cc)
        if message.bcc:
            body["bccRecipients"] = people(message.bcc)
        if message.reply_to:
            body["replyTo"] = people(message.reply_to)
        return {"message": body, "saveToSentItems": False}

    def _send(self, message):
        data = json.dumps(self._payload(message)).encode()
        url = SEND_URL.format(sender=quote(self.sender))
        for attempt in (1, 2):
            token = self._access_token(renew=attempt == 2)  # a refused token (401) is renewed once
            request = Request(url, data=data, method="POST",
                              headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            status, detail = _call(request)
            if status == 202:               # Graph accepts the message for delivery
                return
            if status != 401 or attempt == 2:
                raise GraphError(f"Microsoft send failed ({status}): {_reason(detail)}")

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            if not message.recipients():
                continue
            try:
                self._send(message)
                sent += 1
            except GraphError:
                if not self.fail_silently:
                    raise
        return sent
