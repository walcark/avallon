# Roadmap

`docs/model.md` holds the content model. This file tracks what ships when.

## v0.1.0, the first release

The goal is not new features: it is turning a local application into something
that installs, runs on another machine, and can be reached from a phone without
handing the notes to whoever finds the port.

### Packaging

- [ ] Move the code under a single top-level name: `src/avallon/{web,settings,content}`.
      Three top-level modules (`pages`, `config`, `scripts`) cannot ship to PyPI:
      the names are generic, they collide, and they are not ours.
- [ ] One distribution, `avallon`. There is no standalone CLI here, only
      maintenance commands for the site, which make no sense without it.
- [ ] `pyproject.toml`: metadata, entry point, dependency pins.
- [ ] `pandoc` and `fzf` are assumed, not vendored: they come from conda-forge,
      so the supported install is pixi. `pip install` gets the Python parts and
      the README says what is missing.

### One command

- [ ] `avallon <subcommand>` replaces the `pixi run` tasks and the loose
      scripts: `serve`, `init`, `repo`, `new`, `move`, `sync`, `export`,
      `add-domain`, `add-type`, `check`.
- [ ] `avallon init` accepts a **clone URL**, not only a local path.
- [ ] No content directory configured is an error telling the user to run
      `avallon init`, instead of silently falling back to a directory inside the
      installation.

### Safe by default

- [ ] `SECRET_KEY` read from the environment, generated at setup, never in the
      repository.
- [ ] `DEBUG` off by default, `ALLOWED_HOSTS` configurable.
- [ ] Access token, no-op on loopback, **required** for any other bind. Since
      pages are HTML served to a browser and not an API consumed by a SPA, the
      token is exchanged once for a signed session cookie.

### Multi-device

- [ ] Git poller: a long-running server is one more writer among the devices,
      so it pulls on a timer to reflect what was written elsewhere.
- [ ] `avallon setup` / `avallon install`: env file and systemd user unit, with
      the bind address and port chosen at setup.

### Tests and CI

- [ ] ruff, mypy and pytest through a `dev` pixi environment, with the tasks
      `fmt`, `fmt-check`, `lint`, `type-check`, `test`, `all`.
- [ ] A real suite: content model (dossiers, membership, tag threshold,
      backlinks, wikilink resolution), taxonomy, git sync, and the views
      through Django's test client.
- [ ] `ci.yml`: format, lint, types, tests on every push and pull request.
- [ ] `release.yml`: a `v*` tag builds the sdist and the wheel and publishes to
      PyPI through Trusted Publishing (OIDC), no stored token.

### Docs

- [x] `README.md`, user guide and de facto specification.
- [x] `docs/model.md`, the content model.
- [x] `LICENSE`, Apache 2.0.

## v0.2.0, portable

The site is read on a phone as much as on a desktop, and today it is only
usable on one of the two.

- [ ] **CSS audit at 390 px** and the fixes it turns up: tables need their own
      horizontal scroll container, touch targets need 44 px, the editor toolbar
      and the virtual keyboard have to coexist.
- [ ] **Navigation**: the drawer opens on a swipe from the edge, actions move
      within thumb reach, search goes full screen instead of floating in a
      panel sized for a laptop.
- [ ] **PWA**: manifest, icons and a service worker. That is what gives the
      icon on the home screen, full screen without the address bar, and
      offline reading. This, not a rewrite in React, is what makes it feel like
      an app.
- [ ] Reference for these choices: Obsidian mobile, which solves the same
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
