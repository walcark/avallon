"""Loading, rendering and searching of the Markdown content tree.

The directory layout encodes both the taxonomy and the URL:

    content/<domaine>/<type>/<slug>/index.md   ->   /<domaine>/<type>/<slug>/

Images (and other assets) live next to the index.md that uses them and are
referenced with *relative* paths, so they resolve under the page's own URL
without any src rewriting.
"""

from __future__ import annotations

import html
import json
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

def _highlight(text: str, query: str, width: int = 220) -> str:
    """Return a safe-HTML excerpt of *text* around the first match of *query*,
    with every (case-insensitive) occurrence wrapped in <mark>."""
    low = text.lower()
    i = low.find(query.lower())
    if i == -1:
        start, end = 0, min(len(text), width)
    else:
        start = max(0, i - width // 3)
        end = min(len(text), i + len(query) + 2 * width // 3)
    excerpt = text[start:end].strip()
    escaped = html.escape(excerpt)
    pattern = re.compile(re.escape(html.escape(query)), re.IGNORECASE)
    highlighted = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped)
    return ("… " if start > 0 else "") + highlighted + (" …" if end < len(text) else "")


def _hit_for(index_md: Path, query: str, matched_line: str | None = None) -> SearchHit | None:
    """Build a SearchHit for *index_md*. If *matched_line* is given (from rg),
    the snippet is drawn from it; otherwise the whole file is searched."""
    post = frontmatter.load(index_md)
    page = _page_from(index_md, post)
    if matched_line is not None:
        return SearchHit(page=page, snippet=_highlight(matched_line, query))
    # Python fallback path: search body + searchable metadata.
    blob = "\n".join([post.content, page.title, page.summary, " ".join(page.tags)])
    if query.lower() not in blob.lower():
        return None
    return SearchHit(page=page, snippet=_highlight(blob, query))


def _search_python(query: str) -> list[SearchHit]:
    """Dependency-free fallback used when ripgrep is unavailable."""
    hits = []
    for index_md in sorted(CONTENT_DIR.glob(_PAGE_GLOB)):
        hit = _hit_for(index_md, query)
        if hit is not None:
            hits.append(hit)
    return hits


def search(query: str) -> list[SearchHit]:
    """Full-text search over the content tree. Uses ripgrep for speed and
    falls back to a pure-Python scan if rg is missing or errors out."""
    q = query.strip()
    if not q:
        return []
    try:
        proc = subprocess.run(
            ["rg", "--json", "-i", "-F", "--", q, str(CONTENT_DIR), "--glob", "*.md"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return _search_python(q)
    # rg exit codes: 0 = matches, 1 = no matches, >=2 = real error.
    if proc.returncode >= 2:
        return _search_python(q)

    # Keep the first matching line per file for the snippet.
    first_line: dict[Path, str] = {}
    for raw in proc.stdout.splitlines():
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if evt.get("type") != "match":
            continue
        path = Path(evt["data"]["path"]["text"])
        if path not in first_line:
            first_line[path] = evt["data"]["lines"]["text"]

    hits = []
    for path, line in first_line.items():
        try:
            rel = path.parent.relative_to(CONTENT_DIR)
        except ValueError:
            continue
        if len(rel.parts) != 3 or path.name != "index.md":
            continue  # ignore anything outside the <domaine>/<type>/<slug> shape
        hit = _hit_for(path, q, matched_line=line)
        if hit is not None:
            hits.append(hit)
    hits.sort(key=lambda h: h.page.relpath)
    return hits
