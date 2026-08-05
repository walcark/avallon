# The content model

This file is the source of truth for what a page *is*. `ROADMAP.md` tracks
features; this tracks meaning.

## The path is the taxonomy

```
<domain>/<type>/<slug>/index.md   ->   /<domain>/<type>/<slug>/
```

One directory per page, holding `index.md` and its assets. Images are
referenced relatively (`![](figure.png)`) and resolve under the page's own URL,
so nothing rewrites `src` attributes and a page stays movable as a whole.

Encoding the taxonomy in the path buys three things a database would not: the
tree is readable and editable without the tool, `git` sees a rename when a page
is re-filed, and the URL never has to be stored anywhere.

It costs one thing: **re-filing a page changes its URL**. That is why only the
two axes that never change live in the path.

## Four axes, and why they are separate

| Axis | Question | Where it lives | Changes over time |
| --- | --- | --- | --- |
| **domain** | what is it about | path | no |
| **type** | what is it | path | no |
| **status** | where does it stand | frontmatter | yes |
| **project** | what does it belong to | frontmatter | no, but the dossier ends |

The original vocabulary conflated the last three into `type`, which is where
the model was wrong. `fiche`, `cr` and `tutoriel` are **forms**; `recueil` is a
**role**; `chantier` was a **status**. A compte rendu that belongs to an
unfinished dossier is still a compte rendu: it should not have to pretend to be
something else, nor move (and change URL) the day the dossier closes.

### domain

What the page is about, never the context it was written in. "Work" or
"personal" is a tag, because a page can be both. A domain is earned by content,
not declared in advance: under three pages, prefer the closest existing domain
plus a tag.

### type

What the page is, by form. The first "yes" wins:

1. it points elsewhere rather than saying something, it is a **recueil**;
2. it tells about one precise moment, it is a **cr**;
3. it teaches a procedure step by step, it is a **tutoriel**;
4. otherwise, it is a **fiche**.

Both vocabularies are declared in `taxonomy.toml`, at the root of the notes
repository, and a page cannot be born under an undeclared pair. `[labels]` maps
a directory name to what a reader sees (`sante` to `santé`), leaving paths
lowercase and unaccented because they are also URLs.

### status

`en cours`, `terminé`, `abandonné`, or absent when the question is moot, which
is the case for most pages. It shows as a badge on the page, a dot in the
dossier navigation, and a facet on the home page.

Status is the answer to "a note that will be finished one day": it changes,
therefore it cannot be in the path.

### project

A dossier is **an ordinary page**, the one that introduces it, and the pages
that belong to it name it in their `project:`. There is nothing to declare:
writing `project: x` is what makes `x` a dossier. The target is designated the
way a `[[wikilink]]` is (slug, path or title) and resolved by the same
predicate, so a reference that renders as a link cannot fail to designate a
dossier.

The site derives the rest, and therefore it cannot go stale:

- the dossier's page lists its pages, grouped by type;
- the sidebar browses the dossier while the reader is inside it;
- each page names its dossier above its title, and search shows it too;
- titles can stay short ("Mail retour") because the dossier places them.

**Belonging is not citing.** A page enters a dossier when it will be *archived
with it*: the letters of a dispute, the measurements taken for it. A durable
note the dossier merely cites (an article of law, a method) stays outside and
is linked with `[[…]]`, so it outlives the dossier it was written during.
Without that rule, every reusable note ends up buried in a closed dossier.

## Tags

Free text, normalized on read (trimmed, inner whitespace collapsed, lowercased;
accents kept). They enter the home page facets only from `TAG_FACET_MIN` pages
(three) onward.

A tag carried by one page is a link to that page dressed up as a facet: it
costs a row of chips and finds what the search box finds faster. The threshold
lets tags accumulate silently and surface when they start grouping something,
so nothing has to be curated by hand.

## Links

`[[slug]]` cites another page; `[[slug|label]]` renames the link; `[[file.pdf]]`
points at a file sitting next to the page. Resolution accepts the slug, the
full path or the title, case-insensitively.

Links are one-way in Markdown, so the tree is walked to invert them: every page
shows what cites it. Matching is delegated to the extension's own predicate, so
backlinks and rendered links can never disagree about what counts as a
reference.

## Visibility

`visibility: private` marks a page that must never leave the machine. When
`SHOW_PRIVATE` is off, it vanishes from the listings, the navigation, the
search *and* its own URL (404), so publishing the site cannot leak it through a
direct link. Assets inherit the visibility of the page they sit next to.

## Where the notes live

The notes are **their own git repository**, separate from the tool, pointed at
by a machine-local config file. That separation is what lets the tool be
upgraded, reinstalled or replaced without touching the notes, and what lets the
same notes be opened from several devices.

Everything that configures the site *for a given set of notes* lives inside the
notes repository (`taxonomy.toml`), and is therefore versioned and shared. Only
the pointer to the repository is machine-local.

Writes commit immediately and locally; the network sync runs detached. Edits
made within a window fold into a single commit, so a page written in ten passes
does not leave ten commits behind.

## Open question

`chantier` is still a declared type, and the pages filed under it are really
fiches or comptes rendus whose dossier is unfinished. Removing it means
re-filing about fifteen pages by hand (an editorial choice, page by page) and
changing their URLs. The model above already treats it as a status.
