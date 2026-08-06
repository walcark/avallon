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

# Interface language. English is the default; the rest is a per-machine
# preference, stored next to the notes directory pointer.
LANGUAGE_ENV = "AVALLON_LANGUAGE"
DEFAULT_LANGUAGE = "en"
LANGUAGES = ("en", "fr")


class NotConfigured(RuntimeError):
    """No notes repository is configured yet."""


def local_config_path(app_name: str = APP_NAME) -> Path:
    """Path of the local (non-versioned) config file."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / app_name / "config.toml"


def read_config(path: Path | None = None) -> dict[str, str]:
    """Everything recorded in the local config file, as strings."""
    target = path or local_config_path()
    if not target.exists():
        return {}
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def write_config(**values: str) -> Path:
    """Update the given keys in the local config, leaving the others alone.

    Read-modify-write rather than overwrite: the file holds several unrelated
    settings now, and choosing a language must not erase the notes directory.
    """
    path = local_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {**read_config(path), **values}
    body = "".join(f'{key} = "{value}"\n' for key, value in sorted(merged.items()))
    path.write_text(body, encoding="utf-8")
    return path


def read_content_dir() -> Path | None:
    """The configured ``content_dir``, or ``None`` if unset."""
    for candidate in (local_config_path(), local_config_path(LEGACY_APP_NAME)):
        raw = read_config(candidate).get("content_dir")
        if raw:
            return Path(raw).expanduser()
    return None


def write_content_dir(content_dir: Path) -> Path:
    """Persist ``content_dir`` in the local config; return the config path."""
    return write_config(content_dir=str(content_dir))


def read_language() -> str | None:
    """The configured interface language, or ``None`` if unset."""
    for candidate in (local_config_path(), local_config_path(LEGACY_APP_NAME)):
        raw = read_config(candidate).get("language")
        if raw:
            return raw.strip().lower()
    return None


def write_language(language: str) -> Path:
    """Persist the interface language; return the config path."""
    return write_config(language=language)


def resolve_language() -> str:
    """The active interface language, English unless asked otherwise.

    English is the default because the project ships to strangers; a French
    reader says so once, and the choice follows the machine rather than the
    notes (the same notes are read from several devices).
    """
    chosen = os.environ.get(LANGUAGE_ENV) or read_language()
    return chosen.strip().lower() if chosen else DEFAULT_LANGUAGE


def system_time_zone() -> str:
    """The machine's IANA zone, or ``UTC`` when it cannot be read.

    There is no stdlib call for this. ``/etc/localtime`` is a symlink into the
    zoneinfo database on every systemd distribution, which is where this runs,
    and ``/etc/timezone`` covers the Debian family when it is a copy instead.
    A wrong guess would only shift displayed times, so failure falls back
    rather than raising.
    """
    link = Path("/etc/localtime")
    try:
        if link.is_symlink():
            parts = link.resolve().parts
            if "zoneinfo" in parts:
                return "/".join(parts[parts.index("zoneinfo") + 1 :]) or "UTC"
    except OSError:
        pass
    try:
        name = Path("/etc/timezone").read_text(encoding="utf-8").strip()
    except OSError:
        return "UTC"
    return name or "UTC"


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
