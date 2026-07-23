#!/usr/bin/env python3
"""Manage where the site's content lives (notes + taxonomy.toml).

Like pytodo's ``init`` / ``repo``: point the site at an external content repo,
create or adopt it, and make it active. The active path is stored in the local
config (see content_config.py); nothing here is versioned in the app repo.

    content_repo.py where              # print the active content dir + source
    content_repo.py init <path>        # create/adopt <path>, migrate, activate
    content_repo.py set  <path>        # activate an existing content dir

`init` will, if the in-repo ``content/`` still holds pages, offer to move them
(and taxonomy.toml) into <path> so the switch is seamless. Stdlib only.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import content_config as cc

STAMP_SCRIPT = cc._REPO_ROOT / "scripts" / "stamp_dates.py"

_HOOK = """#!/usr/bin/env sh
# Auto-stamp `updated:` (fill `date:` if missing) on staged content pages, then
# re-stage them. Installed by mysite (`pixi run content-init`).
staged=$(git diff --cached --name-only --diff-filter=ACM | grep -E 'index\\.md$' || true)
[ -z "$staged" ] && exit 0
if ! command -v python3 >/dev/null 2>&1; then
    echo "pre-commit: python3 introuvable, dates non tamponnees" >&2
    exit 0
fi
python3 "{stamp}" --today $staged || exit 1
echo "$staged" | xargs git add
"""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd), check=True)


def _has_pages(root: Path) -> bool:
    return root.exists() and any(root.glob("*/*/*/index.md"))


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
    hook.write_text(_HOOK.format(stamp=STAMP_SCRIPT), encoding="utf-8")
    hook.chmod(0o755)


def _ensure_taxonomy(target: Path) -> None:
    taxo = target / cc.TAXONOMY_NAME
    if taxo.exists():
        return
    taxo.write_text(
        "# Vocabulaire autorisé pour les pages du site.\n"
        "# Édité par `pixi run add-domain <nom>` / `pixi run add-type <nom>`.\n"
        "# Chaque page vit dans <domaine>/<type>/<slug>/.\n\n"
        'domains = []\n'
        'types = []\n',
        encoding="utf-8",
    )


def _migrate(src: Path, target: Path) -> list[str]:
    """Move the page tree + taxonomy.toml from *src* into *target*. Only runs
    when *target* has no pages yet, to avoid clobbering an adopted repo."""
    moved: list[str] = []
    if src.resolve() == target.resolve() or not src.exists():
        return moved
    if _has_pages(target):
        return moved  # adopting a populated repo: don't touch it
    for child in sorted(src.iterdir()):
        if child.name.startswith("."):
            continue
        dest = target / child.name
        if dest.exists():
            continue
        shutil.move(str(child), str(dest))
        moved.append(child.name)
    return moved


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [o/N] ").strip().lower() in ("o", "oui", "y", "yes")
    except EOFError:
        return False


def cmd_where() -> int:
    active = cc.resolve_content_dir()
    print(f"content_dir : {active}")
    print(f"source      : {cc.content_source()}  "
          f"(env {cc.ENV_VAR} > {cc.local_config_path()} > repli in-repo)")
    taxo = cc.taxonomy_path(active)
    print(f"taxonomy    : {taxo}  {'✓' if taxo.exists() else '(absent)'}")
    print(f"pages       : {sum(1 for _ in active.glob('*/*/*/index.md')) if active.exists() else 0}")
    print(f"dépôt git   : {'oui' if cc.is_git_root(active) else 'non'}")
    return 0


def cmd_init(path: str) -> int:
    target = Path(path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    created_repo = _ensure_git(target)

    fallback = cc._DEV_FALLBACK
    moved: list[str] = []
    if _has_pages(fallback) and fallback.resolve() != target and not _has_pages(target):
        if _confirm(f"Déplacer le contenu de {fallback} vers {target} ?"):
            moved = _migrate(fallback, target)

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
    if moved:
        print(f"  - déplacés : {', '.join(moved)}")
    print("  - hook pre-commit (tampon des dates) installé")
    print(f"  - config écrite : {cc.local_config_path()}")
    print("  ↻ redémarre le serveur (pixi run serve) pour qu'il serve ce dossier.")
    return 0


def cmd_set(path: str) -> int:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        sys.exit(f"Dossier introuvable : {target}  (utilise `content-init` pour le créer)")
    cc.write_content_dir(target)
    if cc.is_git_root(target):
        _install_hook(target)
    _ensure_taxonomy(target)
    print(f"✓ content_dir actif : {target}")
    print(f"  - config écrite : {cc.local_config_path()}")
    print("  ↻ redémarre le serveur (pixi run serve) pour qu'il serve ce dossier.")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return cmd_where()
    cmd, *rest = argv
    if cmd == "where":
        return cmd_where()
    if cmd in ("init", "set"):
        if not rest:
            sys.exit(f"usage : content_repo.py {cmd} <path>")
        return cmd_init(rest[0]) if cmd == "init" else cmd_set(rest[0])
    sys.exit(f"commande inconnue : {cmd}  (where | init <path> | set <path>)")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
