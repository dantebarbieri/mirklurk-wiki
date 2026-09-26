# Seed and reimport without overwriting the community

The repository produces MediaWiki export 0.11 XML from original wikitext and
vetted facts. It does not perform an import, fetch research files, or synchronize
with a live server. A fresh encyclopedia bundle includes dedicated entity pages,
compact topic indexes, guidance, and explicit compatibility redirects. New
research topics still require reviewed entries/facts. The builder reports the
actual emitted page count.

## Fresh wiki

Generate a new private output from the reviewed repository:

```powershell
python tools\build_wiki.py --fresh --output .local\seed.xml
```

The `--fresh` flag acknowledges that the complete bundle is intended only for a
new wiki. It is not a live-wiki overwrite safeguard by itself.

Before import, keep public access and editing stopped, initialize the database,
and check all existing page titles. MediaWiki's installer normally creates a
default **Main Page**. Do not assume the database has no pages merely because it
was just installed.

The recommended initial procedure preserves that page until an administrator
reviews and replaces its installer boilerplate through the normal edit UI:

1. Keep web access stopped and take a **complete current-page** XML dump using
   `php maintenance/run.php dumpBackup --current`, with output outside Git.
2. Build a missing-title bundle using that export:
   `python tools/build_wiki.py --existing-export CURRENT_XML --output NEW_XML`.
   Here and below, uppercase filenames stand for private local paths.
3. Review the omitted titles and import only the resulting missing-page XML.
4. Review the authored Main Page wikitext separately and save it through the
   administrator's ordinary editing workflow. Never automate replacement of a
   page that somebody has already edited.

Alternatively, on a genuinely disposable fresh instance only, an administrator
can verify and delete the installer-only Main Page before importing all titles.
Do not use that approach for an established wiki.

## Existing wiki: additive only

Back up the database and stop all writers. Export **all current pages**, not a
partial `Special:Export` selection. The builder cannot prove that an operator's
export is complete or current.

`--existing-export` excludes every title present in the dump's main and Category namespaces,
including redirects, regardless of revision timestamps or content. It
normalizes underscores, spaces, and the initial letter for the standard
first-letter English namespaces (0 and 14). Category pages are emitted with
namespace 14, never as colon-named main-space articles. It never includes existing pages for automatic
replacement. Unreadable/malformed exports fail rather than falling back to
fresh mode.

Keep the wiki stopped from snapshot through import. A page created after the
snapshot would otherwise be absent from the exclusion list. Stop background
writers too; a maintenance banner alone is not a concurrency lock.

Review existing-page changes manually using the live page history and editor.
There is no automatic overwrite option, timestamp-based "newer wins" policy,
scheduled import, or force-update mode in this tool.

## Conflict-aware encyclopedia migration

The encyclopedia is a separate reviewed publication, not an automatic update
to an existing wiki. Keep previous authored output **A0**, the approved
published/stored baseline **B**, new authored output **A1**, and materialized
desired output **D** separately. B is the prior publication's exact stored
corpus (the prior D for subsequent releases), not its authored seed. Retain
and hash all four, with their source commits and materialization/baseline
receipts. Separately capture a fresh frozen complete live dump as **current**.
The read-only planner uses B as **base** and D as **desired**, comparing exact
page contents, never revision timestamps:

```powershell
python tools\plan_migration.py --base-export BASE_XML --current-export CURRENT_XML --desired-export DESIRED_XML --output PRIVATE_PLAN_JSON
```

The new output contains title, action, and content SHA-256 values, not page
texts or permission to edit. It refuses to overwrite an existing report.
It cannot prove a supplied dump is complete; that remains an operator gate.

Report schema version 2 lists every `transclusion_dependencies` edge with
`page`, `owner`, exact named `parameters`, `current_view_declared`, and
`current_owner_matches_desired`. It replaces the historical price-only field
names and does not assume a fixed dependency count or one `onlyinclude` pair.
An absent/unknown view is still reported, never silently skipped. A declaration
is a structural check, not proof that live markup parses correctly or approval
of its contents. A matching hash is not authorization to overwrite a page.

Do not expose a new station, seller, merchant, loot, pool, or currency view until its
existing community-owned source has the reviewed selective contract; otherwise
MediaWiki may leak a full article or return the wrong view. Merge owner blocks
through normal conflict-aware edits while preserving community content.
Rebuild and recreate only the app from the approved ParserFunctions runtime
under fresh guarded backups before switching readers. No database, backup,
provider, or authentication configuration change is part of that runtime step.
Keep the unchanged default `{{:Item}}` price and `{{:Coin}}` summary contracts.

`new_page_dependencies` records links and memberships targeting pages absent
from the base seed, including new damage guides and Category pages. Review
creation/collision decisions for those targets before switching existing
navigation. A target's presence does not mean its live content is approved.
Categories receive the same conflict, deletion, and live-edit preservation
rules as main-space articles.

An offline base-versus-base comparison is a rehearsal only, not a current live
export. Always obtain a fresh complete frozen export for publication; never
use the prior seed as a substitute for the live snapshot.

| Action | Meaning |
| --- | --- |
| `create` | Title absent from both base and frozen current; candidate for additive import |
| `unchanged` | Current text already equals desired |
| `review-update` | Current exactly equals base, but desired changed; operator review still required |
| `preserve-live` | Desired equals base; retain the community's changed text |
| `conflict` | Concurrent content changes or a new canonical-title collision; manual three-way review |
| `preserve-deletion` | A base title is missing live; do not automatically recreate it |
| `preserve-retired` / `preserve-unmanaged` | No desired text; never delete historical or community-only pages |

Generate an additive bundle with the existing-title exclusion, then **also
review it against the plan**: additive exclusion alone cannot distinguish a
deliberately deleted old page from a genuinely new page. Omit any
`preserve-deletion` title from the operator-approved creation set. Never import
the full desired seed into an existing wiki to apply the updates.

Ordinary canonical names may already be community pages. Such collisions must
not be taken over: preserve/edit them through reviewed normal revisions, or
agree a new registry title before publication. Verify the frozen current hash
again before each edit and keep writers stopped through the full operation.
An edited page is not an error to work around with an overwrite option.

Old Items, Bestiary, Nature, Skills, Merchants, Crafting, and Loot tables stay
as indexes. Legacy explicit entity/fact/entry anchors remain on their previous
pages and link to the new primary owner. NPCs receives character navigation;
Bestiary keeps collapsed compatibility links to moved character records.
The proposed **Getting started** redirect points to **Research policy**,
where useful evidence/contribution guidance is retained. If live Getting
started has changed, merge useful edits before reviewing any redirect; do
not erase them just because the repository now supplies a redirect.

Renames require explicit registry aliases and a separately reviewed redirect
plan. Do not rename via source-label changes, redirect ambiguous names to one
arbitrary entity, delete old histories, or silently retarget community links.
After migration, verify canonical and legacy links, skill ownership, NPC
classification, all page counts, and preservation of unrelated live edits.
For transcluded information, edit the owner page rather than generated copies.
Verify a canonical price edit updates the merchant view and a coin-weight edit
updates the guide, without importing full item prose into either. Never
skip recipe verification: change a canonical ingredient quantity and AP cost
separately and confirm all corresponding station rows and the normal item page
update. Confirm filtered sellers omit price back-transclusions and all views
are free of parser loops, expansion limits, and owner-article leaks. The
disposable smoke waits across MediaWiki's whole-second cache boundary and
drains deferred jobs; it does not purge or reseed readers to fake propagation.
It also checks every offer and loot outcome, all pool memberships and their
conditional context, and the in-place raft action. Acquisition quantity, pool
story-gate, source-condition, and construction AP edits must reach their exact
consumer cells through ordinary editing. A named source context is not itself
a promise of an item drop, and a pool's empty filtered result is not an
inventory item. Desired-seed fixtures alone are not baseline-transition or
prefix compatibility evidence.
The disposable baseline-to-desired producer records every prefix of its
deterministic complete write order separately from that limited compatibility
receipt. It preserves the 36 unchanged baseline price contracts and three coin
summaries only after actual default-view checks. The six previously unknown
prices are scoped exceptions on eleven named merchant edges, never general
view-readiness evidence. Named views require their actual selected projection,
not merely an owner hash or a declared selector. Full-page observations bind
current revision identities, parser dependencies, ordered selected rows, and
pending planned-new-title redlinks. Endpoint-composed expectation candidates
must be reviewed independently before a downstream validator trusts them.
An offline baseline rehearsal cannot replace a fresh live export, conflict
review, writer freeze, or explicit operator authorization.
Source-change intent is determined by **A1 versus A0**, never A1 versus B.
When A1 equals A0, D is exact B: no PST and no write, including legacy storage
whitespace differences. Never reintroduce storage-only whitespace or classify
an existing authored/stored difference as a community edit. Actual live
changes are still compared strictly with B; conflicts, collisions, deletions,
and community changes retain the planner's safeguards.
For changed/new source only, the disposable preflight records actual
`ApiParse onlypst=1` output in the title/operator context and requires
`parse.text['*']` to equal A1 with only terminal CR/LF removed. It never uses
`parse.wikitext` as the transformed result. Spaces, tabs, NUL, Unicode,
internal line endings, substitution and signatures have no normalization
waiver. A source-changed result already equal to B is explicitly
`storage-noop`, with PST evidence but no redundant revision.
The schema-2 materialization receipt binds A0/B/A1/D and both source commits;
missing or inconsistent previous-authored identities fail, never default
to B. Migration comparisons and the scoped compatibility/full-prefix proofs
use exact D bytes. Any later authorized writer must deliberately use reviewed
D rather than submit raw A1. Retain A1 and D separately as the next release's
A0 and B. The disposable installer's welcome-page replacement has no
production counterpart.
Never
reseed edited owner pages on a schedule; regenerated repository output is
not authority over subsequent live edits.
Rights-reviewed images have their own backed-up operator import; metadata
alone does not prove that a File title exists or that its bytes match.

## Docker handoff

Run maintenance from the same reviewed image and database configuration as the
wiki. These are Linux shell examples for an operator's **existing** Compose
project, with service `mirklurk`; they do not create routing or a second stack:

```sh
docker compose stop mirklurk
docker compose run --rm --no-deps -T -e MW_READ_ONLY= mirklurk \
  php maintenance/run.php dumpBackup --current > "$PRIVATE_CURRENT_XML"
# Build and review a missing-title bundle on the operator's machine.
docker compose run --rm --no-deps -T -e MW_READ_ONLY= mirklurk \
  php maintenance/run.php importDump < "$PRIVATE_SEED_XML"
docker compose up -d mirklurk
```

Both path variables must resolve to reviewed private files outside Git; do not
paste secrets into the command line. Check the exit status of every command
before continuing. Never import game data, research exports, or an unreviewed
third-party wiki dump.

For the development stack, pass `-f deploy/compose.dev.yml` to each Compose
command. Do not start that stack on a production homeserver.

Verify imported titles, source links, literal names, spoiler warnings, anonymous
read/account-only edit behavior, and the registration CAPTCHA before exposing
the service. A rollback restores the verified database backup; it does not
reimport an older seed over edited pages.

The fixed seed timestamp and synthetic IDs are export metadata, not evidence
dates. An importer may attribute revisions to its configured import identity;
review MediaWiki's import attribution settings before a public rollout.
