"""What the search bar must answer, and what it must stop answering.

Every case here is a real failure that made the bar go unused: the page one was
looking for was almost never first, and a four-letter query returned half the
tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from avallon.web import content

from .conftest import write_page


@pytest.fixture
def corpus(notes: Path) -> Path:
    """A tree shaped like the real one: the answer, and its neighbours."""
    write_page(
        notes,
        "administratif/fiche/entretien-banquier",
        title="Entretien avec le banquier",
        summary="Support d'appel.",
        date="2026-01-01",
    )
    # More recent, and mentions the word in passing: this is what used to win.
    write_page(
        notes,
        "administratif/fiche/retrofacturation",
        title="Contester le paiement",
        summary="Le levier bancaire.",
        date="2026-08-01",
        body="Le banquier a répondu. Voir avec le banquier ensuite.",
    )
    write_page(
        notes,
        "informatique/fiche/penalites",
        title="Pénalités de retard",
        body="Est-ce que cela me pénalise, et pénalise-t-il le dossier ?",
        date="2026-08-05",
    )
    write_page(
        notes,
        "science/fiche/alis-article",
        title="ALIS article B. Mayer",
        date="2026-01-01",
    )
    return notes


def test_a_title_match_comes_first(corpus: Path) -> None:
    """Ranking was recency alone, so the page one wanted was rarely first."""
    hits = content.search("banquier")

    assert hits[0].page.slug == "entretien-banquier"


def test_a_prefix_no_longer_matches_the_middle_of_a_word(corpus: Path) -> None:
    """ "alis" used to find "pénalise", and half the tree with it."""
    slugs = [h.page.slug for h in content.search("ALIS")]

    assert slugs == ["alis-article"]


def test_a_prefix_still_finds_the_word_being_typed(corpus: Path) -> None:
    """Incremental search only works if a half-typed word matches."""
    assert [h.page.slug for h in content.search("banqui")] == [
        "entretien-banquier",
        "retrofacturation",
    ]


def test_a_plural_is_found_by_its_singular(corpus: Path) -> None:
    write_page(notes := corpus, "informatique/fiche/piles", title="Les batteries")

    assert content.search("batterie")[0].page.slug == "piles"
    assert notes  # fixture used


def test_an_unclosed_quote_searches_the_phrase_so_far(corpus: Path) -> None:
    """It used to match the quote character itself, so nothing was found until
    the quote was closed: an empty page for as long as it took to type one."""
    assert content.parse_query('"le banquier') == ["le banquier"]
    assert content.search('"le banquier')


def test_a_closed_quote_still_requires_the_phrase(corpus: Path) -> None:
    assert content.parse_query('"le banquier"') == ["le banquier"]
    assert not content.search('"banquier le"')


def test_words_in_the_order_typed_outrank_words_apart(corpus: Path) -> None:
    write_page(
        corpus,
        "administratif/fiche/dispersed",
        title="Notes",
        body="Le banquier est là. Un entretien plus tard, autre chose.",
        date="2026-09-01",
    )

    hits = content.search("entretien banquier")

    assert hits[0].page.slug == "entretien-banquier"


def test_repetition_cannot_beat_a_title(corpus: Path) -> None:
    """A long page must not win by saying the word twenty times."""
    write_page(
        corpus,
        "informatique/fiche/repete",
        title="Autre chose",
        body="banquier " * 40,
        date="2026-09-01",
    )

    assert content.search("banquier")[0].page.slug == "entretien-banquier"


def test_a_tag_outranks_a_passing_mention(corpus: Path) -> None:
    write_page(
        corpus, "informatique/fiche/tagged", title="Sans rapport", tags="[banquier]"
    )

    slugs = [h.page.slug for h in content.search("banquier")]

    assert slugs.index("tagged") < slugs.index("retrofacturation")


def test_a_title_is_never_truncated_by_its_own_highlight(corpus: Path) -> None:
    """Centring a title on its match read as a bug, not as a match."""
    marked = content.highlight_title("Entretien avec le banquier", "banquier")

    assert marked.startswith("Entretien avec le <mark>")
    assert "…" not in marked


def test_a_title_without_a_match_is_left_alone(corpus: Path) -> None:
    assert content.highlight_title("Rien à voir", "banquier") == "Rien à voir"


def test_a_title_is_escaped_before_being_marked(corpus: Path) -> None:
    """It is rendered with |safe, so nothing in a title may become markup."""
    marked = content.highlight_title("<script>alert(1)</script> banquier", "banquier")

    assert "<script>" not in marked
    assert "&lt;script&gt;" in marked
