"""Loading, rendering and searching of the Markdown content tree.

The directory layout encodes both the taxonomy and the URL:

    content/<domaine>/<type>/<slug>/index.md   ->   /<domaine>/<type>/<slug>/

Images (and other assets) live next to the index.md that uses them and are
referenced with *relative* paths, so they resolve under the page's own URL
without any src rewriting.
"""

from __future__ import annotations

import contextvars
import datetime
import hashlib
import html
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter
from django.conf import settings
from django.http import Http404
from markdownify.templatetags.markdownify import markdownify

from .mdx.wikilinks import WIKILINK_RE, resolves_to

CONTENT_DIR: Path = settings.CONTENT_DIR

# Same pattern the Markdown extension uses, so backlinks and rendered links
# can never disagree about what counts as a reference.
_WIKILINK = re.compile(WIKILINK_RE)

# Glob matching every page: content/<domaine>/<type>/<slug>/index.md.
_PAGE_GLOB = "*/*/*/index.md"

# Where a page stands, when that question makes sense. The path says what a
# page *is*, never how far along it is: a note that will be finished one day is
# still a `cr` or a `fiche`, so progress lives in the frontmatter and can change
# without moving the page (and thus without changing its URL).
STATUSES = ("en cours", "terminé", "abandonné")

# What a page's attached file is, derived from its extension and never typed.
# The type says what a page *is* and cannot be checked; the medium is already
# written in the file name, so declaring it a second time only invites the two
# to disagree.
KIND_BY_EXTENSION = {
    **dict.fromkeys(("png", "jpg", "jpeg", "webp", "svg", "gif", "avif"), "image"),
    "pdf": "pdf",
    **dict.fromkeys(
        ("txt", "md", "csv", "tsv", "py", "sh", "toml", "yaml", "yml", "json"), "text"
    ),
    **dict.fromkeys(("docx", "xlsx", "pptx", "odt", "ods", "odp"), "office"),
    **dict.fromkeys(("zip", "tar", "gz", "xz", "7z", "rar", "epub"), "archive"),
}

# A page with no file is a note: the kind stays a complete partition, so it can
# be a facet without a hole in it.
KIND_NOTE = "note"
KIND_OTHER = "other"

# Kinds a grid can show a picture of. The rest fall back to cards.
VISUAL_KINDS = ("image", "pdf")

# A tag earns a place in the home page's facets once this many pages carry it.
# Below that it filters nothing a search would not find, while crowding out the
# tags that do group pages together.
TAG_FACET_MIN = 3


def _as_date_str(value: Any) -> str:
    """Normalize a frontmatter date (datetime.date, str or None) to an ISO
    'YYYY-MM-DD' string usable for sorting; '' when absent."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _fr_date(value: Any) -> str:
    """Human 'JJ/MM/AAAA' from a frontmatter date, or '' if absent/unparsable."""
    s = _as_date_str(value)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else s


@dataclass(frozen=True)
class Page:
    """Metadata for one Markdown page, derived from its path + frontmatter."""

    relpath: str  # "travail/cr/reunion-hygeos"
    domain: str  # from the path: <domaine>/...
    type: str  # from the path: .../<type>/...
    slug: str  # the leaf directory name
    title: str
    date: Any | None  # creation date (frontmatter, set once)
    updated: Any | None  # last-modified date (frontmatter, stamped on commit)
    tags: list[str]
    summary: str
    visibility: str  # "public" (default) or "private"
    project: str  # slug of the page that indexes the project, or ""
    status: str  # one of STATUSES, or "" when the question is moot
    file: str  # attached file, co-located with index.md, or ""

    @property
    def url(self) -> str:
        return f"/{self.relpath}/"

    @property
    def is_private(self) -> bool:
        return self.visibility == "private"

    @property
    def kind(self) -> str:
        """What this page holds: note, image, pdf, text, office, archive."""
        if not self.file:
            return KIND_NOTE
        suffix = self.file.rsplit(".", 1)[-1].lower() if "." in self.file else ""
        return KIND_BY_EXTENSION.get(suffix, KIND_OTHER)

    @property
    def file_url(self) -> str:
        """URL of the attached file, which sits next to the page."""
        return f"{self.url}{self.file}" if self.file else ""

    @property
    def is_visual(self) -> bool:
        """Whether a grid can show a picture of this page."""
        return self.kind in VISUAL_KINDS

    @property
    def display_date(self) -> str:
        """Human date shown in listings: last-modified, falling back to creation."""
        return _fr_date(self.updated or self.date)

    @property
    def domain_label(self) -> str:
        return label_for(self.domain)

    @property
    def type_label(self) -> str:
        return label_for(self.type)


def _recency_key(page: Page) -> str:
    """Sort key for 'most recent first': updated, falling back to creation."""
    return _as_date_str(page.updated) or _as_date_str(page.date)


def _sort_hits(hits: list[SearchHit]) -> None:
    """Order search hits like the home page: most recent first, then by title."""
    hits.sort(key=lambda h: h.page.title)
    hits.sort(key=lambda h: _recency_key(h.page), reverse=True)


@dataclass(frozen=True)
class SearchHit:
    """A page matched by a full-text query, with a highlighted excerpt."""

    page: Page
    snippet: str  # safe HTML, matched terms wrapped in <mark>


# --------------------------------------------------------------------------- #
# Display names                                                               #
# --------------------------------------------------------------------------- #

# Directory names double as URL segments, so they stay lowercase and
# unaccented. `[labels]` in taxonomy.toml maps them to what a reader sees
# ("sante" -> "santé", "cr" -> "compte rendu"), leaving the paths untouched.
_taxonomy_cache: tuple[float, dict[str, Any]] | None = None


def taxonomy() -> dict[str, Any]:
    """Parsed taxonomy.toml, cached against its mtime.

    It is read on nearly every request and changes about twice a year, so the
    cache matters; keying it on the mtime means an edit still takes effect
    without restarting the server.
    """
    global _taxonomy_cache
    path = CONTENT_DIR / "taxonomy.toml"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _taxonomy_cache is None or _taxonomy_cache[0] != mtime:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        _taxonomy_cache = (mtime, data)
    return _taxonomy_cache[1]


def labels() -> dict[str, str]:
    """Display names declared in taxonomy.toml, keyed by directory name."""
    raw = taxonomy().get("labels")
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def vocabulary() -> dict[str, list[str]]:
    """The declared domains and types, each paired with its display name.

    The creation form offers exactly this and nothing else, which is the same
    rule `avallon new` enforces: a page cannot be born under an undeclared
    domain or type.
    """
    data = taxonomy()
    return {
        key: sorted(str(v) for v in data.get(key, []) or [])
        for key in ("domains", "types")
    }


def _normalize_tag(tag: str) -> str:
    """Canonical form of a tag: trimmed, inner whitespace collapsed, lowercased.

    Case and stray spacing are the usual source of near-duplicate tags
    ("Monte-Carlo" vs "monte-carlo"), which then split the facets in two.
    Folding them here treats the variants as one. Accents are kept, so
    "déformation" stays readable.
    """
    return re.sub(r"\s+", " ", tag.strip()).lower()


def normalize_tags(tags: list[str]) -> list[str]:
    """Normalize *tags* and drop duplicates, preserving first-seen order."""
    seen: dict[str, None] = {}
    for tag in tags:
        norm = _normalize_tag(tag)
        if norm:
            seen.setdefault(norm, None)
    return list(seen)


def label_for(name: str) -> str:
    """Display name for a domain or type, falling back to the name itself.

    Undeclared is the normal case: only the few names whose directory form
    reads badly need an entry.
    """
    return labels().get(name, name)


def safe_resolve(relpath: str) -> Path:
    """Resolve *relpath* under CONTENT_DIR, refusing anything that escapes it
    (e.g. `../../etc/passwd`)."""
    target = (CONTENT_DIR / relpath.strip("/")).resolve()
    if target != CONTENT_DIR and CONTENT_DIR not in target.parents:
        raise Http404("Path outside the notes tree")
    return target


# A leading `# Title` line: the template renders the frontmatter title as the
# page heading, so repeating it in the body would show it twice. Most pages
# already start at `##`; this makes the two conventions render alike.
_LEADING_H1 = re.compile(r"\A\s*#[^#\n][^\n]*\n")


# The directory of the page currently being rendered, so the wikilink
# extension can tell a reference to a co-located file ([[alis-2019.pdf]]) from
# a broken page slug. A ContextVar rather than a global: rendering runs in a
# worker thread (asyncio.to_thread), which copies the context, so concurrent
# renders never see each other's directory.
_render_dir: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "render_dir", default=None
)


def current_render_dir() -> Path | None:
    """The folder of the page being rendered, or None outside a render."""
    return _render_dir.get()


@dataclass
class ExportContext:
    """State for a Word/PDF export in progress.

    Rendering to a document instead of to the site: the content blocks emit
    document-friendly HTML (a plot becomes a self-contained ``<img>`` rather
    than a themed inline SVG). *assets_dir* is where those generated files are
    written for Pandoc to pick up, and *count* names them uniquely.
    """

    assets_dir: Path
    count: int = 0


# Set for the duration of an export render (see pages.exporter). The content
# fences read it to switch to their document-friendly output.
_export: contextvars.ContextVar[ExportContext | None] = contextvars.ContextVar(
    "export", default=None
)


def current_export() -> ExportContext | None:
    """The export in progress, or None during an ordinary site render."""
    return _export.get()


def render_markdown(index_md: Path, export: ExportContext | None = None) -> str:
    """Render an index.md (frontmatter stripped) to HTML, using the same filter
    the template uses so streamed updates match the initial render.

    When *export* is given, the content blocks render their document form
    instead of their interactive one (see :mod:`pages.exporter`).
    """
    post = frontmatter.load(index_md)
    token = _render_dir.set(index_md.parent)
    etoken = _export.set(export)
    try:
        html_out = str(markdownify(_LEADING_H1.sub("", post.content, count=1)))
        if export is not None:
            html_out = _export_code_blocks(html_out)
        return html_out
    finally:
        _render_dir.reset(token)
        _export.reset(etoken)


# A Pygments code box, as pymdownx.highlight emits it: an optional language
# label (auto_title) then the highlighted <pre>. The label and the tokenizing
# <span>s stop Pandoc from reading the <pre> as a code block (it flattens the
# lot into one run-together paragraph), so for export we rebuild a clean
# <pre><code> Pandoc turns into a real, monospace, syntax-highlighted CodeBlock.
_CODE_BOX = re.compile(r'<div class="highlight">(?P<body>.*?)</div>', re.DOTALL)
_CODE_LABEL = re.compile(r'<span class="filename">(?P<name>[^<]*)</span>')
_CODE_INNER = re.compile(r"<code[^>]*>(?P<code>.*?)</code>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def _export_code_blocks(html_out: str) -> str:
    """Rewrite Pygments code boxes to clean ``<pre><code>`` for the export.

    Pygments wraps each line in ``<span>`` tokens; Pandoc's HTML reader then
    treats the box as inline text and collapses the newlines. Stripping the
    tokens back to plain text (Pandoc re-highlights from the language class)
    restores real code blocks in the Word/PDF output.
    """

    def rewrite(match: re.Match[str]) -> str:
        body = match.group("body")
        inner = _CODE_INNER.search(body)
        if inner is None:
            return match.group(0)
        text = html.unescape(_TAG.sub("", inner.group("code")))
        label = _CODE_LABEL.search(body)
        display = label.group("name").strip() if label else ""
        # The label is a display name ("Python"); its first word, lowercased,
        # is a good Pandoc/skylighting language id ("python"). Unknown ids just
        # yield an un-highlighted (still monospace) block, so this is safe.
        lang = display.split()[0].lower() if display else ""
        cls = f' class="{html.escape(lang)}"' if lang else ""
        # A "code-label" caption (word_styles.lua maps it to a darker header
        # style) then the code, so the two stack into one two-tone card.
        header = f'<div class="code-label">{html.escape(display or "Code")}</div>'
        return f"{header}<pre><code{cls}>{html.escape(text)}</code></pre>"

    return _CODE_BOX.sub(rewrite, html_out)


def reading_minutes(index_md: Path) -> int:
    """Rough reading time in minutes, at 200 words per minute, floored at 1."""
    post = frontmatter.load(index_md)
    words = len(_plain_text(post.content).split())
    return max(1, round(words / 200))


# --------------------------------------------------------------------------- #
# Editing                                                                     #
# --------------------------------------------------------------------------- #


class InvalidFrontmatter(ValueError):
    """The submitted Markdown carries a frontmatter block YAML cannot parse."""


class StaleEdit(Exception):
    """The file changed on disk since the editor loaded it.

    Raised instead of overwriting: the browser editor and a local text editor
    can hold the same page at once, and the last writer would otherwise win in
    silence.
    """


class InvalidPage(ValueError):
    """The submitted creation form cannot produce a page."""


def create_page(
    domain: str,
    type_: str,
    title: str,
    tags: list[str],
    summary: str = "",
    project: str = "",
) -> Page:
    """Scaffold ``<domain>/<type>/<slug>/index.md`` and return the new Page.

    The slug and the frontmatter come from ``scripts/new_page.py`` rather than
    from a second implementation here: the browser and ``avallon new`` must
    produce the same URL for the same title, and two copies of the rules would
    drift apart.

    Parameters
    ----------
    domain, type_ : str
        Must both be declared in taxonomy.toml.
    title : str
        Free text; the slug is derived from it.
    tags : list of str
        Free text, no vocabulary.
    summary : str, optional
        One-line summary shown on the home page.
    project : str, optional
        Slug of the project page this one belongs to. Left out of the
        frontmatter when empty, so a standalone note stays free of the field.

    Returns
    -------
    Page
        The page just created.

    Raises
    ------
    InvalidPage
        Undeclared domain or type, or an empty title.
    """
    # scripts/ is on sys.path (see config.settings).
    from avallon.notes.scaffold import scalar, slugify

    vocab = vocabulary()
    if domain not in vocab["domains"]:
        raise InvalidPage(f"Undeclared domain: {domain}")
    if type_ not in vocab["types"]:
        raise InvalidPage(f"Undeclared type: {type_}")
    if not title.strip():
        raise InvalidPage("A title is required.")

    base = CONTENT_DIR / domain / type_
    slug = slugify(title)
    target = base / slug
    suffix = 2
    while target.exists():
        target = base / f"{slug}-{suffix}"
        suffix += 1

    today = datetime.date.today().isoformat()
    lines = [
        f"title: {scalar(title.strip())}",
        f"date: {today}",
        f"updated: {today}",
        "tags: [" + ", ".join(scalar(t) for t in normalize_tags(tags)) + "]",
    ]
    if summary.strip():
        lines.append(f"summary: {scalar(summary.strip())}")
    if project.strip():
        lines.append(f"project: {scalar(project.strip())}")
    body = "---\n" + "\n".join(lines) + "\n---\n\n"

    target.mkdir(parents=True)
    (target / "index.md").write_text(body, encoding="utf-8")
    return _page_from(target / "index.md")


def move_page(relpath: str, new_domain: str, new_type: str) -> Page:
    """Re-file a page under another domain/type and return it at its new home.

    Domain and type *are* the page's directory, so moving a note to a different
    domain or type means moving ``<domain>/<type>/<slug>/`` whole. The slug and
    the co-located assets travel with it, so ``[[wikilink]]`` references by slug
    and relative image paths keep resolving; only the page's own URL changes.

    Parameters
    ----------
    relpath : str
        The page's current relpath, ``<domain>/<type>/<slug>``.
    new_domain, new_type : str
        Destination taxonomy, both declared in taxonomy.toml.

    Returns
    -------
    Page
        The page at its new location.

    Raises
    ------
    InvalidPage
        Undeclared destination, missing source page, an unchanged destination,
        or a slug already taken under the target domain/type.
    """
    vocab = vocabulary()
    if new_domain not in vocab["domains"]:
        raise InvalidPage(f"Undeclared domain: {new_domain}")
    if new_type not in vocab["types"]:
        raise InvalidPage(f"Undeclared type: {new_type}")

    source = safe_resolve(relpath)
    if not (source / "index.md").is_file():
        raise InvalidPage("Page not found.")

    slug = source.name
    target = CONTENT_DIR / new_domain / new_type / slug
    if target == source:
        raise InvalidPage("The page already sits under this domain and type.")
    if target.exists():
        raise InvalidPage(f'A page "{slug}" already exists in {new_domain}/{new_type}.')

    # The intermediate <domain>/<type> dir need not exist yet (a domain/type
    # pair no page has used so far); make it, then move the leaf whole.
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return _page_from(target / "index.md")


def page_mtime(index_md: Path) -> float:
    """Return the page's modification time, the token the editor round-trips."""
    return index_md.stat().st_mtime


def read_source(index_md: Path) -> str:
    """Return the page's Markdown verbatim, frontmatter included."""
    return index_md.read_text(encoding="utf-8")


def save_source(index_md: Path, text: str, expected_mtime: float | None = None) -> None:
    """Overwrite a page's Markdown, refusing to clobber a concurrent edit.

    The write is atomic (temporary file in the same directory, then
    ``os.replace``) because the live-reload stream polls this file every 0.3 s
    and would otherwise be able to read it half-written.

    Parameters
    ----------
    index_md : pathlib.Path
        The page's ``index.md``.
    text : str
        Full Markdown source, frontmatter included.
    expected_mtime : float, optional
        Modification time the editor saw when it loaded the page. When given
        and no longer current, the write is refused.

    Raises
    ------
    InvalidFrontmatter
        The frontmatter block does not parse, which would break the page.
    StaleEdit
        The file changed on disk since ``expected_mtime``.
    """
    try:
        frontmatter.loads(text)
    except Exception as exc:  # yaml raises several unrelated types
        raise InvalidFrontmatter(str(exc)) from exc

    if expected_mtime is not None and index_md.exists():
        # Sub-second timestamps survive JSON as floats, but comparing them for
        # exact equality is brittle across filesystems; a millisecond of slack
        # is far below the interval a human edit takes.
        if abs(page_mtime(index_md) - expected_mtime) > 0.001:
            raise StaleEdit(str(index_md))

    fd, tmp = tempfile.mkstemp(dir=str(index_md.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, index_md)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _tag_list(raw: Any) -> list[str]:
    """Coerce a frontmatter `tags:` value into a list of strings.

    Anything that is not a YAML list (a forgotten bracket, a bare word) yields
    no tags rather than an exception: a malformed frontmatter must not take the
    page down with it.
    """
    return [str(t) for t in raw] if isinstance(raw, list) else []


def _page_from(index_md: Path, post: frontmatter.Post | None = None) -> Page:
    if post is None:
        post = frontmatter.load(index_md)
    rel = index_md.parent.relative_to(CONTENT_DIR)
    parts = rel.parts
    return Page(
        relpath=str(rel),
        domain=parts[0] if len(parts) > 0 else "",
        type=parts[1] if len(parts) > 1 else "",
        slug=parts[-1],
        title=str(post.get("title", parts[-1])),
        date=post.get("date"),
        updated=post.get("updated"),
        tags=normalize_tags(_tag_list(post.get("tags"))),
        summary=str(post.get("summary", "")),
        visibility=str(post.get("visibility", "public")).strip().lower(),
        project=str(post.get("project", "") or "").strip(),
        status=str(post.get("status", "") or "").strip().lower(),
        file=str(post.get("file", "") or "").strip(),
    )


def is_visible(page: Page) -> bool:
    """Whether *page* may be shown at all. Private pages are readable only when
    settings.SHOW_PRIVATE is on (local use); elsewhere they do not exist."""
    return settings.SHOW_PRIVATE or not page.is_private


def load_page(index_md: Path) -> Page:
    page = _page_from(index_md)
    if not is_visible(page):
        raise Http404("Page not found")
    return page


def all_pages() -> list[Page]:
    """Every *visible* page in the tree, most recently modified first (ties
    broken by title). Each is a content/<domaine>/<type>/<slug>/index.md."""
    pages = [_page_from(f) for f in CONTENT_DIR.glob(_PAGE_GLOB)]
    pages = [p for p in pages if is_visible(p)]
    pages.sort(key=lambda p: p.title)
    pages.sort(key=_recency_key, reverse=True)
    return pages


def all_tags() -> list[str]:
    """Every distinct tag across visible pages, alphabetically.

    Feeds the creation form's suggestions so an existing tag gets reused
    instead of a near-duplicate being invented.
    """
    return sorted({tag for page in all_pages() for tag in page.tags})


def backlinks(target: Page) -> list[Page]:
    """Visible pages whose body cites *target* with a [[wikilink]].

    Wikilinks are one-way in the Markdown; this walks the tree to invert them,
    so a page can show what refers to it. Matching is delegated to the
    extension's own `resolves_to`, so the two can never disagree about which
    references count.
    """
    found: list[Page] = []
    for index_md in CONTENT_DIR.glob(_PAGE_GLOB):
        post = frontmatter.load(index_md)
        source = _page_from(index_md, post)
        if source.relpath == target.relpath or not is_visible(source):
            continue
        for match in _WIKILINK.finditer(post.content):
            ref = match.group(1).strip()
            if resolves_to(ref, target.slug, target.relpath):
                found.append(source)
                break
    found.sort(key=lambda p: p.title)
    return found


# --------------------------------------------------------------------------- #
# Projects                                                                    #
# --------------------------------------------------------------------------- #
#
# A project is not a new kind of thing: it *is* an ordinary page, the one that
# introduces the dossier, and the pages that belong to it name it in their
# `project:` frontmatter. That buys the index page's title, summary and URL for
# free, and keeps the vocabulary of the site at domain / type / tag.
#
# Membership is not the same as reference. A page enters a project when it will
# be archived with it (the letters of a dispute); a durable note the project
# merely cites (an article of law, a method) stays outside and is linked with a
# [[wikilink]], so it survives the project it was written during.


def project_of(page: Page) -> Page | None:
    """The project page *page* belongs to, or None.

    The `project:` frontmatter names its index page the way a wikilink does (by
    slug, relpath or title), and resolution goes through the same predicate, so
    a reference that renders as a link cannot fail to designate a project.
    """
    if not page.project:
        return None
    for candidate in all_pages():
        if resolves_to(page.project, candidate.slug, candidate.relpath):
            return candidate
    return None


def project_members(project: Page) -> list[Page]:
    """Visible pages declaring *project* as theirs, grouped-friendly ordering.

    Sorted by type then most recent first, which is the order the project page
    lists them in: the type says what each page is for, the date says which one
    moved last.
    """
    members = [
        page
        for page in all_pages()
        if page.project
        and page.relpath != project.relpath
        and resolves_to(page.project, project.slug, project.relpath)
    ]
    members.sort(key=_recency_key, reverse=True)
    members.sort(key=lambda p: p.type)
    return members


def dossier_nav(page: Page) -> dict[str, Any] | None:
    """The dossier to show in the sidebar while *page* is open, or None.

    A page browses inside its dossier whether it is the index of one or a
    member of it, so both cases resolve to the same thing: the index page and
    everything filed under it. Returns None for a page that belongs to no
    dossier, which leaves the sidebar on the whole tree.

    Returns
    -------
    dict or None
        ``{"index": Page, "members": list[Page]}``.
    """
    own = project_members(page)
    if own:
        return {"index": page, "members": own}
    parent = project_of(page)
    if parent is None:
        return None
    return {"index": parent, "members": project_members(parent)}


def membership() -> dict[str, Page]:
    """Map each page's relpath to the project page it belongs to.

    One pass for the whole tree, because the home page needs the project of
    every card at once and resolving them one by one would walk the tree once
    per card. Pages without a project, or naming one that does not resolve, are
    simply absent.
    """
    pages = all_pages()
    resolved: dict[str, Page] = {}
    seen: dict[str, Page | None] = {}
    for page in pages:
        if not page.project:
            continue
        key = page.project.lower()
        if key not in seen:
            seen[key] = next(
                (c for c in pages if resolves_to(page.project, c.slug, c.relpath)),
                None,
            )
        target = seen[key]
        if target is not None and target.relpath != page.relpath:
            resolved[page.relpath] = target
    return resolved


def all_projects() -> list[Page]:
    """Every page at least one other page claims as its project, by title.

    Being a project is a property a page acquires from the outside, so there is
    nothing to declare: writing `project: x` in a page makes x a project.
    """
    pages = all_pages()
    refs = {page.project for page in pages if page.project}
    found = [
        page
        for page in pages
        if any(resolves_to(ref, page.slug, page.relpath) for ref in refs)
    ]
    found.sort(key=lambda p: p.title)
    return found


def facet_tags(pages: list[Page], minimum: int = TAG_FACET_MIN) -> list[str]:
    """Tags carried by at least *minimum* of *pages*, alphabetically.

    Filtering on a tag only one page carries is a link to that page dressed up
    as a facet: it costs a row of chips and finds what the search box finds
    faster. The threshold lets tags accumulate silently until they group
    something, so nothing has to be curated by hand.
    """
    counts: dict[str, int] = {}
    for page in pages:
        for tag in page.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(tag for tag, n in counts.items() if n >= minimum)


def nav_tree() -> list[dict[str, Any]]:
    """Pages grouped domaine -> type -> pages, for the sidebar navigation.
    Domaines and types are alphabetical; pages keep the recency order."""
    grouped: dict[str, dict[str, list[Page]]] = {}
    for page in all_pages():
        grouped.setdefault(page.domain, {}).setdefault(page.type, []).append(page)
    return [
        {
            "domain": domain,
            "label": label_for(domain),
            # Page count, shown next to a collapsed domain: it is the one thing
            # the sidebar cannot say once the domain is folded shut.
            "count": sum(len(pages) for pages in grouped[domain].values()),
            "types": [
                {"type": type_, "label": label_for(type_), "pages": pages}
                for type_, pages in sorted(grouped[domain].items())
            ],
        }
        for domain in sorted(grouped)
    ]


# --------------------------------------------------------------------------- #
# Selection                                                                   #
# --------------------------------------------------------------------------- #
#
# One selection, not a listing plus a search box. Facets and text narrow the
# same set, server-side, so a filtered view can be typed into and an URL says
# exactly what is on screen. Rendering the whole tree and filtering it in the
# browser could not compose the two: results replaced the list instead of
# narrowing it.


@dataclass(frozen=True)
class Selection:
    """Pages matching a query, and what the facets should offer next."""

    pages: list[Page]
    snippets: dict[str, str]  # relpath -> highlighted excerpt, when text was used
    total: int  # before the display cap
    facets: dict[str, list[tuple[str, int]]]  # facet -> [(value, count)]

    @property
    def is_visual(self) -> bool:
        """Whether every page can show a thumbnail, so a grid makes sense."""
        return bool(self.pages) and all(p.is_visual for p in self.pages)


# Which facet each argument of `select` filters on, so a facet's own values can
# be counted against everything *except* itself.
_FACET_FIELDS = {
    "domains": "domain",
    "types": "type",
    "kinds": "kind",
    "statuses": "status",
    "projects": "project",
    "tags": "tag",
}


def _value_of(page: Page, facet: str, membership_map: dict[str, Page]) -> list[str]:
    """The values *page* holds for *facet* (a list, because of tags)."""
    if facet == "domain":
        return [page.domain]
    if facet == "type":
        return [page.type]
    if facet == "kind":
        return [page.kind]
    if facet == "status":
        return [page.status] if page.status else []
    if facet == "project":
        dossier = membership_map.get(page.relpath)
        return [dossier.slug] if dossier is not None else []
    return page.tags


def _facet_values(
    pages: list[Page],
    facet: str,
    active: Sequence[str],
    membership_map: dict[str, Page],
) -> list[tuple[str, int]]:
    """Count *facet* over *pages*, keeping what is worth offering.

    Two rules, and the second exists because the first alone made the explorer
    a one-way door. A value that would leave the selection unchanged is chrome,
    so it is dropped; but a value that is *active* always stays, otherwise
    picking a domain removes the very chip needed to unpick it.
    """
    counts: dict[str, int] = {}
    for page in pages:
        for value in _value_of(page, facet, membership_map):
            counts[value] = counts.get(value, 0) + 1

    if facet == "tag":
        counts = {v: n for v, n in counts.items() if n >= TAG_FACET_MIN or v in active}
    if len(counts) < 2:
        # Nothing to divide. Keep the active values so they can be undone.
        counts = {v: n for v, n in counts.items() if v in active}
    return sorted(counts.items())


def _matches(
    page: Page, facet: str, values: Sequence[str], membership_map: dict[str, Page]
) -> bool:
    """Whether *page* satisfies *values* for *facet* (empty means no constraint)."""
    if not values:
        return True
    held = _value_of(page, facet, membership_map)
    if facet == "tag":
        # Tags are AND'd with each other: adding one always narrows.
        return all(v in held for v in values)
    return any(v in held for v in values)


def select(
    *,
    query: str = "",
    domains: Sequence[str] = (),
    types: Sequence[str] = (),
    kinds: Sequence[str] = (),
    statuses: Sequence[str] = (),
    projects: Sequence[str] = (),
    tags: Sequence[str] = (),
    limit: int | None = None,
) -> Selection:
    """Resolve facets and text together into one set of pages.

    Values inside a facet are OR'd (two domains widen), facets are AND'd, and
    tags are AND'd with each other: picking two tags asks for pages carrying
    both, which is what a reader means when they keep adding words.
    """
    membership_map = membership()

    if query.strip():
        hits = search(query)
        pages = [hit.page for hit in hits]
        snippets = {hit.page.relpath: hit.snippet for hit in hits}
    else:
        pages = all_pages()
        snippets = {}

    wanted_tags = [_normalize_tag(t) for t in tags if t.strip()]

    kept = [
        page
        for page in pages
        if all(
            _matches(page, facet, values, membership_map)
            for facet, values in {
                "domain": domains,
                "type": types,
                "kind": kinds,
                "status": statuses,
                "project": projects,
                "tag": wanted_tags,
            }.items()
        )
    ]

    # Each facet is counted against the selection narrowed by *every other*
    # facet, never by itself. Counting on the final selection would show a
    # domain its own count of one and hide every alternative, which is how a
    # faceted search stops being able to widen.
    chosen = {
        "domain": domains,
        "type": types,
        "kind": kinds,
        "status": statuses,
        "project": projects,
        "tag": wanted_tags,
    }
    facets = {}
    for facet, active in chosen.items():
        others = [
            page
            for page in pages
            if all(
                _matches(page, other, values, membership_map)
                for other, values in chosen.items()
                if other != facet
            )
        ]
        facets[facet] = _facet_values(others, facet, active, membership_map)

    total = len(kept)
    if limit is not None and limit > 0:
        kept = kept[:limit]
    return Selection(pages=kept, snippets=snippets, total=total, facets=facets)


def thumbnail_path(source: Path, width: int = 320) -> Path | None:
    """Render the first page of *source* to a cached JPEG; None if impossible.

    Cached outside the notes repository, keyed on the file's mtime and size:
    a thumbnail is derived data, and derived data has no business being
    committed next to the document it came from.
    """
    stat = source.stat()
    key = hashlib.sha256(
        f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{width}".encode()
    ).hexdigest()[:32]
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    cached = root / "avallon" / "thumbs" / f"{key}.jpg"
    if cached.is_file():
        return cached

    cached.parent.mkdir(parents=True, exist_ok=True)
    stem = cached.with_suffix("")
    try:
        subprocess.run(
            [
                "pdftoppm",
                "-jpeg",
                "-scale-to",
                str(width),
                "-f",
                "1",
                "-l",
                "1",
                str(source),
                str(stem),
            ],
            capture_output=True,
            timeout=15,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None  # poppler missing, or a PDF it cannot read
    # pdftoppm appends the page number to the prefix it was given.
    produced = next(stem.parent.glob(f"{stem.name}-*.jpg"), None)
    if produced is None:
        return None
    produced.replace(cached)
    return cached


# --- Full-text search ------------------------------------------------------


def _build_fold_table() -> dict[int, str]:
    """Map each accented or upper-case character to its folded equivalent.

    Only one-to-one entries are kept, so folding can never change the length of
    a string. That is what lets the highlighter use the same indices on the
    folded and the original text, instead of carrying a map between them.
    """
    table: dict[int, str] = {}
    for code in range(ord("A"), 0x2100):
        char = chr(code)
        stripped = "".join(
            c
            for c in unicodedata.normalize("NFD", char)
            if not unicodedata.combining(c)
        )
        base = stripped.lower()
        if len(base) == 1 and base != char:
            table[code] = base
    return table


# Built once at import: ~840 entries, covering Latin-1 and Latin Extended.
_FOLD_TABLE = _build_fold_table()


def _fold_text(text: str) -> str:
    """Lower-case *text* and strip its diacritics, preserving its length.

    So a query typed without accents still matches ("systeme" finds "système").
    ``str.translate`` runs in C over the whole string; the previous version
    normalized one character at a time and accounted for 96% of a search.
    """
    return text.translate(_FOLD_TABLE)


def _term_pattern(terms: list[str]) -> re.Pattern[str] | None:
    """Compile the folded *terms* into one alternation, longest first so that
    overlapping terms mark the widest span at each position."""
    folded = sorted({_fold_text(t) for t in terms if t.strip()}, key=len, reverse=True)
    if not folded:
        return None
    return re.compile("|".join(re.escape(t) for t in folded))


def _highlight(
    text: str, terms: list[str], width: int = 220, folded: str | None = None
) -> str:
    """Return a safe-HTML excerpt of *text* centered on the first matched term,
    with every occurrence of every term wrapped in <mark>. Matching ignores case
    and accents; the excerpt itself keeps the original spelling.

    *folded* is the already-folded text when the caller has it, which it does:
    it just tested the terms against it. Folding preserves length, so a match
    found there indexes the original directly.
    """
    pattern = _term_pattern(terms)
    if folded is None:
        folded = _fold_text(text)

    spans: list[tuple[int, int]] = []
    if pattern is not None:
        spans = [(m.start(), m.end()) for m in pattern.finditer(folded)]

    if spans:
        start = max(0, spans[0][0] - width // 3)
    else:
        start = 0
    end = min(len(text), start + width)

    out: list[str] = []
    cursor = start
    for s, e in spans:
        if e <= start or s >= end:
            continue
        s, e = max(s, start), min(e, end)
        out.append(html.escape(text[cursor:s]))
        out.append(f"<mark>{html.escape(text[s:e])}</mark>")
        cursor = e
    out.append(html.escape(text[cursor:end]))

    body = "".join(out).strip()
    return ("… " if start > 0 else "") + body + (" …" if end < len(text) else "")


# Rough Markdown -> plain text, so snippets read cleanly instead of showing
# raw syntax. Code *content* is kept (only the ``` fences are dropped) so it
# stays searchable; image/link targets collapse to their alt/link text.
_MD_STRIP = [
    (re.compile(r"^ *```.*$", re.MULTILINE), ""),  # code-fence lines
    (re.compile(r"\[\[[^\]|]+\|([^\]]+)\]\]"), r"\1"),  # [[slug|label]] -> label
    (re.compile(r"\[\[([^\]|]+)\]\]"), r"\1"),  # [[slug]]       -> slug
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),  # image  -> alt text
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),  # link   -> link text
    (re.compile(r"[`*_~>#|]+"), " "),  # residual inline/table syntax
]


def _plain_text(markdown: str) -> str:
    text = markdown
    for pattern, repl in _MD_STRIP:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()


def _hit_for(index_md: Path, terms: list[str]) -> SearchHit | None:
    """Build a SearchHit for *index_md*, or None unless *every* term is present
    in the readable text (AND semantics). The snippet is always drawn from the
    Markdown body turned into plain text (plus the searchable metadata), so it
    never leaks raw syntax or frontmatter into the results."""
    post = frontmatter.load(index_md)
    page = _page_from(index_md, post)
    if not is_visible(page):
        return None
    blob = "\n".join(
        [_plain_text(post.content), page.title, page.summary, " ".join(page.tags)]
    )
    folded = _fold_text(blob)
    if not all(_fold_text(t) in folded for t in terms):
        return None
    return SearchHit(page=page, snippet=_highlight(blob, terms, folded=folded))


def _search_python(terms: list[str]) -> list[SearchHit]:
    """Dependency-free fallback used when ripgrep is unavailable."""
    hits = []
    for index_md in sorted(CONTENT_DIR.glob(_PAGE_GLOB)):
        hit = _hit_for(index_md, terms)
        if hit is not None:
            hits.append(hit)
    _sort_hits(hits)
    return hits


# Accented spellings each unaccented letter must also match, so the ripgrep
# shortlist stays accent-insensitive like the Python check that follows it.
_ACCENTS = {
    "a": "àáâãäå",
    "c": "ç",
    "e": "èéêë",
    "i": "ìíîï",
    "n": "ñ",
    "o": "òóôõö",
    "u": "ùúûü",
    "y": "ýÿ",
}


def _rg_pattern(term: str) -> str:
    """Turn a folded *term* into a regex where every letter also matches its
    accented forms, e.g. "systeme" -> "s[yýÿ]st[eèéêë]m[eèéêë]"."""
    out = []
    for char in term:
        variants = _ACCENTS.get(char)
        out.append(f"[{char}{variants}]" if variants else re.escape(char))
    return "".join(out)


def search(query: str) -> list[SearchHit]:
    """Full-text search over the content tree. Uses ripgrep for speed and
    falls back to a pure-Python scan if rg is missing or errors out."""
    terms = query.split()
    if not terms:
        return []
    # rg shortlists on the first term (any single term is a necessary condition
    # for the AND); _hit_for then enforces that *all* terms are present and
    # builds the snippet. Both run against the cleaned, accent-folded text.
    try:
        proc = subprocess.run(
            [
                "rg",
                "-l",
                "-i",
                # Before the `--`: everything after it is a path, so a --glob
                # placed there was read as a file to open, rg exited 2, and the
                # pure-Python scan silently ran for every single search.
                "--glob",
                "*.md",
                "--",
                _rg_pattern(_fold_text(terms[0])),
                str(CONTENT_DIR),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return _search_python(terms)
    # rg exit codes: 0 = matches, 1 = no matches, >=2 = real error.
    if proc.returncode >= 2:
        return _search_python(terms)

    hits = []
    for line in proc.stdout.splitlines():
        path = Path(line)
        try:
            rel = path.parent.relative_to(CONTENT_DIR)
        except ValueError:
            continue
        if len(rel.parts) != 3 or path.name != "index.md":
            continue  # ignore anything outside the <domaine>/<type>/<slug> shape
        hit = _hit_for(path, terms)
        if hit is not None:
            hits.append(hit)
    _sort_hits(hits)
    return hits
