#!/usr/bin/env python3
"""Where the notes live: a machine-local, non-versioned pointer.

This is the *only* per-machine state. A local config file
(``~/.config/avallon/config.toml``, honoring ``$XDG_CONFIG_HOME``) stores
``content_dir``: the path of the notes repository holding the Markdown tree
**and** ``taxonomy.toml``. Everything else that configures the site for a given
set of notes lives inside that repository, and is therefore versioned and
shared across devices.

Resolution order (first hit wins):

    1. ``$AVALLON_CONTENT_DIR``       env override, handy for tests and CI
    2. ``content_dir`` in the config  the configured notes repository

There is no third rule. Falling back to a directory inside the installation
would have a user write notes into their own site-packages and lose them at
the next upgrade, so an unconfigured install is an error, not a default.

Stdlib only: the git pre-commit hook imports nothing from the project env.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

APP_NAME = "avallon"
ENV_VAR = "AVALLON_CONTENT_DIR"

# Read (never written) so an install predating the rename keeps working.
LEGACY_APP_NAME = "mysite"
LEGACY_ENV_VAR = "MYSITE_CONTENT_DIR"

TAXONOMY_NAME = "taxonomy.toml"


class NotConfigured(RuntimeError):
    """No notes repository is configured yet."""


def local_config_path(app_name: str = APP_NAME) -> Path:
    """Path of the local (non-versioned) config file."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / app_name / "config.toml"


def _read(path: Path) -> Path | None:
    """The ``content_dir`` recorded in *path*, or None."""
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    raw = data.get("content_dir")
    return Path(str(raw)).expanduser() if raw else None


def read_content_dir() -> Path | None:
    """The configured ``content_dir``, or ``None`` if unset."""
    return _read(local_config_path()) or _read(local_config_path(LEGACY_APP_NAME))


def write_content_dir(content_dir: Path) -> Path:
    """Persist ``content_dir`` in the local config; return the config path."""
    path = local_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'content_dir = "{content_dir}"\n', encoding="utf-8")
    return path


def content_dir_env() -> str | None:
    """The env override, if any, new name first."""
    return os.environ.get(ENV_VAR) or os.environ.get(LEGACY_ENV_VAR)


def resolve_content_dir() -> Path:
    """The active notes directory, following the resolution order above.

    Raises
    ------
    NotConfigured
        Nothing points at a notes repository yet.
    """
    env = content_dir_env()
    if env:
        return Path(env).expanduser().resolve()
    configured = read_content_dir()
    if configured:
        return configured.resolve()
    raise NotConfigured(
        "No notes repository configured.\n"
        "  avallon init <path|url>   to create or adopt one"
    )


def content_source() -> str:
    """Which rule produced the active dir ('env' / 'config' / 'aucun')."""
    if content_dir_env():
        return "env"
    if read_content_dir():
        return "config"
    return "aucun"


def taxonomy_path(content_dir: Path | None = None) -> Path:
    """Path of ``taxonomy.toml`` inside the (active) notes dir."""
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
