#!/usr/bin/env python3
"""Manage where the notes live (the Markdown tree + taxonomy.toml).

Point the site at a notes repository, create or adopt it, and make it active.
The active path is stored in the machine-local config (see config.py); nothing
here is versioned in the application repository.

    avallon repo               # print the active notes dir and its source
    avallon init <path>        # create or adopt <path>, then activate it
    avallon repo <path>        # activate an existing notes dir

Stdlib only.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from avallon.notes import config as cc

# The hook runs outside any environment we control, so it names the very
# interpreter that installed it. Reinstalling (`avallon init`) is what moves it
# to another one.
STAMP_CMD = f'"{sys.executable}" -m avallon.notes.stamp'

_HOOK = """#!/usr/bin/env sh
# Auto-stamp `updated:` (fill `date:` if missing) on staged pages, then re-stage
# them. Installed by avallon (`avallon init`).
staged=$(git diff --cached --name-only --diff-filter=ACM \\
  | grep -E 'index\\.md$' || true)
[ -z "$staged" ] && exit 0
# Never block a commit: an unstamped date is a detail, a commit one cannot make
# is not. A missing interpreter or package only costs a warning.
{stamp} --today $staged 2>/dev/null || {{
    echo "pre-commit: avallon introuvable, dates non tamponnees" >&2
    exit 0
}}
echo "$staged" | xargs git add
"""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd), check=True)


def _ensure_git(target: Path) -> bool:
    """Init a git repo at *target* if it isn't one already. Returns True if it
    created one."""
    if cc.is_git_root(target):
        return False
    _run(["git", "init", "-q"], cwd=target)
    return True


def _install_hook(target: Path) -> None:
    hook = target / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(_HOOK.format(stamp=STAMP_CMD), encoding="utf-8")
    hook.chmod(0o755)


def _ensure_taxonomy(target: Path) -> None:
    taxo = target / cc.TAXONOMY_NAME
    if taxo.exists():
        return
    taxo.write_text(
        "# Vocabulaire autorisé pour les pages du site.\n"
        "# Édité par `avallon add-domain <nom>` / `avallon add-type <nom>`.\n"
        "# Chaque page vit dans <domaine>/<type>/<slug>/.\n\n"
        "domains = []\n"
        "types = []\n",
        encoding="utf-8",
    )


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [o/N] ").strip().lower() in ("o", "oui", "y", "yes")
    except EOFError:
        return False


def cmd_where() -> int:
    try:
        active = cc.resolve_content_dir()
    except cc.NotConfigured as exc:
        print(exc)
        return 1
    print(f"content_dir : {active}")
    print(
        f"source      : {cc.content_source()}  "
        f"(env {cc.ENV_VAR} > {cc.local_config_path()})"
    )
    taxo = cc.taxonomy_path(active)
    print(f"taxonomy    : {taxo}  {'✓' if taxo.exists() else '(absent)'}")
    n_pages = sum(1 for _ in active.glob("*/*/*/index.md")) if active.exists() else 0
    print(f"pages       : {n_pages}")
    print(f"dépôt git   : {'oui' if cc.is_git_root(active) else 'non'}")
    return 0


def cmd_init(path: str) -> int:
    target = Path(path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    created_repo = _ensure_git(target)

    _ensure_taxonomy(target)
    _install_hook(target)
    cc.write_content_dir(target)

    # Initial commit if the repo is fresh (or was just created) and has content.
    if created_repo:
        _run(["git", "add", "-A"], cwd=target)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init: contenu du site"],
            cwd=str(target),
        )

    print(f"✓ content_dir actif : {target}")
    if created_repo:
        print("  - dépôt git initialisé")
    print("  - hook pre-commit (tampon des dates) installé")
    print(f"  - config écrite : {cc.local_config_path()}")
    print("  ↻ redémarre le serveur pour qu'il serve ce dossier.")
    return 0


def cmd_set(path: str) -> int:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        sys.exit(
            f"Dossier introuvable : {target}  (utilise `avallon init` pour le créer)"
        )
    cc.write_content_dir(target)
    if cc.is_git_root(target):
        _install_hook(target)
    _ensure_taxonomy(target)
    print(f"✓ content_dir actif : {target}")
    print(f"  - config écrite : {cc.local_config_path()}")
    print("  ↻ redémarre le serveur pour qu'il serve ce dossier.")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return cmd_where()
    cmd, *rest = argv
    if cmd == "where":
        return cmd_where()
    if cmd in ("init", "set"):
        if not rest:
            sys.exit(f"usage : avallon {cmd} <path>")
        return cmd_init(rest[0]) if cmd == "init" else cmd_set(rest[0])
    sys.exit(f"commande inconnue : {cmd}  (where | init <path> | set <path>)")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
