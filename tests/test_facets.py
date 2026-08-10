"""Each axis gets the control its cardinality warrants."""

from __future__ import annotations

from pathlib import Path

from django.test import Client

from .conftest import write_page


def _tree(notes: Path) -> None:
    write_page(notes, "administratif/recueil/dossier-a", title="Dossier A")
    write_page(notes, "administratif/recueil/dossier-b", title="Dossier B")
    for i, dossier in enumerate(("dossier-a", "dossier-b")):
        write_page(
            notes,
            f"administratif/fiche/note-{i}",
            title=f"Note {i}",
            project=dossier,
            tags="[banque]",
        )


def test_dossiers_are_a_menu_not_chips(notes: Path) -> None:
    """They grow without limit; chips would eventually fill the screen."""
    _tree(notes)

    body = Client().get("/").content.decode()

    assert 'class="facet-menu" data-param="dossier"' in body
    assert 'data-param="dossier"' not in body.split('class="facet-menu"')[0]


def test_the_menu_offers_a_way_back_to_everything(notes: Path) -> None:
    _tree(notes)

    body = Client().get("/", {"dossier": "dossier-a"}).content.decode()

    assert '<option value="">' in body


def test_tags_stay_out_of_the_way_until_one_is_used(notes: Path) -> None:
    _tree(notes)

    plain = Client().get("/").content.decode()
    filtered = Client().get("/", {"tag": "banque"}).content.decode()

    assert 'data-facet="tag"' not in plain
    # Present once active, or a selection reached from a tag link could not be
    # undone: exactly the one-way door the domains once had.
    assert 'data-facet="tag"' in filtered


def test_the_panel_opens_itself_when_something_is_filtered(notes: Path) -> None:
    """Folded on a phone, but never folded over a filter already in force."""
    _tree(notes)

    plain = Client().get("/").content.decode()
    filtered = Client().get("/", {"domaine": "administratif"}).content.decode()

    assert '<details class="facet-panel" id="facetPanel">' in plain
    assert 'id="facetPanel" open>' in filtered
    assert '<span class="facet-count">1</span>' in filtered


def test_a_dossier_page_offers_its_own_explorer(notes: Path) -> None:
    """The prose stays; what was missing was the other way in."""
    _tree(notes)

    body = Client().get("/administratif/recueil/dossier-a/").content.decode()

    assert 'href="/?dossier=dossier-a"' in body


def test_a_member_page_does_not(notes: Path) -> None:
    """It is not the index, and its sidebar already lists the dossier."""
    _tree(notes)

    body = Client().get("/administratif/fiche/note-0/").content.decode()

    assert "dossier-explore" not in body
