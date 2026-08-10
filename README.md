# avallon

<p align="center"><em>A place where notes are kept, and found again.</em></p>

<p align="center">
  <a href="https://github.com/walcark/avallon/actions/workflows/ci.yml"><img src="https://github.com/walcark/avallon/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://codecov.io/gh/walcark/avallon"><img src="https://codecov.io/gh/walcark/avallon/branch/main/graph/badge.svg"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue">
  <a href="https://pixi.sh"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/prefix-dev/pixi/main/assets/badge/v0.json"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/mypy-checked-2a6db2"></a>
  <img src="https://img.shields.io/badge/tested%20with-pytest-0a9edc?logo=pytest&logoColor=white">
  <img src="https://img.shields.io/badge/Django-092E20?logo=django&logoColor=white">
</p>

A personal note site: every page is a Markdown file in a directory tree that
encodes both its URL and its taxonomy. Pages cite each other with `[[wikilinks]]`
and show their backlinks, group into dossiers, and are found through faceted
browsing or full-text search. Notes live in **their own git repository**, apart
from this tool, and sync across devices on their own.

The content model, and the reasoning behind it, lives in
[`docs/model.md`](docs/model.md). This README is the user guide.

> **Status.** v0.3.0. What comes next, and why, is in
> [`ROADMAP.md`](ROADMAP.md).

## How it works in one picture

```
your machine                              git remote (e.g. GitHub)
------------                              ------------------------
avallon serve  --> reads/writes the notes repo
                   |
                   +--> commit (instant, batched)
                        |
                        +--> [detached] pull + push  ------------> origin
                                                                     ^
another device: the running server polls  <-- pull ----------------- +
```

- **One directory per page**, holding `index.md` and its images.
- **Instant local commit** on every save, network sync in the background.
- **The tool and the notes are two repositories.** Upgrading one never touches
  the other.

## Requirements

- Python 3.11+
- `git`
- [`pandoc`](https://pandoc.org) for the Word/PDF export
- [LibreOffice](https://www.libreoffice.org) for the PDF specifically, and so
  for a page's download button; the `.docx` export needs only pandoc
- [`fzf`](https://github.com/junegunn/fzf) for the interactive pickers
- [`ripgrep`](https://github.com/BurntSushi/ripgrep) *(optional)*: full-text
  search falls back to a pure-Python scan without it

`pandoc` and `fzf` are not Python packages. The supported install is through
[pixi](https://pixi.sh), which brings them along.

## Install

```bash
pixi global install avallon      # brings pandoc and fzf
pip install avallon              # Python parts only, see Requirements
```

## Setup a notes repository

The notes live in their own git repository, separate from this tool. Point
avallon at it once:

```bash
avallon init ~/notes                          # local path
avallon init git@github.com:you/notes.git     # or a clone URL
```

`init` creates the layout, makes the repository active, and remembers its path
in `~/.config/avallon/config.toml`. The created repository looks like:

```
notes/
├── taxonomy.toml          # the declared domains and types
└── <domain>/<type>/<slug>/
    ├── index.md
    └── figure.png         # assets sit next to the page that uses them
```

`init` and `repo` are **create-or-validate**:

| Target | What happens |
| --- | --- |
| Path does not exist | `mkdir` + `git init` + full scaffold |
| Existing directory, not a git repository | `git init` + scaffold what is missing |
| Existing repository, already conformant | adopted as is |
| Existing repository with unrelated content | asks for confirmation first |
| A clone URL | cloned into `~/<repo-name>`, then validated |

### Switch repositories

```bash
avallon repo                 # print the active notes repository
avallon repo ~/other-notes   # switch to another one (same rules)
```

## Pages

A page is a directory holding an `index.md`. Its path is both its URL and its
taxonomy:

```
content/<domain>/<type>/<slug>/index.md   ->   /<domain>/<type>/<slug>/
```

- **domain**: what the page is about (`informatique`, `administratif`, ...). A
  subject, never a context: "work" or "personal" is a tag, because a page can
  be both.
- **type**: what the page is (`fiche`, `cr`, `tutoriel`, `recueil`).

Both are declared in `taxonomy.toml`, and a page cannot be born under an
undeclared pair. Extend the vocabulary with `avallon add-domain` /
`avallon add-type`, check the tree with `avallon check`.

### Frontmatter

```yaml
---
title: Page title
date: 2026-07-01        # creation, set once
updated: 2026-07-08     # last change, stamped on commit
tags: [smartg, flux]
summary: One sentence, shown on the home page.
project: recours-batterie   # slug of the page indexing the dossier (optional)
status: en cours            # en cours | terminé | abandonné (optional)
visibility: private         # local only, never served elsewhere (optional)
---
```

### Documents

A file worth looking for on its own becomes a page, with `avallon add-file`:

```
administratif/doc/carte-identite/
├── index.md          # title, tags, doc_date, and `file:`
└── carte.png
```

The page shows the file above the notes about it. What it shows is decided by
the extension, never by the type: a `cr` carrying a scan displays it exactly as
a `doc` would.

| `kind` | From | Shown as |
| --- | --- | --- |
| `note` | no `file:` | the body alone, as always |
| `image` | png, jpg, webp, svg | the image |
| `pdf` | pdf | an inline viewer, thumbnail in grids |
| `text` | txt, md, csv, code | download |
| `office`, `archive` | docx, zip… | download |

`kind` is derived, never typed: the type says what a page *is* and nobody can
check it, while the medium is already written in the file name.

The test for promoting a file: **would I look for it on its own?** If not, leave
it as an illustration next to the page that uses it.

A file used by several notes is a document by definition: promote it once, then
show it where it is needed with `![[slug]]`. One copy, one set of tags, one URL,
and updating it updates every note that shows it.

### Dossiers

A dossier is not a new kind of object: **it is an ordinary page**, the one that
introduces it, and its pages name it in their `project:`. The site derives the
rest, so nothing has to be kept up to date by hand:

- the dossier's page lists its own pages, grouped by type;
- the sidebar browses the dossier instead of the whole tree while you are in it;
- each page names the dossier it belongs to, and search shows it too.

Titles can therefore stay short ("Mail retour"): the dossier places them.

**Belonging is not citing.** A page enters a dossier when it will be archived
with it; a durable note the dossier merely cites stays outside and is linked
with `[[…]]`, so it outlives the dossier it was written during.

### Writing

Standard Markdown, plus:

| Syntax | What it does |
| --- | --- |
| `[[slug]]`, `[[slug\|label]]` | link another page, by slug, path or title |
| `[[figure.pdf]]` | link a file sitting next to the page |
| `![[carte-identite]]` | show a document here; the file stays in its own page |
| `![[carte-identite\|Recto]]` | the same, with a caption |
| `![[dossier/verso.png]]` | one file of a multi-file document |
| ` ```python ` | syntax-highlighted code (Pygments) |
| `!!! note` / `!!! warning` | admonition cards |
| `$…$`, `$$…$$` | LaTeX math (MathJax) |
| `{rouge}(texte)` | inline coloured span |
| ` ```gallery `, ` ```plot `, ` ```csv `, ` ```query ` | content blocks |
| `- [ ]` | task lists |

Every page shows what cites it, so a note is never a dead end.

### Links that keep working

A link points at a slug, so it already survives a page changing domain, type or
title. What it would not survive is the directory being renamed, so nothing
renames one silently:

- **`avallon rename <page> "New title"`** records the former slug and the
  former title as `aliases:` before moving anything. Resolution tries the slug
  first, then the aliases, so every link written against the old name keeps
  landing on the page. Editing the title in the browser does the same.
- **`avallon check-links`** verifies that every `[[link]]` resolves, and the
  pre-commit hook runs it on the staged pages. It reports rather than blocks: a
  half-written dossier still commits.
- A page that deliberately shows unresolvable examples opts out with
  `check_links: false` in its frontmatter.

**A name is either taken or freed.** The name a page goes by *now* belongs to
it alone: creating or renaming onto a name another page currently bears is
refused, across the whole tree rather than within a folder, because a link
designates a page site-wide. A *former* name is free, and giving it to a new
page is allowed: the new bearer wins every `[[name]]`, while the old page keeps
the alias so links written before the rename still land. Should two pages ever
claim one freed name, nothing resolves at all: a dead link is visible and
fixable, a working link to the wrong page is neither.

### Documents

**A file sitting beside a page is already a document.** It is indexed as it
is, with no page of its own and nothing to declare: it inherits that page's
domain, type, tags, date and dossier, which is what "identify a document by the
folder it is in" amounts to. A result leads to the file itself, not to a page
about it.

At any depth, because depth says nothing about what a file is: a dossier keeps
its exhibits in `pieces/`, and those are the most document-like things there
are, while a note keeps its working set in `data/`. The **extension** separates
them and does the whole job on its own, so no list of folder names has to be
guessed at: a `.nc` grid and a `.pyc` are not kinds this site knows, and never
appear. A document is named by its path under its page, so two files of the
same name in two subfolders stay distinct.

Every document opens in the browser rather than downloading. A `.sh`, a `.py`
or an `.eml` is text, but the type guessed from its extension is one no browser
renders, so they are declared `text/plain`, which is what they are. Saved markup
(`.html`) is rendered, under `Content-Security-Policy: sandbox`: a merchant's
page kept as evidence is worth *seeing*, and is exactly the kind of file that
carries scripts, so the sandbox puts it in an opaque origin with scripts off.
It draws as itself and can do nothing as this site.

Documents stay out of the default listing, which is about pages, and come in
the moment a **kind** is asked for: that facet counts them at all times, so
`image` is offered on the home page even when the listing holds none. They are
searched by **filename** and by their page's title and tags, never by its body,
or one compte rendu would answer with all four of its figures.

Promoting one to a page of its own stays possible, and is the exception: a page
buys a title, a date of the document distinct from the filing date, tags of its
own and an identity several notes can cite. That page is **a page whose `file:`
is what it is for**. It has a domain, a type, tags, a date and a dossier like any
page, and only its display differs, driven by the file's extension rather than
by the page's type: an image and a pdf are shown as themselves, a text file is
printed, anything needing software to open is a download button.

That is what makes a scan findable on its own, filterable by kind, and part of
a collection. Citing it is citing a page:

| Written in a note | What it does |
| --- | --- |
| `[[carte-identite]]` | links the document's page |
| `![[carte-identite]]` | shows the document right there, the file staying in its own page |

**Filing one from the browser**, which is the only way when the site runs on a
server: attach a file in the creation form, or, while editing a note, use *Add
a document* (dropping a file on the source, or pasting a screenshot, does the
same). The file becomes its own page and the reference is written at the caret.
`avallon add-file` does the same from a terminal.

Uploads are capped at 20 Mo, because git keeps every version of a binary and a
deleted scan still weighs its size in the history forever. Only extensions the
site knows how to classify are accepted, which is also what keeps a `.html`
from being served as part of the site.

### The past of a page

The date in a page's label is a button. It lists the **last five recorded
states** as `YYYY/MM/DD-hh:mm`, and opening one shows the page as it was then,
under a banner with the way back to the present. Images and attached files come
from that same commit, so a state of last week never shows today's scan.

History follows relocations: a page moved from `administratif/` to `perso/`
keeps one continuous story, reconstructed by git rather than recorded by hand.
A page edited and not yet committed says so, instead of pretending the last
commit is what is on screen.

**Sessions, not saves.** Commits on the same page less than
`AVALLON_HISTORY_WINDOW` seconds apart (an hour by default) read as one state:
fixing three typos in an afternoon should not spend the whole menu. The entry
shows how many saves it stands for, and opens the last of them, which is what
the session ended on. Nothing is rewritten, git keeps every commit; only the
menu groups them.

Times are shown in the machine's timezone, not in the one each commit recorded.
Notes written from a laptop and from a server in UTC would otherwise read two
hours apart when they were saved at the same moment.

Next to it, a download button, adapted to what the page holds: **the file
itself** when the frontmatter carries a `file:`, the **page as a PDF**
otherwise. The PDF is rendered by the machine running the site, so it is the
same document whether the button is clicked from a laptop or a phone (it needs
pandoc and LibreOffice there, see [Requirements](#requirements)).

## Commands

| Command | What it does |
| --- | --- |
| `avallon serve` | Run the site (see [Server](#server)). |
| `avallon init <path\|url>` | Initialize or adopt a notes repository, make it active. |
| `avallon repo [path]` | Print or switch the active repository. |
| `avallon new` | Scaffold a page (domain and type picked from the taxonomy). |
| `avallon add-file <path>` | Promote a file to a page of its own. |
| `avallon move <page>` | Re-file a page under another domain/type. |
| `avallon rename <page> <title>` | Rename a page, keeping every link to it alive. |
| `avallon sync` | Pull, commit, push. `--local` commits without the network. |
| `avallon export <page>` | Export a page to `.docx` or `.pdf` (needs pandoc). |
| `avallon add-domain <name>` | Extend the taxonomy. |
| `avallon add-type <name>` | Extend the taxonomy. |
| `avallon check` | Verify every page sits under a declared domain/type. |
| `avallon check-links` | Verify every `[[link]]` resolves. |
| `avallon language [en\|fr]` | Print or switch the interface language. |
| `avallon stamp` | Fill missing `date:` / `updated:` in the frontmatter. |
| `avallon setup` | Write the deployment env file (address, port, token). |
| `avallon install` | Install and start the systemd user unit. |

## Server

### Quick start (local)

```bash
avallon serve                 # 127.0.0.1:8000
avallon serve --port 8800
```

The browser is also the editor: `Ctrl+E` opens the raw Markdown of the page,
saving writes the file and commits it. `Ctrl+K` opens the command palette,
`Ctrl+N` creates a page. What you type is re-rendered live.

### Access token

Binding anywhere other than loopback **requires** a token:

```bash
AVALLON_TOKEN=$(openssl rand -hex 32) avallon serve --host 10.8.0.2
```

The guard is a no-op when no token is set, which is only safe on loopback, so
the command refuses any other bind without one. The token is the second layer,
behind the network boundary: it is what stands between your notes and any other
device that can reach the port.

### Deploy (systemd + wireguard)

```bash
avallon setup      # write the env file, generate a token
avallon install    # install and start a systemd user unit
```

The unit binds the address given at setup, and the notes repository is polled
on a timer so pages written on another device show up without a restart.

### Configuration

| Variable | Default | What it does |
| --- | --- | --- |
| `AVALLON_CONTENT_DIR` | the configured repository | Override the notes location. |
| `AVALLON_TOKEN` | *(none)* | Bearer token required for every request. |
| `AVALLON_HOST` / `AVALLON_PORT` | `127.0.0.1` / `8000` | Bind address. |
| `AVALLON_LANGUAGE` | `en` | Interface language: `en` or `fr`. |
| `AVALLON_SHOW_PRIVATE` | on in debug | Serve pages marked `visibility: private`. |
| `AVALLON_SYNC_WINDOW` | `900` (`0` from `avallon setup`) | Seconds during which consecutive edits fold into one commit. |
| `AVALLON_HISTORY_WINDOW` | `3600` | Seconds under which two commits on a page read as one state. `0` shows every commit. |
| `AVALLON_TIME_ZONE` | the machine's | Zone the dates are displayed in. |
| `AVALLON_POLL_INTERVAL` | `120` | Seconds between two pulls; `0` disables the poller. |
| `AVALLON_ALLOWED_HOSTS` | loopback | Comma separated names the site answers to. |
| `AVALLON_SECRET_KEY` | *(generated per process)* | Django secret key. `avallon setup` writes a fixed one. |
| `AVALLON_DEBUG` | `0` | Debug mode. Never on when exposed. |

## Finding things again

### Search

A term matches **at the start of a word**, not anywhere inside one. That is the
difference between `ALIS` finding one page and finding twenty, half of them for
`pénalise`; and matching a prefix rather than a whole word is what lets a query
narrow while it is being typed, and finds `batteries` from `batterie`.

Results are ranked by **where the terms matched**, not by date. A term is worth
what its strongest field is worth:

| Where it matched | Weight |
| --- | --- |
| The title, as a whole word | highest |
| The title, as a prefix | high |
| A tag | high |
| The summary | medium |
| The body | low, with a capped bonus for repetition |

A page carrying every term **in the order typed, contiguously** gets a bonus,
double when that run is in the title. Recency only separates pages the score
cannot. Before this, ordering was recency alone, so a page whose title *was*
the query routinely lost to one mentioning it in passing, which is why the
search bar went unused.

Quotes still *require* a phrase, and an unclosed one searches the phrase typed
so far, so results appear while it is being written.



The home page is one **selection**, not a listing with a search box beside it.
Facets and text narrow the same set, and the URL says what is on screen:

```
/?domain=administratif&kind=image        every administrative image, as a grid
/?domain=administratif&kind=image&q=id   the same grid, narrowed by typing
/?dossier=recours-batterie               one dossier
```

Search takes words or phrases: `batterie mesure` narrows on both words wherever
they appear, `"batterie non conforme"` requires the run as written. Without
quotes, pages that do contain the run are ranked first anyway. Accents,
apostrophes and dashes are folded, so `l'etiquette` finds `l’étiquette`.

Every facet shows how many pages each value would leave, and a facet that
cannot divide the current selection is not shown at all. A selection whose
pages all carry a thumbnail renders as a grid; `&view=cards` or `&view=grid`
overrides the guess.

A stored query renders the same three ways:

````markdown
```query
tag: identité
as: gallery      # table (default) | list | gallery
```
````

So an "identity documents" page is one query, and it stays correct when a
passport is added tomorrow.

**Cache and freshness.** The stylesheets are requested with a fingerprint of
their own bytes (`style.css?v=…`), so the service worker can keep serving them
cache-first, offline and instantly, while an upgrade still shows up on the next
load. Pages themselves are fetched network-first: a note that changed on
another device is worse stale than slow.

### Starting a dossier

A dossier is not declared anywhere and has no type of its own: **a page becomes
one the moment another page names it** in `project:`. So starting a dossier is
picking, in the creation form's *Dossier* field, the page that will index it.
The field offers existing dossiers first and every other page after them, which
is what makes the first dossier possible without editing frontmatter by hand.

### Tags

Tags are not on the home page: there are hundreds of them, and a facet listing
them all crowded out the axes one actually filters on. They live on **`/tags/`**
instead, where every tag appears twice over, ranked by weight and again
alphabetically. Ranking is what makes the near-duplicates visible: `batterie`
and `batteries` end up next to each other, and one of them is a typo.

A tag still narrows the same selection as any facet (`/?tag=banque`), and the
tag facet reappears on the home page as soon as one is active, so a selection
reached from a tag link can be undone.

## Not withering

Two things make a personal wiki rot: ideas that never land because writing them
down costs too much, and pages left half-done that nothing ever points at
again.

**Capture** answers the first. `Ctrl+Shift+C` from anywhere opens one box,
which hands you back to where you were; on a phone, avallon is a **share
target**, so anything shared from another application arrives here already
filled in. The domain and type are asked for but remembered, and the page is
filed `à trier`: the vocabulary is not optional, so the honest thing is to say
the answer was guessed rather than to invent a place for it.

**`/entretien/`** answers the second, in one screen read from the tree:

| | |
| --- | --- |
| To file | captures whose place has not been chosen yet |
| Open | pages `en cours`, stalest first, each with what it still has to do |
| Contradictions | a page marked finished that still carries unticked boxes |
| Cited by nothing | not a fault, but the one thing that makes a page reachable only by searching for it |

Unticked task boxes are the measure of *unfinished* here, not length: the
shortest pages in this tree are lists that are complete at forty words.

## On a phone

The site is installable: open it, then "Add to home screen". It runs full
screen, without an address bar, and pages already read stay readable offline
(the notes are cached as you go; writing still needs the network).

The drawer opens on a swipe from the left edge and closes on a swipe left, the
actions sit in a bottom bar within thumb reach, and search takes the screen
rather than floating in a panel sized for a laptop.

## Sync model

Every write commits immediately and locally, then a detached process pulls and
pushes. A save never waits on the network, and being offline only costs a
warning.

**Commit batching.** Consecutive edits fold into a single commit for
`AVALLON_SYNC_WINDOW` seconds, so a page written in ten passes does not leave
ten commits behind. Only commits the tool made itself are amended, recognized
by their trailer.

`avallon setup` writes `AVALLON_SYNC_WINDOW=0` instead, which turns batching
off. Nothing is lost by it: the history panel groups a page's commits back into
sessions when it displays them (`AVALLON_HISTORY_WINDOW`), so recording every
save costs a longer `git log` and buys a history that can be regrouped later,
whereas an amended commit is gone for good.

**Polling.** A long-running server is one more git writer among the devices, so
it pulls on a timer to reflect what was written elsewhere.

## Development

```bash
pixi run serve        # the site, with live reload
pixi run fmt          # ruff format
pixi run lint         # ruff check
pixi run type-check   # mypy
pixi run test         # pytest + coverage
pixi run all          # the four above
```

### Releasing

Version numbers live in `pyproject.toml`. Tagging `vX.Y.Z` and pushing the tag
triggers the release workflow, which builds the sdist and the wheel and
publishes them to PyPI through Trusted Publishing (OIDC), so no token is
stored anywhere.

```bash
git tag v0.3.0 && git push origin v0.3.0
```

## License

Apache License 2.0, see [`LICENSE`](LICENSE).
