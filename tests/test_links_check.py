"""check-links: the net under aliases and rename."""

from __future__ import annotations

from pathlib import Path

from avallon.notes import links

from .conftest import write_page


def _body(index: Path, extra: str) -> None:
    index.write_text(index.read_text(encoding="utf-8") + extra, encoding="utf-8")


def test_a_link_to_nothing_is_reported(notes: Path) -> None:
    index = write_page(notes, "informatique/fiche/a", title="A")
    _body(index, "\nVoir [[cette-page-nexiste-pas]].\n")

    dead = links.dead_links()

    assert [t for _, t in dead] == ["cette-page-nexiste-pas"]


def test_a_link_that_resolves_is_not_reported(notes: Path) -> None:
    write_page(notes, "informatique/fiche/cible", title="Cible")
    index = write_page(notes, "informatique/cr/a", title="A")
    _body(index, "\n[[cible]] et [[Cible]]\n")

    assert links.dead_links() == []


def test_an_alias_counts_as_resolving(notes: Path) -> None:
    """Otherwise the checker would fight the mechanism that keeps links alive."""
    write_page(notes, "informatique/fiche/cible", title="Cible", aliases="[vieux-nom]")
    index = write_page(notes, "informatique/cr/a", title="A")
    _body(index, "\n[[vieux-nom]]\n")

    assert links.dead_links() == []


def test_a_link_inside_backticks_is_syntax_not_a_link(notes: Path) -> None:
    index = write_page(notes, "informatique/fiche/a", title="A")
    _body(index, "\nOn écrit `[[slug]]` pour citer une page.\n")

    assert links.dead_links() == []


def test_a_page_can_opt_out(notes: Path) -> None:
    """A page documenting the syntax shows dead links on purpose."""
    index = write_page(
        notes, "informatique/tutoriel/demo", title="Démo", check_links="false"
    )
    _body(index, "\nUn lien mort ressemble à [[rien-du-tout]].\n")

    assert links.dead_links() == []


def test_a_co_located_file_is_checked_on_disk(notes: Path) -> None:
    index = write_page(notes, "informatique/fiche/a", title="A")
    _body(index, "\n[[joint.pdf]] et [[absent.pdf]]\n")
    (notes / "informatique/fiche/a/joint.pdf").write_bytes(b"%PDF")

    assert [t for _, t in links.dead_links()] == ["absent.pdf"]


def test_the_command_exits_non_zero_on_a_dead_link(notes: Path) -> None:
    index = write_page(notes, "informatique/fiche/a", title="A")
    _body(index, "\n[[nulle-part]]\n")

    assert links.main([]) == 1


def test_the_command_exits_zero_when_everything_resolves(notes: Path) -> None:
    write_page(notes, "informatique/fiche/a", title="A")

    assert links.main([]) == 0
