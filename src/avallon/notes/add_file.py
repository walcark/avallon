#!/usr/bin/env python3
"""Promote a file to a page of its own.

    avallon add-file ~/scans/carte-identite.jpg --domain administratif \\
        --type doc --title "Carte d'identité" --tags "identité, officiel"

The file moves into a page directory next to an ``index.md`` that describes it,
which is what gives it a title, tags, a URL and a place in the search index. A
scan left as an asset inside somebody else's page has none of those, and nothing
can collect what does not exist.

The test for promoting a file, from `docs/documents.md`: *would I look for this
file on its own?* If not, leave it as an illustration next to the page that
uses it.
"""

from __future__ import annotations

import argparse
import datetime
import re
import shutil
import sys
from pathlib import Path

from avallon.notes import config as cc
from avallon.notes import taxonomy
from avallon.notes.scaffold import ask, pick, scalar, slugify

# A file bigger than this bloats the repository forever: git keeps every
# version of a binary, and a deleted 50 Mo scan still weighs 50 Mo in the
# history. The limit is a guard, not a judgement, hence --force.
SIZE_LIMIT_MB = 20


def add_file(
    source: Path,
    domain: str,
    type_: str,
    title: str,
    tags: list[str],
    summary: str = "",
    doc_date: str = "",
    copy: bool = False,
) -> Path:
    """Create the page, move (or copy) *source* into it, return its directory."""
    content = cc.resolve_content_dir()
    from avallon.web import content as _content

    base = content / domain / type_
    slug = slugify(title)
    taken = _content.page_named(slug)
    if taken is not None:
        sys.exit(
            f'A page already goes by "{slug}": {taken.relpath}\n'
            "  choose another title, or `avallon rename` that page first"
        )
    target = base / slug
    suffix = 2
    while target.exists():
        target = base / f"{slug}-{suffix}"
        suffix += 1

    target.mkdir(parents=True)
    destination = target / source.name
    if copy:
        shutil.copy2(source, destination)
    else:
        shutil.move(str(source), str(destination))

    today = datetime.date.today().isoformat()
    lines = [
        f"title: {scalar(title.strip())}",
        f"date: {today}",
        f"updated: {today}",
        f"file: {scalar(source.name)}",
        "tags: [" + ", ".join(scalar(t) for t in tags) + "]",
    ]
    if summary.strip():
        lines.append(f"summary: {scalar(summary.strip())}")
    if doc_date.strip():
        # The date *of the document* (issued, signed, received), which is what
        # one looks for later; `date` stays the filing date.
        lines.append(f"doc_date: {scalar(doc_date.strip())}")
    (target / "index.md").write_text(
        "---\n" + "\n".join(lines) + "\n---\n\n", encoding="utf-8"
    )
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="Promote a file to a page.")
    ap.add_argument("path", help="the file to file away")
    ap.add_argument("--domain")
    ap.add_argument("--type")
    ap.add_argument("--title")
    ap.add_argument("--tags", default=None)
    ap.add_argument("--summary", default=None)
    ap.add_argument("--doc-date", default="", help="date of the document itself")
    ap.add_argument("--copy", action="store_true", help="copy instead of moving")
    ap.add_argument(
        "--force", action="store_true", help=f"accept a file over {SIZE_LIMIT_MB} Mo"
    )
    args = ap.parse_args()

    source = Path(args.path).expanduser().resolve()
    if not source.is_file():
        sys.exit(f"File not found: {source}")

    size_mb = source.stat().st_size / 1_000_000
    if size_mb > SIZE_LIMIT_MB and not args.force:
        sys.exit(
            f"{source.name} weighs {size_mb:.0f} Mo, over the {SIZE_LIMIT_MB} Mo "
            "limit.\n"
            "  git keeps every version of a binary forever, deleted or not.\n"
            "  --force to add it anyway."
        )

    taxo = taxonomy.load()
    if not taxo["domains"] or not taxo["types"]:
        sys.exit(
            "taxonomy.toml is empty: declare a domain and a type first "
            "(avallon add-domain …, avallon add-type …)."
        )

    domain = args.domain or pick("Domain", taxo["domains"])
    if not domain:
        sys.exit("Cancelled.")
    if domain not in taxo["domains"]:
        sys.exit(f"undeclared domain: {domain}  (avallon add-domain {domain})")

    type_ = args.type or pick("Type", taxo["types"])
    if not type_:
        sys.exit("Cancelled.")
    if type_ not in taxo["types"]:
        sys.exit(f"undeclared type: {type_}  (avallon add-type {type_})")

    title = args.title or ask("Title") or source.stem
    tags_raw = args.tags if args.tags is not None else ask("Tags (comma separated)")
    tags = list(
        dict.fromkeys(
            re.sub(r"\s+", " ", t.strip()).lower()
            for t in re.split(r"[,\n]+", tags_raw or "")
            if t.strip()
        )
    )
    summary = args.summary if args.summary is not None else ask("Summary (optional)")

    target = add_file(
        source, domain, type_, title, tags, summary or "", args.doc_date, args.copy
    )
    print(f"Created {target / 'index.md'}.")
    print(f"  file  : {target.name}/{source.name}")
    print(f"  tags  : {', '.join(tags) or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
