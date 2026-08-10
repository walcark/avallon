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
from collections.abc import Sequence
from typing import Any

from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.treeprocessors import Treeprocessor

# [[ target ]] with an optional | label. Targets/labels may not contain ] or |.
WIKILINK_RE = r"\[\[\s*([^\]|]+?)\s*(?:\|\s*([^\]]+?)\s*)?\]\]"

# `![[…]]`: show a document here instead of linking to it. The file stays in
# the one page that owns it, so a scan used by three notes has one copy, one
# set of tags and one URL. Copying it into each note is what this exists to
# avoid.
EMBED_RE = r"!\[\[\s*([^\]|]+?)\s*(?:\|\s*([^\]]+?)\s*)?\]\]"

# A target ending in a short extension is read as a filename, not a slug. Slugs
# and relpaths use hyphens and slashes, never a dotted suffix, so this cannot
# swallow a real page reference; and a dotted target is only treated as a file
# once one actually exists next to the page (see below).
_FILE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,8}$")


def resolves_to(
    target: str, slug: str, relpath: str, aliases: Sequence[str] = ()
) -> bool:
    """Whether the wikilink *target* designates the page (*slug*, *relpath*).

    The single matching rule, shared with the backlink walker so a reference
    that renders as a link is always the one that shows up as a backlink.
    Three forms are accepted, so a cross-reference can be written the way the
    page reads rather than the way its folder happens to be named:

    - the slug or the full relpath, verbatim: ``[[titre-exact]]``
    - either of those in any case: ``[[Titre-Exact]]``
    - the title itself: ``[[Titre exact]]``, or ``[[titre exact]]``
    - any name the page used to answer to, listed in its ``aliases:``

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
    return matches_current(target, slug, relpath) or matches_former(target, aliases)


def matches_current(target: str, slug: str, relpath: str) -> bool:
    """Whether *target* is a name the page answers to **now**."""
    from avallon.notes.scaffold import slugify

    lowered = target.lower()
    if lowered in (slug.lower(), relpath.lower()):
        return True
    # Not applied to the relpath: slugify would eat its slashes and turn it
    # into something that can only ever collide by accident.
    return slugify(target) == slug.lower()


def matches_former(target: str, aliases: Sequence[str]) -> bool:
    """Whether *target* is a name the page **used to** answer to.

    Former names, written by the tool when a title or a slug changes: the
    identity travels with the page, not with the notes that cite it.
    """
    from avallon.notes.scaffold import slugify

    lowered = target.lower()
    return any(
        lowered == alias.lower() or slugify(target) == slugify(alias)
        for alias in aliases
    )


def resolve_among(target: str, pages: Sequence[Any]) -> Any | None:
    """The page *target* designates among *pages*, or None.

    Two passes, and the order is the whole point. A page that bears the name
    now always beats a page that merely bore it: a freed name can be given to a
    new page, and the new page must own it. Without the split, the winner was
    whichever came first in the list, which is sorted by recency, so a rename
    made today could quietly capture a link meant for a note dated last June.

    Ambiguity is not resolved, it is refused. Two pages that were both once
    called the same thing give no answer at all, which renders as a dead link
    someone can see and fix. Guessing would render as a working link to the
    wrong page, and these notes are read as evidence.
    """
    current = [p for p in pages if matches_current(target, p.slug, p.relpath)]
    if current:
        # More than one page bearing a name is prevented at creation, so this
        # only happens in a tree edited by hand: same rule, no guess.
        return current[0] if len(current) == 1 else None
    former = [p for p in pages if matches_former(target, p.aliases)]
    return former[0] if len(former) == 1 else None


def _resolve(target: str):
    """Return the Page *target* designates, else None."""
    # Imported lazily: the extension is loaded while Django builds the markdown
    # pipeline, and `content` pulls in settings/Http404, so importing it at
    # module top would risk an import cycle. Resolving here also means the map is
    # always current (matters for live-reload).
    from avallon.web import content

    return resolve_among(target, content.all_pages())


def _deleted(target: str):
    """The trashed page *target* names, or None."""
    from avallon.web import content

    try:
        return content.deleted_named(target)
    except Exception:
        # Rendering a note must never fail because git did: a dead link stays
        # a dead link, it simply loses the offer to undo.
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
            el.set("title", f"Target not found: {target}")
            el.text = label or target
            # A link to a page that was deleted is not a typo, and saying only
            # "not found" makes it a dead end: it carries what it needs for the
            # reader to choose between bringing the page back and letting the
            # link go. The trash is read once per render, not once per link.
            gone = _deleted(target)
            if gone is not None:
                el.set("class", "wikilink wikilink-deleted")
                el.set("data-slug", gone.slug)
                el.set("data-target", target)
                el.set("data-when", gone.when)
        else:
            el = etree.Element("a")
            el.set("href", page.url)
            el.set("class", "wikilink")
            el.text = label or page.title
        return el, m.start(0), m.end(0)


class EmbedInlineProcessor(InlineProcessor):
    """Render ``![[doc]]`` as the document's own file, captioned and linked."""

    def handleMatch(self, m, data):
        target = m.group(1).strip()
        caption = (m.group(2) or "").strip()

        # `![[doc/file.png]]` picks one file out of a multi-file document.
        page_ref, _, inner = target.partition("/")
        page = _resolve(page_ref if inner else target)
        if page is None or not (page.file or inner):
            el = etree.Element("span")
            el.set("class", "wikilink wikilink-missing")
            el.set("title", f"Target not found: {target}")
            el.text = caption or target
            return el, m.start(0), m.end(0)

        name = inner or page.file
        src = f"{page.url}{name}"
        kind = page.kind if not inner else _kind_of(name)

        figure = etree.Element("figure")
        figure.set("class", "embed")
        if kind == "image":
            link = etree.SubElement(figure, "a")
            link.set("href", page.url)
            img = etree.SubElement(link, "img")
            img.set("src", src)
            img.set("alt", caption or page.title)
            img.set("loading", "lazy")
        else:
            # Anything not an image is announced rather than shown: a viewer
            # inside a paragraph would take over the note it illustrates.
            link = etree.SubElement(figure, "a")
            link.set("href", page.url)
            link.set("class", "embed-file")
            link.text = caption or page.title
        legend = etree.SubElement(figure, "figcaption")
        legend.text = caption or page.title
        return figure, m.start(0), m.end(0)


def _kind_of(name: str) -> str:
    """The kind of a bare file name, for `![[doc/file.png]]`."""
    from avallon.web import content

    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return content.KIND_BY_EXTENSION.get(suffix, content.KIND_OTHER)


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
        # Above the wikilink, so `![[…]]` is consumed as an embed rather than
        # as a `!` followed by a link.
        md.inlinePatterns.register(
            EmbedInlineProcessor(EMBED_RE, md), "wikilink_embed", 176
        )
        md.inlinePatterns.register(
            WikiLinkInlineProcessor(WIKILINK_RE, md), "wikilink", 175
        )
        # Low priority so it runs after inline processing has created every
        # <a>, including the wikilinks above.
        md.treeprocessors.register(NewTabTreeprocessor(md), "new_tab", 5)


def makeExtension(**kwargs):
    return WikiLinkExtension(**kwargs)
