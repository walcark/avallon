#!/usr/bin/env python3
"""Where the content lives: a user-configurable, non-versioned pointer.

Mirrors pytodo. A *local* config file (``~/.config/mysite/config.toml``,
honoring ``$XDG_CONFIG_HOME``) stores ``content_dir``: the path of the external
content repo that holds the Markdown tree **and** ``taxonomy.toml``. It is read
by both Django (to serve the site) and the scripts (to scaffold/stamp pages).

Resolution order (first hit wins):

    1. ``$MYSITE_CONTENT_DIR``        env override, handy for tests / CI
    2. ``content_dir`` in the config  the configured external repo
    3. the in-repo ``content/``       dev fallback, so a fresh clone still runs

Stdlib only: the git pre-commit hook imports nothing from the project env.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

APP_NAME = "mysite"
ENV_VAR = "MYSITE_CONTENT_DIR"

# scripts/ -> repo root -> repo/content (the dev fallback location).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEV_FALLBACK = _REPO_ROOT / "content"

TAXONOMY_NAME = "taxonomy.toml"


def local_config_path() -> Path:
    """Path of the local (non-versioned) config file."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / APP_NAME / "config.toml"


def read_content_dir() -> Path | None:
    """The configured ``content_dir``, or ``None`` if unset."""
    path = local_config_path()
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw = data.get("content_dir")
    return Path(raw).expanduser() if raw else None


def write_content_dir(content_dir: Path) -> Path:
    """Persist ``content_dir`` in the local config; return the config path."""
    path = local_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'content_dir = "{content_dir}"\n', encoding="utf-8")
    return path


def resolve_content_dir() -> Path:
    """The active content directory, following the resolution order above."""
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser().resolve()
    configured = read_content_dir()
    if configured:
        return configured.resolve()
    return _DEV_FALLBACK.resolve()


def content_source() -> str:
    """Which rule produced the active dir ('env' / 'config' / 'fallback')."""
    if os.environ.get(ENV_VAR):
        return "env"
    if read_content_dir():
        return "config"
    return "fallback"


def taxonomy_path(content_dir: Path | None = None) -> Path:
    """Path of ``taxonomy.toml`` inside the (active) content dir."""
    return (content_dir or resolve_content_dir()) / TAXONOMY_NAME


def is_git_root(path: Path) -> bool:
    """True if *path* is the top level of a git working tree."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return out.returncode == 0 and Path(out.stdout.strip()) == path.resolve()
