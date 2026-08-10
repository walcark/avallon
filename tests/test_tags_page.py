"""The tag survey: where near-duplicates become visible."""

from __future__ import annotations

from pathlib import Path

from django.test import Client

from avallon.web import content

from .conftest import write_page


def _tagged(notes: Path) -> None:
    write_page(notes, "informatique/fiche/a", title="A", tags="[banque, pret]")
    write_page(notes, "informatique/fiche/b", title="B", tags="[banque]")
    write_page(notes, "informatique/fiche/c", title="C", tags="[banques]")


def test_tags_are_ranked_by_weight(notes: Path) -> None:
    _tagged(notes)

    assert content.tag_counts()[0] == ("banque", 2)


def test_ties_break_alphabetically(notes: Path) -> None:
    """So the list is stable, and two spellings of one tag sit together."""
    _tagged(notes)

    assert content.tag_counts()[1:] == [("banques", 1), ("pret", 1)]


def test_the_page_lists_every_tag_twice_over(notes: Path) -> None:
    """By weight to survey them, alphabetically to find a known one."""
    _tagged(notes)

    body = Client().get("/tags/").content.decode()

    assert body.count('href="/?tag=banque"') == 2
    assert "Par poids" in body


def test_a_tag_leads_to_its_selection(notes: Path) -> None:
    _tagged(notes)

    # The fragment, not the whole page: the sidebar lists the entire tree, so
    # a page being absent from the *results* is what has to be checked.
    body = Client().get("/search/", {"tag": "banque"}).content.decode()

    assert 'href="/informatique/fiche/a/"' in body
    assert 'href="/informatique/fiche/c/"' not in body  # tagged "banques"


def test_an_empty_tree_says_so(notes: Path) -> None:
    write_page(notes, "informatique/fiche/a", title="A")

    assert "Aucun tag" in Client().get("/tags/").content.decode()
