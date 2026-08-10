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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import frontmatter
from django.conf import settings
from django.http import Http404
from markdownify.templatetags.markdownify import markdownify

from .mdx.wikilinks import WIKILINK_RE, resolve_among

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
    aliases: list[str]  # names this page used to answer to

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


def _sort_hits(hits: list[SearchHit], query: str = "") -> None:
    """Order hits: exact runs of the query first, then most recent, then title.

    Someone typing several words often remembers a sentence. Requiring the run
    would be wrong (adding a word usually means narrowing, not quoting), and
    ignoring it entirely buries the page they were thinking of, so it ranks
    instead of filtering. Quotes remain the way to *require* it.
    """
    hits.sort(key=lambda h: h.page.title)
    hits.sort(key=lambda h: _recency_key(h.page), reverse=True)

    run = _fold_text(" ".join(query.replace('"', " ").split()))
    if " " in run:
        hits.sort(key=lambda h: run not in _fold_text(h.blob))


@dataclass(frozen=True)
class SearchHit:
    """A page matched by a full-text query, with a highlighted excerpt."""

    page: Page
    snippet: str  # safe HTML, matched terms wrapped in <mark>
    blob: str = ""  # the readable text it matched, kept for ranking


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


def render_markdown_text(text: str, index_md: Path) -> str:
    """Render *text* as if it were the body of *index_md*.

    The path still matters: it is what relative images and co-located files
    resolve against, so an old revision renders with the same rules as the
    current one.
    """
    post = frontmatter.loads(text)
    token = _render_dir.set(index_md.parent)
    try:
        return str(markdownify(_LEADING_H1.sub("", post.content, count=1)))
    finally:
        _render_dir.reset(token)


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


# A file bigger than this bloats the repository forever: git keeps every
# version of a binary, so a deleted 50 Mo scan still weighs 50 Mo in the
# history. Same limit as `avallon add-file`, for the same reason.
UPLOAD_LIMIT = 20 * 1024 * 1024


class RejectedUpload(Exception):
    """The submitted file cannot become a document."""


def safe_filename(name: str) -> str:
    """A filename derived from *name* that can only land where intended.

    The stem goes through the same slugifier as a title, so a name carrying
    slashes, dots or spaces comes out as one harmless segment. The extension is
    kept only when `KIND_BY_EXTENSION` knows it, which is both what decides how
    the document is displayed and, as it happens, the allowlist: an `.html` or
    a `.js` is not a kind, so it never reaches a directory this site serves.

    Raises
    ------
    RejectedUpload
        The extension is missing or not one this site can hold.
    """
    from avallon.notes.scaffold import slugify

    suffix = Path(name).suffix.lstrip(".").lower()
    if suffix not in KIND_BY_EXTENSION:
        known = ", ".join(sorted(KIND_BY_EXTENSION))
        raise RejectedUpload(
            f'Unsupported file type: "{Path(name).name}". Accepted: {known}.'
        )
    stem = slugify(Path(name).stem)
    return f"{stem}.{suffix}"


def create_document(
    domain: str,
    type_: str,
    title: str,
    filename: str,
    data: bytes,
    tags: list[str] | None = None,
    summary: str = "",
    project: str = "",
    doc_date: str = "",
) -> Page:
    """Create a page holding *data* as its document, and return it.

    A document is not a new kind of thing, it is a page with a `file:`. That is
    what makes it findable, taggable, datable and part of a dossier like any
    other, and what lets `![[slug]]` show it inside a note while the file stays
    in one place.

    The page is written first and removed again if the bytes cannot be stored,
    so a failure leaves nothing behind rather than a page pointing at a file
    that is not there.
    """
    if len(data) > UPLOAD_LIMIT:
        raise RejectedUpload(
            f"File too large: {len(data) / 1e6:.1f} Mo, limit "
            f"{UPLOAD_LIMIT // 10**6} Mo. Git keeps every version of a binary "
            "for good, so a big file is paid for forever."
        )
    if not data:
        raise RejectedUpload("Empty file.")

    name = safe_filename(filename)
    page = create_page(
        domain,
        type_,
        title or Path(filename).stem,
        tags or [],
        summary=summary,
        project=project,
        file=name,
        doc_date=doc_date,
    )
    directory = CONTENT_DIR / page.relpath
    try:
        (directory / name).write_bytes(data)
    except OSError:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return page


TEXT_PREVIEW_LINES = 400


def attached_text(page: Page) -> str:
    """The attached file's text when it is one, else an empty string.

    Only for `kind == "text"`. Anything that needs software to be read (an
    office document) is a download, and anything the browser renders natively
    (an image, a pdf) is already shown as itself.
    """
    if page.kind != "text" or not page.file:
        return ""
    target = CONTENT_DIR / page.relpath / page.file
    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = raw.splitlines()
    if len(lines) > TEXT_PREVIEW_LINES:
        lines = [*lines[:TEXT_PREVIEW_LINES], "…"]
    return "\n".join(lines)


def page_named(name: str, exclude: str = "") -> Page | None:
    """The page that bears *name* right now, ignoring *exclude*'s relpath.

    A name is either taken or freed. A **current** name (a slug, a relpath, or
    a title that slugifies to one) belongs to exactly one page, and handing it
    to a second would make every `[[name]]` in the tree ambiguous. A **former**
    name is free: its page kept it as an alias only so old links keep landing,
    and `resolve_among` gives a new bearer priority over it.

    So this is what creation and renaming must refuse on, and nothing else.
    """
    from .mdx.wikilinks import matches_current

    # Every page on disk, not `all_pages()`: a private page holds its name just
    # as firmly, and would collide the moment private pages are shown.
    for index_md in CONTENT_DIR.glob(_PAGE_GLOB):
        page = _page_from(index_md)
        if page.relpath != exclude and matches_current(name, page.slug, page.relpath):
            return page
    return None


def create_page(
    domain: str,
    type_: str,
    title: str,
    tags: list[str],
    summary: str = "",
    project: str = "",
    file: str = "",
    doc_date: str = "",
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

    slug = slugify(title)
    taken = page_named(slug)
    if taken is not None:
        raise InvalidPage(
            f'A page already goes by "{slug}": {taken.relpath}. '
            "Choose another title, or rename that page first."
        )

    base = CONTENT_DIR / domain / type_
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
    if file.strip():
        lines.append(f"file: {scalar(file.strip())}")
    if doc_date.strip():
        # The date *of the document* (issued, signed, received), which is what
        # one looks for later; `date` stays the filing date.
        lines.append(f"doc_date: {scalar(doc_date.strip())}")
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


_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_ALIASES_LINE = re.compile(r"^aliases:\s*\[(.*)\]\s*$", re.M)
_TITLE_LINE = re.compile(r"^title:\s*(.+?)\s*$", re.M)


def _yaml_scalar(value: str) -> str:
    """Quote *value* only when it could be misread unquoted."""
    return value if not re.search(r"""[:#\[\]{},"']""", value) else f'"{value}"'


def add_alias(text: str, alias: str) -> str:
    """Return *text* with *alias* added to its frontmatter ``aliases:``.

    Edited as text, not through a YAML round-trip: the frontmatter is written
    by hand and a dump would reorder its keys and requote its values, turning
    every title change into a diff nobody asked for.
    """
    match = _FRONTMATTER.match(text)
    if not match or not alias.strip():
        return text
    block = match.group(1)

    existing = _ALIASES_LINE.search(block)
    if existing:
        current = [a.strip().strip("\"'") for a in existing.group(1).split(",")]
        if alias in current:
            return text
        values = [a for a in current if a] + [alias]
        line = "aliases: [" + ", ".join(_yaml_scalar(v) for v in values) + "]"
        new_block = block[: existing.start()] + line + block[existing.end() :]
    else:
        # After the title, where a reader expects the names of the page.
        title = _TITLE_LINE.search(block)
        line = f"aliases: [{_yaml_scalar(alias)}]"
        if title:
            new_block = block[: title.end()] + "\n" + line + block[title.end() :]
        else:
            new_block = block + "\n" + line
    return text[: match.start(1)] + new_block + text[match.end(1) :]


def title_of(text: str) -> str:
    """The title declared in *text*'s frontmatter, or ""."""
    match = _FRONTMATTER.match(text)
    if not match:
        return ""
    found = _TITLE_LINE.search(match.group(1))
    return found.group(1).strip().strip("\"'") if found else ""


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
        aliases=[a for a in _tag_list(post.get("aliases")) if a.strip()],
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


def tag_counts() -> list[tuple[str, int]]:
    """Every tag with how many visible pages carry it, most used first.

    Ties break alphabetically, so the list is stable between two reads and two
    tags of equal weight sit next to each other, which is exactly where a near
    duplicate ("batterie" and "batteries") becomes visible.
    """
    counts: dict[str, int] = {}
    for page in all_pages():
        for tag in page.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def dossier_candidates() -> list[Page]:
    """Pages that are not dossiers yet but could become one, by title.

    Being a dossier is not declared: a page acquires it when another page names
    it in `project:`. So every page is a candidate, and offering them is what
    makes a *first* dossier possible without editing frontmatter by hand.
    """
    already = {page.relpath for page in all_projects()}
    return sorted(
        (page for page in all_pages() if page.relpath not in already),
        key=lambda p: p.title,
    )


def backlinks(target: Page) -> list[Page]:
    """Visible pages whose body cites *target* with a [[wikilink]].

    Wikilinks are one-way in the Markdown; this walks the tree to invert them,
    so a page can show what refers to it.

    A reference is resolved against the whole tree, exactly as the renderer
    resolves it, rather than merely tested against this page: a link that
    *renders* as pointing elsewhere must not show up here as a backlink. Asking
    only "does this ref match me" was enough while a name designated one page,
    and stopped being enough once a freed name could be claimed by a new page
    while the old one kept it as an alias.
    """
    # One walk, used twice: the bodies to find the references, and the pages
    # themselves as the set to resolve them against. Calling `all_pages()` here
    # instead would parse every file a second time, which measured 2.4x on this
    # path, and it runs on every page view.
    walked = []
    for index_md in CONTENT_DIR.glob(_PAGE_GLOB):
        post = frontmatter.load(index_md)
        source = _page_from(index_md, post)
        if is_visible(source):
            walked.append((source, post.content))
    candidates = [source for source, _ in walked]

    resolved: dict[str, str | None] = {}  # ref -> relpath, refs repeat a lot
    found: list[Page] = []
    for source, body in walked:
        if source.relpath == target.relpath:
            continue
        for match in _WIKILINK.finditer(body):
            ref = match.group(1).strip()
            if ref not in resolved:
                page = resolve_among(ref, candidates)
                resolved[ref] = page.relpath if page else None
            if resolved[ref] == target.relpath:
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
    return resolve_among(page.project, all_pages())


def project_members(project: Page) -> list[Page]:
    """Visible pages declaring *project* as theirs, grouped-friendly ordering.

    Sorted by type then most recent first, which is the order the project page
    lists them in: the type says what each page is for, the date says which one
    moved last.
    """
    candidates = all_pages()
    resolved: dict[str, str | None] = {}
    members = []
    for page in candidates:
        if not page.project or page.relpath == project.relpath:
            continue
        if page.project not in resolved:
            named = resolve_among(page.project, candidates)
            resolved[page.project] = named.relpath if named else None
        if resolved[page.project] == project.relpath:
            members.append(page)
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
            seen[key] = resolve_among(page.project, pages)
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
    named = {
        page.relpath
        for page in (
            resolve_among(ref, pages) for ref in {p.project for p in pages if p.project}
        )
        if page is not None
    }
    found = [page for page in pages if page.relpath in named]
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
# History                                                                     #
# --------------------------------------------------------------------------- #
#
# Read from git on demand, never recorded. `--follow` reconstructs renames and
# relocations by similarity, so a page moved between domains keeps one
# continuous story without anything being written when it moved.


# Commits closer together than this, on the same page, read as one editing
# session rather than as distinct states. Fixing a typo three times in an hour
# is one modification to whoever opens the menu.
MERGE_WINDOW = 3600  # 1 hour
MERGE_WINDOW_ENV = "AVALLON_HISTORY_WINDOW"

# How far back to look before folding. A burst can be long, and folding only
# what a first `-5` returned would show fewer than five states.
_SCAN_FACTOR = 20
_SCAN_CAP = 200


def merge_window() -> int:
    """The seconds under which two commits on a page fold into one state."""
    raw = os.environ.get(MERGE_WINDOW_ENV)
    if raw is None:
        return MERGE_WINDOW
    try:
        return max(0, int(raw))
    except ValueError:
        return MERGE_WINDOW


@dataclass(frozen=True)
class Revision:
    """One recorded state of a page.

    Possibly several commits: *saves* says how many folded into it, and *sha*
    is the last of them, so opening it gives the state the session ended on.
    """

    sha: str
    when: str  # YYYY/MM/DD-hh:mm, the form the menu shows
    subject: str
    saves: int = 1


def _git(args: list[str], root: Path | None = None) -> subprocess.CompletedProcess:
    """Run git inside the notes repository."""
    return subprocess.run(
        ["git", "-C", str(root or CONTENT_DIR), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def history(relpath: str, limit: int = 5) -> list[Revision]:
    """The last recorded states of a page, most recent first.

    Empty when the notes are not a git repository, or the page was never
    committed: both are ordinary, and neither is an error worth showing.
    """
    limit = max(1, limit)
    target = f"{relpath.strip('/')}/index.md"
    try:
        out = _git(
            [
                "log",
                f"-{min(limit * _SCAN_FACTOR, _SCAN_CAP)}",
                "--follow",
                "--format=%h\t%at\t%ad\t%s",
                # -local, not the offset each commit recorded: notes are
                # written from several machines, and a state committed from a
                # server in UTC must not read as two hours before one written
                # here at the same moment.
                "--date=format-local:%Y/%m/%d-%H:%M",
                "--",
                target,
            ]
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []

    commits = []
    for line in out.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4 and parts[1].isdigit():
            commits.append((int(parts[1]), Revision(parts[0], parts[2], parts[3])))
    return _fold_bursts(commits, merge_window())[:limit]


def _fold_bursts(commits: list[tuple[int, Revision]], window: int) -> list[Revision]:
    """Collapse commits less than *window* apart into one state each.

    *commits* comes newest first, each paired with its unix time. The first of
    a burst is therefore its end, which is the state worth opening: nobody
    wants the page as it was three saves into a session of fixing typos.

    The gap is measured against the previous commit, not against the start of
    the burst, so an afternoon of steady editing reads as one session rather
    than as one state per hour.
    """
    folded: list[Revision] = []
    previous = 0
    for when, revision in commits:
        if folded and window and previous - when < window:
            head = folded[-1]
            folded[-1] = replace(head, saves=head.saves + 1)
        else:
            folded.append(revision)
        previous = when
    return folded


def at_revision(relpath: str, sha: str, name: str = "index.md") -> bytes | None:
    """The bytes of a page's file as of *sha*, or None if it did not exist.

    Used for the markdown and for its images alike: a state of the page shown
    with today's pictures would be a mix of two dates, and this site holds
    evidence.
    """
    if not re.fullmatch(r"[0-9a-f]{4,40}", sha):
        return None  # a revision is a hash, never a path
    target = f"{relpath.strip('/')}/{name}"
    try:
        out = subprocess.run(
            ["git", "-C", str(CONTENT_DIR), "show", f"{sha}:{target}"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def is_dirty(relpath: str) -> bool:
    """Whether the page has changes git has not recorded yet.

    The label must not claim a page is at its last commit when the working tree
    is ahead of it.
    """
    target = f"{relpath.strip('/')}/index.md"
    try:
        out = _git(["status", "--porcelain", "--", target])
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


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
    # Typography a keyboard cannot easily type, mapped to what it does type.
    # A note pasted from a website carries curly quotes; a search box does not.
    table: dict[int, str] = {
        0x2018: "'",
        0x2019: "'",
        0x201A: "'",
        0x201B: "'",  # curly single
        0x201C: '"',
        0x201D: '"',
        0x201E: '"',  # curly double
        0x00AB: '"',
        0x00BB: '"',  # guillemets
        0x2013: "-",
        0x2014: "-",
        0x2212: "-",  # dashes
        0x00A0: " ",
        0x202F: " ",
        0x2009: " ",  # hard spaces
    }
    for code in range(ord("A"), 0x2100):
        char = chr(code)
        stripped = "".join(
            c
            for c in unicodedata.normalize("NFD", char)
            if not unicodedata.combining(c)
        )
        base = stripped.lower()
        if len(base) == 1 and base != char and code not in table:
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
    return SearchHit(
        page=page, snippet=_highlight(blob, terms, folded=folded), blob=blob
    )


def _search_python(terms: list[str], query: str = "") -> list[SearchHit]:
    """Dependency-free fallback used when ripgrep is unavailable."""
    hits = []
    for index_md in sorted(CONTENT_DIR.glob(_PAGE_GLOB)):
        hit = _hit_for(index_md, terms)
        if hit is not None:
            hits.append(hit)
    _sort_hits(hits, query)
    return hits


# Spellings each typed character must also match, so the ripgrep shortlist stays
# as forgiving as the Python check that follows it. rg reads the file as it is
# written, while the check runs on folded text, so anything the fold flattens
# has to be widened back here or the shortlist drops files the check would keep.
_EQUIVALENTS = {
    "'": "'\u2018\u2019\u201a\u201b",
    '"': '"\u201c\u201d\u201e\u00ab\u00bb',
    "-": "-\u2013\u2014\u2212",
}

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
        variants = _ACCENTS.get(char) or _EQUIVALENTS.get(char)
        if variants:
            # The typed character itself belongs in the class: _ACCENTS lists
            # only the accented spellings.
            out.append(f"[{re.escape(char + variants)}]")
        elif char == " ":
            # A phrase can be broken by a line wrap in the file even though the
            # flattened text reads as one line.
            out.append(r"\s+")
        else:
            out.append(re.escape(char))
    return "".join(out)


_QUOTED = re.compile(r'"([^"]+)"')


def parse_query(query: str) -> list[str]:
    """Split *query* into terms, keeping quoted runs whole.

    ``jardin "je m'appelle kevin"`` is two terms: a word, and a phrase that must
    appear as written. Without quotes the words are independent, which is what
    someone means when they add a word to narrow a search; with them they are a
    sequence, which is what someone means when they remember a sentence.
    """
    phrases = [m.group(1).strip() for m in _QUOTED.finditer(query)]
    phrases = [p for p in phrases if p]
    rest = _QUOTED.sub(" ", query)
    return phrases + rest.split()


def _shortlist_term(terms: list[str]) -> str:
    """The term to hand ripgrep: the longest *word* in the query.

    A phrase cannot be used as-is: the page's text is flattened before matching
    (a phrase may span two lines in the file), while rg reads the file itself.
    So the shortlist narrows on the most selective single word, and the phrase
    is checked afterwards on the flattened text.
    """
    words = [w for term in terms for w in term.split()]
    return max(words, key=len) if words else ""


def search(query: str) -> list[SearchHit]:
    """Full-text search over the content tree. Uses ripgrep to shortlist files
    and falls back to a pure-Python scan if rg is missing or errors out."""
    terms = parse_query(query)
    if not terms:
        return []
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
                _rg_pattern(_fold_text(_shortlist_term(terms))),
                str(CONTENT_DIR),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return _search_python(terms, query)
    # rg exit codes: 0 = matches, 1 = no matches, >=2 = real error.
    if proc.returncode >= 2:
        return _search_python(terms, query)

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
    _sort_hits(hits, query)
    return hits
