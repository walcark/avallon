"""Adopting a notes repository: clone URLs, scaffolding, and the hook."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from avallon.notes import config, repo


@pytest.mark.parametrize(
    "target",
    [
        "git@github.com:walcark/notes.git",
        "https://github.com/walcark/notes.git",
        "ssh://git@example.org/notes",
    ],
)
def test_a_clone_url_is_recognized(target: str) -> None:
    assert repo.looks_like_url(target)


@pytest.mark.parametrize("target", ["~/notes", "/tmp/notes", "notes"])
def test_a_local_path_is_not_a_url(target: str) -> None:
    assert not repo.looks_like_url(target)


def test_an_existing_directory_named_dot_git_wins_over_the_url_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local `notes.git/` directory is a path, not something to clone."""
    (tmp_path / "notes.git").mkdir()
    monkeypatch.chdir(tmp_path)

    assert not repo.looks_like_url("notes.git")


@pytest.fixture
def local_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the machine-local config so a test never writes the real one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv(config.ENV_VAR, raising=False)
    monkeypatch.delenv(config.LEGACY_ENV_VAR, raising=False)
    return tmp_path


def test_init_scaffolds_a_repository_and_activates_it(local_config: Path) -> None:
    target = local_config / "notes"

    assert repo.cmd_init(str(target)) == 0

    assert (target / config.TAXONOMY_NAME).is_file()
    assert (target / ".git" / "hooks" / "pre-commit").is_file()
    assert config.read_content_dir() == target


def test_init_adopts_an_existing_repository_without_touching_its_pages(
    local_config: Path,
) -> None:
    target = local_config / "notes"
    (target / "informatique" / "fiche" / "note").mkdir(parents=True)
    (target / "informatique/fiche/note/index.md").write_text("---\ntitle: N\n---\n")
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    taxonomy = target / config.TAXONOMY_NAME
    taxonomy.write_text('domains = ["informatique"]\ntypes = ["fiche"]\n')

    assert repo.cmd_init(str(target)) == 0

    assert taxonomy.read_text().startswith('domains = ["informatique"]')
    assert (target / "informatique/fiche/note/index.md").is_file()


def test_the_installed_hook_never_blocks_a_commit(local_config: Path) -> None:
    """An unstamped date is a detail; a commit one cannot make is not."""
    target = local_config / "notes"
    repo.cmd_init(str(target))

    hook = (target / ".git" / "hooks" / "pre-commit").read_text()

    assert "exit 0" in hook
    assert "avallon.notes.stamp" in hook
