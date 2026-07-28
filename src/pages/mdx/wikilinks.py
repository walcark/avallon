"""python-markdown extension: ``[[slug]]`` -> internal page links.

Turns author cross-references into real ``<a>`` links. The target is matched,
in order, against each page's *slug* (leaf folder name) or its full *relpath*
(``domaine/type/slug``). Two forms are supported::

    [[pyspark-et-foundry]]              -> link, text = the page title
    [[pyspark-et-foundry|le sujet]]     -> link, text = "le sujet"

A target that names a file sitting next to the page (``[[alis-2019.pdf]]``)
links to that co-located file instead, so a dropped PDF is one click away.

An unresolved reference renders as a marked ``<span>`` (not a link) so broken
cross-references stay visible while editing instead of silently vanishing.

The extension also opens every content link in a new tab (see
:class:`NewTabTreeprocessor`).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as etree

from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.treeprocessors import Treeprocessor

# [[ target ]] with an optional | label. Targets/labels may not contain ] or |.
WIKILINK_RE = r"\[\[\s*([^\]|]+?)\s*(?:\|\s*([^\]]+?)\s*)?\]\]"

# A target ending in a short extension is read as a filename, not a slug. Slugs
# and relpaths use hyphens and slashes, never a dotted suffix, so this cannot
# swallow a real page reference; and a dotted target is only treated as a file
# once one actually exists next to the page (see below).
_FILE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,8}$")


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


def _colocated_file(target: str):
    """Return *target* if it names a file next to the page being rendered.

    Relative to the page's own directory, which is also the URL the browser
    resolves ``href="alis-2019.pdf"`` against (page URLs end in a slash), so a
    bare filename is all the href needs.
    """
    from .. import content

    if not _FILE_SUFFIX.search(target):
        return None
    base = content.current_render_dir()
    if base is not None and (base / target).is_file():
        return target
    return None


class WikiLinkInlineProcessor(InlineProcessor):
    def handleMatch(self, m, data):
        target = m.group(1).strip()
        label = (m.group(2) or "").strip()

        href = _colocated_file(target)
        if href is not None:
            el = etree.Element("a")
            el.set("href", href)
            el.set("class", "wikilink wikilink-file")
            el.text = label or target
            return el, m.start(0), m.end(0)

        page = _resolve(target)
        if page is None:
            el = etree.Element("span")
            el.set("class", "wikilink wikilink-missing")
            el.set("title", f"Cible introuvable : {target}")
            el.text = label or target
        else:
            el = etree.Element("a")
            el.set("href", page.url)
            el.set("class", "wikilink")
            el.text = label or page.title
        return el, m.start(0), m.end(0)


class NewTabTreeprocessor(Treeprocessor):
    """Open every content link in a new tab.

    In-page anchors are left alone: the sommaire permalinks and any ``#id``
    jump belong in the current tab, and spawning a tab for them would be
    baffling. Everything else (external links, other notes, co-located files)
    opens beside the note being read.
    """

    def run(self, root):
        for a in root.iter("a"):
            href = a.get("href", "")
            if href and not href.startswith("#"):
                a.set("target", "_blank")
                a.set("rel", "noopener")
        return root


class WikiLinkExtension(Extension):
    def extendMarkdown(self, md):
        # Priority 175 > the built-in `link` (160), so `[[...]]` is consumed
        # here before the standard `[...]( )` link parser sees the brackets.
        md.inlinePatterns.register(
            WikiLinkInlineProcessor(WIKILINK_RE, md), "wikilink", 175
        )
        # Low priority so it runs after inline processing has created every
        # <a>, including the wikilinks above.
        md.treeprocessors.register(NewTabTreeprocessor(md), "new_tab", 5)


def makeExtension(**kwargs):
    return WikiLinkExtension(**kwargs)
