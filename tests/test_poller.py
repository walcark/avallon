"""The git poller: when it runs, and what it survives."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from avallon.web import poller


def test_the_interval_defaults_to_something_sane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AVALLON_POLL_INTERVAL", raising=False)

    assert poller.interval() == poller.DEFAULT_INTERVAL


@pytest.mark.parametrize(("raw", "expected"), [("30", 30), ("0", 0), ("bruit", 120)])
def test_the_interval_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: int
) -> None:
    monkeypatch.setenv("AVALLON_POLL_INTERVAL", raw)

    assert poller.interval() == expected


def test_a_zero_interval_disables_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AVALLON_POLL_INTERVAL", "0")

    assert poller.start(tmp_path) is None


def test_a_tree_without_a_remote_is_not_polled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing to pull from, nothing to push to."""
    monkeypatch.setenv("AVALLON_POLL_INTERVAL", "30")

    assert poller.start(tmp_path) is None


def test_a_failing_sync_does_not_kill_the_poller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead poller is worse than a missed tick."""
    from avallon.notes import sync

    calls: list[int] = []

    def boom(content_dir: Path) -> None:
        calls.append(1)
        raise RuntimeError("git est fâché")

    monkeypatch.setattr(sync, "flush", boom)

    async def run() -> None:
        task = asyncio.ensure_future(poller.poll(tmp_path, every=0.01))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(run())

    assert len(calls) > 1  # it kept going after the first failure
