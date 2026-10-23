"""
Top-level URL map: which address goes to which part of the site.

    /                   -> the dashboard (calls app)
    /api/...            -> JSON data for the dashboard (calls app)
    /accounts/login/    -> Django's built-in login page (and /accounts/logout/, /accounts/password_change/)
    /password-reset/... -> "Forgot password": a one-time link by email, to company addresses only
    /admin/             -> Django admin, for superusers only (the address can be changed: DJANGO_ADMIN_PATH)
"""
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from calls.password_reset import ResetConfirmView, ResetRequestView

urlpatterns = [
    path(settings.ADMIN_PATH, admin.site.urls),
    # Django's login, logout and change-password pages
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
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
