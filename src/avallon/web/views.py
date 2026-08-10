import asyncio
import json
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import render
from django.views.decorators.http import require_POST

from avallon.notes import sync

from . import content, exporter, security

# How often the stream re-checks the watched file's modification time (seconds).
POLL_INTERVAL = 0.3


# Query parameters, English first. The French spellings are still read, since
# they are baked into breadcrumb links of pages already written.
_FACET_PARAMS = {
    "domains": ("domain", "domaine"),
    "types": ("type",),
    "kinds": ("kind",),
    "statuses": ("state", "etat"),
    "projects": ("dossier", "project"),
    "tags": ("tag",),
}

# How many results a page renders. Beyond that the answer is "narrow it down",
# not "scroll": nobody pages through their own notes.
PAGE_SIZE = 60


def _active_facets(request):
    """The facet values the request asks for, per facet name."""
    return {
        name: [v for key in keys for v in request.GET.getlist(key) if v]
        for name, keys in _FACET_PARAMS.items()
    }


def _explorer_context(request):
    """Everything the explorer needs: the selection, its view mode, the echo."""
    active = _active_facets(request)
    selection = content.select(
        query=request.GET.get("q", ""), limit=PAGE_SIZE, **active
    )
    membership = content.membership()

    query = request.GET.get("q", "")
    view = request.GET.get("view", "")
    if view not in ("grid", "cards"):
        # Guessed from what was selected: a set of images should not render as
        # a list of titles. An explicit `view=` always wins.
        view = "grid" if selection.is_visual else "cards"

    # Each axis gets the control its cardinality warrants, rather than one
    # uniform widget. Domains and types are closed and small, and will stay
    # small: chips show every value with its count, one tap away. Dossiers grow
    # without limit, so they become a menu, which is also the better control on
    # a phone since the OS renders it. Tags are the extreme case, in the
    # hundreds, and have their own page; here they only appear once one is
    # active, so a selection arrived at from a tag link can still be undone.
    facets = [
        {
            "param": "domain",
            "label": "Domain",
            "values": selection.facets["domain"],
            "active": active["domains"],
            "translate": False,
            "control": "chips",
        },
        {
            "param": "type",
            "label": "Type",
            "values": selection.facets["type"],
            "active": active["types"],
            "translate": False,
            "control": "chips",
        },
        {
            "param": "kind",
            "label": "Kind",
            "values": selection.facets["kind"],
            "active": active["kinds"],
            "translate": True,
            "control": "chips",
        },
        {
            "param": "state",
            "label": "State",
            "values": selection.facets["status"],
            "active": active["statuses"],
            "translate": True,
            "control": "chips",
        },
        {
            "param": "dossier",
            "label": "Dossier",
            "values": selection.facets["project"],
            "active": active["projects"],
            "translate": False,
            "control": "menu",
        },
        {
            "param": "tag",
            "label": "Tags",
            "values": selection.facets["tag"],
            "active": active["tags"],
            "translate": False,
            "control": "chips",
            "only_when_active": True,
        },
    ]
    facets = [f for f in facets if f["active"] or not f.get("only_when_active")]
    active_count = sum(len(f["active"]) for f in facets)

    return {
        "selection": selection,
        "facets": facets,
        "active_count": active_count,
        "view": view,
        "query": request.GET.get("q", ""),
        "active": active,
        "cards": [
            {
                "page": page,
                "project": membership.get(page.relpath),
                "snippet": selection.snippets.get(page.key, ""),
                # A document leads to the file itself, so the card must not
                # read as a page one is about to open.
                "is_document": isinstance(page, content.Asset),
                "title_html": content.highlight_title(page.title, query),
            }
            for page in selection.pages
        ],
    }


def home(request):
    """The explorer: one selection, narrowed by facets and by text alike.

    Both are resolved server-side and rendered together, so filtering on a kind
    and then typing narrows the same set instead of replacing it, and the URL
    says exactly what is on screen.
    """
    return render(request, "home.html", _explorer_context(request))


def tags_index(request):
    """Every tag, with its weight, each leading to its own selection.

    Tags left the home page because there are hundreds of them; this is where
    they are surveyed instead. Seeing them ranked is also the only way to spot
    the near-duplicates worth merging, which is what this page is for as much
    as navigation.
    """
    counts = content.tag_counts()
    return render(
        request,
        "tags.html",
        {
            "tags": counts,
            "total": sum(n for _, n in counts),
            # Alphabetical is the other way one looks for a tag: by name, when
            # the name is already known.
            "alphabetical": sorted(counts),
        },
    )


def capture(request):
    """Write an idea down now, decide where it belongs later.

    GET is the form, and also the PWA share target, so anything shared from
    another application on a phone arrives here already filled in. POST files
    it and returns to where the capture started, because a capture that takes
    you somewhere else is one you stop making.

    The domain and type are asked for but remembered, and the page is marked
    `à trier`: the vocabulary is not optional here, so the honest thing is to
    say the answer was guessed rather than to invent a place for it.
    """
    if not may_edit(request):
        raise Http404("Editing unavailable")

    vocab = content.vocabulary()
    shared = " ".join(
        part
        for part in (request.GET.get("text", ""), request.GET.get("url", ""))
        if part.strip()
    )
    error = ""

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        body = request.POST.get("body", "").strip()
        domain = request.POST.get("domain", "").strip()
        type_ = request.POST.get("type", "").strip()
        try:
            page = content.create_page(
                domain,
                type_,
                title or (body.splitlines() or [""])[0][:80],
                [],
                status=content.CAPTURED,
            )
        except content.InvalidPage as exc:
            error = str(exc)
        else:
            if body:
                index_md = content.CONTENT_DIR / page.relpath / "index.md"
                content.save_source(
                    index_md, content.read_source(index_md).rstrip() + f"\n\n{body}\n"
                )
            _commit_page(page.relpath, action="capture")
            return HttpResponseRedirect(request.POST.get("back") or page.url)

    return render(
        request,
        "capture.html",
        {
            "domains": vocab["domains"],
            "types": vocab["types"],
            "title": request.GET.get("title", ""),
            "body": shared,
            "back": request.GET.get("back", ""),
            "error": error,
        },
    )


def upkeep(request):
    """One screen answering "what is waiting for me?".

    Scattered nags are ignored one by one; a single place can be visited on
    purpose. Everything here is derived from the tree, so nothing has to be
    kept up to date for it to stay true.
    """
    pages = content.all_pages()
    open_pages = [
        {
            "page": page,
            "tasks": content.open_tasks(page),
            "days": content.days_since(page),
        }
        for page in pages
        if page.status in (content.CAPTURED, "en cours")
    ]
    # Stalest first: what has been left alone longest is what is rotting, and a
    # page untouched for a week is not the one that needs looking at.
    open_pages.sort(key=lambda row: -(row["days"] or 0))

    return render(
        request,
        "upkeep.html",
        {
            "captured": [r for r in open_pages if r["page"].status == content.CAPTURED],
            "ongoing": [r for r in open_pages if r["page"].status == "en cours"],
            "total_tasks": sum(r["tasks"] for r in open_pages),
            # Standing alone is not a fault, it is the one thing that makes a
            # page unreachable except by searching for it.
            "orphans": content.orphans(),
            # A page cannot be finished and still carry things to do.
            "contradictions": [
                page
                for page in pages
                if page.status == "terminé" and content.open_tasks(page)
            ],
        },
    )


def explore(request):
    """The explorer fragment alone, for the browser to swap in as you type."""
    return render(request, "_explorer.html", _explorer_context(request))


# A generic sheet, served when a thumbnail cannot be produced. Inline rather
# than a static file: it is the fallback, so it must not depend on anything.
_SHEET_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 64">'
    '<rect x="4" y="2" width="40" height="60" rx="3" fill="#e8e3d9"/>'
    '<path d="M12 18h24M12 28h24M12 38h16" stroke="#a9a091" stroke-width="3"/>'
    "</svg>"
)


def thumbnail(request, relpath):
    """A thumbnail: the first page of a PDF, cached on disk.

    *relpath* is a page, or a page and one of the documents beside it, since a
    document indexed on its own has no page of its own to name.

    Images are their own thumbnail and never reach here. Anything else, and any
    machine without poppler, gets a generic sheet: the grid must not depend on
    a binary being installed.
    """
    target = content.safe_resolve(relpath)
    if target.is_file():
        # A document beside a page: /thumb/<page>/<file>.
        source = target
        kind = content.kind_of_file(target.name)
    else:
        index_md = target / "index.md"
        if not index_md.is_file():
            raise Http404("Page not found")
        page = content.load_page(index_md)
        source = index_md.parent / page.file if page.file else None
        kind = page.kind

    if kind != "pdf" or source is None or not source.is_file():
        return HttpResponse(_SHEET_SVG, content_type="image/svg+xml")

    cached = content.thumbnail_path(source)
    if cached is None:
        return HttpResponse(_SHEET_SVG, content_type="image/svg+xml")
    return FileResponse(open(cached, "rb"), content_type="image/jpeg")


def manifest(request):
    """The web app manifest, rendered so its name follows the language."""
    return render(
        request,
        "manifest.webmanifest",
        {
            # Matches the stylesheet's --bg / --accent in the light theme, so
            # the splash screen does not flash a different colour.
            "background": "#faf9f6",
            "theme": "#2a5d8f",
        },
        content_type="application/manifest+json",
    )


def service_worker(request):
    """Serve the worker from the root.

    A worker only controls what sits under its own URL, so one served from
    /static/ would control /static/ and nothing else.
    """
    path = Path(__file__).resolve().parent / "static" / "avallon" / "pwa" / "sw.js"
    return FileResponse(
        open(path, "rb"),
        content_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


def page_history(request):
    """The last recorded states of a page, as the menu behind the date."""
    relpath = request.GET.get("path", "").strip("/")
    content.safe_resolve(relpath)  # refuses anything outside the notes tree
    revisions = content.history(relpath, limit=5)
    return JsonResponse(
        {
            "dirty": content.is_dirty(relpath),
            "revisions": [
                {
                    "sha": r.sha,
                    "when": r.when,
                    "subject": r.subject,
                    "saves": r.saves,
                }
                for r in revisions
            ],
        }
    )


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
        vocab = content.vocabulary()

        # Reading an older state: the markdown comes from that commit, and so do
        # its images (see the asset branch below), so the page is never a mix of
        # two dates.
        at = request.GET.get("at", "").strip()
        revision = None
        if at:
            old_text = content.at_revision(page.relpath, at)
            if old_text is None:
                raise Http404("Unknown revision")
            revision = next(
                (r for r in content.history(page.relpath, limit=20) if r.sha == at),
                None,
            )
            html = content.render_markdown_text(old_text.decode("utf-8"), index_md)
        else:
            html = content.render_markdown(index_md)

        return render(
            request,
            "index.html",
            {
                "page": page,
                "revision": revision,
                "at": at,
                "content_html": html,
                "relpath": page.relpath,
                "reading_minutes": content.reading_minutes(index_md),
                "backlinks": content.backlinks(page),
                # The dossier this page belongs to: `project` names it above
                # the title, `dossier` is what the sidebar browses. Both are
                # derived from the pages themselves, so a dossier's contents
                # can never fall behind.
                "project": content.project_of(page),
                "dossier": content.dossier_nav(page),
                # A text document is shown as itself rather than as a download
                # button. Capped, because a page is not a file viewer: past a
                # few hundred lines the browser's own is the better tool.
                "file_text": content.attached_text(page),
                # Destinations offered by the "move" control in the editor:
                # exactly the declared taxonomy, like the creation form.
                "domains": vocab["domains"],
                "types": vocab["types"],
            },
        )

    if target.is_file():
        # An asset sits next to the index.md that uses it, so it inherits that
        # page's visibility: serving figures from a hidden page would leak it.
        sibling = target.parent / "index.md"
        if sibling.is_file():
            content.load_page(sibling)  # raises Http404 when private
        at = request.GET.get("at", "").strip()
        if at and sibling.is_file():
            page_rel = str(sibling.parent.relative_to(settings.CONTENT_DIR))
            blob = content.at_revision(page_rel, at, target.name)
            if blob is not None:
                return _served(HttpResponse(blob), target)
        return _served(FileResponse(open(target, "rb")), target)

    raise Http404("Page not found")


def _served(response, target: Path):
    """Set the headers a document is served with, by what it is.

    Two things a browser will not show on its own. A `.sh`, a `.py`, an `.eml`
    are text, but the type guessed from their extension is one no browser
    renders, so they were offered as downloads while a `.txt` beside them
    displayed: they are declared `text/plain`, which is what they are.

    And markup is rendered rather than downloaded, but under a sandbox: a
    merchant's page saved as evidence is worth *seeing*, and is exactly the
    kind of file that carries scripts. The sandbox puts it in an opaque origin
    with scripts off, so it draws as itself and can do nothing as this site.
    """
    suffix = target.suffix.lower()
    response["X-Content-Type-Options"] = "nosniff"
    if content.kind_of_file(target.name) == "text" and suffix not in (
        ".html",
        ".htm",
        ".xhtml",
    ):
        response["Content-Type"] = "text/plain; charset=utf-8"
        response["Content-Disposition"] = f'inline; filename="{target.name}"'
    elif suffix in (".html", ".htm", ".xhtml"):
        response["Content-Type"] = "text/html; charset=utf-8"
        response["Content-Disposition"] = f'inline; filename="{target.name}"'
        response["Content-Security-Policy"] = "sandbox"
    return response


def may_edit(request) -> bool:
    """Whether *request* is allowed to write to the content tree.

    Every write funnels through this one predicate. Reading is already gated by
    the middleware, so this is the same answer for now; keeping it separate is
    what will allow a read-only session later without auditing every view.
    """
    return security.is_unlocked(request)


def _editable_page(relpath: str):
    """Resolve *relpath* to an editable page, or raise Http404.

    Reuses the reader's checks on purpose: ``safe_resolve`` refuses paths that
    escape the content tree, and ``load_page`` refuses a page hidden by
    ``SHOW_PRIVATE``, so the editor cannot reach what the site will not serve.
    """
    index_md = content.safe_resolve(relpath) / "index.md"
    if not index_md.is_file():
        raise Http404("Page not found")
    content.load_page(index_md)
    return index_md


def _commit_page(relpath: str, action: str = "edit") -> bool:
    """Commit the saved page, then push in the background. Returns whether a
    commit was made.

    The commit is synchronous because it is local and instant, and because
    answering 200 before the write is recorded would be a lie. The push is
    detached: it is the slow, failure-prone half, and a save must not wait on
    the network.
    """
    content_dir = settings.CONTENT_DIR
    if not sync.is_repo_root(content_dir):
        return False  # not its own repo (dev fallback): saving stays unversioned
    committed, _ = sync.commit_scoped(
        content_dir, f"{action} {relpath}", window=sync.sync_window()
    )
    if committed:
        sync.spawn_flush(content_dir)
    return committed


def new_page(request):
    """Create a page from the browser: the form on GET, the page on POST.

    Domain and type are offered from taxonomy.toml only, so the web cannot
    create what `avallon check` would then flag as out of vocabulary.
    """
    if not may_edit(request):
        raise Http404("Editing unavailable")

    vocab = content.vocabulary()
    form = {
        "domain": "",
        "type": "",
        "title": "",
        "tags": "",
        "summary": "",
        "project": "",
    }
    error = ""

    if request.method == "POST":
        form = {k: request.POST.get(k, "").strip() for k in form}
        tags = [t for t in re.split(r"[,\n]+", form["tags"]) if t.strip()]
        upload = request.FILES.get("file")
        try:
            if upload is not None:
                # Same form, same vocabulary: attaching a file only decides
                # what the page shows, not what kind of thing it is.
                page = content.create_document(
                    form["domain"],
                    form["type"],
                    form["title"],
                    upload.name,
                    upload.read(),
                    [t.strip() for t in tags],
                    summary=form["summary"],
                    project=form["project"],
                )
            else:
                page = content.create_page(
                    form["domain"],
                    form["type"],
                    form["title"],
                    [t.strip() for t in tags],
                    form["summary"],
                    form["project"],
                )
        except (content.InvalidPage, content.RejectedUpload) as exc:
            error = str(exc)
        else:
            _commit_page(page.relpath, action="new")
            # Straight into the editor, because a page created from the browser
            # is empty. A document is not: it already shows what was filed, so
            # it opens on itself.
            return HttpResponseRedirect(page.url if page.file else page.url + "#edit")

    return render(
        request,
        "new.html",
        {
            "domains": vocab["domains"],
            "types": vocab["types"],
            "form": form,
            "error": error,
            # Existing tags, offered as clickable chips so they get reused
            "known_tags": content.all_tags(),
            # Existing dossiers, so a new page can join one at birth, and
            # every other page after them: a dossier is not declared anywhere,
            # a page *becomes* one the moment another names it. Without the
            # second group the first dossier could never be created here.
            "projects": content.all_projects(),
            "candidates": content.dossier_candidates(),
        },
    )


def page_source(request):
    """Return a page's raw Markdown (`?path=<relpath>`), for the editor.

    The ``mtime`` travels with the text and must come back on save: it is what
    lets the server tell an ordinary write from one that would silently
    overwrite an edit made meanwhile in a local text editor.
    """
    if not may_edit(request):
        raise Http404("Editing unavailable")
    index_md = _editable_page(request.GET.get("path", ""))
    return JsonResponse(
        {"text": content.read_source(index_md), "mtime": content.page_mtime(index_md)}
    )


@require_POST
def save_page(request):
    """Write a page's Markdown back to disk, then commit it.

    Answers 409 when the file moved under the editor and 400 when the
    frontmatter would no longer parse, rather than saving something that
    breaks the page.
    """
    if not may_edit(request):
        raise Http404("Editing unavailable")
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Unreadable request."}, status=400)

    relpath = str(payload.get("path", ""))
    index_md = _editable_page(relpath)
    text = payload.get("text")
    if not isinstance(text, str):
        return JsonResponse({"error": "Missing content."}, status=400)

    try:
        # A title change would strand every link written to the old one, so the
        # old title becomes an alias at the moment it stops being the title.
        previous = content.title_of(content.read_source(index_md))
        new_title = content.title_of(text)
        if previous and new_title and previous != new_title:
            text = content.add_alias(text, previous)
        content.save_source(index_md, text, payload.get("mtime"))
    except content.InvalidFrontmatter as exc:
        return JsonResponse({"error": f"Invalid frontmatter: {exc}"}, status=400)
    except content.StaleEdit:
        return JsonResponse(
            {
                "error": "The file changed on disk since the editor opened it. "
                "Reload the page to start from the current version.",
            },
            status=409,
        )

    committed = _commit_page(relpath)
    # Re-read *after* committing: the content repo's pre-commit hook stamps
    # `updated:` into the frontmatter, so the text and the mtime the editor
    # holds are already out of date by the time we answer.
    page = content.load_page(index_md)
    return JsonResponse(
        {
            "text": content.read_source(index_md),
            "mtime": content.page_mtime(index_md),
            "title": page.title,
            "committed": committed,
        }
    )


@require_POST
def upload_document(request):
    """Store an uploaded file as a document page, and answer with its slug.

    Referencing a document is creating a page for it: the browser then inserts
    `![[slug]]`, so the file lives in one place and every note that shows it
    points at the same page. This is `avallon add-file` reachable from a phone,
    which is the only way to file anything when the site runs on a server.
    """
    if not may_edit(request):
        raise Http404("Editing unavailable")

    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"error": "No file submitted."}, status=400)

    # Beside the page by default. A file there is already a document: indexed,
    # filterable by kind, part of that page's dossier. Wrapping it in a page of
    # its own is the exception, for what deserves a title and a date of its own.
    page_path = request.POST.get("beside", "").strip()
    if page_path:
        try:
            asset = content.attach_file(page_path, upload.name, upload.read())
        except content.RejectedUpload as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        _commit_page(page_path, action="attach")
        return JsonResponse(
            {
                "url": asset.url,
                "kind": asset.kind,
                "file": asset.file,
                "snippet": content.markdown_for(asset),
            }
        )

    vocab = content.vocabulary()
    domain = request.POST.get("domain", "").strip()
    type_ = request.POST.get("type", "").strip() or DOCUMENT_TYPE
    if type_ not in vocab["types"]:
        type_ = vocab["types"][0]
    if domain not in vocab["domains"]:
        return JsonResponse({"error": f"Undeclared domain: {domain}"}, status=400)

    try:
        page = content.create_document(
            domain,
            type_,
            request.POST.get("title", "").strip(),
            upload.name,
            upload.read(),
            [
                t.strip()
                for t in re.split(r"[,\n]+", request.POST.get("tags", ""))
                if t.strip()
            ],
            summary=request.POST.get("summary", "").strip(),
            project=request.POST.get("project", "").strip(),
            doc_date=request.POST.get("doc_date", "").strip(),
        )
    except (content.RejectedUpload, content.InvalidPage) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    _commit_page(page.relpath, action="add document")
    return JsonResponse(
        {
            "slug": page.slug,
            "title": page.title,
            "url": page.url,
            "kind": page.kind,
            # What to write in the citing note: an embed shows the document
            # where it is cited, which is what someone dropping a file wants.
            "snippet": f"![[{page.slug}]]",
        }
    )


@require_POST
def move_page(request):
    """Re-file a page under another domain/type (its directory moves on disk).

    The slug is kept, so the page's assets and the wikilinks pointing at it by
    slug keep resolving; only its URL changes, which the browser follows via
    the ``url`` returned here. Answers 400 on an undeclared destination or a
    slug collision, rather than moving the page somewhere it cannot live.
    """
    if not may_edit(request):
        raise Http404("Editing unavailable")
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Unreadable request."}, status=400)

    relpath = str(payload.get("path", ""))
    # Same guards as the reader: refuse a path escaping the tree or a page the
    # site would not serve, before touching anything on disk.
    _editable_page(relpath)
    try:
        page = content.move_page(
            relpath, str(payload.get("domain", "")), str(payload.get("type", ""))
        )
    except content.InvalidPage as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    _commit_page(page.relpath, action=f"move {relpath} ->")
    return JsonResponse({"url": page.url})


# A document page says what it is *for* through its type like any page; `doc`
# is the one for a page whose whole purpose is to hold the file. The *kind*
# (pdf, image, office) is derived from the extension, and is a separate axis.
DOCUMENT_TYPE = "doc"


_EXPORT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


def export_page(request):
    """Download a note as a styled Word document (``?format=pdf`` for a PDF).

    The document is built in a temp dir and streamed back as an attachment;
    nothing is written into the content tree. Reuses the reader's path guards
    so only a servable page can be exported.
    """
    index_md = _editable_page(request.GET.get("path", ""))
    page = content.load_page(index_md)
    fmt = request.GET.get("format", "docx")
    if fmt not in _EXPORT_TYPES:
        raise Http404("Unknown export format")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"{page.slug}.{fmt}"
        try:
            if fmt == "pdf":
                exporter.export_pdf(index_md, out)
            else:
                exporter.export_docx(index_md, out)
        except exporter.ExportError as exc:
            return JsonResponse({"error": str(exc)}, status=500)
        data = out.read_bytes()

    response = HttpResponse(data, content_type=_EXPORT_TYPES[fmt])
    response["Content-Disposition"] = f'attachment; filename="{page.slug}.{fmt}"'
    return response


async def markdown_stream(request):
    """Server-Sent Events endpoint: watch one page's index.md mtime and push
    the freshly rendered HTML whenever it changes. The page to watch is given
    by `?path=<relpath>`, so live-reload works for any page. The browser swaps
    it into `.prose` in place, keeping scroll position and UI state."""
    target = content.safe_resolve(request.GET.get("path", ""))
    index_md = target / "index.md"
    if not index_md.is_file():
        raise Http404("Page not found")
    content.load_page(index_md)  # refuse to stream a page that is not visible

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

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # disable proxy buffering (e.g. nginx)
    return response
