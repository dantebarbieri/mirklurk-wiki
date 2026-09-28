# Seed a new wiki

The builder produces MediaWiki export 0.11 XML from original wikitext and
vetted facts. It does not perform an import or contact a wiki. A fresh
encyclopedia bundle includes dedicated entity pages, compact topic indexes,
guidance, and explicit compatibility redirects. New research topics still
require reviewed entries/facts. The builder reports the actual emitted page count.

An existing wiki is updated by [publishing](PUBLISHING.md) instead: the API
sync creates missing pages, updates pages the automation saved last, and skips
pages people edited.

## Fresh wiki

Generate a new private output from the reviewed repository:

```powershell
python tools\build_wiki.py --fresh --output .local\seed.xml
```

The `--fresh` flag acknowledges that the complete bundle is intended only for a
new wiki. It is not a live-wiki overwrite safeguard by itself.

Keep public access and editing stopped, initialize the database, and import the
bundle with the Docker handoff below. MediaWiki's installer creates a default
**Main Page**; the seed's older revision does not replace it. The first
`tools/sync_wiki.py --apply` does, because the installer's revision belongs to
MediaWiki itself rather than a person. Then verify the site before exposing it.

## Adding missing pages without the API

`python tools/build_wiki.py --existing-export CURRENT_XML --output NEW_XML`
emits only titles absent from a complete current-page dump
(`php maintenance/run.php dumpBackup --current`). Uppercase filenames stand for
private paths outside Git. It excludes every title present in the dump's main
and Category, Template and Module namespaces, including redirects, normalizing underscores, spaces
and the initial letter; it never emits an existing page. Unreadable or
malformed exports fail rather than falling back to fresh mode.

Keep the wiki and its background writers stopped from the dump through the
import; a page created in between would otherwise be missing from the
exclusion list.

## Renames and removals

Neither tool renames, moves or deletes pages. Renames require explicit registry
aliases and a separately reviewed redirect plan. Do not rename via source-label
changes, redirect ambiguous names to one arbitrary entity, delete old
histories, or silently retarget community links. For transcluded information,
edit the owner page rather than generated copies. Rights-reviewed images have
their own operator import; metadata alone does not prove that a File title
exists or that its bytes match.

## Docker handoff

Run maintenance from the same reviewed image and database configuration as the
wiki. The image must already have Scribunto enabled before importing the
display bundle. XML declares Template namespace 10, Module namespace 828,
and truthful `Scribunto`/`text/plain` models for Lua (`wikitext`/`text/x-wiki`
for articles and templates). Verify these models after import, not just title
existence. The API publisher performs the runtime preflight; `importDump`
does not substitute for that operator prerequisite.

These are Linux shell examples for an operator's **existing** Compose
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
