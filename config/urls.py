"""
Top-level URL map: which address goes to which part of the site.

    /                   -> the dashboard (calls app)
    /api/...            -> JSON data for the dashboard (calls app)
    /accounts/login/    -> Django's built-in login page (and /accounts/logout/, /accounts/password_change/)
    /accounts/oci/login/ -> "Sign in with OCI"; OCI sends people back to the path of OCI_SSO_REDIRECT_URI
    /password-reset/... -> "Forgot password": a one-time link by email, to company addresses only
    /admin/             -> Django admin, for superusers only (the address can be changed: DJANGO_ADMIN_PATH)
"""
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from calls import oci_sso
from calls.password_reset import ResetConfirmView, ResetRequestView

# Where OCI sends people back after login: the path of the Redirect URL registered in OCI.
OCI_CALLBACK_PATH = urlsplit(settings.OCI_SSO_REDIRECT_URI).path.strip("/") or "accounts/oci/callback"

urlpatterns = [
    path(settings.ADMIN_PATH, admin.site.urls),
    # Django's login, logout and change-password pages
    path("accounts/login/", oci_sso.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Sign in with OCI (calls/oci_sso.py)
    path("accounts/oci/login/", oci_sso.oci_start, name="oci_login"),
    path(f"{OCI_CALLBACK_PATH}/", oci_sso.oci_callback, name="oci_callback"),
    path("accounts/password_change/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("accounts/password_change/done/", auth_views.PasswordChangeDoneView.as_view(),
         name="password_change_done"),
    # Forgot password: ask for a link, "check your email", set the new password, done
    path("password-reset/", ResetRequestView.as_view(), name="password_reset"),
    path("password-reset/sent/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/", ResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password-reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("", include("calls.urls")),
]
