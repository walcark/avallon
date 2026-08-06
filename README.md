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

> **Status.** v0.1.0. What comes next, and why, is in
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
| ` ```python ` | syntax-highlighted code (Pygments) |
| `!!! note` / `!!! warning` | admonition cards |
| `$…$`, `$$…$$` | LaTeX math (MathJax) |
| `{rouge}(texte)` | inline coloured span |
| ` ```gallery `, ` ```plot `, ` ```csv `, ` ```query ` | content blocks |
| `- [ ]` | task lists |

Every page shows what cites it, so a note is never a dead end.

## Commands

| Command | What it does |
| --- | --- |
| `avallon serve` | Run the site (see [Server](#server)). |
| `avallon init <path\|url>` | Initialize or adopt a notes repository, make it active. |
| `avallon repo [path]` | Print or switch the active repository. |
| `avallon new` | Scaffold a page (domain and type picked from the taxonomy). |
| `avallon add-file <path>` | Promote a file to a page of its own. |
| `avallon move <page>` | Re-file a page under another domain/type. |
| `avallon sync` | Pull, commit, push. `--local` commits without the network. |
| `avallon export <page>` | Export a page to `.docx` or `.pdf` (needs pandoc). |
| `avallon add-domain <name>` | Extend the taxonomy. |
| `avallon add-type <name>` | Extend the taxonomy. |
| `avallon check` | Verify every page sits under a declared domain/type. |
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
| `AVALLON_SYNC_WINDOW` | `900` | Seconds during which consecutive edits fold into one commit. |
| `AVALLON_POLL_INTERVAL` | `120` | Seconds between two pulls; `0` disables the poller. |
| `AVALLON_ALLOWED_HOSTS` | loopback | Comma separated names the site answers to. |
| `AVALLON_SECRET_KEY` | *(generated per process)* | Django secret key. `avallon setup` writes a fixed one. |
| `AVALLON_DEBUG` | `0` | Debug mode. Never on when exposed. |

## Finding things again

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
git tag v0.1.0 && git push origin v0.1.0
```

## License

Apache License 2.0, see [`LICENSE`](LICENSE).
