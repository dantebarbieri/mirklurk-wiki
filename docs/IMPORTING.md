# Seed and reimport without overwriting the community

The repository produces MediaWiki export 0.11 XML from original wikitext and
vetted facts. It does not perform an import, fetch research files, or synchronize
with a live server. A fresh bundle contains 11 main-namespace pages.

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

`--existing-export` excludes every title present in the dump's main namespace,
including redirects, regardless of revision timestamps or content. It
normalizes underscores, spaces, and the initial letter for the standard
first-letter English namespace. It never includes existing pages for automatic
replacement. Unreadable/malformed exports fail rather than falling back to
fresh mode.

Keep the wiki stopped from snapshot through import. A page created after the
snapshot would otherwise be absent from the exclusion list. Stop background
writers too; a maintenance banner alone is not a concurrency lock.

Review existing-page changes manually using the live page history and editor.
There is no automatic overwrite option, timestamp-based "newer wins" policy,
scheduled import, or force-update mode in this tool.

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
