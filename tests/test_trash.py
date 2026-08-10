"""The trash: git already holds every deleted page, what was missing is a door."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from django.test import Client

from avallon.web import content

from .conftest import write_page


def _repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for key, value in (("user.email", "t@t"), ("user.name", "T")):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)


def _commit(root: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], check=True)


@pytest.fixture
def buried(notes: Path) -> Path:
    """A page written, then deleted, with a document under it."""
    _repo(notes)
    write_page(notes, "informatique/fiche/perdue", title="Perdue", body="du texte")
    (notes / "informatique/fiche/perdue/piece.pdf").write_bytes(b"%PDF")
    write_page(notes, "informatique/fiche/citer", title="Citer", body="[[perdue]]")
    _commit(notes, "first")
    content.delete_page("informatique/fiche/perdue")
    _commit(notes, "delete")
    content._deleted_at.cache_clear()
    return notes


def test_a_deleted_page_is_in_the_trash_with_its_title(buried: Path) -> None:
    entries = content.deleted_pages()

    assert [(e.slug, e.title) for e in entries] == [("perdue", "Perdue")]


def test_a_moved_page_is_not_in_the_trash(notes: Path) -> None:
    """git reports a move as a deletion; a page whose slug lives somewhere was
    re-filed, not thrown away."""
    _repo(notes)
    write_page(notes, "informatique/fiche/note", title="Note")
    _commit(notes, "first")
    content.move_page("informatique/fiche/note", "administratif", "cr")
    _commit(notes, "moved")
    content._deleted_at.cache_clear()

    assert content.deleted_pages() == []


def test_restoring_brings_back_the_documents_too(buried: Path) -> None:
    page = content.restore_page("perdue")

    assert page.title == "Perdue"
    assert (buried / "informatique/fiche/perdue/piece.pdf").is_file()


def test_a_name_given_away_hides_its_deleted_page(buried: Path) -> None:
    """The deliberate limit of reading the trash from git: a page is in it
    while no live page bears its slug.

    Distinguishing "moved" from "the name was reused" is something git cannot
    reliably say, and the other rule would list every moved page as deleted,
    which is both wrong and far more frequent. The page stays in the history
    either way; only this view stops offering it.
    """
    write_page(buried, "administratif/cr/perdue", title="Autre")
    content._deleted_at.cache_clear()

    assert content.deleted_pages() == []
    with pytest.raises(content.InvalidPage, match="Not in the trash"):
        content.restore_page("perdue")


def test_a_link_to_a_deleted_page_offers_a_way_out(buried: Path) -> None:
    """Saying only "not found" makes it a dead end."""
    html = content.render_markdown_text(
        "Voir [[perdue]] et [[jamais]].",
        buried / "informatique/fiche/citer/index.md",
    )

    assert 'class="wikilink wikilink-deleted"' in html
    assert 'data-slug="perdue"' in html
    # A target that never existed stays inert: there is nothing to offer.
    assert 'wikilink-missing" title="Target not found: jamais"' in html


def test_removing_a_link_keeps_the_words(buried: Path) -> None:
    """The label is prose someone wrote; only the brackets go."""
    text, removed = content.strip_wikilink("Voir [[perdue|la page]] ici.", "perdue")

    assert (text, removed) == ("Voir la page ici.", 1)


def test_removing_a_link_leaves_the_others_alone(buried: Path) -> None:
    text, removed = content.strip_wikilink("[[perdue]] et [[autre]]", "perdue")

    assert (text, removed) == ("perdue et [[autre]]", 1)


def test_the_trash_says_how_many_links_a_restore_would_mend(buried: Path) -> None:
    body = Client().get("/corbeille/").content.decode()

    assert "1 liens à réparer" in body or "1 links to mend" in body


def test_unlinking_rewrites_the_citing_page(buried: Path) -> None:
    response = Client().post(
        "/unlink/",
        data='{"path": "informatique/fiche/citer", "target": "perdue"}',
        content_type="application/json",
    )

    assert response.json()["removed"] == 1
    assert "[[perdue]]" not in content.read_source(
        buried / "informatique/fiche/citer/index.md"
    )
