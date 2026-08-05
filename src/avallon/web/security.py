"""One shared secret in front of the whole site.

The notes are private by nature, so the guard covers reading as much as
writing: everything behind it, nothing in front except the unlock page and the
static files it needs to render.

It is the second layer, behind the network boundary (wireguard, a firewall):
even a device that reaches the port cannot read or write without the secret.
When no token is configured the guard is a no-op, which is only safe on
loopback, and `avallon serve` refuses any other bind without one.

Unlike an API consumed by a script, a browser will never send an
``Authorization`` header on its own. The token is therefore exchanged once for
a signed session cookie, which is what every later request carries.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

SESSION_KEY = "avallon_unlocked"


def is_unlocked(request: HttpRequest) -> bool:
    """Whether *request* may see the site at all."""
    if not settings.ACCESS_TOKEN:
        return True
    return bool(request.session.get(SESSION_KEY))


class TokenGateMiddleware:
    """Redirect every request to the unlock page until the session is opened."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if is_unlocked(request):
            return self.get_response(request)

        unlock = reverse("unlock")
        # The unlock page itself, and the stylesheet that makes it readable.
        if request.path == unlock or request.path.startswith(settings.STATIC_URL):
            return self.get_response(request)

        target = request.get_full_path()
        return HttpResponseRedirect(
            f"{unlock}?next={target}" if target != "/" else unlock
        )


@require_http_methods(["GET", "POST"])
def unlock(request: HttpRequest) -> HttpResponse:
    """Exchange the access token for an open session.

    The comparison is constant-time: a token is a secret, and an early exit on
    the first wrong character is what makes a secret guessable one character at
    a time.
    """
    if not settings.ACCESS_TOKEN:
        return HttpResponseRedirect("/")

    error = ""
    if request.method == "POST":
        given = request.POST.get("token", "")
        if secrets.compare_digest(given, settings.ACCESS_TOKEN):
            request.session[SESSION_KEY] = True
            # A fresh session id on privilege change, so a cookie captured
            # before the unlock cannot be replayed after it.
            request.session.cycle_key()
            return HttpResponseRedirect(request.POST.get("next") or "/")
        error = "Jeton invalide."

    return render(
        request,
        "unlock.html",
        {"error": error, "next": request.GET.get("next", "")},
        status=401 if error else 200,
    )
