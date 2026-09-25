# Server-only illustrations and rights review

Image bytes never belong in this repository, its Git history, CI artifacts,
issues, or pull requests. MediaWiki may serve separately approved pictures from
its persistent `/var/www/html/images` storage. That is an operator workflow,
not an exception to the repository's asset exclusions.

**No redistribution permission has been established by this project.**
Owning the game, inspecting its files, or choosing server-only storage does not
grant permission to publish its artwork. Actual publication stays pending until
the operator confirms a suitable rights basis for each image.

## Metadata only

Optional `illustrations` records in the curated JSON associate an item or being
with a stable local title such as `File:Item-2.png`. There are no URLs, domain
names, local source paths, image bytes, download instructions, or automatic
uploads in these records.

Every record contains `id`, `entity`, `file_title`, `caption`, `creator`,
`sha256`, `rights_status`, `rights_basis`, `rights_note`, `confidence`, and
`evidence`. Evidence uses the existing source/section/key format; the SHA-256
identifies the exact separately reviewed **image** bytes, not the original game
container. Captions and rights notes are original writing.

For `rights_status: pending`, creator/hash/rights fields may be null. A pending
record renders a review notice and its reserved title as text, **not** an image
or File link. Do not manufacture empty records for every entity.

For `rights_status: approved`, creator, hash, rights basis, and review note are
required. The reviewed record may then emit `[[File:...|thumb|...]]`.
An approved flag is a recorded human decision, not a legal conclusion made by
the software. The builder cannot verify permission or the live file's existence.
Publish approved metadata only after the corresponding operator import is ready.

Titles are restricted to simple ASCII raster-image basenames: PNG, JPEG, or
WebP. Use stable names, not version-specific host URLs. MediaWiki resolves these
relative File references after a domain migration.

## Private staging and attribution

After rights approval, prepare a small private directory outside Git containing
only the individually reviewed images for this batch. Exclude symlinks,
unexpected formats, oversized images, unnecessary embedded metadata, and any
unreviewed export. Compare each image's SHA-256 with its approved record.

The basename becomes the MediaWiki File title: `Item-2.png` becomes
`File:Item-2.png`. Check existing titles before import and do not rename files
casually.

Place an original attribution sidecar beside each image, for example
`Item-2.png.txt`. Its wikitext should identify the creator/rightsholder, describe
the actual permission or license basis, record the source and review scope,
and give the original caption and image fingerprint. Do not reproduce
localization prose, private correspondence, personal paths, or confidential
permission details. If sensitive permission evidence must be retained, keep it
in the operator's private records and publish only the appropriate attribution.

## Operator-only MediaWiki 1.43 workflow

The pinned MediaWiki CLI supports `importImages`, `--dry`, `--comment-ext`,
`--skip-dupes`, and `--extensions`. It publishes through the local file backend
rather than the web-upload form. No change to `$wgEnableUploads` is made:
anonymous and registered-user web uploads remain disabled.

Thumbnail generation requires a renderer even though web uploads are disabled.
The runtime template explicitly enables ImageMagick at `/usr/bin/convert`, already
installed in the pinned MediaWiki image; PHP GD is not available there. Rebuild
and recreate the app from the reviewed template rather than editing live settings.

The following Linux commands are **instructions only**. They require explicit
operator authorization, reviewed rights, an existing image-volume mount, the
same app/database configuration, a valid operator account, and a verified
backup. They do not configure a server, proxy, or credentials.

```sh
docker compose run --rm --no-deps -T -e MW_READ_ONLY= \
  --volume "$PRIVATE_APPROVED_IMAGE_DIR:/private-images:ro" \
  mirklurk php maintenance/run.php importImages /private-images \
  --extensions png,jpg,jpeg,webp --user WikiAdmin \
  --comment-ext txt --skip-dupes --dry
```

Review the complete preview and every description privately. The script can
fall back to a generic comment if an attribution sidecar is missing, so the
operator must verify that **every** image has its intended sidecar. A dry run is
not a substitute for validating formats, bytes, rights, or attribution.

Only after approving that exact batch, repeat the same command without `--dry`.
Never add `--overwrite`, `--search-recursively`, or `--source-wiki-url`.
Existing same-title files are skipped by default; `--skip-dupes` also detects
matching content under another title. Skips are not proof that the intended
File title now exists, so inspect them rather than ignoring them.

Check the command's exit status and its added/skipped/failed counts. Verify each
File page's title, attribution, served image and reviewed bytes; verify thumbnail
display and public read access while web uploads remain disabled. Preserve the
rights record privately as required. Update approved reference metadata and
merge affected live wiki pages through the normal review process.

The image volume and database must be backed up and restored together. Do not
copy random exports directly into MediaWiki's hashed image directories.
The repository neither performs this procedure nor supplies any artwork.
CI imports only an original synthetic PNG generated inside its disposable test,
then reads and decodes an actually resized thumbnail over anonymous HTTP while
web uploads stay disabled. No image fixture is stored in Git or CI artifacts.
This does not import game images or establish that any artwork is cleared for publication.
