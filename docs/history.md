# Links that always resolve, and the past of a page

Two wishes, stated together but answered separately, because conflating them is
what would make the design wrong:

> Writing `[[a-link]]` and committing should record which commit the target was
> last modified in, and visiting a page should resolve to that.

> The label of a page, an image or a document should carry two buttons: one
> listing the last five modification dates, opening an older state; one
> downloading it, adapted to what it is.

The second is a real feature. The first is a solution to a problem that is not
the one being felt, and the measurements below say why.

## 1. What actually breaks a link

A link breaks when its target's **slug changes**, not when time passes. Today
`[[slug]]` already survives a page moving from one domain or type to another,
because resolution is by slug, not by path. What it does not survive is a
rename.

Recording the target's commit at write time does not fix that, and costs three
things:

- **It goes stale by design.** A link is meant to point at what the note says
  now. Pinning it to the commit that existed when it was typed means every
  target edit leaves every inbound link pointing at an older reading.
- **It denormalizes what git already knows.** `git log -1 -- <path>` answers
  "when did this last change" in 4 ms, measured on this repository. Storing that
  in the linking file is a cache written by hand, in the source, that nothing
  invalidates.
- **It makes the Markdown unwritable by hand.** `[[note@1cf7bc2]]` cannot be
  typed from memory, and the tree stops being editable outside the tool, which
  is the property the whole project is built on.

So the answer to "a link should always resolve" is not to freeze it, but to
**refuse to let it break**:

| Mechanism | What it covers | Cost |
| --- | --- | --- |
| `check-links` in `pre-commit` | a commit that would break an internal link is refused | ~40 lines, and the hook already exists for dates |
| `avallon move` rewriting inbound links | the one operation that breaks links, made safe | ~50 lines |
| `aliases:` in the frontmatter, tried after the slug | every former name of a page, forever | ~30 lines, and the rename writes them itself |

That order matters: the first two remove the cause, the third compensates for
it. `documents.md` already argued for the same sequence.

**Aliases are what got built**, rather than an opaque `id:`. A former name is
readable, a link written against it keeps working, and nothing has to be
migrated when the mechanism is introduced: `avallon rename` records both the
old slug and the old title before moving the directory, so a link never learns
that the page was renamed. Resolution tries the slug, then the aliases, which
costs one extra comparison per candidate on a miss.

## 2. The past of a page is git's job, exposed

The second wish is the interesting one, and everything it needs already exists.
Measured on the notes repository:

| Operation | Time |
| --- | --- |
| `git log -5 --follow -- <path>` | 4 to 19 ms |
| `git show <sha>:<path>` | 2 ms |

`--follow` is what answers the relocation question: a page moved from
`administratif/` to `perso/` keeps one continuous history, and git reconstructs
the rename by similarity, without anything being recorded at write time.

### What the buttons would do

On the page's label, next to the date:

**A history button** listing the last five states as `YYYY/MM/DD-hh:mm`, each
opening the page as it was then, at `/<relpath>/?at=<sha>`, under a banner
saying which state is being read and offering the way back to the current one.

**A download button**, adapted to what the page holds: the file itself when
there is a `file:` (that is what someone wants of a scan), the page as a PDF
otherwise. The export already exists (`avallon export`), so this is a matter of
wiring, with one caveat below.

### Four decisions this forces

**Load the history on click, not on render.** 4 to 19 ms is cheap once, and
noticeable on every page view for a panel most visits never open. It is one
fetch, and it keeps page rendering exactly as fast as it is today.

**An old state renders with the assets of its time.** A "version of 3 August"
showing today's image would be a lie, and this site holds evidence for a
dispute. `git show <sha>:<dir>/<file>` costs the same 2 ms, so the page and its
images come from the same commit. Where an asset did not exist then, the tile
says so rather than falling back silently.

**Outbound links from an old state point at current pages.** Freezing the whole
graph at a commit would mean resolving every `[[…]]` at that date too, which
turns one page view into a walk of the tree's history. The banner says the page
is old; its links are of today.

**The working tree is not the last commit.** A page edited and not yet synced is
newer than anything git knows. The label must distinguish "modified, not yet
recorded" from a committed state, otherwise the history silently lies about what
is on screen.

## 3. The uncomfortable finding: the granularity is not yours

This is the part that changes what the feature is worth.

The sync batches: consecutive edits fold into a single commit for fifteen
minutes, by amending it. That is a good property for a history one reads, and it
means **the five "last modifications" are five commits, not five saves**.

Measured on the notes repository as it stands: 42 commits, of which several are
`batch: N changes`, and one covers **31 files at once**. Most pages have one or
two commits to their name. The dossier pages, written across a whole day, have
exactly one: everything from the split into ten pages to the dossier tagging
landed together.

So the honest description of the feature is: **"see this page at earlier
recorded points"**, not "see every version". Two consequences:

- A page with a single commit shows a single entry, and the button should say
  that rather than opening an empty menu.
- If finer history is wanted, that is a change to the *sync* (a shorter window,
  or a commit per save), not to the history view. The trade is readable history
  against fine history, and it was settled in favour of the second: **one commit
  per modification**, by setting `AVALLON_SYNC_WINDOW=0` on the deployment. The
  history panel then lists five saves rather than five batches, which is what
  the button implies when it shows a time to the minute.

## 4. What I would build, in order

1. **`check-links` in the pre-commit hook.** Small, deterministic, and it makes
   "a link always resolves" true going forward rather than hopefully.
2. **Link rewriting in `avallon move`**, which removes the only routine cause of
   breakage.
3. **The history panel**, fetched on click: five states, `--follow` so
   relocations are part of the story, and a banner when reading an old one.
4. **Old assets served from the same commit**, without which the panel shows a
   mix of two dates.
5. **The contextual download button**: the file when there is one, the page
   otherwise.

Deliberately not built: commits recorded in links, and any index of
`path -> commit`. Both are caches of something git answers in milliseconds, and
a cache that can disagree with the tree is worse than no cache, because the tree
is the product.

## 5. The caveat on the PDF

The current export goes through Pandoc, then LibreOffice for the PDF. Pandoc is
a declared dependency; LibreOffice is not, and it will not be on a small server.
A download button that fails on the machine it matters most on is not a feature.

Three options, cheapest first:

1. **Print stylesheet plus `window.print()`**: the browser makes the PDF, on
   desktop and on phone, with no dependency at all. It is also what a reader
   expects of a page.
2. Keep the Pandoc route, and fall back to `.docx` when LibreOffice is absent.
3. Add a Python PDF writer, which means rendering the site's typography twice
   and keeping the two in step. Not worth it.

**Option 2 is what got built**, for both, because the two software packages
are installed on the server that runs the site. The rendering happens where the
site runs, not on the machine holding the browser: clicking the button from a
phone produces the same PDF as clicking it from a desktop, which is the
property that matters when the point is to hand a document to a bank.

Option 1 stays worth having later, as a second path rather than a replacement:
a print stylesheet costs nothing at runtime and works when the server has
neither package. Noted, not built.

## 6. What the page ended up showing

The date in the label is a button. Clicking it fetches `/history/?path=…` and
drops a menu of at most five entries, each `YYYY/MM/DD-hh:mm` followed by the
commit subject, so a batch is recognisable as one. Choosing an entry reloads
the page at `?at=<sha>`, under a banner naming the state being read and linking
back to the present. The revision is validated as a hexadecimal hash before it
reaches git, so it can never be read as a path.

Two states have their own wording rather than an empty menu: a page modified
and not yet recorded says so, and a page with no commit at all says that too.
Both are ordinary, and both would otherwise look like a bug.

Next to it, the download button: the file when the page carries one, the page
as a PDF otherwise.

## 7. Where the granularity was finally settled

Section 3 said the choice was readable history against fine history, and set it
on the write side. That was the wrong side to decide it on.

Amending is destructive: a commit folded into another cannot be taken apart, so
choosing a window at write time throws away detail forever to make a menu
readable today. Folding at read time costs nothing and is reversible, and the
same `git log` that answers the panel in 4 ms can group its own output.

So both, in opposite directions:

- **`AVALLON_SYNC_WINDOW=0`** on a deployment: every save is a commit, and the
  repository keeps everything that happened.
- **`AVALLON_HISTORY_WINDOW=3600`** in the panel: commits on the same page less
  than an hour apart become one entry, showing how many saves it stands for and
  opening the last of them.

The gap is measured between consecutive commits rather than from the start of a
burst, so an afternoon of steady writing is one session rather than one state
per hour. That chains, deliberately: someone editing every fifty minutes for
six hours is having one long session, not seven.

Two consequences worth stating:

- **The menu can no longer be read as "the last five commits."** It is the last
  five *sessions*, and the count on each line is what says so.
- **A folded entry opens the end of its session**, never a page halfway through
  someone fixing typos. Opening the start would show a state nobody ever
  considered finished.

### The timezone, found by looking

The dates came from `--date=format:`, which renders each commit in the offset
it recorded. The notes repository holds commits in `+0000` (from the server)
and `+0200` (from here), so two states 2h40 apart displayed as 40 minutes
apart, and the folding, which uses true instants, disagreed with what was on
screen for good reason.

`--date=format-local:` fixes the display, and then Django's `TIME_ZONE = "UTC"`
became the visible problem, since it exports `TZ` for the whole process: a note
saved at 14:39 in Paris showed 12:39 in its own history. `TIME_ZONE` now
defaults to the machine's zone, read from `/etc/localtime`, and
`AVALLON_TIME_ZONE` overrides it.

## 8. What aliases cost, and the rule that pays for it

Introducing former names created a question the tree did not have before: if
`batterie` is both the name of a new page and the former name of an older one,
which does `[[batterie]]` mean?

It had an answer, and the answer was wrong. `_resolve` returned the first page
matching, walking the list `all_pages()` returns, which is sorted by recency.
So the winner depended on dates: a page renamed today captured links meant for
a note dated last June. Reproduced on a throwaway tree, with a compte rendu
dated to the event it recounts, which is how this repository dates them.

The rule now is a priority, not an order:

1. **A page that bears the name beats a page that bore it.** Current names are
   matched first, and former names are only consulted when nothing bears it.
2. **Ambiguity is refused, not resolved.** Two pages that were both once called
   the same thing yield nothing, which renders as a dead link someone can see.
   Guessing would render as a working link to the wrong page, in notes that are
   read as evidence.
3. **A current name cannot be given twice.** Creation and renaming refuse it,
   across the whole tree: a folder is not a namespace, because a link is not
   scoped to one. Private pages hold their names too, or the collision would
   appear the day private pages are shown.

Together these make a freed name safely reusable, which is the property that
lets a rename be cheap.

The backlink walker had to follow: it used to ask "does this reference match
me", which was enough while a name designated one page. It now resolves the
reference against the tree and compares, so a link that renders as pointing
elsewhere cannot show up as a backlink here. That doubled its work (4.8 ms to
11.4 ms on this repository, on every page view); folding its two walks into one
and memoizing `slugify` brought it back to 5.4 ms.

Deliberately not built: an index from name to page. It would remove the last
0.6 ms and add a second implementation of the matching rules, which is exactly
the kind of cache that drifts from the tree it describes. Section 4 refused one
for the same reason.
