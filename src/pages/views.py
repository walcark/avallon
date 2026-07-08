import asyncio
import json

from django.http import (
    FileResponse,
    Http404,
    HttpResponsePermanentRedirect,
    StreamingHttpResponse,
)
from django.shortcuts import render

from . import content

# How often the stream re-checks the watched file's modification time (seconds).
POLL_INTERVAL = 0.3


def home(request):
    """Central page: lists every page in the content tree.

    Filtering (domain/type/tags) and full-text search come in phase 2."""
    return render(request, "home.html", {"pages": content.all_pages()})


def serve_content(request, relpath):
    """Resolve a hierarchical URL to either a Markdown page or a co-located
    asset (image, etc.) sitting next to it in the content tree."""
    target = content.safe_resolve(relpath)
    index_md = target / "index.md"

    if target.is_dir() and index_md.is_file():
        # Enforce a trailing slash so relative image paths in the Markdown
        # (e.g. `![](fig.png)`) resolve under this page's own URL.
        if not request.path.endswith("/"):
            return HttpResponsePermanentRedirect(request.path + "/")
        page = content.load_page(index_md)
        return render(
            request,
            "index.html",
            {
                "page": page,
                "content_html": content.render_markdown(index_md),
                "relpath": page.relpath,
            },
        )

    if target.is_file():
        return FileResponse(open(target, "rb"))

    raise Http404("Page introuvable")


async def markdown_stream(request):
    """Server-Sent Events endpoint: watch one page's index.md mtime and push
    the freshly rendered HTML whenever it changes. The page to watch is given
    by `?path=<relpath>`, so live-reload works for any page. The browser swaps
    it into `.prose` in place, keeping scroll position and UI state."""
    target = content.safe_resolve(request.GET.get("path", ""))
    index_md = target / "index.md"
    if not index_md.is_file():
        raise Http404("Page introuvable")

    async def event_stream():
        # When the client disconnects, the ASGI server closes this generator
        # (raising GeneratorExit here), so the loop ends on its own.
        last_mtime = None
        while True:
            try:
                mtime = index_md.stat().st_mtime
            except FileNotFoundError:
                mtime = None
            if mtime != last_mtime:
                last_mtime = mtime
                # Markdown rendering is CPU work; keep the event loop free.
                html = await asyncio.to_thread(content.render_markdown, index_md)
                # JSON-encode so the (multi-line) HTML fits a single SSE
                # `data:` line; the client JSON.parses it back.
                yield f"event: update\ndata: {json.dumps(html)}\n\n"
            await asyncio.sleep(POLL_INTERVAL)

    response = StreamingHttpResponse(
        event_stream(), content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # disable proxy buffering (e.g. nginx)
    return response
