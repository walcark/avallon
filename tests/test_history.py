"""Reading a page as it was, and saying so."""

from __future__ import annotations

import os
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


def _commit(root: Path, message: str, when: str = "2026-03-01T09:00:00+00:00") -> None:
    """Commit with both dates forced: a burst is built by choosing them."""
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", message],
        check=True,
        env={**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when},
    )


@pytest.fixture
def versioned(notes: Path) -> Path:
    """A notes repository with one page recorded twice."""
    _repo(notes)
    index = write_page(notes, "informatique/fiche/p", title="Première version")
    _commit(notes, "first", "2026-03-01T09:00:00+00:00")
    index.write_text(
        "---\ntitle: Seconde version\ndate: 2026-01-01\n---\n\nDu texte neuf.\n",
        encoding="utf-8",
    )
    _commit(notes, "second", "2026-03-05T09:00:00+00:00")
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
    _commit(versioned, "moved", "2026-03-09T09:00:00+00:00")

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


@pytest.fixture
def burst(notes: Path) -> Path:
    """Three saves within an hour, then one the next day."""
    _repo(notes)
    index = write_page(notes, "informatique/fiche/p", title="P")
    _commit(notes, "save 1", "2026-03-01T09:00:00+00:00")
    for minutes, hour in ((20, "09:20"), (50, "09:50")):
        index.write_text(f"---\ntitle: P\n---\n\nÉtat {minutes}.\n", encoding="utf-8")
        _commit(notes, f"save at {hour}", f"2026-03-01T{hour}:00+00:00")
    index.write_text("---\ntitle: P\n---\n\nLe lendemain.\n", encoding="utf-8")
    _commit(notes, "next day", "2026-03-02T11:00:00+00:00")
    return notes


def test_small_edits_within_the_hour_read_as_one_state(burst: Path) -> None:
    revisions = content.history("informatique/fiche/p")

    assert len(revisions) == 2
    assert revisions[0].subject == "next day"
    assert revisions[1].saves == 3


def test_a_folded_state_opens_the_end_of_the_session(burst: Path) -> None:
    """Not a page halfway through someone fixing typos."""
    session = content.history("informatique/fiche/p")[1]

    body = Client().get(f"/informatique/fiche/p/?at={session.sha}").content.decode()

    assert "État 50." in body


def test_the_window_is_configurable(burst: Path, monkeypatch) -> None:
    """A shorter window splits the session where the longer one held it."""
    monkeypatch.setenv(content.MERGE_WINDOW_ENV, "1800")  # 30 minutes

    # 09:00 and 09:20 still fold, twenty minutes apart; 09:50 breaks away,
    # its gap being thirty minutes exactly, which the window does not cover.
    assert len(content.history("informatique/fiche/p")) == 3


def test_folding_can_be_turned_off(burst: Path, monkeypatch) -> None:
    monkeypatch.setenv(content.MERGE_WINDOW_ENV, "0")

    assert len(content.history("informatique/fiche/p")) == 4


def test_states_are_shown_in_one_timezone(notes: Path, monkeypatch) -> None:
    """Notes come from several machines; a menu mixing offsets is unreadable."""
    monkeypatch.setenv("TZ", "UTC")
    _repo(notes)
    index = write_page(notes, "informatique/fiche/p", title="P")
    _commit(notes, "from here", "2026-03-01T09:00:00+02:00")  # 07:00 UTC
    index.write_text("---\ntitle: P\n---\n\nSuite.\n", encoding="utf-8")
    _commit(notes, "from the server", "2026-03-02T08:00:00+00:00")

    revisions = content.history("informatique/fiche/p")

    assert [r.when for r in revisions] == ["2026/03/02-08:00", "2026/03/01-07:00"]
