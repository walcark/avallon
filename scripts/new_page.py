#!/usr/bin/env python3
"""Scaffold a new content page:

    content/<domaine>/<type>/<slug>/index.md

Domaine and type are chosen among the declared taxonomy (taxonomy.toml); tags
are free text. The interactive picker uses gum, then fzf, then a plain numbered
menu — whichever is available — so it works without extra tooling. Every field
can also be passed as a flag, which makes the command scriptable and testable:

    python scripts/new_page.py --domain travail --type notes \\
        --title "Ma note" --tags "smartg, flux"
"""

from __future__ import annotations

import argparse
import datetime
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import taxonomy  # sibling module (scripts/ is on sys.path[0])

ROOT = taxonomy.ROOT
CONTENT = ROOT / "content"


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "sans-titre"


def scalar(s: str) -> str:
    """YAML scalar: quote only when the value could be misparsed unquoted."""
    if s and s == s.strip() and not re.search(r"""[:#\[\]{},"']""", s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def pick(prompt: str, options: list[str]) -> str:
    """Choose one of *options* via gum, else fzf, else a numbered menu."""
    if shutil.which("gum"):
        out = subprocess.run(
            ["gum", "choose", "--header", prompt, *options],
            text=True, capture_output=True,
        ).stdout.strip()
        return out
    if shutil.which("fzf"):
        out = subprocess.run(
            ["fzf", "--prompt", prompt + " › ", "--height", "40%"],
            input="\n".join(options), text=True, capture_output=True,
        ).stdout.strip()
        return out
    print(prompt)
    for i, opt in enumerate(options, 1):
        print(f"  {i}) {opt}")
    while True:
        try:
            s = input("> ").strip()
        except EOFError:
            return ""  # no input available (non-interactive) -> caller cancels
        if s.isdigit() and 1 <= int(s) <= len(options):
            return options[int(s) - 1]
        if s in options:
            return s


def ask(prompt: str) -> str:
    if shutil.which("gum"):
        return subprocess.run(
            ["gum", "input", "--header", prompt],
            text=True, capture_output=True,
        ).stdout.strip()
    try:
        return input(f"{prompt} : ").strip()
    except EOFError:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Créer une nouvelle page de contenu.")
    ap.add_argument("--domain")
    ap.add_argument("--type")
    ap.add_argument("--title")
    ap.add_argument("--tags", default=None)
    ap.add_argument("--summary", default=None)
    args = ap.parse_args()

    taxo = taxonomy.load()
    if not taxo["domains"] or not taxo["types"]:
        sys.exit("taxonomy.toml est vide : déclare d'abord un domaine et un type "
                 "(pixi run add-domain …, pixi run add-type …).")

    domain = args.domain or pick("Domaine", taxo["domains"])
    if not domain:
        sys.exit("Annulé.")
    if domain not in taxo["domains"]:
        sys.exit(f"domaine non déclaré : {domain}  (pixi run add-domain {domain})")
    type_ = args.type or pick("Type", taxo["types"])
    if not type_:
        sys.exit("Annulé.")
    if type_ not in taxo["types"]:
        sys.exit(f"type non déclaré : {type_}  (pixi run add-type {type_})")

    title = args.title or ask("Titre")
    if not title.strip():
        sys.exit("titre requis.")
    tags_raw = args.tags if args.tags is not None else ask("Tags (séparés par des virgules)")
    tags = [t.strip() for t in re.split(r"[,\n]+", tags_raw) if t.strip()]
    summary = args.summary if args.summary is not None else ask("Résumé (optionnel)")

    slug = slugify(title)
    base = CONTENT / domain / type_
    target = base / slug
    n = 2
    while target.exists():
        target = base / f"{slug}-{n}"
        n += 1

    today = datetime.date.today().isoformat()
    lines = [
        f"title: {scalar(title)}",
        f"date: {today}",
        f"updated: {today}",
        "tags: [" + ", ".join(scalar(t) for t in tags) + "]",
    ]
    if summary.strip():
        lines.append(f"summary: {scalar(summary)}")
    body = "---\n" + "\n".join(lines) + "\n---\n\n# " + title + "\n"

    target.mkdir(parents=True)
    (target / "index.md").write_text(body, encoding="utf-8")
    print(f"Créé : {(target / 'index.md').relative_to(ROOT)}")
    print(f"URL  : /{target.relative_to(CONTENT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
