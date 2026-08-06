"""Keep the working copy fresh while the server runs.

A long-running server is one more git writer among the devices, coordinated
with the others through the remote. It must therefore *pull* on a timer to
reflect what was written elsewhere, and push what was written here.

The work itself is :func:`avallon.notes.sync.flush`, which already pulls,
pushes, drains and takes the shared lock; this is only the "every N seconds"
wrapper. The blocking git call runs in a thread so it never stalls the event
loop, and every failure is swallowed: a dead poller is worse than a missed
tick.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Long enough that a laptop opening its lid does not fire a burst of them,
# short enough that a page written on the phone shows up on the desktop while
# still thinking about it.
DEFAULT_INTERVAL = 120


def interval() -> int:
    """Seconds between two pulls; 0 disables the poller."""
    raw = os.environ.get("AVALLON_POLL_INTERVAL")
    if raw is None:
        return DEFAULT_INTERVAL
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_INTERVAL


async def poll(content_dir: Path, every: int | None = None) -> None:
    """Pull and push *content_dir* forever, every *every* seconds."""
    from avallon.notes import sync

    period = interval() if every is None else every
    if period <= 0:
        return
    while True:
        await asyncio.sleep(period)
        try:
            await asyncio.to_thread(sync.flush, content_dir)
        except Exception:  # noqa: BLE001 - a poller must outlive its failures
            logger.warning("poller: sync failed", exc_info=True)


def start(content_dir: Path) -> asyncio.Task[None] | None:
    """Start the poller on the running loop, or return None when disabled.

    Returns the task so the caller can keep a reference: an asyncio task that
    nobody holds can be garbage collected mid-flight.
    """
    from avallon.notes import sync

    if interval() <= 0 or not sync.is_repo_root(content_dir):
        return None
    if not sync.has_origin(content_dir):
        return None  # nothing to pull from, nothing to push to
    return asyncio.ensure_future(poll(content_dir))
