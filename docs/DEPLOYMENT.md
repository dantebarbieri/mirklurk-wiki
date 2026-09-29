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
The template loads bundled ParserFunctions for named canonical views,
Scribunto with the bundled `luastandalone` engine for [display templates](TEMPLATES.md),
and ConfirmEdit/QuestyCaptcha. The Docker build asserts the extensions exist;
no extension download is needed. Scribunto registers Module namespace 828
and the `Scribunto` Lua content model. Its standard CPU/memory limits remain
enabled, alongside the display module's explicit input/geometry bounds.

**Rollout order matters:** separately authorize the runtime rebuild/deployment
before publishing pages using Lua. Follow the upgrade procedure below and
verify the new image in a disposable wiki first. A Git merge does not rebuild
the homeserver image. The publisher fails before any page edits when the target
lacks the required extensions, namespaces, content models or a working Lua
engine; it also probes unsaved module compilation. Never bypass that gate or
seed Lua pages into the old runtime. No production action is implied by the
repository changes. Do not roll back the runtime while live Lua readers remain.

## Responsive Vector 2022

The runtime sets `$wgVectorResponsive = true` alongside the existing
`$wgDefaultSkin = 'vector-2022'`. In the bundled Vector 1.43 code,
`VectorResponsive` defaults to false: `SkinVector22::isResponsive()` gates
the device-width viewport on that setting even though the skin emits
`skin--responsive`. Without it, the skin uses its fixed `width=1120`
desktop viewport. CSS alone cannot correct that mobile scaling.
See the [1.43 setting](https://github.com/wikimedia/mediawiki-skins-Vector/blob/REL1_43/skin.json)
and [skin implementation](https://github.com/wikimedia/mediawiki-skins-Vector/blob/REL1_43/includes/SkinVector22.php).
No MobileFrontend service, alternate skin, user-agent redirect, or zoom
restriction is required.

The setting is baked into the application image. **A separately authorized
rebuild/recreate is required**; publishing wiki pages does not apply it.
Local horizontal scroll wrappers are a separate content change: the generator
publishes ordinary editable article markup and `Module:Display` renders the
grid wrappers. Their inline styles use the existing publishing path; there is
no `MediaWiki:Common.css`/JavaScript publication or expanded namespace grant.
Publish the wrappers before, or together with, enabling the responsive runtime,
so wide existing tables do not become page-wide overflow at phone widths.
Human-edited pages/modules remain skipped and need the normal explicit review
and adoption before they acquire the new presentation.

Check anonymous Vector pages at 320px and 390px after both changes: actual
layout/visual viewport width must match the device, document scroll width must
not exceed it, and wide tables/grids must scroll locally by keyboard and touch.
Recheck desktop at 1440px. The disposable smoke covers real Items, merchant,
recipe, creature/grid and long-item-name pages plus a no-JavaScript phone and
desktop resizing. CI's `vector-layout` artifact contains synthetic-art
screenshots and `responsive-geometry.json`; never use game screenshots in Git.

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
| `MW_LOGO_URL` / `MW_LOGO_ICON_URL` | Optional pair of root-relative PNG paths: a legacy logo no larger than 135px wide and the square Vector 2022 icon. Set both or neither. |
| `MW_FAVICON_URL` | Optional root-relative PNG path for the browser tab icon; independent of the logo pair. |

### Site logo and favicon

The optional branding settings use MediaWiki's `$wgLogo`, `$wgLogos` (`1x`
and `icon`), and `$wgFavicon`. With all three unset, upstream branding remains
unchanged. Vector 2022 displays the square icon at 50 x 50 beside the existing
site-name text; do not pass the square artwork as a wordmark. Legacy Vector
needs its own smaller raster because it does not shrink an oversized `1x` logo.

Paths must start with a single `/`, end in `.png`, and use only ASCII letters,
digits, underscores and hyphens in directory segments; filenames may also
contain dots. Origins, traversal, query strings, fragments and external image
hosts are rejected. Use new versioned filenames rather than overwriting an
image when refreshing browser-cached branding.

Stage the [separately approved branding images](IMAGES.md#site-branding) in a
dedicated, backed-up directory outside Git, mounted read-only at
`/var/www/html/branding`. Include a public `attribution.txt` identifying the
creator, display permission, original fingerprints and derivative method.
Use versioned paths such as `/branding/2026-09/logo-128.png`.
Do not mount over existing image storage or put assets into the application image.
Alternatively, use the private operator import workflow with attribution
sidecars and obtain direct root-relative paths from MediaWiki's `imageinfo`
API, not File description pages or `Special:FilePath` redirects.
Neither approach requires public uploads or changes to gameplay pages.

Rebuild the runtime from the reviewed source and recreate only the app with
the configured paths. A content-publishing merge does not apply these settings
to the homeserver. Confirm the rendered `mw-logo-icon` and favicon `link` use
the intended paths, the API's legacy logo uses the smaller image, and each URL
returns the expected PNG dimensions and bytes anonymously. Preserve the
existing access policy, database and artwork.

### Secrets and proxies

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
Content reaches an existing wiki through [publishing](PUBLISHING.md), never a
full reseed.

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
available, install the browser test runner with `python -m pip install playwright==1.55.0`
and `python -m playwright install --with-deps chromium`. Set
`MIRKLURK_SMOKE_ARTIFACTS` to an external scratch directory to retain synthetic
Vector screenshots/geometry (otherwise they are temporary). Then
`python tools/smoke_deploy.py --run` builds the image in its own
randomly named Compose project with temporary generated credentials, then:

- checks installation refusal on reuse, anonymous permissions, disabled web
  uploads, the loaded ParserFunctions extension, and CAPTCHA-protected
  self-registration;
- imports original synthetic solid-color PNGs for every referenced File through
  the operator `importImages` path, then checks thumbnails and anonymous reads;
- checks the configured Vector 2022 logo, legacy logo and PNG favicon against
  separate synthetic fixtures, including rendered markup and served bytes;
- imports the release and publishes it with `tools/sync_wiki.py`, exactly as
  the live publish job does. A second release changes a price owner and creates
  a page: the merchant and the linking page must show the result without
  running MediaWiki's job queue. Rolling back and repeating the sync must work;
- checks rendered category memberships, grids, shields, landmarks, guides and
  named recipe, seller, loot and pool views;
- as a self-registered editor, edits owner pages within the newcomer limit of
  three edits per minute and checks that dependent pages update;
- confirms that the next sync skips every page that editor changed.

The live wiki is never contacted; the disposable containers and volumes are
removed afterwards. CI runs the smoke on every pull request and before every
publish, with a 30-minute budget.
