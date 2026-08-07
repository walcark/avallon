"""A page that bears a name beats a page that merely bore it."""

from __future__ import annotations

from pathlib import Path

from avallon.web import content
from avallon.web.mdx.wikilinks import _resolve, resolve_among

from .conftest import write_page


def _pair(notes: Path, freed_is_newer: bool) -> None:
    """Two pages: one named `batterie`, one that used to be.

    The order `all_pages()` returns them in is by recency, which used to decide
    the winner, so both orders have to be built.
    """
    old, new = (
        ("2026-08-07", "2026-06-01")
        if freed_is_newer
        else (
            "2026-01-01",
            "2026-08-07",
        )
    )
    write_page(
        notes,
        "informatique/fiche/analyse-de-la-batterie",
        title="Analyse de la batterie",
        date=old,
        updated=old,
        aliases="[batterie]",
    )
    write_page(
        notes, "informatique/fiche/batterie", title="Batterie", date=new, updated=new
    )


def test_the_bearer_wins_when_it_is_the_more_recent(notes: Path) -> None:
    _pair(notes, freed_is_newer=False)

    assert _resolve("batterie").slug == "batterie"


def test_the_bearer_wins_when_it_is_the_older(notes: Path) -> None:
    """The case that used to fail: a rename made today captured the link."""
    _pair(notes, freed_is_newer=True)

    assert _resolve("batterie").slug == "batterie"


def test_a_freed_name_still_resolves_while_nobody_bears_it(notes: Path) -> None:
    """Aliases must keep working, that is what they are for."""
    write_page(
        notes,
        "informatique/fiche/analyse-de-la-batterie",
        title="Analyse de la batterie",
        aliases="[batterie]",
    )

    assert _resolve("batterie").slug == "analyse-de-la-batterie"


def test_two_claims_on_a_freed_name_resolve_to_nothing(notes: Path) -> None:
    """A visible dead link beats a working link to the wrong page."""
    for slug in ("analyse", "mesure"):
        write_page(
            notes,
            f"informatique/fiche/{slug}",
            title=slug.title(),
            aliases="[batterie]",
        )

    assert _resolve("batterie") is None


def test_the_backlink_agrees_with_the_link(notes: Path) -> None:
    """A reference rendering as pointing elsewhere is not a backlink here."""
    _pair(notes, freed_is_newer=True)
    write_page(notes, "informatique/fiche/citante", title="Citante")
    (notes / "informatique/fiche/citante/index.md").write_text(
        "---\ntitle: Citante\ndate: 2026-08-01\n---\n\nVoir [[batterie]].\n",
        encoding="utf-8",
    )

    bearer = content.load_page(notes / "informatique/fiche/batterie/index.md")
    freed = content.load_page(
        notes / "informatique/fiche/analyse-de-la-batterie/index.md"
    )

    assert [p.slug for p in content.backlinks(bearer)] == ["citante"]
    assert content.backlinks(freed) == []


def test_resolution_refuses_two_bearers_of_one_name(notes: Path) -> None:
    """Creation prevents this; a tree edited by hand can still hold it."""
    write_page(notes, "informatique/fiche/note", title="Note")
    write_page(notes, "administratif/cr/note", title="Note")

    assert resolve_among("note", content.all_pages()) is None
