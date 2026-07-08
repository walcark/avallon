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


@dataclass(frozen=True)
class Page:
    """Metadata for one Markdown page, derived from its path + frontmatter."""

    relpath: str          # "travail/cr/reunion-hygeos"
    domain: str           # from the path: <domaine>/...
    type: str             # from the path: .../<type>/...
    slug: str             # the leaf directory name
    title: str
    date: Any | None
    tags: list[str]
    summary: str

    @property
    def url(self) -> str:
        return f"/{self.relpath}/"


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
        tags=[str(t) for t in (post.get("tags") or [])],
        summary=str(post.get("summary", "")),
    )


def load_page(index_md: Path) -> Page:
    return _page_from(index_md)


def all_pages() -> list[Page]:
    """Every page in the tree: each content/<domaine>/<type>/<slug>/index.md."""
    return [_page_from(f) for f in sorted(CONTENT_DIR.glob(_PAGE_GLOB))]


# --- Full-text search ------------------------------------------------------

def _highlight(text: str, terms: list[str], width: int = 220) -> str:
    """Return a safe-HTML excerpt of *text* centered on the first matched term,
    with every (case-insensitive) occurrence of every term wrapped in <mark>."""
    low = text.lower()
    found = [i for i in (low.find(t.lower()) for t in terms) if i != -1]
    if found:
        start = max(0, min(found) - width // 3)
        end = min(len(text), start + width)
    else:
        start, end = 0, min(len(text), width)
    excerpt = text[start:end].strip()
    escaped = html.escape(excerpt)
    # Longest first so overlapping terms mark the widest span at each position.
    escaped_terms = sorted(
        {re.escape(html.escape(t)) for t in terms if t}, key=len, reverse=True
    )
    if escaped_terms:
        pattern = re.compile("|".join(escaped_terms), re.IGNORECASE)
        escaped = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped)
    return ("… " if start > 0 else "") + escaped + (" …" if end < len(text) else "")


# Rough Markdown -> plain text, so snippets read cleanly instead of showing
# raw syntax. Code *content* is kept (only the ``` fences are dropped) so it
# stays searchable; image/link targets collapse to their alt/link text.
_MD_STRIP = [
    (re.compile(r"^ *```.*$", re.MULTILINE), ""),    # code-fence lines
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
    blob = "\n".join(
        [_plain_text(post.content), page.title, page.summary, " ".join(page.tags)]
    )
    low = blob.lower()
    if not all(t.lower() in low for t in terms):
        return None
    return SearchHit(page=page, snippet=_highlight(blob, terms))


def _search_python(terms: list[str]) -> list[SearchHit]:
    """Dependency-free fallback used when ripgrep is unavailable."""
    hits = []
    for index_md in sorted(CONTENT_DIR.glob(_PAGE_GLOB)):
        hit = _hit_for(index_md, terms)
        if hit is not None:
            hits.append(hit)
    return hits


def search(query: str) -> list[SearchHit]:
    """Full-text search over the content tree. Uses ripgrep for speed and
    falls back to a pure-Python scan if rg is missing or errors out."""
    terms = query.split()
    if not terms:
        return []
    # rg shortlists on the first term (any single term is a necessary condition
    # for the AND); _hit_for then enforces that *all* terms are present and
    # builds the snippet. Both run against the cleaned text.
    try:
        proc = subprocess.run(
            ["rg", "-l", "-i", "-F", "--", terms[0], str(CONTENT_DIR), "--glob", "*.md"],
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
    hits.sort(key=lambda h: h.page.relpath)
    return hits
