"""Answering each request in the language that reader chose.

A cookie rather than the configured default, because the default belongs to the
installation while the choice belongs to whoever is holding the screen: a phone
reading in French and a laptop showing the same site to someone in English are
the same server, and neither should have to restart it to be understood.
"""

from __future__ import annotations

from django.conf import settings

from . import i18n


class LanguageMiddleware:
    """Set the request's language from its cookie, else from the settings."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        chosen = request.COOKIES.get(i18n.COOKIE, "")
        i18n.activate(chosen if chosen else settings.LANGUAGE)
        return self.get_response(request)
