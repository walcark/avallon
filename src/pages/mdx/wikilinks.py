"""python-markdown extension: ``[[slug]]`` -> internal page links.

Turns author cross-references into real ``<a>`` links. The target is matched,
in order, against each page's *slug* (leaf folder name) or its full *relpath*
(``domaine/type/slug``). Two forms are supported::

    [[pyspark-et-foundry]]              -> link, text = the page title
    [[pyspark-et-foundry|le sujet]]     -> link, text = "le sujet"

An unresolved reference renders as a marked ``<span>`` (not a link) so broken
cross-references stay visible while editing instead of silently vanishing.
"""

from __future__ import annotations

import xml.etree.ElementTree as etree

from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor

# [[ target ]] with an optional | label. Targets/labels may not contain ] or |.
WIKILINK_RE = r"\[\[\s*([^\]|]+?)\s*(?:\|\s*([^\]]+?)\s*)?\]\]"


def _resolve(target: str):
    """Return the Page whose slug or relpath equals *target*, else None."""
    # Imported lazily: the extension is loaded while Django builds the markdown
    # pipeline, and `content` pulls in settings/Http404, so importing it at
    # module top would risk an import cycle. Resolving here also means the map is
    # always current (matters for live-reload).
    from .. import content

    for page in content.all_pages():
        if target == page.slug or target == page.relpath:
            return page
    return None


class WikiLinkInlineProcessor(InlineProcessor):
    def handleMatch(self, m, data):
        target = m.group(1).strip()
        label = (m.group(2) or "").strip()
        page = _resolve(target)
        if page is None:
            el = etree.Element("span")
            el.set("class", "wikilink wikilink-missing")
            el.set("title", f"Page introuvable : {target}")
            el.text = label or target
        else:
            el = etree.Element("a")
            el.set("href", page.url)
            el.set("class", "wikilink")
            el.text = label or page.title
        return el, m.start(0), m.end(0)


class WikiLinkExtension(Extension):
    def extendMarkdown(self, md):
        # Priority 175 > the built-in `link` (160), so `[[...]]` is consumed
        # here before the standard `[...]( )` link parser sees the brackets.
        md.inlinePatterns.register(
            WikiLinkInlineProcessor(WIKILINK_RE, md), "wikilink", 175
        )


def makeExtension(**kwargs):
    return WikiLinkExtension(**kwargs)
