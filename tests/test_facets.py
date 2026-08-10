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


def test_the_panel_is_always_reachable(notes: Path) -> None:
    """Rendered closed, its content is hidden by the browser and its summary is
    hidden on a wide screen, which left no way to filter at all. It ships open;
    the fold is a small-screen affordance applied where the viewport is known.
    """
    _tree(notes)

    plain = Client().get("/").content.decode()

    assert 'id="facetPanel" open' in plain
    assert 'data-active="0"' in plain


def test_the_panel_carries_the_count_of_active_filters(notes: Path) -> None:
    """So a folded panel can never hide that something is in force."""
    _tree(notes)

    filtered = Client().get("/", {"domaine": "administratif"}).content.decode()

    assert 'data-active="1"' in filtered
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


def test_a_first_dossier_can_be_started_from_the_browser(notes: Path) -> None:
    """Being a dossier is not declared: a page becomes one when another names
    it. Offering only existing dossiers made the first one impossible here."""
    write_page(notes, "administratif/recueil/le-litige", title="Le litige")

    body = Client().get("/nouvelle/").content.decode()

    assert 'value="le-litige"' in body
    assert "Ouvrir un dossier sur" in body


def test_an_existing_dossier_is_offered_first(notes: Path) -> None:
    _tree(notes)

    body = Client().get("/nouvelle/").content.decode()

    existing = body.index("Dossiers existants")
    candidates = body.index("Ouvrir un dossier sur")
    assert existing < candidates
    # A dossier is not offered twice, once per group.
    assert body.count('value="dossier-a"') == 1


def test_naming_a_page_makes_it_a_dossier(notes: Path) -> None:
    write_page(notes, "administratif/recueil/le-litige", title="Le litige")

    Client().post(
        "/nouvelle/",
        {
            "domain": "administratif",
            "type": "fiche",
            "title": "Un courrier",
            "tags": "",
            "summary": "",
            "project": "le-litige",
        },
    )

    from avallon.web import content

    assert [p.slug for p in content.all_projects()] == ["le-litige"]
