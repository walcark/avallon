#!/usr/bin/env python3
"""Move a content page to another domaine/type (its directory moves):

    content/<old-domaine>/<old-type>/<slug>/  ->  content/<domaine>/<type>/<slug>/

The slug and the page's co-located assets travel with it, so ``[[wikilink]]``
references by slug and relative image paths keep resolving; only the page's URL
changes. Domaine and type are chosen among the declared taxonomy
(taxonomy.toml). The source page and the destination can be passed as flags,
which makes the command scriptable and testable:

    python scripts/move_page.py --path informatique/fiche/ma-note \\
        --domain science --type cr

The move is left uncommitted, like `new`: `avallon sync` records it (git sees
a rename) on the next sync.
"""

from __future__ import annotations

import argparse
import shutil
import sys

from avallon.notes import config as cc
from avallon.notes import taxonomy
from avallon.notes.scaffold import pick  # shared picker (gum / fzf / menu)

CONTENT = cc.resolve_content_dir()


def pages() -> list[str]:
    """Every page relpath (<domaine>/<type>/<slug>), for the source picker."""
    return sorted(
        str(p.parent.relative_to(CONTENT)) for p in CONTENT.glob("*/*/*/index.md")
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Re-file a page under another domain/type."
    )
    ap.add_argument("--path", help="the page, as <domain>/<type>/<slug>")
    ap.add_argument("--domain")
    ap.add_argument("--type")
    args = ap.parse_args()

    taxo = taxonomy.load()
    if not taxo["domains"] or not taxo["types"]:
        sys.exit(
            "taxonomy.toml is empty: declare a domain and a type first "
            "(avallon add-domain …, avallon add-type …)."
        )

    all_pages = pages()
    if not all_pages:
        sys.exit("No page to move.")
    relpath = (args.path or pick("Page to move", all_pages)).strip("/")
    if not relpath:
        sys.exit("Cancelled.")
    source = (CONTENT / relpath).resolve()
    if CONTENT not in source.parents or not (source / "index.md").is_file():
        sys.exit(f"Page not found: {relpath}")

    domain = args.domain or pick("Nouveau domaine", taxo["domains"])
    if not domain:
        sys.exit("Cancelled.")
    if domain not in taxo["domains"]:
        sys.exit(f"undeclared domain: {domain}  (avallon add-domain {domain})")
    type_ = args.type or pick("Nouveau type", taxo["types"])
    if not type_:
        sys.exit("Cancelled.")
    if type_ not in taxo["types"]:
        sys.exit(f"undeclared type: {type_}  (avallon add-type {type_})")

    slug = source.name
    target = CONTENT / domain / type_ / slug
    if target.resolve() == source:
        sys.exit("The page already sits under this domain and type.")
    if target.exists():
        sys.exit(f'a page "{slug}" already exists in {domain}/{type_}.')

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    print(f"Moved {relpath}.")
    print(f"      -> {target.relative_to(CONTENT)}")
    print(f"URL     : /{target.relative_to(CONTENT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
