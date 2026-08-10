# Roadmap

`docs/model.md` holds the content model. This file tracks what ships when.

## v0.3.0, documents without ceremony

Filing a document stopped requiring a page for it. What was there all along
became visible: 47 files sat beside pages and not one was declared, so the kind
filter showed nothing while a dossier's sixteen exhibits were on disk.

- [x] **A file beside a page is a document**, at any depth, indexed as it
      stands. It inherits that page's domain, type, tags, date and dossier, and
      leads to itself rather than to a page about it.
- [x] **The kind facet counts them at all times**, being the switch that
      reveals them; it cannot be derived from a selection that excludes them.
- [x] Searched by **filename** and by their page's title and tags, never by its
      body, or a compte rendu would answer with all four of its figures.
- [x] **Uploading stores the file beside the page** and writes plain Markdown.
      Promotion to a page of its own remains, for what deserves a title, a date
      of the document and an identity several notes can cite.
- [x] **Every document opens in the browser**: text declared as text, saved
      markup rendered under a sandbox rather than handed over as a download.
- [x] Four mobile faults, one of which hid the dossier filter outright.

## v0.5.0, the reader's own language

- [x] **A language switch in the top bar.** The language was a property of the
      process, so one reader switching it switched it for every device reading
      the same server, and it took a restart to apply at all. It is answered
      per request now, from a cookie, with the configured value as the default.

## v0.4.0, not withering

A note site rots two ways: ideas never land because writing them down costs too
much, and pages pile up half-done with nothing pointing at them again. This
release is about both, plus the hole that capture opened by making pages cheap.


- [x] **Capture**, org-mode fashion: one box from anywhere, a PWA share target
      on a phone, filed `à trier` and handed back to where you were.
- [x] **`/entretien/`**: what is waiting, read from the tree. Captures to file,
      anything marked open or still carrying unticked boxes, contradictions,
      and pages nothing cites.
- [x] **Deleting a page**, saying first what it strands, and recorded as a
      commit of its own so it can be brought back.
- [x] **`/corbeille/`**, a trash read from git rather than a folder of its own,
      restoring a page with the documents filed under it.
- [x] **A dead link that offers a way out**: restore the page, or drop the link
      and keep the words. A target that never existed stays inert.
- [x] **`avallon version`**, for when a running site behaves like an older one.

### Next

- [ ] The lightbox for an image opened from the results, rather than a new tab.
- [ ] Renaming and merging tags, now that `/tags/` makes the duplicates visible.
- [ ] Print stylesheet as a second path to PDF, for a server without
      LibreOffice.
- [ ] `docs/documents.md` is still in French while the rest of the project is
      in English.

## v0.2.0, reachable from a phone

The site could be read anywhere and only administered from a terminal. This
release closes that gap, and pays two debts the first one left.

- [x] **Documents from the browser.** A document is a page whose `file:` is
      what it is for; uploading one creates that page, and `![[slug]]` shows it
      inside a note. Two ways in: the creation form, and a button plus
      drag-and-drop and paste while editing.
- [x] **The editor takes the screen.** It was capped at the reading measure and
      kept the page header above it, while the title was being typed in the
      frontmatter just below.
- [x] **The past of a page.** The date opens the last five recorded states,
      grouped into editing sessions, with the file of that same commit.
- [x] **Links that keep working.** Aliases, `avallon rename`, `check-links` in
      the pre-commit hook, and a resolution rule where a page bearing a name
      always beats a page that merely bore it.
- [x] **Facets by cardinality**, folded on a phone; tags moved to their own
      page; `chantier` retired as a type, being a status.
- [x] **A stylesheet that can change again**: the service worker was serving
      `/static/` cache-first under URLs that never varied.


## v0.1.0, the first release

The goal is not new features: it is turning a local application into something
that installs, runs on another machine, and can be reached from a phone without
handing the notes to whoever finds the port.

### Packaging

- [x] Move the code under a single top-level name: `src/avallon/{web,settings,notes}`.
      Three top-level modules (`pages`, `config`, `scripts`) cannot ship to PyPI:
      the names are generic, they collide, and they are not ours.
- [x] One distribution, `avallon`. There is no standalone CLI here, only
      maintenance commands for the site, which make no sense without it.
- [x] `pyproject.toml`: metadata, entry point, dependency pins.
- [x] `pandoc` and `fzf` are assumed, not vendored: they come from conda-forge,
      so the supported install is pixi. `pip install` gets the Python parts and
      the README says what is missing.

### One command

- [x] `avallon <subcommand>` replaces the `pixi run` tasks and the loose
      scripts: `serve`, `init`, `repo`, `new`, `move`, `sync`, `export`,
      `add-domain`, `add-type`, `check`.
- [x] `avallon init` accepts a **clone URL**, not only a local path.
- [x] No content directory configured is an error telling the user to run
      `avallon init`, instead of silently falling back to a directory inside the
      installation.

### Safe by default

- [x] `SECRET_KEY` read from the environment, generated at setup, never in the
      repository.
- [x] `DEBUG` off by default, `ALLOWED_HOSTS` configurable.
- [x] Access token, no-op on loopback, **required** for any other bind. Since
      pages are HTML served to a browser and not an API consumed by a SPA, the
      token is exchanged once for a signed session cookie.

### Multi-device

- [x] Git poller: a long-running server is one more writer among the devices,
      so it pulls on a timer to reflect what was written elsewhere.
- [x] `avallon setup` / `avallon install`: env file and systemd user unit, with
      the bind address and port chosen at setup.

### Tests and CI

- [x] ruff, mypy and pytest through a `dev` pixi environment, with the tasks
      `fmt`, `fmt-check`, `lint`, `type-check`, `test`, `all`.
- [x] A real suite: content model (dossiers, membership, tag threshold,
      backlinks, wikilink resolution), taxonomy, git sync, and the views
      through Django's test client.
- [x] `ci.yml`: format, lint, types, tests on every push and pull request.
- [x] `release.yml`: a `v*` tag builds the sdist and the wheel and publishes to
      PyPI through Trusted Publishing (OIDC), no stored token.

### Docs

- [x] `README.md`, user guide and de facto specification.
- [x] `docs/model.md`, the content model.
- [x] `LICENSE`, Apache 2.0.

## v0.2.0, portable

The site is read on a phone as much as on a desktop, and it used to be usable
on only one of the two. Interface language moved here too: the project ships
publicly, so it defaults to English and `avallon language` switches it.

- [x] **CSS audit at 390 px** and the fixes it turns up: tables need their own
      horizontal scroll container, touch targets need 44 px, the editor toolbar
      and the virtual keyboard have to coexist.
- [x] **Navigation**: the drawer opens on a swipe from the edge, actions move
      within thumb reach, search goes full screen instead of floating in a
      panel sized for a laptop.
- [x] **PWA**: manifest, icons and a service worker. That is what gives the
      icon on the home screen, full screen without the address bar, and
      offline reading. This, not a rewrite in React, is what makes it feel like
      an app.
- [x] Reference for these choices: Obsidian mobile, which solves the same
      problem (a tree, linked notes, long reading, Markdown editing on a small
      screen).

## Later

- [ ] Retire the `chantier` type: it is a status, and the model already treats
      it as one. Blocked on re-filing about fifteen pages by hand, which changes
      their URLs.
- [ ] Wikilink resolution relative to the dossier first, then global, so two
      dossiers can both hold a `[[mail-retour]]`.
- [ ] Full-text search served from an index rather than a scan, if the tree
      ever grows enough to notice.
