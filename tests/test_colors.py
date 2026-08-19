"""`{couleur}(texte)`: where the text ends is a question of depth.

Prose has parentheses in it. The rule used to be "no closing parenthesis
inside", which meant the writer had to remember a limitation of the parser at
the moment of writing, and got black text after the first `)` when they did
not.
"""

from __future__ import annotations

from pathlib import Path

from avallon.web import content

from .conftest import write_page


def _render(notes: Path, body: str) -> str:
    index = write_page(notes, "informatique/fiche/p", title="P", body=body)
    return content.render_markdown(index)


def test_a_colour_tints_its_text(notes: Path) -> None:
    html = _render(notes, "{rouge}(attention)")

    assert '<span class="c-rouge">attention</span>' in html


def test_a_parenthesis_inside_closes_nothing(notes: Path) -> None:
    html = _render(notes, "{rouge}(Exemple de texte (avec parenthèse) pour illustrer)")

    assert (
        '<span class="c-rouge">Exemple de texte (avec parenthèse) pour illustrer</span>'
        in html
    )


def test_parentheses_nest(notes: Path) -> None:
    html = _render(notes, "{vert}(un (deux (trois) deux) un)")

    assert '<span class="c-vert">un (deux (trois) deux) un</span>' in html


def test_what_follows_stays_outside(notes: Path) -> None:
    """The span must end where the writer closed it, not later."""
    html = _render(notes, "{bleu}(dedans (encore)) dehors")

    assert '<span class="c-bleu">dedans (encore)</span> dehors' in html


def test_two_colours_on_one_line_stay_apart(notes: Path) -> None:
    html = _render(notes, "{rouge}(un (a)) et {vert}(deux (b))")

    assert '<span class="c-rouge">un (a)</span>' in html
    assert '<span class="c-vert">deux (b)</span>' in html


def test_nested_markup_still_renders(notes: Path) -> None:
    html = _render(notes, "{vert}(ok, **validé** (enfin))")

    assert "<strong>validé</strong>" in html
    assert 'class="c-vert"' in html


def test_an_unclosed_opening_is_left_as_text(notes: Path) -> None:
    """Swallowing the rest of the paragraph would be the worse answer."""
    html = _render(notes, "{rouge}(oublié de fermer")

    assert "c-rouge" not in html
    assert "{rouge}(oublié de fermer" in html


def test_an_escaped_parenthesis_does_not_close_the_span(notes: Path) -> None:
    html = _render(notes, r"{orange}(un smiley \) et la suite)")

    assert 'class="c-orange"' in html
    assert "et la suite</span>" in html


def test_an_undeclared_colour_is_not_markup(notes: Path) -> None:
    html = _render(notes, "{turquoise}(rien)")

    assert "<span" not in html
    assert "{turquoise}(rien)" in html
