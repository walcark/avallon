"""Loading, rendering and searching of the Markdown content tree.

The directory layout encodes both the taxonomy and the URL:

    content/<domaine>/<type>/<slug>/index.md   ->   /<domaine>/<type>/<slug>/

Images (and other assets) live next to the index.md that uses them and are
referenced with *relative* paths, so they resolve under the page's own URL
without any src rewriting.
"""

from __future__ import annotations

import html
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter
from django.conf import settings
from django.http import Http404
from markdownify.templatetags.markdownify import markdownify

CONTENT_DIR: Path = settings.CONTENT_DIR

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


def safe_resolve(relpath: str) -> Path:
    """Resolve *relpath* under CONTENT_DIR, refusing anything that escapes it
    (e.g. `../../etc/passwd`)."""
    target = (CONTENT_DIR / relpath.strip("/")).resolve()
    if target != CONTENT_DIR and CONTENT_DIR not in target.parents:
        raise Http404("Chemin hors du contenu")
    return target


def render_markdown(index_md: Path) -> str:
    """Render an index.md (frontmatter stripped) to HTML, using the same filter
    the template uses so streamed updates match the initial render."""
    post = frontmatter.load(index_md)
    return str(markdownify(post.content))


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
        tags=[str(t) for t in (post.get("tags") or [])],
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


def nav_tree() -> list[dict[str, Any]]:
    """Pages grouped domaine -> type -> pages, for the sidebar navigation.
    Domaines and types are alphabetical; pages keep the recency order."""
    grouped: dict[str, dict[str, list[Page]]] = {}
    for page in all_pages():
        grouped.setdefault(page.domain, {}).setdefault(page.type, []).append(page)
    return [
        {
            "domain": domain,
            "types": [
                {"type": type_, "pages": pages}
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
