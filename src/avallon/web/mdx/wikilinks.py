"""python-markdown extension: ``[[slug]]`` -> internal page links.

Turns author cross-references into real ``<a>`` links. The target is matched
against each page's *slug* (leaf folder name) or its full *relpath*
(``domaine/type/slug``), and may be written as the page's title rather than as
its folder name (see :func:`resolves_to`)::

    [[pyspark-et-foundry]]              -> link, text = the page title
    [[pyspark-et-foundry|le sujet]]     -> link, text = "le sujet"
    [[PySpark et Foundry]]              -> same page, written as it reads

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


def resolves_to(target: str, slug: str, relpath: str) -> bool:
    """Whether the wikilink *target* designates the page (*slug*, *relpath*).

    The single matching rule, shared with the backlink walker so a reference
    that renders as a link is always the one that shows up as a backlink.
    Three forms are accepted, so a cross-reference can be written the way the
    page reads rather than the way its folder happens to be named:

    - the slug or the full relpath, verbatim: ``[[titre-exact]]``
    - either of those in any case: ``[[Titre-Exact]]``
    - the title itself: ``[[Titre exact]]``, or ``[[titre exact]]``

    The last form works by slugifying the target, which is exactly how the
    slug was derived from the title when the page was created (accents
    stripped, case folded, runs of punctuation collapsed to hyphens). Slugs
    are already in that shape, so the rule is a strict superset of the exact
    match and cannot make two pages compete for one reference.

    Parameters
    ----------
    target : str
        The text inside the brackets, already stripped.
    slug : str
        The candidate page's leaf folder name.
    relpath : str
        The candidate page's ``domaine/type/slug``.

    Returns
    -------
    bool
        True when *target* designates that page.
    """
    from avallon.notes.scaffold import slugify

    lowered = target.lower()
    if lowered in (slug.lower(), relpath.lower()):
        return True
    # Not applied to the relpath: slugify would eat its slashes and turn it
    # into something that can only ever collide by accident.
    return slugify(target) == slug.lower()


def _resolve(target: str):
    """Return the Page *target* designates, else None."""
    # Imported lazily: the extension is loaded while Django builds the markdown
    # pipeline, and `content` pulls in settings/Http404, so importing it at
    # module top would risk an import cycle. Resolving here also means the map is
    # always current (matters for live-reload).
    from avallon.web import content

    for page in content.all_pages():
        if resolves_to(target, page.slug, page.relpath):
            return page
    return None


def _colocated_file(target: str):
    """Return *target* if it names a file next to the page being rendered.

    Relative to the page's own directory, which is also the URL the browser
    resolves ``href="alis-2019.pdf"`` against (page URLs end in a slash), so a
    bare filename is all the href needs.
    """
    from avallon.web import content

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
