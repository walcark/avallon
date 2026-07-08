"""Loading and rendering of the Markdown content tree.

The directory layout encodes both the taxonomy and the URL:

    content/<domaine>/<type>/<slug>/index.md   ->   /<domaine>/<type>/<slug>/

Images (and other assets) live next to the index.md that uses them and are
referenced with *relative* paths, so they resolve under the page's own URL
without any src rewriting.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter
from django.conf import settings
from django.http import Http404
from markdownify.templatetags.markdownify import markdownify

CONTENT_DIR: Path = settings.CONTENT_DIR


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


def _page_from(index_md: Path) -> Page:
    rel = index_md.parent.relative_to(CONTENT_DIR)
    parts = rel.parts
    post = frontmatter.load(index_md)
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
    files = sorted(CONTENT_DIR.glob("*/*/*/index.md"))
    return [_page_from(f) for f in files]
