"""
Tests for "Forgot password" (calls/password_reset.py) and the Microsoft 365 email backend (calls/mail_graph.py).
Django's tests keep emails in a list (mail.outbox) instead of sending them, so nothing leaves the computer.
"""
import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from calls.lockout import MAX_FAILURES
from calls.mail_graph import GraphEmailBackend

PASSWORD = "a-long-test-password"


@override_settings(PASSWORD_RESET_EMAIL_DOMAIN="dash-mfb.com", PUBLIC_URL="https://calls.dash-mfb.com")
class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()  # the request limits and lockouts live in the cache
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user("amina", "amina@dash-mfb.com", PASSWORD)

    def ask(self, email):
        return self.client.post(reverse("password_reset"), {"email": email})

    def link(self):
        return re.search(r"https://calls\.dash-mfb\.com(/password-reset/\S+/)", mail.outbox[-1].body).group(1)

    def test_the_login_page_links_to_it(self):
        self.assertContains(self.client.get(reverse("login")), reverse("password_reset"))

    def test_a_company_address_gets_a_link_to_the_public_address(self):
        response = self.ask("Amina@dash-mfb.com")
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Reset your Call Dashboard password")
        self.assertIn("https://calls.dash-mfb.com/password-reset/", mail.outbox[0].body)

    def test_another_domain_is_refused_on_the_form(self):
        response = self.ask("amina@gmail.com")
        self.assertContains(response, "Use your @dash-mfb.com email address.")
        self.assertEqual(len(mail.outbox), 0)

    def test_an_account_saved_with_another_domain_gets_nothing(self):
        get_user_model().objects.create_user("toke", "toke@gmail.com", PASSWORD)
        self.ask("toke@dash-mfb.com")  # no account has this address
        self.assertEqual(len(mail.outbox), 0)

    def test_at_most_three_requests_an_hour_per_address(self):
        for _ in range(5):
            self.assertRedirects(self.ask("amina@dash-mfb.com"), reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 3)

    def test_the_link_sets_a_new_password_and_lifts_a_lockout(self):
        for _ in range(MAX_FAILURES):  # locked out by wrong passwords
            self.client.post(reverse("login"), {"username": "amina", "password": "wrong"})
        self.assertFalse(self.client.login(username="amina", password=PASSWORD))
        self.ask("amina@dash-mfb.com")
        form_page = self.client.get(self.link(), follow=True)  # Django swaps the token for a session first
        new = "a-brand-new-password-42"
        response = self.client.post(form_page.redirect_chain[-1][0], {"new_password1": new, "new_password2": new})
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.assertTrue(self.client.login(username="amina", password=new))

    def test_a_used_link_no_longer_works(self):
        self.ask("amina@dash-mfb.com")
        link = self.link()
        page = self.client.get(link, follow=True)
        new = "a-brand-new-password-42"
        self.client.post(page.redirect_chain[-1][0], {"new_password1": new, "new_password2": new})
        self.assertContains(self.client.get(link, follow=True), "This link no longer works")


@override_settings(MSGRAPH_TENANT_ID="t", MSGRAPH_CLIENT_ID="c", MSGRAPH_CLIENT_SECRET="s",
                   MSGRAPH_SENDER="no-reply@dash-mfb.com")
class GraphEmailTests(SimpleTestCase):
    def test_the_message_microsoft_receives(self):
        message = EmailMultiAlternatives("Subject", "Plain text", "no-reply@dash-mfb.com",
                                         ["Amina <amina@dash-mfb.com>"], reply_to=["help@dash-mfb.com"])
        message.attach_alternative("<p>HTML</p>", "text/html")
        payload = GraphEmailBackend()._payload(message)
        body = payload["message"]
        self.assertEqual(body["body"], {"contentType": "HTML", "content": "<p>HTML</p>"})
        self.assertEqual(body["toRecipients"], [{"emailAddress": {"address": "amina@dash-mfb.com"}}])
        self.assertEqual(body["replyTo"], [{"emailAddress": {"address": "help@dash-mfb.com"}}])
        self.assertFalse(payload["saveToSentItems"])

    def test_a_plain_message_without_reply_to_is_sent_too(self):
        payload = GraphEmailBackend()._payload(EmailMultiAlternatives("S", "Plain", to=["a@dash-mfb.com"]))
        self.assertEqual(payload["message"]["body"], {"contentType": "Text", "content": "Plain"})

    @override_settings(MSGRAPH_CLIENT_SECRET="")
    def test_missing_settings_are_named(self):
        with self.assertRaisesMessage(Exception, "MSGRAPH_CLIENT_SECRET"):
            GraphEmailBackend()
