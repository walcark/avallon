#!/usr/bin/env python3
"""Rename a page: new title, new slug, old names kept as aliases.

    avallon rename informatique/fiche/ma-note "Un meilleur titre"

Renaming is the one routine operation that used to strand links: the folder
name changes, and every `[[old-slug]]` written elsewhere stops resolving. Here
both former names are recorded on the page itself before it moves, so the notes
that cite it keep working without being touched.

The directory moves with `git mv` when the notes are a repository, so the
history follows the page rather than showing a delete and an add.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from avallon.notes import config as cc
from avallon.notes.scaffold import scalar, slugify


def _title_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("title:"):
            return line
    return ""


def rename(relpath: str, new_title: str) -> Path:
    """Rename the page at *relpath*, return its new directory."""
    from avallon.web import content

    root = cc.resolve_content_dir()
    source = (root / relpath.strip("/")).resolve()
    index = source / "index.md"
    if not index.is_file():
        sys.exit(f"Page not found: {relpath}")
    if not new_title.strip():
        sys.exit("A title is required.")

    text = index.read_text(encoding="utf-8")
    old_title = content.title_of(text)
    old_slug = source.name
    new_slug = slugify(new_title)
    target = source.parent / new_slug
    if target.exists() and target != source:
        sys.exit(f'A page "{new_slug}" already exists in {source.parent.name}.')

    # Aliases first, on the still-current text: both names are known here and
    # nowhere else.
    for alias in (old_title, old_slug):
        if alias and alias != new_title and alias != new_slug:
            text = content.add_alias(text, alias)
    line = _title_line(text)
    if line:
        text = text.replace(line, f"title: {scalar(new_title.strip())}", 1)
    index.write_text(text, encoding="utf-8")

    if target != source:
        moved = subprocess.run(
            ["git", "-C", str(root), "mv", str(source), str(target)],
            capture_output=True,
            text=True,
        )
        if moved.returncode != 0:
            # Not a git repository, or the page is untracked: a plain move is
            # still the right outcome.
            source.rename(target)
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="Rename a page, keeping its links alive.")
    ap.add_argument("path", help="the page, as <domain>/<type>/<slug>")
    ap.add_argument("title", help="its new title")
    args = ap.parse_args()

    target = rename(args.path, args.title)
    print(f"Renamed to {target.relative_to(cc.resolve_content_dir())}.")
    print("  former names kept as aliases, so existing links still resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
