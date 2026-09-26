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

### Explicit incremental disposable inputs

Historical CI continues to use the existing historical baseline and strict cohort
order. For a reviewed later release, opt in explicitly:

```powershell
python tools\smoke_deploy.py --run --incremental-inputs C:\private\inputs.json --evidence-dir C:\private\new-evidence
```

This is the **same disposable Compose / Rehearsal / NativeSmoke pipeline**, not
a production executor. It imports exact owned stored **B**, not previous authored
A0. Inputs and resulting evidence are private: do not commit them, put them in
CI, or treat synthetic XML identities as production history. A separate reviewed
community-title inventory detects collisions but is not imported as owned data.
Fresh production observation, conflict reconciliation, writer freeze and
publication approval remain operator responsibilities.

The input is a closed JSON object with `schema_version: 1` and
`kind: "disposable-incremental-inputs"`, containing these additional required keys:

| Key | Required value |
| --- | --- |
| `previous_source`, `candidate_source` | Objects with exact `head_sha` and `tree_sha`. Candidate must be the clean executing HEAD. |
| `previous_authored`, `baseline`, `authored`, `provenance` | Each has `path`, positive integer `bytes`, and `sha256`. Relative paths resolve beside the input JSON. The first three are A0, B and A1 XML; provenance is pinned reviewed JSON. |
| `owned_titles`, `community_titles` | Sorted unique normalized title lists, disjoint. Owned titles must equal both A0 and B; no owned deletion or candidate/community collision is accepted. |
| `reviewed_drift_sha256` | SHA-256 of canonical JSON `{title: {previous_authored_sha256, baseline_sha256}}` for **every** A0/B raw difference, including storage-only differences. No inferred normalization or unreviewed drift. |
| `catalog_inputs` | Exactly `previous` and `candidate`, each mapping the five bare filenames `game.json`, `catalog.json`, `acquisition.json`, `entity_details.json`, `illustrations.json` to their exact raw SHA-256 hashes. |

Canonical JSON here means sorted compact UTF-8, unescaped Unicode, no NaN and no
terminal newline. XML must equal `build_xml`'s deterministic synthetic disposable
format; production history exports and unsupported namespaces/shapes are rejected.
The previous source is archived from its pinned Git commit and its own generator
must reproduce A0. `load_publication_inputs` loads the previous archived catalog
without rounding or serializing away its Decimals. The current generator must
reproduce A1. Runtime materialization still performs actual only-PST only for
source-changed/new titles; source-unchanged titles retain exact B without PST.

Incremental order is exactly the changed B/D set, once each, deterministically
preferring ready creates and then lexical title order. Every transclusion owner
must be at D before saving its changed consumer; unchanged owners are already
ready, unless the following closed default policy is explicitly approved.
Missing views and affected cycles still fail. There are no historical nine-save
cohorts, six unknown-price exceptions, named-view waivers or ignored cycles.
Zero operations produces explicit `no-publication`, one baseline prefix and no
release journal/accepted operation.

The only optional input key is `default_readiness`, with exactly
`{"schema_version":1,"policy":"registered-default-source-and-measurement","source_contracts_sha256":"<sha256>"}`.
It permits an **empty-argument registered default only** to use its actual B
owner until that owner reaches D. Named, parameterized and self references remain
owner-at-D prerequisites. All 45 typed registry entries must be unchanged. The
ordered full literal `<onlyinclude>...</onlyinclude>` blocks must be identical
across reproduced A0, exact B and materialized D, with unambiguous inclusion
structure and only the existing closed view/station switches: templates, mutable
magic and transclusion dependencies are rejected. The approval digest binds the
owner-keyed source-contract map described below. Source equality never replaces
genuine measured B expansion/image-aware DOM in each consumer context, a fresh
pre-save probe/current revision, or all-45 final D equality. Native prerequisites
pin the actual B or D raw/CAS, never an anticipated D revision. Without this
object, strict owner-at-D ordering remains mandatory.

Baseline named projections are measured from MediaWiki in neutral and complete
B/D consumer contexts, using the baseline catalog and the genuine old pool shape.
Desired pool checks reuse the current compact-pool checker. Actual owner raw state
selects B/D semantics even while the consumer is still B. Context, expansion,
leaf dependencies, current revision, full consumer DOM, links and bounded natural
settling remain checked. All current registered defaults (42 prices and three
coins) have explicit baseline/final neutral probes and per-prefix references;
all six formerly unknown prices must stay established. Unchanged leaf caches are
keyed by owner revision, raw hash, parameters and consumer context; changed owners
and pre-save prerequisites are freshly probed. Every D default expansion and
semantic DOM (including images) must equal its measured B context contract even
if the owner's article/revision changed. Prices permit only their exact 20px
denomination icons with no links, including empty links; coin summaries permit
only the exact owner link/table and no images.

Selected offers use their actual B/D stock-reference and location semantics.
Outside table rows, each affected merchant/offer consumer must equal the combined
word/link multisets of its actual direct-source MediaWiki preview and selected
named projections, including repeated invocations. This retains legitimate
consumer-owned B notes while rejecting stale/missing selected notes or location
links even when table rows are unchanged. Direct previews remove only recorded
literal colon invocations, have no remaining template dependencies, and are
cached by consumer title/revision/raw. Mismatches use the existing bounded
settling and fail if they persist; no synthetic HTML is runtime evidence.

`full-prefix-proof.json` retains the existing baseline/desired revision maps,
`order`, `prefixes`, `view_evidence`, `final_observations` and `default_contracts`.
Each view adds `parse_title`. Its additive `incremental` envelope has:

- `schema_version: 1`, `kind: "disposable-incremental-envelope"`, `inputs` (the
  original input pins without local paths, plus original `input_sha256`), and
  `outcome` (`rehearsed` or `no-publication`).
- `coverage`: `titles` and `counts`, each keyed `create`, `update`, `preserved`;
  plus `operations`, `prefixes` and `desired_titles`, derived independently from B/D.
- `default_endpoint_probe_ids` (`baseline`, `desired`) and
  `default_prefix_probe_ids` (one list per prefix); each list covers all default
  owners in sorted title order, in the neutral `Prefix projection` context.
- `default_readiness_sha256`: canonical digest of `default-readiness.json`.
- `corpora` and `seeds`, each mapping `previous_authored`, `baseline`, `authored`,
  `desired` to canonical corpus-map and deterministic XML digests respectively;
  `order_sha256`; and `native`, binding the manifest, exact prerequisite-plan,
  executor/journal implementations, native proof and full journal-record artifact.
  `cold_replay` is `passed` or `not-applicable-no-publication`.

`native-publication-proof.json.incremental` independently records input, dynamic
coverage, manifest, prerequisite-plan and `default_source_contracts_sha256`
hashes. The plan hash covers the ordered
list of operation prerequisite arrays from the native manifest retained in
`native-journal-proof.json.records["manifest.json"]`. Native operation guards have
`prefix`, `prerequisite_checks`, `default_probe_ids`, `incremental_input_sha256`,
`baseline_default_edges` and `offer_context_checks`;
the final guard also binds final observations and the pre-native-binding envelope.
The envelope's native hashes are attached afterward to avoid a circular digest.
The unchanged native executor/journal still require one launch/collection/whole
exit, exact CAS/prerequisites/effects and full cold replay for each accepted write.

`default-readiness.json` has `schema_version: 1`, kind
`registered-default-readiness`, the selected `policy` (or `strict-owner-D`),
`source_contracts`, `used_baseline_edges` and `default_endpoint_probe_ids`.
Each owner source contract has `previous_authored_raw_sha256`,
`baseline_raw_sha256`, `desired_raw_sha256` and `transcludable_source_sha256`
(canonical digest of the ordered full literal inclusion-block list).
Each actually used B-default edge records `index`, `consumer`, `owner`,
`parameters: {}`, those four source digests, exact `owner_revision` metadata and
`probe_id`; operation guards must contain the same annotations.

`offer-context-evidence.json` has `schema_version: 1`, `direct_previews` and
`checks`. Check keys are canonical digests of
`{consumer, html_sha256, probe_ids}`, preserving revision/context evidence even
when HTML is unchanged. Each check contains those fields, `direct_context_id`
(index into `direct_previews`), `outside_words_sha256` and `outside_links_sha256`.
The digests cover the expected word-count object and sorted
`[[[target,text],count],...]` link-count list respectively. Native guards retain
the complete required check map; missing evidence fails rather than disappearing
from the guard.

`endpoint-link-view-candidates.json` retains measured selected/context/direct/full
endpoint HTML and expansion preimages. `consumer-html.json` maps each actual
consumer HTML digest to its preimage. The normal artifact manifest hashes all
retained files. No fabricated `price_prefix`, ten-state compatibility receipt or
historical expectation artifact is emitted in incremental mode. Generic fault
tests and historical CI are separate evidence, never incremental DOM/native proof.
Offline unit tests use explicitly synthetic fixtures; only an authorized real
disposable MediaWiki run can provide measured incremental evidence.

Endpoint captures keep the raw MediaWiki `links` inventory and full `dom_links`
unchanged. These inventories are not interchangeable: the parser omits same-page
fragments and unlinked selflinks, while HTML also contains generated navigation.
Only local TOC links inside `id="toc" class="toc"` and current-page section-edit
links inside `mw-editsection` are classified as navigation. Ordinary content
fragment/edit links are retained. The additive `semantic_targets` list contains
normalized content destinations **including fragments**; selected-context and
direct-plus-projected-union checks compare these destinations, not the raw
parser inventory. API/DOM parser-inventory agreement, content links, expansion,
existence and contextual destination/fragment checks still apply. No same-title
or named-view exemption is granted.

### Failed disposable evidence

`--evidence-dir` must name a new directory; existing destinations, including
dangling symlinks, are rejected before loading inputs or starting Docker.
Previous attempts are never replaced.
The existing writer now runs before disposable cleanup on failure or interruption,
as well as on success. Success artifact names remain unchanged; the manifest adds
`status: "passed"` and `complete: true`. A failed run instead writes
`failed-rehearsal.json` with `schema_version: 1`, kind
`failed-disposable-rehearsal`, `status: "failed"`, `complete: false`, source head,
failure type/message, `partial_evidence`, `rehearsal` and `native_partial`.
Previously gathered named evidence is nested inside `partial_evidence`, never
emitted as a successful full-prefix proof. Available seed bytes are retained and
hashed by `artifact-manifest.json`, whose status is `failed`/incomplete.

The partial rehearsal includes captured endpoints, revisions, prefixes, probes,
default/context checks, consumer HTML and settling observations when available;
uninitialized fields are `null`. Endpoint `capture_complete` is false until the
ending revision/actor checks pass. `active_capture` retains the in-flight
projection/direct/original input, expansion and parser result, if received, when
validation aborts. `candidate_promotion_blocked` stays true for incomplete or
discrepant captures. Native proof/journal records are snapshots only, not completed
replay or acceptance claims. The exception still propagates and cleanup still
runs; neither cleanup success nor a release is certified by a failed artifact.
Operators must separately retain stdout, stderr and exit status. Lost diagnostics
from earlier runs cannot be reconstructed by this change.

### Historical and ordinary-editor checks

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
The rehearsal reconstructs the pinned published source as previous authored A0,
then reconstructs the independently observed 401-title stored baseline B under
the release-specific binding in `smoke_prefix.py`. This historical transform
preserves the entire **Evidence and spoilers** body (including its terminal
LF), removes terminal LF from the other 400 titles only for that exact release,
and must match both
the captured B deterministic XML and canonical corpus hashes. It is not a
generic storage normalization rule, live observation, or permission to change
production. A bootstrap check captures the untouched installer's welcome Main Page against
its installed English message source, removes only that default page by the
normal API, and imports all 401 baseline titles exactly. This is exclusively
fresh disposable setup, never a live migration step. A separate receipt retains
the welcome identity/raw text and deletion log ID.
One baseline cache refresh occurs before prefix zero; no purge or reseed occurs
during the planned transition or ordinary-editor propagation checks. Every
planned changed/new stored page is then saved once, after actual revision-bound leaf-view
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
The retained four artifacts are `previous-authored-seed.xml` (A0),
`baseline-seed.xml` (exact stored B), `authored-seed.xml` (unaltered generator
A1), and `desired-seed.xml` (D). `stored-baseline-binding.json` records the
narrow historical reconstruction pins, not raw host snapshots or accounts.
Source-unchanged means A1 equals A0, even when A1 differs from B: preserve
exact B in D with no PST or write. Never reintroduce legacy storage-only
whitespace. Changed/new source undergoes actual `ApiParse onlypst=1` in the
operator's title/user context. Its transformed `parse.text['*']` must equal
A1 with terminal CR/LF removed, and nothing else; broader whitespace trimming,
internal changes, substitution and signatures fail. A source-changed PST
result equal to B is `storage-noop` and creates no revision.
`storage-materialization.json` schema 2 binds source/runtime/actor and all
four seed hashes, adding `previous_source_head_sha`,
`previous_authored_seed_sha256`, and per-title `previous_authored_sha256`.
Page classifications are `unchanged`, `storage-noop`, `update`, or `create`;
unchanged rows have null `only_pst_output` and null `removed_suffix` (no PST), while
all others retain the actual PST output and exact removed suffix.
All subsequent raw hashes, comparisons and migration/receipt pins use D,
without normalized equality; the write order and counts are derived from B
versus D, not hardcoded. Independent review must approve this linkage. A later
live operation must explicitly target reviewed D, not silently reuse raw-A1
writer assumptions. Preserve A1 and D separately as the next release's A0 and B;
an existing A/D difference is not a community edit. A fresh frozen live dump
must still pass strict comparison against B. No live operation is authorized
by these artifacts.
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
