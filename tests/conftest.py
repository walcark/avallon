"""Shared fixtures: a throwaway notes tree, pointed at through the settings.

The content directory is resolved once, at import time, into
``settings.CONTENT_DIR`` and ``content.CONTENT_DIR``. Tests therefore rebind
both to a temporary tree rather than trying to re-import the module, which
would drag Django's app registry along with it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from django.conf import settings

from avallon.web import content

TAXONOMY = """\
domains = ["informatique", "administratif"]
types = ["fiche", "cr", "doc", "recueil"]

[labels]
cr = "compte rendu"
"""


def write_page(
    root: Path, relpath: str, *, body: str = "Du texte.", **frontmatter: str
) -> Path:
    """Create ``<root>/<relpath>/index.md`` with *frontmatter* and return it.

    *body* is the page's prose. It matters wherever what is being tested reads
    the text rather than the metadata, which searching does.
    """
    page_dir = root / relpath
    page_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(f"{key}: {value}" for key, value in frontmatter.items())
    index = page_dir / "index.md"
    index.write_text(f"---\n{lines}\n---\n\n{body}\n", encoding="utf-8")
    return index


@pytest.fixture
def notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An empty notes tree, active for the duration of one test."""
    root = tmp_path / "notes"
    root.mkdir()
    (root / "taxonomy.toml").write_text(TAXONOMY, encoding="utf-8")
    monkeypatch.setattr(settings, "CONTENT_DIR", root)
    monkeypatch.setattr(content, "CONTENT_DIR", root)
    # Anything resolving the directory at call time (the notes commands) must
    # land here too: without this a test writes into the developer's real
    # notes, which is exactly what happened once.
    monkeypatch.setenv("AVALLON_CONTENT_DIR", str(root))
    # The taxonomy is cached against its mtime, and a fresh tmp file can land
    # on the same one as the previous test's.
    monkeypatch.setattr(content, "_taxonomy_cache", None)
    yield root


@pytest.fixture(autouse=True)
def allow_test_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let Django's test client reach the site.

    ALLOWED_HOSTS is empty, which in debug means localhost only; the test
    client introduces itself as "testserver".
    """
    monkeypatch.setattr(settings, "ALLOWED_HOSTS", ["testserver", "127.0.0.1"])
