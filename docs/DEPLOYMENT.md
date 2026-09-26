# Portable MediaWiki deployment contract

This repository supplies an application image, not homeserver orchestration.
It does not manage DNS, certificates, reverse-proxy routes, existing credentials,
or live deployment. The operator owns those choices.

## Pinned images and persistent state

Build from the repository root using `deploy/Dockerfile`. It extends the
official Apache image:

`mediawiki:1.43.9@sha256:39a6503b8739f6aa58f8a458e9537258dd537f7cec7dd93c665bd3b43252d971`

The development database and agreed production interface use:

`mariadb:11.4.13@sha256:70cc072b29b4a89ae07abb2d4da2c64678a7f2dfe092751bb51c87d67dc1338b`

Review supported upstream releases and refresh **both tag and digest** deliberately
when applying security updates. A digest makes a build repeatable, not perpetually
secure. No game content is baked into the image.

Apache serves HTTP on container port 80. Production should expose only the app
through an operator-managed TLS proxy; do not publish the database port. The app
joins a proxy network and a private database network; MariaDB joins only the
database network.

Store MariaDB data, any optional images directory, backups, and secret files
outside the checkout. Uploads are disabled, so an images volume is not needed for
the initial functionality. If one is mounted at `/var/www/html/images`, provision
it deliberately for Apache's `www-data` user (UID/GID 33 in the pinned image);
never recursively change ownership of a shared parent directory.

Future rights-approved server-only illustrations use [the private operator import
workflow](IMAGES.md). No artwork is supplied or cleared by this repository, and
web uploads remain disabled. The runtime explicitly uses the pinned image's
`/usr/bin/convert` (ImageMagick) for thumbnails; it does not rely on PHP GD.

The original nonsecret template is baked as `/var/www/html/LocalSettings.php`.
Do not bind-mount another settings file over it. Rebuild/recreate for changes.
The template loads bundled ParserFunctions for named, canonical recipe and
seller views as well as ConfirmEdit/QuestyCaptcha. The Docker build asserts
that the bundled extension exists; no extension download, new namespace, or
database migration is introduced. Existing live sites need a separately
approved app-only rebuild/recreation under fresh verified backups before
publishing the named-view content. This is not authorization to deploy.

## Runtime variables

| Variable | Contract |
| --- | --- |
| `MW_SERVER_URL` | Required canonical origin, HTTPS in production; no path/trailing slash. Only loopback origins may use HTTP. |
| `MW_DB_SERVER` | Default `mirklurk-db`, standard MariaDB port |
| `MW_DB_NAME` / `MW_DB_USER` | Default `mirklurk` |
| `MW_DB_PASSWORD_FILE` | Required path, convention `/run/secrets/MIRKLURK_DB_PASSWORD`; at least 16 characters |
| `MW_SECRET_KEY_FILE` | Required path, convention `/run/secrets/MIRKLURK_SECRET_KEY`; at least 64 characters |
| `MW_UPGRADE_KEY_FILE` | Required path, convention `/run/secrets/MIRKLURK_UPGRADE_KEY`; at least 32 characters |
| `MW_CAPTCHA_QUESTIONS_FILE` | Required path, convention `/run/secrets/MIRKLURK_CAPTCHA_QUESTIONS` |
| `MW_TRUSTED_PROXY_CIDRS` | Optional comma-separated verified proxy IPs/CIDRs; no all-address prefix. Required operationally for correct client-IP throttling behind a proxy. |
| `MW_READ_ONLY` | Optional maintenance reason; freezes ordinary edits while set |

The CAPTCHA file is a private JSON **object** mapping original, harmless question
strings to nonempty arrays of short answer strings. Use multiple questions
appropriate for visitors, not trivia requiring purchase or game spoilers.
Question text is HTML-escaped before QuestyCaptcha renders it. Keep the answers
outside Git, rotate them when abused, and do not treat a question CAPTCHA as
strong bot protection.

Generate independent high-entropy application keys/passwords. The app reads
secret **files**, not password environment values. Missing, unreadable, empty,
or malformed required configuration fails explicitly. Do not disclose secret
contents in logs or support requests.

For Linux bind-backed Compose secrets, protect the parent host directory with
mode 0700 and use files readable by the container's Apache process. Files with
mode 0444 inside that protected directory are one option: the parent prevents
other host users from traversing it, while the mounted file is readable to
UID 33. Respect your deployment's ACLs and container trust boundaries. Mount only
the app's four secrets into the app; MariaDB alone also receives its separate
root password. The administrator's initial password is a separate one-shot
mount, not a permanent service secret.

Trust only verified proxy addresses and ensure that proxy overwrites forwarding
headers. Without explicit trust, requests share the proxy's rate-limit bucket.
Do not solve that by trusting the internet or an unreviewed shared network.

## Initial installation

The database must already exist, with the dedicated `mirklurk` user granted
access only to that database. MariaDB's image initialization variables can
create it on an empty data volume. Start the database and wait for its
`healthcheck.sh --connect --innodb_initialized` check before installing.

This one-off Linux command assumes the operator's Compose service is `mirklurk`:

```sh
docker compose run --rm --no-deps \
  --volume "$PRIVATE_ADMIN_PASSWORD_FILE:/run/secrets/MIRKLURK_ADMIN_PASSWORD:ro" \
  mirklurk php /usr/local/lib/mirklurk/install.php \
  --admin WikiAdmin --password-file /run/secrets/MIRKLURK_ADMIN_PASSWORD
```

The administrator file must contain a strong password of at least 16 characters.
The helper refuses a nonempty database, uses upstream `--dbpassfile` and
`--passfile`, and writes the installer's generated settings only to a random
private temporary directory outside the web root. A shutdown handler removes
that file. The normal image template remains in place. Keep the administrator
credential in the operator's password manager, not the running web container.

Do not expose the web service until setup and [safe seeding](IMPORTING.md) are
complete. Health is expected to fail before installation. The image's baked
check, `php /usr/local/lib/mirklurk/healthcheck.php`, queries the local API's
database-backed site statistics; it makes no external request.

## Access, moderation, and upgrades

Public users can read and register. Logged-in users can edit; anonymous users
cannot edit or create pages. Uploads, remote image embedding, outgoing email,
and email-based password resets are off. Plan administrator-assisted recovery
and record the first administrator's credentials securely.

Bundled ConfirmEdit/QuestyCaptcha protects registration, bad logins, and link
additions. Shared database caches support account and edit rate limits across
Apache workers. Limits include three registrations per IP per hour and ten
per day; authenticated edits are limited to ten per minute, with tighter new-user
limits. Review moderation burden and false positives after launch.

For upgrades, back up and verify the database, stop all web/background writers,
build the reviewed new image, and run
`php maintenance/run.php update --quick` in a one-off app container with
`MW_READ_ONLY` cleared. Check its exit status before starting the new app.
Use [the additive import procedure](IMPORTING.md), never an automatic full reseed.

Maintain encrypted, access-controlled backups outside Git. Verify a restore
into a **separate disposable database** before relying on the backup. Do not
test restores against production or assume an XML content export preserves
accounts, permissions, and all database state.

Changing domains is an operator action: update `MW_SERVER_URL`, rebuild only
if source changes, recreate the app, and handle redirects/TLS externally.
Authored pages and the seed contain no deployment hostname.

## Development only

`deploy/compose.dev.yml` creates a separate development project, a private
MariaDB network/volume, and a loopback-only app listener. Set
`MIRKLURK_SECRETS_DIR` to an **absolute directory outside the checkout** containing
the four app secret files plus `MIRKLURK_DB_ROOT_PASSWORD`.
Set `MIRKLURK_DEV_PORT` if port 8089 is unavailable.

```sh
docker compose -f deploy/compose.dev.yml build
docker compose -f deploy/compose.dev.yml up -d --wait mirklurk-db
# Run the one-off installer above, adding -f deploy/compose.dev.yml.
docker compose -f deploy/compose.dev.yml up -d --wait mirklurk
```

These commands require Docker Engine and Compose v2. Do not start this stack
alongside an existing production integration. A normal `down` leaves the database
volume; removing volumes destroys that development database.

## Validation without touching infrastructure

Run `php tests/test_runtime.php` for isolated configuration tests. With Docker
available, run `python tools/smoke_deploy.py --run`. The latter creates its own
randomly named Compose project and temporary generated credentials; it checks
installation refusal on reuse, health, anonymous permissions, CAPTCHA-protected
self-registration, ordinary account editing, seed import, and preservation of live edits.
The ordinary-editor checks bind recipe inputs, outputs and AP to their ordered
cells, cover every merchant offer and loot outcome, and verify the documented
pool memberships, story gates and in-place construction result. They pace writes
within the unchanged newcomer limit of three edits per minute, without granting
the account a rate-limit exemption. Logged
`VIEW_CONTRACT_JSON` records capture desired-seed expansions, rendered HTML,
template dependencies and owner hashes before mutation tests. Their synthetic
artwork URLs/cache metadata are not portable, and these records are not live
readiness or baseline-prefix receipts.
The rehearsal first reconstructs the pinned 401-title baseline and verifies its
exact frozen XML hash. A bootstrap check captures the untouched installer's welcome Main Page against
its installed English message source, removes only that default page by the
normal API, and imports all 401 baseline titles exactly. This is exclusively
fresh disposable setup, never a live migration step. A separate receipt retains
the welcome identity/raw text and deletion log ID.
One baseline cache refresh occurs before prefix zero; no purge or reseed occurs
during the planned transition or ordinary-editor propagation checks. Every
changed/new page is then saved once, after actual revision-bound leaf-view
checks, with all affected consumers observed at each prefix. Ready new pages
are preferred. Deferred stale consumer rows or redlinks receive at most ten
natural job-drain observations within a 90-second settling budget, with verified
server-clock boundaries; arbitrary parser/schema errors are not retried.
Separate settling evidence retains the observed HTML, identities and server
times instead of replacing stale DOM with database existence flags. HTTP reads
and job subprocesses are bounded by the remaining retry budget; an in-container
timeout also bounds maintenance after a client disconnect. Exhaustion records
current queue diagnostics within a separate five-second bound. Ordinary
new-title links may remain explicit, verified redlinks
at intermediate prefixes; they are not selector prerequisites and must resolve
at the final prefix.

`--evidence-dir NEW_DIRECTORY` retains the complete prefix proof, exact seeds,
schema-2 delta, desired-view fixtures, and a separate eleven-edge/six-price
compatibility receipt. The compatibility expectation candidate is composed from
separately captured baseline/desired endpoints, not copied from intermediate
receipt observations; it still requires independent review. Neither artifact
authorizes a live migration. Runtime provenance binds the rebuilt image, loaded
ParserFunctions registry version, configuration-source hashes, and a hash of
exactly six effective nonsecret settings: `EnableUploads`, `AllowCopyUploads`,
`AllowExternalImages`, `ReadOnly`, `GroupPermissions`, `CaptchaTriggers`.
Canonical bytes use UTF-8 sorted compact JSON, preserve types, and have no
trailing newline; secrets and CAPTCHA questions/answers are never projected.
CI checks out the exact source head with history and retains successful,
nonsecret rehearsal artifacts for seven days.
`authored-seed.xml` retains generator output A unchanged. Before any rehearsal
save, changed/new titles undergo actual `ApiParse onlypst=1` in the operator's
title/user context. Its transformed `parse.text` must equal A with terminal
CR/LF removed, and nothing else; broader whitespace trimming, internal changes,
substitution and signatures fail. Unchanged baseline titles are never
transformed. The exact results form materialized desired snapshot D in
`desired-seed.xml`; all subsequent raw hashes, comparisons and migration/receipt
pins use D, without normalized equality. `storage-materialization.json` binds
source/runtime/actor, baseline/A/D hashes and each title's exact output and
removed suffix. Independent review must approve this linkage. A later live
operation must explicitly target reviewed D, not silently reuse raw-A writer
assumptions; no live operation is authorized by these artifacts.
`endpoint-link-view-candidates.json` separately captures both exact endpoints.
Direct previews remove every explicit colon inclusion by recorded UTF-8 byte
span, retaining duplicates and all other source bytes, and must have no
remaining template dependencies. Selected views are freshly expanded and
parsed in a neutral title and every actual consumer title, with unsupported
baseline named views explicitly recorded. Full endpoint HTML, API links,
DOM links (including href/classes) and non-wiki links are retained. Direct plus
projected API-link unions, context invariance and API/DOM differences are
reported explicitly; discrepancies block candidate promotion, and even a clean
candidate requires independent review. Endpoint owner/consumer revisions and
the parser user must remain unchanged across the read-only batch. No endpoint
preview edits a page, purges a cache, or substitutes for the prefix sequence.
It also generates unique original synthetic PNGs outside the checkout for all
326 active and four preserved tree File titles, plus a separate 64x32 thumbnail
fixture. It imports them by CLI as `www-data` and anonymously fetches and decodes
every original and thumbnail, retaining mature-tree dimensions and translucent
shield pixels. Generic icons use neutral square fixtures, not game silhouettes.
Every rendered File reference must be covered; missing-image placeholders are
rejected rather than stripped from row evidence. The custom thumbnail must be
16x8, and original-URL fallbacks are rejected. Administrator and ordinary-user
web-upload attempts must still fail as disabled. No game images are used or retained.
It removes only its own containers, network, volume, and temporary files.

CI runs that disposable test on GitHub's runner. It does not deploy an image,
publish secrets, contact a homeserver, or configure a provider or proxy.
