"""ASGI entry point.

Static files are handled by WhiteNoise in the middleware, so the Django
application is all uvicorn needs, with or without debug.

The lifespan protocol is handled here rather than passed on: Django does not
implement it, and it is the one hook that runs once per process, inside the
event loop uvicorn is about to drive. That is exactly what the git poller
needs, so it starts on startup and is cancelled on shutdown.
"""

from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "avallon.settings.settings")

from django.core.asgi import get_asgi_application  # noqa: E402

django_application = get_asgi_application()

from django.conf import settings  # noqa: E402

from avallon.web import poller  # noqa: E402


async def _lifespan(receive: Any, send: Any) -> None:
    """Run the poller for the lifetime of the server process."""
    task = None
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            task = poller.start(settings.CONTENT_DIR)
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            if task is not None:
                task.cancel()
            await send({"type": "lifespan.shutdown.complete"})
            return


async def application(scope: dict[str, Any], receive: Any, send: Any) -> None:
    """Dispatch to Django, keeping the lifespan protocol for ourselves."""
    if scope["type"] == "lifespan":
        await _lifespan(receive, send)
        return
    await django_application(scope, receive, send)
