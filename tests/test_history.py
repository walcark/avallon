"""Reading a page as it was, and saying so."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from django.test import Client

from avallon.web import content

from .conftest import write_page


def _repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)


def _commit(root: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], check=True)


@pytest.fixture
def versioned(notes: Path) -> Path:
    """A notes repository with one page recorded twice."""
    _repo(notes)
    index = write_page(notes, "informatique/fiche/p", title="Première version")
    _commit(notes, "first")
    index.write_text(
        "---\ntitle: Seconde version\ndate: 2026-01-01\n---\n\nDu texte neuf.\n",
        encoding="utf-8",
    )
    _commit(notes, "second")
    return notes


def test_the_history_lists_the_recorded_states(versioned: Path) -> None:
    revisions = content.history("informatique/fiche/p")

    assert [r.subject for r in revisions] == ["second", "first"]
    assert all(len(r.when) == 16 for r in revisions)  # YYYY/MM/DD-hh:mm


def test_history_follows_a_page_that_moved(versioned: Path) -> None:
    """A page changing domain keeps one story, without anything being recorded."""
    (versioned / "administratif/fiche").mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(versioned),
            "mv",
            "informatique/fiche/p",
            "administratif/fiche/p",
        ],
        check=True,
    )
    _commit(versioned, "moved")

    revisions = content.history("administratif/fiche/p")

    assert len(revisions) >= 2  # the states from before the move are still there


def test_an_older_state_can_be_read(versioned: Path) -> None:
    older = content.history("informatique/fiche/p")[-1].sha

    body = Client().get(f"/informatique/fiche/p/?at={older}").content.decode()

    assert "Du texte neuf." not in body
    assert 'class="revision-banner"' in body


def test_an_unknown_revision_is_a_404(versioned: Path) -> None:
    assert Client().get("/informatique/fiche/p/?at=deadbee").status_code == 404


def test_a_revision_cannot_be_a_path(versioned: Path) -> None:
    """The argument is a hash, so nothing else is even tried."""
    assert content.at_revision("informatique/fiche/p", "../../etc/passwd") is None


def test_uncommitted_changes_are_announced(versioned: Path) -> None:
    (versioned / "informatique/fiche/p/index.md").write_text(
        "---\ntitle: En cours\n---\n\nPas encore enregistré.\n", encoding="utf-8"
    )

    payload = Client().get("/history/", {"path": "informatique/fiche/p"}).json()

    assert payload["dirty"] is True


def test_history_is_empty_outside_a_repository(notes: Path) -> None:
    """Not every notes directory is versioned, and that is not an error."""
    write_page(notes, "informatique/fiche/p", title="P")

    assert content.history("informatique/fiche/p") == []


def test_a_page_carrying_a_file_downloads_that_file(notes: Path) -> None:
    """The button gives the document itself, not a PDF rendering of its frame."""
    write_page(notes, "administratif/doc/carte", title="Carte", file="carte.pdf")
    (notes / "administratif/doc/carte/carte.pdf").write_bytes(b"%PDF-1.4\n")

    body = Client().get("/administratif/doc/carte/").content.decode()

    assert 'class="meta-action" href="/administratif/doc/carte/carte.pdf"' in body


def test_a_page_without_a_file_downloads_a_pdf_of_itself(notes: Path) -> None:
    write_page(notes, "informatique/fiche/p", title="P")

    body = Client().get("/informatique/fiche/p/").content.decode()

    assert (
        'class="meta-action" href="/export/?path=informatique/fiche/p&amp;format=pdf"'
        in body
    )
