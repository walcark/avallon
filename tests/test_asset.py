"""Static URLs carry a fingerprint, so a cached stylesheet cannot go stale."""

from __future__ import annotations

import re
from pathlib import Path

from django.test import Client

from avallon.web.templatetags import asset as asset_tag

from .conftest import write_page


def test_a_stylesheet_url_carries_a_fingerprint(notes: Path) -> None:
    write_page(notes, "informatique/fiche/p", title="P")

    body = Client().get("/informatique/fiche/p/").content.decode()

    assert re.search(r"avallon/css/style\.css\?v=[0-9a-f]+", body)


def test_the_fingerprint_changes_with_the_file(tmp_path: Path, monkeypatch) -> None:
    """The whole point: an edited file is a different URL."""
    stand_in = tmp_path / "style.css"
    stand_in.write_text("a{}", encoding="utf-8")
    monkeypatch.setattr(asset_tag.finders, "find", lambda path: str(stand_in))

    first = asset_tag.asset("avallon/css/style.css")
    stand_in.write_text("a{color:red}", encoding="utf-8")

    assert asset_tag.asset("avallon/css/style.css") != first


def test_an_unknown_asset_degrades_to_the_plain_url() -> None:
    """A missing file is the static app's problem to report, not a crash here."""
    assert asset_tag.asset("avallon/css/nope.css").endswith("nope.css")
