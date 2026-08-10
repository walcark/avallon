"""Template context shared by every page."""

from . import content, i18n


def navigation(request):
    """Expose the sidebar tree and the interface language to every template."""
    return {
        "nav": content.nav_tree(),
        "lang": i18n.active(),
        # The other one, which is what a one-click switch has to offer.
        "other_lang": "en" if i18n.active() != "en" else "fr",
    }
