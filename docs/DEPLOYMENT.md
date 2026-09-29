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

## Short article URLs

Articles use `/w/$1` (for example `/w/Items`); scripts remain at the origin
root: `/index.php`, `/api.php`, `/rest.php`, `/load.php`, `/resources`, `/skins`
and `/images`. `MW_SERVER_URL` remains the sole canonical origin. Native
`[[Title]]`, template and category links need no content changes. Titles, page
IDs, revision history and the database are unchanged.

The image enables `mod_rewrite` and installs `deploy/apache-short-urls.conf`
as its port-80 virtual host. Following the
[MediaWiki Apache short-URL instructions](https://www.mediawiki.org/wiki/Manual:Short_URL/Apache),
only `/w`, `/w/...` and `/` are mapped internally to the fixed root `index.php`.
The original request URI and query are preserved; **never rewrite a captured,
decoded title into `?title=$1`**. MediaWiki parses and encodes titles itself.
`AllowEncodedSlashes NoDecode` is set inside that virtual host, allowing encoded
subpages on both article and REST paths without Apache decoding them first.

Root and empty article paths lead to MediaWiki's configured main page, not a
hardcoded title. A small action hook supplements core title normalization:
plain `/index.php?title=...` GET/HEAD views, optionally with `action=view`,
receive a 301 to MediaWiki's own title URL. It does not canonicalize duplicate
parameters or requests with any other parameters. POSTs, special pages,
history, old revisions, diffs, search, login, raw/render/edit/submit and API
requests retain upstream behavior. Native wiki redirects still show their
redirected-from notice. Browser fragments survive ordinary HTTP redirects;
the server neither receives nor rewrites them.

**Proxy prerequisite:** route `/w` and `/w/...` to this same application, in
addition to the existing root script/static paths. Forward the original encoded
path, query string and method without stripping `/w`, decoding `%2F`, rewriting
titles, or dropping REST `PATH_INFO`. Do not configure an upstream catch-all
Main Page redirect, or a redirect for all `index.php` requests. Retain the
canonical Host/protocol and the verified forwarding-header/trusted-proxy policy.
DNS, TLS and homeserver/proxy changes require separate operator authorization.

**Rollout:** first pass the disposable image HTTP smoke, preserve the previous
image reference and take the normal verified backup. Separately authorize and
apply any proxy prerequisite, rebuild the reviewed image, then recreate only
the app with the same database, images, origin and secret mounts. No schema
change, seed import, database copy, article rename or content sync is required.
Merging/publishing wiki text does **not** install these Apache/settings changes.
Keep the API publisher URL ending in `/api.php`.

Existing parser-cache entries may contain old generated links. After the app
and proxy are ready, invalidate parser output using MediaWiki's supported
`$wgCacheEpoch` deployment setting (a UTC `YYYYMMDDHHMMSS` timestamp for this
rollout), or perform an authorized bounded page purge through the API. Then
invalidate any proxy/CDN HTML cache, including prior `/w/...` Main Page
responses and root redirects. Do not clear session storage or edit pages to
refresh links. Confirm fresh article/category/template links and siteinfo,
encoded punctuation/subpages, 404s, root scripts/assets and a login/edit/save
through the public proxy before declaring the runtime rollout complete.

**Rollback:** before public rollout, restore the previous image and matching
proxy configuration together; no database restoration or reverse content sync
is needed for this URL-only change. Purge affected proxy HTML/redirect caches.
Once short URLs have been shared, a pre-short-URL image cannot serve those
bookmarks, and browsers may retain 301s. Prefer a forward fix or rollback image
that retains this article-path/routing pair. Do not revert just one half or
add reverse redirects from `/w/...` to legacy views (which can loop with cached
301s). A complete removal after public use requires a separately reviewed
compatibility plan; clearing server caches cannot erase browser redirects.

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

## Canonical URLs, descriptions and social sharing

The image enables MediaWiki 1.43's native `$wgEnableCanonicalServerLink`.
Core chooses article, redirect-target, historical-revision, history and info
canonicals using its Title/config APIs. No hostname or article-path assumption
is baked into metadata: the deployed-source `/w/$1` and the previous
`/index.php?title=$1` both work with `MW_SERVER_URL`/`$wgCanonicalServer`.
Core robots/noindex policies remain authoritative. Missing pages, special pages,
nonarticle responses and unreadable pages have no canonical: core's generic
fallback otherwise copies arbitrary request parameters into that tag.
History/info retain their native action canonical; diffs, edit views and old
revisions retain the native article canonical, but receive no social description.

`mirklurk-metadata.php` is a small local output hook, not a third-party SEO
extension. It runs after core has built the head, uses the existing canonical
for `og:url`, and never writes user/request-derived data into a parser or shared
cache. Only anonymous, current, indexable main/category wikitext article views
receive Open Graph title, site, type and URL, plus a summary social card.
Titles retain their original punctuation/Unicode; MediaWiki escapes attributes.
Logged-in views, previews, old revisions, redirects shown with `redirect=no`,
nonreader namespaces, errors and noindex views have no sharing tags.

Descriptions follow the **live rendered lead**, including community edits and
normal MediaWiki transclusion invalidation, not a generated-source manifest.
Only direct visible lead paragraphs before the first heading are candidates;
tables, navigation, images/captions, hidden content, reference/unverified markers,
raw wiki markup and research/editorial caveats are excluded. A description uses
at most 240 Unicode characters, preferring a complete paragraph or whole
sentences rather than chopping words or bytes. If no suitable short lead exists,
the description is omitted rather than invented. Improve the article lead
through the ordinary editorial workflow; this runtime change edits no articles.

`og:image` uses only the explicitly configured `MW_LOGO_ICON_URL`, expanded
against the canonical origin. That setting already requires the operator's
separately approved branding asset. With no configured icon there is no image
tag; no game image is bundled, guessed, scraped or newly cleared for sharing.
No analytics, external metadata service or search-engine account is involved.

### Native sitemap generation and serving

The bundled `generateSitemap` maintenance script owns database enumeration,
Title URLs, timestamps, namespace splitting and XML escaping. The local
`refresh-sitemap.php` wrapper only checks the reviewed public policy, stages and
validates that output, and publishes it atomically. It selects namespaces
**0 (articles) and 14 (categories)** via `$wgSitemapNamespaces` and passes
`--skip-redirects`. It excludes missing pages, actions, special/user/talk/template/
file/module pages and native `__NOINDEX__` page properties. The configuration
sets `$wgExemptFromUserRobotsControl = []` so article authors can now use
`__NOINDEX__` as well as category authors; it does not override existing noindex.

Core 1.43's generator does **not** honor per-article/per-namespace config robot
policies or private-wiki permissions. The wrapper therefore fails explicitly
if reading is private, default robots differ from `index,follow`, any
`$wgArticleRobotPolicies` exist, main/category namespace robot overrides exist,
author noindex controls are exempted, or the sitemap namespace set changes.
Do not bypass this guard by invoking the
raw generator against served storage. New access-control extensions or indexing
policies require a fresh integration review. Before making a public wiki private
or restricting previously public titles, remove its published sitemap/index and
cached copies first; a failed refresh deliberately preserves the previous index.

Apache serves `/sitemap.xml` and uniquely named root-level `sitemap-*.xml`
shards from `/var/lib/mirklurk-sitemap/public`, with XML content types,
no directory listing and a five-minute public cache lifetime. Root-level shard
URLs allow articles in either URL layout without sitemap directory-scope
ambiguity. Staging and locks are outside the web root and have no public alias.
The image does **not** run a refresh on startup or create a cron job.

The dynamic `/robots.txt` endpoint adds `Sitemap: <MW_SERVER_URL>/sitemap.xml`
and narrowly disallows API, REST, ResourceLoader and search endpoints. It does
not disallow all of `/index.php` or `/w/`, nor block revision/action URLs needed
for crawlers to see native noindex. It reads only validated origin configuration,
never the Host header or request query. If the operator already serves robots at
the proxy, preserve that policy and **append this Sitemap directive there**
instead of replacing the policy; verify the final anonymous `/robots.txt`.

### Authorized rollout and refresh

Merging this PR only changes repository/runtime source. Content publishing does
not rebuild/recreate the application or generate sitemaps. Separately authorize:

1. Build the reviewed image and perform the normal backed-up runtime upgrade.
   Ensure the proxy forwards `/robots.txt`, `/sitemap.xml`, and root
   `/sitemap-*.xml` requests to Apache as well as the existing wiki endpoints.
2. Provision a dedicated persistent volume at `/var/lib/mirklurk-sitemap`,
   outside Git, with its root and `public` child owned by UID/GID 33 and mode
   0755. Only this dedicated directory needs write access; do not change
   ownership of shared parent paths. Without a mount the disposable image
   directory works, but is lost on container recreation.
3. Finish content publication and pending parser/link-update jobs. Then run
   the following in the app's existing database/secret/network context, as
   `www-data`, not root. It needs no administrator password, root database
   credential, external service or expanded database grants.

```sh
docker compose exec --user www-data mirklurk \
  php /var/www/html/maintenance/run.php /usr/local/lib/mirklurk/refresh-sitemap.php
```

4. Check exit status, anonymous robots/index/shard HTTP 200 responses and
   canonical URLs, including an article with punctuation. A missing initial
   sitemap is a real 404, not an empty success response. Check metadata on
   Items, a redirect, an old revision and a noindex page.

Repeat that exact command after content releases, URL/origin changes and
significant live edits, or schedule it daily with the operator's existing job
runner. Monitor nonzero exits and sitemap age. Refreshes are serialized by a
nonblocking lock. New shards have unique names; only after all output is valid
and readable is the index renamed on the same filesystem. Failures retain the
old complete index. Keep previous shards for at least a day so cached/in-flight
indexes resolve; periodically remove only old, unreferenced `sitemap-*.xml`
files from the dedicated public directory. No runtime data belongs in Git.
After an origin/path change refresh before crawler verification, invalidate
old proxy caches if necessary, and keep old URL redirects as an operator task.

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
- exercises real Apache HTTP old/new title and revision identity, GET/HEAD,
  root/main-page routing, punctuation, Unicode, namespaces, encoded subpages,
  missing-page 404s, query/action semantics, REST path info and root assets;
  a browser checks fragment retention, login with an edit return target, and
  short-path source editing followed by an actual root-script POST save;
- imports original synthetic solid-color PNGs for every referenced File through
  the operator `importImages` path, then checks thumbnails and anonymous reads;
- checks the configured Vector 2022 logo, legacy logo and PNG favicon against
  separate synthetic fixtures, including rendered markup and served bytes;
- checks actual HTML head metadata for current, old, diff, history/info, edit,
  redirect, missing, special, private and noindex views, escaping/Unicode and
  live edits; generates and fetches native sitemap XML and robots discovery in
  query-style regression and the actual Apache short-URL configuration, with loopback and custom
  canonical origins, including preservation of the old index on refresh refusal;
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
