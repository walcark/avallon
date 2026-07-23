"""Template access to the taxonomy's display names.

The facet chips and the breadcrumbs iterate over bare directory names, which
have no Page object to carry a label, hence a filter rather than a property.
"""

from django import template

from .. import content

register = template.Library()


@register.filter
def label(value: str) -> str:
    """Display name for a domain or type, or the value itself if undeclared."""
    return content.label_for(str(value))
