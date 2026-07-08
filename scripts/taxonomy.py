#!/usr/bin/env python3
"""Read and update the site taxonomy (allowed domains and types).

taxonomy.toml is the single source of truth for the <domaine>/<type>
directories a page may live in. new_page.py only offers values declared here,
and `add-domain` / `add-type` extend it — committing the change — so pages are
never created under an undeclared domain or type.

    taxonomy.py add-domain <nom>
    taxonomy.py add-type   <nom>
    taxonomy.py check                 # every page sits under a declared d/t
    taxonomy.py list                  # print domains and types
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAXO = ROOT / "taxonomy.toml"
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_KEY = {"domain": "domains", "type": "types"}
_FR = {"domain": "domaine", "type": "type"}


def load() -> dict[str, list[str]]:
    if not TAXO.exists():
        return {"domains": [], "types": []}
    data = tomllib.loads(TAXO.read_text(encoding="utf-8"))
    return {
        "domains": list(data.get("domains", [])),
        "types": list(data.get("types", [])),
    }


def _dump(data: dict[str, list[str]]) -> str:
    def arr(key: str) -> str:
        items = ", ".join(f'"{v}"' for v in sorted(set(data.get(key, []))))
        return f"{key} = [{items}]\n"

    return (
        "# Vocabulaire autorisé pour les pages du site.\n"
        "# Édité par `pixi run add-domain <nom>` / `pixi run add-type <nom>`.\n"
        "# Chaque page vit dans content/<domaine>/<type>/<slug>/.\n\n"
        + arr("domains")
        + arr("types")
    )


def add(kind: str, name: str, *, commit: bool = True) -> bool:
    key = _KEY[kind]
    name = name.strip().lower()
    if not _SLUG.match(name):
        sys.exit(f"nom invalide : {name!r} (minuscules, chiffres et tirets)")
    data = load()
    if name in data[key]:
        print(f"{_FR[kind]} « {name} » déjà présent.")
        return False
    data[key].append(name)
    TAXO.write_text(_dump(data), encoding="utf-8")
    print(f"{_FR[kind]} « {name} » ajouté à {TAXO.name}.")
    if commit:
        subprocess.run(["git", "add", "--", str(TAXO)], cwd=ROOT, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"taxo: ajoute le {_FR[kind]} « {name} »",
             "--", str(TAXO)],
            cwd=ROOT, check=True,
        )
    return True


def check() -> int:
    """Verify every existing page sits under a declared domain and type."""
    data = load()
    bad = []
    for idx in sorted((ROOT / "content").glob("*/*/*/index.md")):
        domain, type_ = idx.parts[-4], idx.parts[-3]
        if domain not in data["domains"] or type_ not in data["types"]:
            bad.append((idx.relative_to(ROOT), domain, type_))
    for rel, domain, type_ in bad:
        dd = "" if domain in data["domains"] else " ✗inconnu"
        tt = "" if type_ in data["types"] else " ✗inconnu"
        print(f"hors taxonomie : {rel}  [{domain}{dd} / {type_}{tt}]",
              file=sys.stderr)
    if bad:
        print(f"{len(bad)} page(s) hors taxonomie.", file=sys.stderr)
        return 1
    print("Toutes les pages respectent la taxonomie.")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        sys.exit("usage : taxonomy.py {add-domain|add-type|check|list} [nom]")
    cmd, *rest = argv
    if cmd in ("add-domain", "add-type"):
        if not rest:
            sys.exit(f"usage : taxonomy.py {cmd} <nom>")
        add("domain" if cmd == "add-domain" else "type", rest[0])
    elif cmd == "check":
        return check()
    elif cmd == "list":
        data = load()
        print("domaines :", " ".join(data["domains"]) or "(aucun)")
        print("types    :", " ".join(data["types"]) or "(aucun)")
    else:
        sys.exit(f"commande inconnue : {cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
