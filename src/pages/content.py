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
import html
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter
from django.conf import settings
from django.http import Http404
from markdownify.templatetags.markdownify import markdownify

from .mdx.wikilinks import WIKILINK_RE

CONTENT_DIR: Path = settings.CONTENT_DIR

# Same pattern the Markdown extension uses, so backlinks and rendered links
# can never disagree about what counts as a reference.
_WIKILINK = re.compile(WIKILINK_RE)

# Glob matching every page: content/<domaine>/<type>/<slug>/index.md.
_PAGE_GLOB = "*/*/*/index.md"


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

    relpath: str          # "travail/cr/reunion-hygeos"
    domain: str           # from the path: <domaine>/...
    type: str             # from the path: .../<type>/...
    slug: str             # the leaf directory name
    title: str
    date: Any | None      # creation date (frontmatter, set once)
    updated: Any | None   # last-modified date (frontmatter, stamped on commit)
    tags: list[str]
    summary: str
    visibility: str       # "public" (default) or "private"

    @property
    def url(self) -> str:
        return f"/{self.relpath}/"

    @property
    def is_private(self) -> bool:
        return self.visibility == "private"

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


def _sort_hits(hits: list["SearchHit"]) -> None:
    """Order search hits like the home page: most recent first, then by title."""
    hits.sort(key=lambda h: h.page.title)
    hits.sort(key=lambda h: _recency_key(h.page), reverse=True)


@dataclass(frozen=True)
class SearchHit:
    """A page matched by a full-text query, with a highlighted excerpt."""

    page: Page
    snippet: str          # safe HTML, matched terms wrapped in <mark>


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
    rule `pixi run new` enforces: a page cannot be born under an undeclared
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
        raise Http404("Chemin hors du contenu")
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
        # The label is a display name ("Python"); its first word, lowercased,
        # is a good Pandoc/skylighting language id ("python"). Unknown ids just
        # yield an un-highlighted (still monospace) block, so this is safe.
        lang = label.group("name").strip().split()[0].lower() if label else ""
        cls = f' class="{html.escape(lang)}"' if lang else ""
        return f"<pre><code{cls}>{html.escape(text)}</code></pre>"

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
    domain: str, type_: str, title: str, tags: list[str], summary: str = ""
) -> Page:
    """Scaffold ``<domain>/<type>/<slug>/index.md`` and return the new Page.

    The slug and the frontmatter come from ``scripts/new_page.py`` rather than
    from a second implementation here: the browser and ``pixi run new`` must
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
    from new_page import scalar, slugify

    vocab = vocabulary()
    if domain not in vocab["domains"]:
        raise InvalidPage(f"Domaine non déclaré : {domain}")
    if type_ not in vocab["types"]:
        raise InvalidPage(f"Type non déclaré : {type_}")
    if not title.strip():
        raise InvalidPage("Le titre est obligatoire.")

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
        raise InvalidPage(f"Domaine non déclaré : {new_domain}")
    if new_type not in vocab["types"]:
        raise InvalidPage(f"Type non déclaré : {new_type}")

    source = safe_resolve(relpath)
    if not (source / "index.md").is_file():
        raise InvalidPage("Page introuvable.")

    slug = source.name
    target = CONTENT_DIR / new_domain / new_type / slug
    if target == source:
        raise InvalidPage("La note est déjà dans ce domaine et ce type.")
    if target.exists():
        raise InvalidPage(
            f"Une note « {slug} » existe déjà dans {new_domain}/{new_type}."
        )

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


def save_source(
    index_md: Path, text: str, expected_mtime: float | None = None
) -> None:
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
        tags=normalize_tags([str(t) for t in (post.get("tags") or [])]),
        summary=str(post.get("summary", "")),
        visibility=str(post.get("visibility", "public")).strip().lower(),
    )


def is_visible(page: Page) -> bool:
    """Whether *page* may be shown at all. Private pages are readable only when
    settings.SHOW_PRIVATE is on (local use); elsewhere they do not exist."""
    return settings.SHOW_PRIVATE or not page.is_private


def load_page(index_md: Path) -> Page:
    page = _page_from(index_md)
    if not is_visible(page):
        raise Http404("Page introuvable")
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
    so a page can show what refers to it. Matching follows the same rule as the
    extension itself: the reference is either the slug or the full relpath.
    """
    found: list[Page] = []
    for index_md in CONTENT_DIR.glob(_PAGE_GLOB):
        post = frontmatter.load(index_md)
        source = _page_from(index_md, post)
        if source.relpath == target.relpath or not is_visible(source):
            continue
        for match in _WIKILINK.finditer(post.content):
            ref = match.group(1).strip()
            if ref in (target.slug, target.relpath):
                found.append(source)
                break
    found.sort(key=lambda p: p.title)
    return found


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


# --- Full-text search ------------------------------------------------------

def _fold(text: str) -> tuple[str, list[int]]:
    """Lowercase *text* and strip its diacritics, so a query typed without
    accents still matches ("systeme" finds "système").

    Returns the folded text together with a map from each folded character back
    to the index of the character it came from in *text*. Folding can change the
    length (one source character may fold to zero or several), so highlighting
    needs that map to place its <mark> tags on the original string.
    """
    folded: list[str] = []
    origin: list[int] = []
    for i, char in enumerate(text):
        decomposed = unicodedata.normalize("NFD", char)
        base = "".join(c for c in decomposed if not unicodedata.combining(c))
        piece = base.lower()
        folded.append(piece)
        origin.extend([i] * len(piece))
    return "".join(folded), origin


def _fold_text(text: str) -> str:
    """The folded form of *text*, without the index map."""
    return _fold(text)[0]


def _term_pattern(terms: list[str]) -> re.Pattern[str] | None:
    """Compile the folded *terms* into one alternation, longest first so that
    overlapping terms mark the widest span at each position."""
    folded = sorted({_fold_text(t) for t in terms if t.strip()}, key=len, reverse=True)
    if not folded:
        return None
    return re.compile("|".join(re.escape(t) for t in folded))


def _highlight(text: str, terms: list[str], width: int = 220) -> str:
    """Return a safe-HTML excerpt of *text* centered on the first matched term,
    with every occurrence of every term wrapped in <mark>. Matching ignores case
    and accents; the excerpt itself keeps the original spelling."""
    pattern = _term_pattern(terms)
    folded, origin = _fold(text)

    # Matches are found on the folded text, then mapped back to spans of the
    # original so the excerpt reads normally.
    spans: list[tuple[int, int]] = []
    if pattern is not None:
        for m in pattern.finditer(folded):
            if m.start() >= len(origin):
                continue
            spans.append((origin[m.start()], origin[m.end() - 1] + 1))

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
    (re.compile(r"^ *```.*$", re.MULTILINE), ""),    # code-fence lines
    (re.compile(r"\[\[[^\]|]+\|([^\]]+)\]\]"), r"\1"),  # [[slug|label]] -> label
    (re.compile(r"\[\[([^\]|]+)\]\]"), r"\1"),          # [[slug]]       -> slug
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),  # image  -> alt text
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),   # link   -> link text
    (re.compile(r"[`*_~>#|]+"), " "),                # residual inline/table syntax
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
    return SearchHit(page=page, snippet=_highlight(blob, terms))


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
    "a": "àáâãäå", "c": "ç", "e": "èéêë", "i": "ìíîï", "n": "ñ",
    "o": "òóôõö", "u": "ùúûü", "y": "ýÿ",
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
                "rg", "-l", "-i", "--",
                _rg_pattern(_fold_text(terms[0])), str(CONTENT_DIR), "--glob", "*.md",
            ],
            capture_output=True, text=True, timeout=10,
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
