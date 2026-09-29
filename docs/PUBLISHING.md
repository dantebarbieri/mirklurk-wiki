# Publishing to the live wiki

Merging to `main` publishes. The repository generates every managed page, and
`tools/sync_wiki.py` brings the live wiki up to date through MediaWiki's normal
edit API. There is no edit freeze, rehearsal, or manual approval step. Pages
that a person edited on the wiki are skipped, never overwritten, unless a
maintainer explicitly adopts them (see below).

**Interface exception:** `MediaWiki:Sidebar` is operator-managed, not generated.
Merging its reviewed artifact does **not** activate or update site navigation.
The sync report always calls out this boundary; see [Native sidebar](#native-sidebar).

## From change to live

**Lua rollout prerequisite:** the operator must separately approve and deploy
the rebuilt Scribunto-enabled image before merging a release that uses the
[display templates](TEMPLATES.md). A merge only publishes content; it does not
deploy the image. Missing runtime, namespaces, content models, invalid Lua or
a failed engine probe stop the apply run before any page edits. The read-only
preview checks registration without logging in or executing the console probe.

**Mobile presentation has two parts:** publishing updates the ordinary
table/figure wrappers and Lua grid output, not the skin's runtime viewport.
The operator separately rebuilds/recreates the image with
`$wgVectorResponsive = true` after the wrappers are present. See
[responsive Vector rollout](DEPLOYMENT.md#responsive-vector-2022).
No Common.css or JavaScript namespace is added to the publisher.

1. Change `content/` (or the generator) on a branch and open a pull request.
2. CI runs the publication gate, the unit tests and the PHP runtime checks
   (about 2 minutes), plus the disposable Docker smoke (about 10–15 minutes).
   A read-only **preview** job shows which live pages the change would create
   or update.
3. Merge. On `main` the same checks run again, then the **publish** job runs
   `python3 tools/sync_wiki.py --apply`. Changed pages are usually live about
   15 minutes after the merge.

The job summary of each run lists what was created, updated, skipped and
refreshed. Runs on `main` queue in order and none is dropped: every merge and
every manual run, including adoption requests, is validated and published in
turn, and a publish is never cut off midway.

## What the sync does

For every generated page it reads the latest live revision (50 pages per
request) and then:

| Live page | Action |
| --- | --- |
| Missing | Create it (`createonly`) |
| Same text, ignoring trailing whitespace | Leave it alone |
| Last saved by the publishing automation | Update it (`nocreate`, `baserevid`) |
| Last saved by anyone else | **Skip it** and report it |

The *publishing automation* is a revision saved by `WikiAdmin`, the account
the sync logs in as, or any member of the `bot` group, with a summary that
starts with `repo-sync:` (this tool) or with one of the earlier publication
summaries (`native-publication/v1:`, `Publish reviewed `,
`Original repository seed`). Each sync save ends its summary with
`text:<hash>` of the text it meant to store, and a `repo-sync:` revision
counts only while its text still matches that hash. MediaWiki's own
`MediaWiki default`, `Maintenance script` and `imported>` identities also
count, because nobody can log in as them.

Writes follow the transclusion graph: a page whose views others include is
saved before the pages that include it. A page is only saved once every view it
includes exists in its owner's text as the wiki will serve it. If the owner is
still to be saved in this run, the page waits for it. If the owner failed or a
person edited it without that view, the page is listed as *blocked* and a
later run retries it. Merchants and items include views of each other, so when
pages in such a cycle wait only on each other, one is saved first. After
writing, the sync re-renders every automation-owned page that was rendered
before a page it includes was saved, or that shows a link to a page this run
created, by re-saving the exact text it just read with that revision as
`baserevid` (a null edit). Inclusion counts through nested views too: a
workstation that shows an item's recipe view, which shows a source's loot
view, is re-rendered when that source changes. Readers therefore see the new
content immediately, without waiting for MediaWiki's job queue; the preview
lists these pages too. Pages people edited, and the dependents of an
interrupted publish, are left to the queue, which catches up as the wiki is
used.

This includes ordinary Template transclusions, `#invoke` and static
`mw.loadData`/`require` module edges, not just selective main-namespace views.
Only the registered display/row templates, the Unverified marker and their two Lua modules are
publishable outside main/Category namespaces. Lua uses the `Scribunto` content
model and `text/plain`, never wikitext. Presentation cycles or missing generated
dependencies are rejected before writes. Display pages do not need selective
`view` declarations. A divergent human-edited template/module is skipped and
blocks new or changed dependent readers until reviewed/ported and explicitly
adopted; a failed module/template save also blocks dependent readers instead
of publishing against an older definition. Existing readers are not removed.

Finally it re-reads every page it saved and fails the run if the stored text
differs from the generated text, which catches wikitext that MediaWiki's
pre-save transform would change. It also lists `[[File:...]]` references that
are not on the wiki yet.

The sync never deletes, moves or renames pages and never uploads files. A page
dropped from the generator stays on the wiki until someone removes it.

### Retired research pages

The publication check builds the entire indexed page set, not the working copy.
The disposable MediaWiki smoke parses every reader page to check visible text,
tooltips, transcluded views, uncertainty markers and retirement links.

The reader cleanup keeps these managed titles so normal sync can replace their
old content safely:

| Title | Redirect target |
| --- | --- |
| Evidence and spoilers | Main Page |
| Research policy | Main Page |
| Source provenance | Game mechanics |
| Getting started | Starting equipment |

The source ledger remains available in repository data and the local audit
renderer, not under another public title. No article links to the retired
research titles. `World seed logic` remains a separate compatibility redirect
to `World generation`.

Before sharing the live cleanup, check the publish report and follow each old
URL. A human-edited legacy page is **skipped**, not retired automatically: port
any useful changes, then explicitly adopt that exact title, or ask an operator
to remove it. Do the same for any human-edited navigation that still links there.
Page history is retained; redirects replace current content, not past revisions.
Merging publishes automatically, so review and authorization must precede merge.

`baserevid` turns a person's save in the seconds between the read and the
write into an edit conflict. MediaWiki can instead merge non-overlapping
changes; the sync notices that the page changed underneath it and reports a
conflict. The merged revision keeps both edits, and because it no longer
matches its `text:` hash, later runs treat the page as a person's edit. The
same holds if a response is lost: the run reports an error, and a save that
merged someone's edit is never mistaken for the automation's.

## When a person edits a generated page

The sync skips the page on every run and warns about it until it is resolved:

1. If the edit is worth keeping, port it into `content/` so the generator
   produces it, and merge. While the live text matches the repository, the
   page is simply *unchanged* and no warning appears.
2. When the generated text next differs from the live page, the warning
   returns. Hand the page back: **Actions → Validate and publish → Run
   workflow** on `main`, with the page title in *adopt* (separate several
   titles with `|`). That run replaces the page, and later runs update it
   normally. Adopting a page whose text already matches does nothing yet; the
   run lists it under *Adoption waits for a change*.

To discard the person's edit instead, adopt the page without porting anything;
the edit stays in the page history.

## Images

Image bytes never enter Git. When a run lists missing images, import the
approved files on the server as described in [IMAGES.md](IMAGES.md); until
then the page shows a red file link. Nothing else waits on images.

## Native sidebar

The single source for the proposed native menu is
[`content/interface/Sidebar.wiki`](../content/interface/Sidebar.wiki).
It replaces the external MediaWiki help link with **Editing help**, adds the
existing Items, Bestiary, NPCs, Merchants, Crafting and Game mechanics hubs,
and retains Main page, Random page, Recent changes, search, the native toolbox
and language links. Crafting lists inventory crafting and workstations;
Game mechanics covers survival, combat and progression. No game facts change.

The artifact uses native `*` / `** target|label` sidebar syntax, internal
titles and MediaWiki's standard main-page/random/recent-changes message keys.
Do not replace them with a hostname or an `index.php` URL. Vector controls its
own accessible desktop/mobile menu; no navigation JavaScript, custom CSS or
per-article navigation template is required.

### One-time activation and later updates

**Dependency:** publish and verify the editing-help release's `Help:Editing`
article **before activating** this sidebar. That separate release owns the
article; this repository artifact does not create a placeholder help page.
If the article is missing or skipped by its publisher, defer sidebar activation.
The encyclopedia destinations are already canonical generated pages.

1. Obtain separate operator approval. Use a trusted human session with the
   `editinterface` right (normally an administrator) to edit `MediaWiki:Sidebar`.
   Its wikitext does not require `editsitecss`, `editsitejs` or interface-admin
   privileges. Do **not** expand the publication bot password's grants, add
   interface rights to ordinary contributors, or add credentials to CI.
2. Verify every destination above and `Help:Editing` exists on the target wiki.
   Open `MediaWiki:Sidebar` and its history using the wiki's search/title UI.
   Compare the live text and latest revision with the previously installed
   artifact (or the default menu on first installation). Preserve local links
   and useful human changes: review and port them to the artifact in a PR
   before proceeding. A divergent human edit is a stop for review, not
   permission to overwrite it.
3. Open **Edit source** on that live revision, paste the approved artifact and
   inspect **Show changes**. Save with a descriptive summary naming the reviewed
   commit, not a `repo-sync:` summary. If another editor saves meanwhile,
   resolve the normal MediaWiki edit conflict by reviewing the new revision;
   never force a stale copy over it. Keep the prior revision ID for rollback.
4. Check the actual anonymous Vector menu on both a wide and a narrow screen.
   Open the collapsed main menu, follow each link, and use keyboard navigation
   to reach Editing help. Confirm Recent changes and Special pages remain
   available. Reload with browser caching disabled if the old menu is cached.
   Record the installed commit and wiki revision in the operator change log.
   To roll back, review subsequent human edits and undo only the operator's
   sidebar revision through page history.

The file is on the exact-file Git publication allowlist with a 2 KiB budget,
but is deliberately absent from `build_pages()`, generated XML, and all sync
create/update/refresh/adoption operations. `--adopt MediaWiki:Sidebar` is
rejected. A successful publish job therefore says nothing about interface
activation; the separate operator step above is required on **every** update.
The normal human-edit skip and explicit adoption rules for articles are unchanged.

CI installs the exact artifact only in its disposable localhost wiki and checks
the native Vector links on desktop, mobile and mobile without JavaScript,
including keyboard access. Until the editing-help release is present, that
smoke uses a clearly synthetic `Help:Editing` target solely in the disposable
database; it does not validate the future help article or satisfy the live
activation dependency.

## Undoing a release

Every sync revision is an ordinary edit summarized
`repo-sync: <commit> text:<hash>`:

- Revert the commit in Git and merge; the sync publishes the previous text.
- Or undo individual revisions in the page history. The page then counts as
  edited by a person; adopt it when a release next changes it.
- For database-level recovery, restore the regular backup. Test restores on a
  schedule rather than before each release.

No freeze is needed for publishing. For other maintenance, the deployment's
`MW_READ_ONLY` setting still makes the wiki read-only.

## One-time setup

The publish job does nothing (and says so) until these exist.

1. **Bot account.** Signed in as `WikiAdmin`, create an account such as
   `MirkLurkBot` and add it to the `bot` and `administrator` groups at
   `Special:UserRights`. Bot membership exempts its edits from the link
   CAPTCHA and flags them as bot edits; only administrators are exempt from
   the wiki's limit of ten edits a minute. The bot password below still limits
   the automation to editing.
2. **Bot password.** Signed in as that account, open `Special:BotPasswords`,
   create `repo-sync` and grant **High-volume (bot) access**, **Edit existing
   pages** and **Create, edit, and move pages**. Keep the generated password in
   a password manager. Without the administrator group or the high-volume
   grant the sync still works, but it warns and waits out the rate limit,
   which can take longer than the job allows for a large release.
3. **GitHub configuration** for this repository:

   ```sh
   gh variable set MIRKLURK_API_URL --body "https://wiki.example.org/api.php"
   gh secret set MIRKLURK_BOT_USERNAME   # enter MirkLurkBot@repo-sync
   gh secret set MIRKLURK_BOT_PASSWORD   # paste the bot password
   ```

4. Run the workflow once on `main` (**Actions → Validate and publish → Run
   workflow**). When the wiki already matches the repository, it reports no
   changes.

Revoke or regenerate the bot password at `Special:BotPasswords` at any time;
only the GitHub secret needs updating.

## Running the sync by hand

A preview reads public pages only and needs no credentials:

```sh
MIRKLURK_API_URL=https://wiki.example.org/api.php python3 tools/sync_wiki.py
```

To publish from a trusted machine, export `MIRKLURK_BOT_USERNAME` and
`MIRKLURK_BOT_PASSWORD` without typing the password into shell history (for
example `read -rs MIRKLURK_BOT_PASSWORD` then `export MIRKLURK_BOT_PASSWORD`),
and add `--apply`. From PowerShell, set `$env:MIRKLURK_API_URL` and use
`python tools\sync_wiki.py`. Other options: `--adopt TITLE`, `--summary`,
`--automation-account` and `--report FILE` (see `--help`).

The exit status is 0 when every intended write succeeded; skipped, blocked and
conflicting pages are warnings. It is 1 for errors or saved text that differs
from the generated text, and 2 when `--apply` lacks credentials.
