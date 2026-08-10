"""Not withering: capture what comes, and see what is waiting."""

from __future__ import annotations

from pathlib import Path

from django.test import Client

from avallon.web import content

from .conftest import write_page


def _main(response) -> str:
    """The page's own content. The sidebar lists the whole tree, so asserting
    on the full document says nothing about what this view decided."""
    body = response.content.decode()
    return body[body.index("<main") : body.index("</main>")]


def test_open_tasks_are_counted_from_the_page(notes: Path) -> None:
    """The most honest measure of unfinished this tree has; length is not one,
    the shortest pages being lists that are complete at forty words."""
    write_page(
        notes,
        "administratif/fiche/p",
        title="P",
        body="- [ ] appeler\n- [x] fait\n- [ ] relancer\n",
    )

    page = content.load_page(notes / "administratif/fiche/p/index.md")
    assert content.open_tasks(page) == 2


def test_a_page_nothing_cites_is_an_orphan(notes: Path) -> None:
    write_page(notes, "administratif/fiche/cited", title="Cited")
    write_page(notes, "administratif/fiche/alone", title="Alone")
    write_page(notes, "administratif/fiche/citer", title="Citer", body="[[cited]]")

    assert sorted(p.slug for p in content.orphans()) == ["alone", "citer"]


def test_upkeep_lists_what_is_open_stalest_first(notes: Path) -> None:
    """What has been left alone longest is what is rotting."""
    write_page(
        notes,
        "administratif/fiche/vieux",
        title="Vieux",
        status="en cours",
        date="2026-01-01",
        updated="2026-01-01",
    )
    write_page(
        notes,
        "administratif/fiche/frais",
        title="Frais",
        status="en cours",
        date="2026-08-01",
        updated="2026-08-01",
    )

    body = _main(Client().get("/entretien/"))

    assert body.index("Vieux") < body.index("Frais")


def test_upkeep_shows_what_is_left_to_do(notes: Path) -> None:
    write_page(
        notes,
        "administratif/fiche/p",
        title="P",
        status="en cours",
        body="- [ ] a\n- [ ] b\n",
    )

    body = _main(Client().get("/entretien/"))

    assert "2 to do" in body


def test_a_finished_page_with_open_tasks_is_a_contradiction(notes: Path) -> None:
    write_page(
        notes,
        "administratif/fiche/p",
        title="Fini",
        status="terminé",
        body="- [ ] reste\n",
    )

    body = _main(Client().get("/entretien/"))

    assert "Finished, but still has things to do" in body


def test_a_capture_is_filed_as_to_sort(notes: Path) -> None:
    """The vocabulary is not optional, so the honest thing is to say the answer
    was guessed rather than to invent a place for it."""
    response = Client().post(
        "/capture/",
        {
            "title": "Une idée",
            "body": "le corps",
            "domain": "administratif",
            "type": "fiche",
            "back": "/",
        },
    )

    assert response["Location"] == "/"
    page = content.load_page(notes / "administratif/fiche/une-idee/index.md")
    assert page.status == content.CAPTURED
    assert "le corps" in content.read_source(
        notes / "administratif/fiche/une-idee/index.md"
    )


def test_a_capture_without_a_title_takes_its_first_line(notes: Path) -> None:
    """Nothing must stand between the idea and its being written down."""
    Client().post(
        "/capture/",
        {
            "title": "",
            "body": "Regarder les tarifs",
            "domain": "administratif",
            "type": "fiche",
        },
    )

    assert (notes / "administratif/fiche/regarder-les-tarifs").is_dir()


def test_a_capture_shows_up_in_upkeep(notes: Path) -> None:
    Client().post(
        "/capture/",
        {"title": "À classer", "body": "", "domain": "administratif", "type": "fiche"},
    )

    body = _main(Client().get("/entretien/"))

    assert "To file" in body  # the heading, in the pinned interface language
    assert "À classer" in body


def test_a_share_arrives_already_filled_in(notes: Path) -> None:
    """The PWA share target: anything shared from another application."""
    body = (
        Client()
        .get(
            "/capture/",
            {"title": "Un article", "text": "à lire", "url": "https://x.fr"},
        )
        .content.decode()
    )

    assert 'value="Un article"' in body
    assert "à lire https://x.fr" in body
