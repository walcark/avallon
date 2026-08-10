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


def test_a_refused_capture_gives_back_everything_typed(notes: Path) -> None:
    """Losing a capture to an error message defeats the one thing a capture
    has to be: cheaper than remembering."""
    write_page(notes, "administratif/fiche/deja-pris", title="Déjà pris")

    body = (
        Client()
        .post(
            "/capture/",
            {
                "title": "Déjà pris",
                "body": "un texte précieux",
                "domain": "administratif",
                "type": "fiche",
                "back": "/ailleurs",
            },
        )
        .content.decode()
    )

    assert "un texte précieux" in body
    assert 'value="Déjà pris"' in body
    assert 'value="/ailleurs"' in body


def test_an_empty_capture_is_never_refused(notes: Path) -> None:
    """The moment it can fail is the moment it stops being used."""
    response = Client().post(
        "/capture/",
        {"title": "", "body": "", "domain": "administratif", "type": "fiche"},
    )

    assert response.status_code == 302
    assert len(content.all_pages()) == 1


def test_a_page_with_tasks_but_no_status_is_still_waiting(notes: Path) -> None:
    """Reading only the status left six tasks invisible in the real tree, on
    pages nobody had thought to mark."""
    write_page(notes, "culture/recueil/jeux", title="Jeux", body="- [ ] essayer\n")

    body = _main(Client().get("/entretien/"))

    assert "Jeux" in body
    assert "1 to do" in body


def test_a_page_its_dossier_lists_is_not_adrift(notes: Path) -> None:
    """It is reachable through the dossier, wikilink or not."""
    write_page(notes, "administratif/recueil/dossier", title="Dossier")
    write_page(notes, "administratif/fiche/membre", title="Membre", project="dossier")

    assert [p.slug for p in content.orphans()] == ["dossier"]


def test_a_page_can_be_deleted_with_everything_under_it(notes: Path) -> None:
    """Capture makes pages cheap to create, so they have to be cheap to undo."""
    write_page(notes, "informatique/fiche/jetable", title="Jetable")
    (notes / "informatique/fiche/jetable/piece.pdf").write_bytes(b"%PDF")

    response = Client().post(
        "/delete/",
        data='{"path": "informatique/fiche/jetable"}',
        content_type="application/json",
    )

    assert response.status_code == 200
    assert not (notes / "informatique/fiche/jetable").exists()


def test_deleting_says_what_it_strands(notes: Path) -> None:
    """A count of pages about to lose a link is the one thing worth a pause."""
    write_page(notes, "informatique/fiche/cible", title="Cible")
    write_page(notes, "informatique/fiche/citer", title="Citer", body="[[cible]]")
    write_page(notes, "informatique/fiche/membre", title="Membre", project="cible")

    payload = (
        Client()
        .post(
            "/delete/",
            data='{"path": "informatique/fiche/cible"}',
            content_type="application/json",
        )
        .json()
    )

    assert payload["stranded"] == ["Citer"]
    assert payload["members"] == ["Membre"]


def test_deleting_a_page_that_is_not_there_is_refused(notes: Path) -> None:
    response = Client().post(
        "/delete/",
        data='{"path": "informatique/fiche/fantome"}',
        content_type="application/json",
    )

    assert response.status_code == 404


def test_a_delete_cannot_reach_outside_the_tree(notes: Path) -> None:
    response = Client().post(
        "/delete/",
        data='{"path": "../../etc"}',
        content_type="application/json",
    )

    assert response.status_code == 404
