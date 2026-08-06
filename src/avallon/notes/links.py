#!/usr/bin/env python3
"""Check that every internal link resolves.

    avallon check-links            # every page
    avallon check-links a/b/c …    # only these, as the pre-commit hook does

Run from the pre-commit hook, this is the net under the two mechanisms that
remove the causes: aliases, so a renamed page keeps answering to its old names,
and `avallon rename`, which writes them. What is left is a link typed to a page
that never existed, or a rename done by hand without the tool, and the moment to
catch it is before it is recorded, not months later on a page one is reading.

Stdlib plus the site's own resolver, so the hook and the site can never
disagree about what counts as a link.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from avallon.notes import config as cc

# Same pattern as the Markdown extension, embed form included.
_LINK = re.compile(r"!?\[\[\s*([^\]|]+?)\s*(?:\|[^\]]*)?\]\]")

# A target with a file extension is a co-located file, resolved against the
# page's own folder rather than against the tree of pages.
_FILE = re.compile(r"\.[A-Za-z0-9]{1,8}$")

# `[[slug]]` inside backticks is the syntax being explained, not a link being
# made: the renderer does not turn it into one either.
_CODE = re.compile(r"`[^`\n]*`|```.*?```", re.S)


def _exempt(text: str) -> bool:
    """Whether the page opted out with ``check_links: false``.

    A page documenting the link syntax shows dead ones on purpose, and it is
    the only honest way to demonstrate what a dead link looks like.
    """
    head = text.split("---", 2)[1] if text.startswith("---") else ""
    return bool(re.search(r"^check_links:\s*(false|no|0)\s*$", head, re.M | re.I))


def _pages(root: Path) -> list[tuple[str, str, list[str]]]:
    """(slug, relpath, aliases) for every page, read once."""
    import frontmatter

    out = []
    for index in root.glob("*/*/*/index.md"):
        post = frontmatter.load(index)
        rel = index.parent.relative_to(root)
        raw = post.get("aliases") or []
        aliases = [str(a).strip() for a in raw] if isinstance(raw, list) else []
        out.append((rel.name, str(rel), aliases))
    return out


def dead_links(paths: list[Path] | None = None) -> list[tuple[Path, str]]:
    """Return every (file, target) whose target resolves to nothing."""
    from avallon.web.mdx.wikilinks import resolves_to

    root = cc.resolve_content_dir()
    known = _pages(root)
    targets = paths or sorted(root.glob("*/*/*/index.md"))

    dead = []
    for index in targets:
        if not index.is_file():
            continue
        text = index.read_text(encoding="utf-8")
        if _exempt(text):
            continue
        text = _CODE.sub(" ", text)
        for match in _LINK.finditer(text):
            target = match.group(1).strip()
            if _FILE.search(target):
                # `[[fig.png]]`, or `![[doc/verso.png]]`: a file next to a page.
                name = target.split("/")[-1]
                folder = index.parent
                if "/" in target:
                    slug = target.split("/")[0]
                    folder = next(
                        (root / rel for _, rel, _ in known if rel.endswith(slug)),
                        folder,
                    )
                if not (folder / name).is_file():
                    dead.append((index, target))
                continue
            if not any(
                resolves_to(target, slug, rel, aliases) for slug, rel, aliases in known
            ):
                dead.append((index, target))
    return dead


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    paths = [Path(a).resolve() for a in args] or None

    root = cc.resolve_content_dir()
    dead = dead_links(paths)
    for index, target in dead:
        try:
            where = index.relative_to(root)
        except ValueError:
            where = index
        print(f"dead link: [[{target}]] in {where}", file=sys.stderr)
    if dead:
        print(
            f"{len(dead)} link(s) resolve to nothing.\n"
            "  `avallon rename` keeps links alive; a typo is fixed by hand.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
