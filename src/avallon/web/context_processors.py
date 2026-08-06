"""Template context shared by every page."""

from django.conf import settings

from . import content


def navigation(request):
    """Expose the sidebar tree and the interface language to every template."""
    return {"nav": content.nav_tree(), "lang": settings.LANGUAGE}
