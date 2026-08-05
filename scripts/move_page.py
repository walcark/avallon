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

The move is left uncommitted, like `new`: `pixi run sync` records it (git sees
a rename) on the next sync.
"""

from __future__ import annotations

import argparse
import shutil
import sys

import content_config as cc
import taxonomy  # sibling module (scripts/ is on sys.path[0])
from new_page import pick  # shared interactive picker (gum / fzf / menu)

CONTENT = cc.resolve_content_dir()


def pages() -> list[str]:
    """Every page relpath (<domaine>/<type>/<slug>), for the source picker."""
    return sorted(
        str(p.parent.relative_to(CONTENT)) for p in CONTENT.glob("*/*/*/index.md")
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Déplacer une page vers un autre domaine/type."
    )
    ap.add_argument("--path", help="relpath de la page, <domaine>/<type>/<slug>")
    ap.add_argument("--domain")
    ap.add_argument("--type")
    args = ap.parse_args()

    taxo = taxonomy.load()
    if not taxo["domains"] or not taxo["types"]:
        sys.exit(
            "taxonomy.toml est vide : déclare d'abord un domaine et un type "
            "(pixi run add-domain …, pixi run add-type …)."
        )

    all_pages = pages()
    if not all_pages:
        sys.exit("Aucune page à déplacer.")
    relpath = (args.path or pick("Page à déplacer", all_pages)).strip("/")
    if not relpath:
        sys.exit("Annulé.")
    source = (CONTENT / relpath).resolve()
    if CONTENT not in source.parents or not (source / "index.md").is_file():
        sys.exit(f"page introuvable : {relpath}")

    domain = args.domain or pick("Nouveau domaine", taxo["domains"])
    if not domain:
        sys.exit("Annulé.")
    if domain not in taxo["domains"]:
        sys.exit(f"domaine non déclaré : {domain}  (pixi run add-domain {domain})")
    type_ = args.type or pick("Nouveau type", taxo["types"])
    if not type_:
        sys.exit("Annulé.")
    if type_ not in taxo["types"]:
        sys.exit(f"type non déclaré : {type_}  (pixi run add-type {type_})")

    slug = source.name
    target = CONTENT / domain / type_ / slug
    if target.resolve() == source:
        sys.exit("La note est déjà dans ce domaine et ce type.")
    if target.exists():
        sys.exit(f"une note « {slug} » existe déjà dans {domain}/{type_}.")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    print(f"Déplacé : {relpath}")
    print(f"      -> {target.relative_to(CONTENT)}")
    print(f"URL     : /{target.relative_to(CONTENT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
