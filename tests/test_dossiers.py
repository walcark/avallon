"""Dossiers: membership, contents, and what the sidebar browses.

These cover the rule the model rests on: a dossier is an ordinary page, and
membership is derived from the pages that claim it, never written down twice.
"""

from __future__ import annotations

from pathlib import Path

from avallon.web import content

from .conftest import write_page

INDEX = "administratif/recueil/recours-batterie"


def build(root: Path) -> None:
    """A dossier index plus three members and one unrelated page."""
    write_page(root, INDEX, title="Recours batterie", status="en cours")
    write_page(
        root,
        "administratif/cr/mail-du-01-08",
        title="Mail du 01/08",
        project="recours-batterie",
        status="terminé",
    )
    write_page(
        root,
        "administratif/cr/mail-du-03-08",
        title="Mail du 03/08",
        project="recours-batterie",
    )
    write_page(
        root,
        "administratif/fiche/pieces",
        title="Les pièces",
        project="recours-batterie",
    )
    write_page(root, "informatique/fiche/garantie", title="Garantie légale")


def test_members_are_derived_from_the_pages_that_claim_the_dossier(notes: Path) -> None:
    build(notes)
    index = content.load_page(notes / INDEX / "index.md")

    titles = {page.title for page in content.project_members(index)}

    assert titles == {"Mail du 01/08", "Mail du 03/08", "Les pièces"}


def test_a_page_citing_the_dossier_without_claiming_it_stays_out(notes: Path) -> None:
    """Belonging is not citing: the durable note is linked, not filed."""
    build(notes)
    page = notes / "informatique/fiche/garantie/index.md"
    page.write_text(
        page.read_text(encoding="utf-8") + "\nVoir [[recours-batterie]].\n",
        encoding="utf-8",
    )
    index = content.load_page(notes / INDEX / "index.md")

    assert "Garantie légale" not in {p.title for p in content.project_members(index)}
    assert "Garantie légale" in {p.title for p in content.backlinks(index)}


def test_members_are_grouped_by_type_then_most_recent(notes: Path) -> None:
    build(notes)
    index = content.load_page(notes / INDEX / "index.md")

    types = [page.type for page in content.project_members(index)]

    assert types == sorted(types)


def test_a_page_becomes_a_dossier_by_being_claimed(notes: Path) -> None:
    """Nothing is declared: writing `project: x` is what makes x a dossier."""
    build(notes)

    slugs = {page.slug for page in content.all_projects()}

    assert slugs == {"recours-batterie"}


def test_membership_maps_every_member_to_its_dossier(notes: Path) -> None:
    build(notes)

    mapping = content.membership()

    assert mapping["administratif/cr/mail-du-01-08"].slug == "recours-batterie"
    assert "informatique/fiche/garantie" not in mapping
    assert INDEX not in mapping  # a dossier does not belong to itself


def test_the_sidebar_browses_the_dossier_from_a_member(notes: Path) -> None:
    build(notes)
    member = content.load_page(notes / "administratif/cr/mail-du-01-08/index.md")

    nav = content.dossier_nav(member)

    assert nav is not None
    assert nav["index"].slug == "recours-batterie"
    assert len(nav["members"]) == 3


def test_the_sidebar_browses_the_dossier_from_its_index(notes: Path) -> None:
    build(notes)
    index = content.load_page(notes / INDEX / "index.md")

    nav = content.dossier_nav(index)

    assert nav is not None
    assert nav["index"].relpath == index.relpath


def test_a_page_outside_any_dossier_leaves_the_sidebar_alone(notes: Path) -> None:
    build(notes)
    page = content.load_page(notes / "informatique/fiche/garantie/index.md")

    assert content.dossier_nav(page) is None


def test_a_project_naming_nothing_that_exists_is_ignored(notes: Path) -> None:
    """A typo must not invent a dossier, nor crash the listing."""
    build(notes)
    write_page(
        root=notes,
        relpath="informatique/fiche/orpheline",
        title="Orpheline",
        project="dossier-inexistant",
    )

    assert content.membership().get("informatique/fiche/orpheline") is None
    assert {p.slug for p in content.all_projects()} == {"recours-batterie"}
