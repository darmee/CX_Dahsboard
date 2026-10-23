"""Tests for lockout.py: repeated wrong passwords pause logins for that username."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from calls.lockout import MAX_FAILURES

PASSWORD = "a-long-test-password"


# A quick password hasher, only so these tests don't take 20 seconds.
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LockoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        get_user_model().objects.create_superuser("manager", password=PASSWORD)

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def login(self, password, url_name="login"):
        return self.client.post(reverse(url_name), {"username": "manager", "password": password})

    def logged_in(self):
        return "_auth_user_id" in self.client.session

    def test_right_password_logs_in(self):
        self.login(PASSWORD)
        self.assertTrue(self.logged_in())

    def test_locked_after_too_many_wrong_passwords(self):
        for _ in range(MAX_FAILURES):
            self.login("wrong")
        self.login(PASSWORD)
        self.assertFalse(self.logged_in())

    def test_lock_covers_the_admin_login_too(self):
        for _ in range(MAX_FAILURES):
            self.login("wrong")
        self.login(PASSWORD, url_name="admin:login")
        self.assertFalse(self.logged_in())

    def test_a_few_wrong_tries_do_not_lock(self):
        for _ in range(MAX_FAILURES - 1):
            self.login("wrong")
        self.login(PASSWORD)
        self.assertTrue(self.logged_in())

    def test_other_usernames_are_not_locked(self):
        get_user_model().objects.create_user("agent", password=PASSWORD)
        for _ in range(MAX_FAILURES):
            self.login("wrong")
        self.client.post(reverse("login"), {"username": "agent", "password": PASSWORD})
        self.assertTrue(self.logged_in())

    def test_successful_login_resets_the_count(self):
        for _ in range(MAX_FAILURES - 1):
            self.login("wrong")
        self.login(PASSWORD)
        self.client.logout()
        for _ in range(MAX_FAILURES - 1):
            self.login("wrong")
        self.login(PASSWORD)
        self.assertTrue(self.logged_in())
