#!/usr/bin/env python3
"""Stamp creation / last-modified dates into content pages' frontmatter.

Two date fields are maintained:

    date     creation date, set once and never overwritten
    updated  last-modified date, refreshed on every commit

The frontmatter is edited *textually* (only the two date lines are touched),
so the rest of the file — key order, inline lists, comments — stays byte for
byte identical and diffs stay clean. This script uses the standard library
only, so the git pre-commit hook can run it without the project environment.

Usage:
    stamp_dates.py --today  <file>...     # set updated=today (fill date if missing)
    stamp_dates.py --backfill [<file>...] # fill any *missing* date/updated
                                          # (no files given -> every page)
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

import content_config as cc

# The (user-configurable) content dir; also the git repo the dates come from.
CONTENT = cc.resolve_content_dir()
TODAY = datetime.date.today().isoformat()


def _git_date(path: Path, added: bool) -> str | None:
    """Committer date (YYYY-MM-DD) of the commit that added *path* (added=True)
    or last touched it (added=False). None if the file isn't tracked yet."""
    cmd = ["git", "log", "--format=%cs"]
    if added:
        cmd += ["--diff-filter=A"]
    else:
        cmd += ["-1"]
    cmd += ["--", str(path)]
    try:
        out = subprocess.run(
            cmd, cwd=CONTENT, capture_output=True, text=True
        ).stdout.strip()
    except OSError:
        return None
    if not out:
        return None
    # For --diff-filter=A the earliest (last printed) line is the creation.
    return out.splitlines()[-1] if added else out.splitlines()[0]


def _mtime_date(path: Path) -> str:
    return datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()


def creation_date(path: Path) -> str:
    return _git_date(path, added=True) or _mtime_date(path)


def modified_date(path: Path) -> str:
    return _git_date(path, added=False) or _mtime_date(path)


# --- Textual frontmatter editing -------------------------------------------

def _frontmatter_lines(text: str) -> tuple[list[str], int, int] | None:
    """Return (lines, start, end) where lines[start:end] is the YAML body of
    the leading `---` frontmatter block, or None if there is no frontmatter."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return lines, 1, i
    return None


def _get_key(lines: list[str], start: int, end: int, key: str) -> str | None:
    pat = re.compile(rf"^{re.escape(key)}\s*:\s*(.*?)\s*$")
    for j in range(start, end):
        m = pat.match(lines[j])
        if m:
            return m.group(1)
    return None


def set_date_fields(path: Path, *, date: str | None, updated: str | None,
                    overwrite_updated: bool) -> bool:
    """Ensure `date`/`updated` in *path*'s frontmatter. `date` is only written
    when missing; `updated` is written when missing or when overwrite_updated.
    Returns True if the file changed."""
    text = path.read_text(encoding="utf-8")
    parsed = _frontmatter_lines(text)
    if parsed is None:
        print(f"  skip (no frontmatter): {path}", file=sys.stderr)
        return False
    lines, start, end = parsed

    changed = False

    def ensure(key: str, value: str, *, overwrite: bool, after: list[str]) -> None:
        nonlocal end, changed
        pat = re.compile(rf"^{re.escape(key)}\s*:")
        for j in range(start, end):
            if pat.match(lines[j]):
                if overwrite and _get_key(lines, start, end, key) != value:
                    lines[j] = f"{key}: {value}\n"
                    changed = True
                return
        # Not present: insert right after the first present key of *after*
        # (highest priority first), else at the top of the block.
        insert_at = start
        for k in after:
            kp = re.compile(rf"^{re.escape(k)}\s*:")
            hit = next((j for j in range(start, end) if kp.match(lines[j])), None)
            if hit is not None:
                insert_at = hit + 1
                break
        lines.insert(insert_at, f"{key}: {value}\n")
        end += 1
        changed = True

    if date is not None:
        ensure("date", date, overwrite=False, after=["title"])
    if updated is not None:
        ensure("updated", updated, overwrite=overwrite_updated, after=["date", "title"])

    if changed:
        path.write_text("".join(lines), encoding="utf-8")
    return changed


# --- Page discovery & CLI ---------------------------------------------------

def _pages(args_files: list[str]) -> list[Path]:
    if args_files:
        paths = [Path(f).resolve() for f in args_files]
    else:
        paths = sorted(CONTENT.glob("*/*/*/index.md"))
    out = []
    for p in paths:
        try:
            rel = p.parent.relative_to(CONTENT)
        except ValueError:
            continue  # outside the content tree
        if p.name == "index.md" and len(rel.parts) == 3:
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--today", action="store_true",
                      help="set updated=today (fill date if missing)")
    mode.add_argument("--backfill", action="store_true",
                      help="fill any missing date/updated from git history")
    ap.add_argument("files", nargs="*", help="content pages (default: all)")
    args = ap.parse_args()

    n = 0
    for path in _pages(args.files):
        if args.today:
            changed = set_date_fields(
                path, date=creation_date(path), updated=TODAY,
                overwrite_updated=True,
            )
        else:  # --backfill: only fill what's missing
            changed = set_date_fields(
                path, date=creation_date(path), updated=modified_date(path),
                overwrite_updated=False,
            )
        if changed:
            n += 1
            print(f"  stamped {path.relative_to(CONTENT)}")
    print(f"{n} file(s) stamped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
