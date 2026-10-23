"""
Login lockout: stops someone guessing a password by trying over and over.

After MAX_FAILURES wrong passwords for one username, every login for that
username is refused until LOCKOUT_SECONDS have passed since the first wrong try.
It works for both login pages (/accounts/login/ and /admin/login/), because it
sits where Django checks the password rather than on one page.

The counts live in Django's cache (see CACHES in settings.py).
"""
import hashlib

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.dispatch import receiver

MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60


def _key(username):
    # Hashed so that anything typed into the username box makes a valid cache key.
    return "login-failures:" + hashlib.sha256(str(username).casefold().encode()).hexdigest()


class LockoutBackend(ModelBackend):
    """Django's normal username + password check, skipped while the username is locked."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is not None and cache.get(_key(username), 0) >= MAX_FAILURES:
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)


@receiver(user_login_failed)
def count_failure(sender, credentials, **kwargs):
    username = credentials.get("username")
    if username is None:
        return
    key = _key(username)
    cache.add(key, 0, LOCKOUT_SECONDS)  # the first wrong try starts the clock
    try:
        cache.incr(key)
    except ValueError:
        pass  # the count expired between the two lines above


def unlock(username):
    """Lift a lockout on `username` straight away (used when someone sets a new password with Forgot password)."""
    cache.delete(_key(username))


@receiver(user_logged_in)
def forget_failures(sender, user, **kwargs):
    unlock(user.get_username())
