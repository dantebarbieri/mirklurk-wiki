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
VisualEditor, TemplateData, and ConfirmEdit/QuestyCaptcha. The Docker build asserts the extensions exist;
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

## Visual editing and REST

The pinned 1.43.9 image includes matching VisualEditor and TemplateData.
VisualEditor uses MediaWiki 1.43's **DirectParsoidClient**, backed by the integrated
PHP Parsoid library. Do not install RESTBase, a Node Parsoid service, or configure
`$wgVirtualRestConfig['modules']['parsoid']` for this version. It does not need
to call the public HTTPS hostname from inside the container; port mapping and
split DNS are not reasons to override its client.

Eligible logged-in users get both **Edit** and **Edit source**, with visual editing
enabled without a beta opt-in. Existing individual preferences remain respected.
The classic source editor remains the default source route. Help pages are
eligible; template definitions are source-edited, and Lua is not a visual content
model. Anonymous edit/write API restrictions, QuestyCaptcha, shared-cache rate
limits, uploads and email policy are unchanged.

The Apache site sets `AllowEncodedSlashes NoDecode` **inside the active port-80
VirtualHost**, not just the global server scope (where it is not inherited).
This allows encoded slash-bearing titles/subpages through `rest.php`.
The operator's reverse proxy must preserve the original escaped URI and
`/rest.php/...` PATH_INFO, pass GET/POST requests and request bodies to the app,
and leave `/api.php`, `/load.php` and `/index.php` accessible. Do not redirect
REST requests to article pages, strip cookies, cache authenticated API/POST
responses, decode `%2F` before forwarding, or disable TLS certificate checks.
For nginx, preserve the request URI without replacing the path in `proxy_pass`.
Keep the public HTTPS `MW_SERVER_URL` and verified proxy trust settings.

**Separate operator rollout:** back up first, rebuild the reviewed image, run
`php maintenance/run.php update --quick` using the upgrade procedure, and
recreate the app only when separately authorized. Then verify extension
registration, `/rest.php/v1/page/Help%3AEditing/html` (after the page exists),
and a slash-bearing practice page through the real proxy. Sign in as a normal
user and open, change, review and save a practice page, including a template
parameter; also test Edit source and an unsolved add-link CAPTCHA. Extension
presence alone is not an editor acceptance test.

Only after runtime activation should the content release publish TemplateData
and `Help:Editing`; the publisher fails closed before page edits when metadata
is present but TemplateData is missing. A PR/merge does not activate the runtime,
and the deployment does not publish those pages. Do not roll back TemplateData
while pages contain its tags.

**Compatibility boundary:** simple prose and display-template fields are visual
editing targets. The disposable test exercises no-change Parsoid round trips on
real generated item, coin, merchant and recipe pages, plus a visual prose edit
beside wrapped selective data. Editing/restructuring `onlyinclude`, nested
Recipe row/Ware row arguments, parser-function selectors, price gates or stable
anchors remains a **source-editing workflow**. Metadata is field help, not proof
that arbitrary restructuring can round-trip. Do not flatten shared views or
move their factual owners. See [TEMPLATES.md](TEMPLATES.md).

Upstream implementation references (version-specific):
[VisualEditor client factory](https://github.com/wikimedia/mediawiki-extensions-VisualEditor/blob/REL1_43/includes/VisualEditorParsoidClientFactory.php)
and [editor configuration](https://github.com/wikimedia/mediawiki-extensions-VisualEditor/blob/REL1_43/extension.json).

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
- imports the release and publishes it with `tools/sync_wiki.py`, exactly as
  the live publish job does. A second release changes a price owner and creates
  a page: the merchant and the linking page must show the result without
  running MediaWiki's job queue. Rolling back and repeating the sync must work;
- checks rendered category memberships, grids, shields, landmarks, guides and
  named recipe, seller, loot and pool views;
- opens VisualEditor as an ordinary account, edits a TemplateData-backed field
  and prose, reviews the diff and saves with a summary; exercises encoded-slash
  REST paths, exact no-change Parsoid round trips, wrapped selective data and
  the source preview/save fallback without changing price/view ownership;
- rejects anonymous visual API saves and requires an add-link CAPTCHA; retains
  synthetic editor screenshots and `editing.json` alongside Vector artifacts;
- as a self-registered editor, edits owner pages within the newcomer limit of
  three edits per minute and checks that dependent pages update;
- confirms that the next sync skips every page that editor changed.

The live wiki is never contacted; the disposable containers and volumes are
removed afterwards. CI runs the smoke on every pull request and before every
publish, with a 30-minute budget.
