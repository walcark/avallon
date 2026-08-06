"""Template access to the interface translations.

A filter rather than a tag, because it has to compose: ``|escapejs`` inside a
script block, ``|title`` where a heading wants it. The English text is the key,
so an untranslated string renders as itself.
"""

from django import template
from django.conf import settings

from avallon.web import i18n

register = template.Library()


@register.filter(name="t")
def translate(value: str) -> str:
    """Return *value* in the configured interface language."""
    return i18n.translate(str(value), settings.LANGUAGE)
