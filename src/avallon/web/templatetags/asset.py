"""Static URLs that change when the file does.

The service worker serves ``/static/`` cache-first, which is what makes a page
open instantly and work offline. The cost is that a stylesheet cached once is
the stylesheet forever: an upgrade, or an edit during development, only shows
up after a hard reload, which nobody should have to know about.

A fingerprint in the query string fixes it at the source. The URL of a changed
file is a different URL, so it misses the cache, is fetched, and replaces the
old entry. Nothing has to expire, and no cache has to be versioned by hand.

``{% asset %}`` rather than Django's ``ManifestStaticFilesStorage``: that one
rewrites file names at ``collectstatic`` time, and this project serves its
static files straight from the package (``WHITENOISE_USE_FINDERS``) so there is
no collect step to hook into.
"""

from __future__ import annotations

import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()

# path -> (mtime, size, url). Stat is one syscall, but it is one per asset per
# page, and the answer only changes when the file does.
_CACHE: dict[str, tuple[float, int, str]] = {}


@register.simple_tag
def asset(path: str) -> str:
    """The static URL for *path*, with a fingerprint of its current bytes."""
    url = static(path)
    found = finders.find(path)
    if not found:
        return url
    try:
        stat = os.stat(found)
    except OSError:
        return url
    cached = _CACHE.get(path)
    if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]
    # mtime and size, not a content hash: reading every asset on every start
    # buys nothing here, where the files only change when this package does.
    stamp = format(int(stat.st_mtime) ^ (stat.st_size << 8), "x")[-8:]
    fingerprinted = f"{url}?v={stamp}"
    _CACHE[path] = (stat.st_mtime, stat.st_size, fingerprinted)
    return fingerprinted
