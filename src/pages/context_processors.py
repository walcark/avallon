"""Template context shared by every page."""

from . import content


def navigation(request):
    """Expose the domaine -> type -> pages tree to the sidebar in base.html."""
    return {"nav": content.nav_tree()}
