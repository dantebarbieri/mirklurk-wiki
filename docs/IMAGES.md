# Server-only illustrations and rights review

Image bytes never belong in this repository, its Git history, CI artifacts,
issues, or pull requests. MediaWiki may serve separately approved pictures from
its persistent `/var/www/html/images` storage. That is an operator workflow,
not an exception to the repository's asset exclusions.

On 2026-09-25, the wiki operator reported permission to display game artwork
on the public wiki. This is **not permission to put assets in Git or grant
a redistribution license**. Each selected image still requires verified
identity, attribution, bytes, and an operator-reviewed import. Owning or
inspecting the game would not itself establish that permission.

## Metadata only

Optional `illustrations` records associate an item, being, nature record, or
skill with a stable local title such as `File:Item-2.png`. The encyclopedia
stores new records in the exact allowlisted `content/facts/illustrations.json`
with root `{"schema_version": 1, "illustrations": [...]}` and a 512 KiB cap.
Non-item workstation illustrations use `station` instead of `entity`, with an
optional reviewed `variant` ID. The target must exist in the station registry;
item workstations reuse their entity images. Legacy `game.json` illustration
support remains compatible; duplicate IDs or
File titles across both inputs are rejected. There are no URLs, domain
names, local source paths, image bytes, download instructions, or automatic
uploads in these records.

Every record contains `id`, `file_title`, `caption`, `creator`,
`sha256`, `rights_status`, `rights_basis`, `rights_note`, `confidence`, and
`evidence`, plus exactly one target: `entity`, `station`, or `health_armor`.
Only station targets may have `variant`. Evidence uses the existing source/section/key format; the SHA-256
identifies the exact separately reviewed **image** bytes, not the original game
container. Captions and rights notes are original writing.

The current reviewed batch attributes game artwork to **Edym Pixels** and
records operator-reported permission for public-wiki display, confirmed on
2026-09-25. Its notes explicitly exclude asset redistribution through this
repository. Actual image hashes and source-to-frame associations must be
reviewed individually; attribution strings are not a substitute for review.

The original metadata batch contains 323 selections: 243 items, 36 beings,
25 skills, 16 nature records, and early/later alchemy plus armor workstations.
The original 320 entity records are unchanged. Unarmed's internal pixel placeholder is not
used as artwork. Flax and Linen lack verified initializer image associations.
Finish Raft requests an out-of-range sprite frame; no wraparound or replacement
frame is guessed. These four item pages therefore have no image reference.

Some nature records use their associated ground tile, explicitly captioned as
not a complete mature specimen; Rift Vine uses a branch detail. Do not relabel
these crops as full procedurally assembled plants. The metadata only identifies
the reviewed selection; source files and images remain outside Git.

Three shared shield records bring the total to 326 without changing any of the
original 323 selections. They use `health_armor`, an integer restricted to 1,
2, or 3, not a fabricated entity. Each level has exactly one reserved File title:

| Armor layers | Shield | File title | Sprite frame | PNG bytes |
| --- | --- | --- | --- | --- |
| 1 | Bronze | `File:Health-armor-1.png` | 11 | 188 |
| 2 | Silver | `File:Health-armor-2.png` | 12 | 213 |
| 3 | Gold | `File:Health-armor-3.png` | 13 | 230 |

The reviewed `spr_ui_16x16` frames are native 16x16 RGBA overlays, privately
scaled to 64x64 PNG using integer nearest-neighbor scaling. The health-cell
renderer uses a 32px File reference over the existing red base and preserves
the cell dimensions. HP and armor remain in the cell's title and ARIA label
and the image's alt text; there is no additional visible armor-count chip.
The Health and armor guide owns the three-shield legend.
The frame association is cited through `hpcell_draw` in Source provenance.
Actual PNG hashes, rights, and exact evidence keys are in each metadata record.
No additional health art or other frames are included in this approval.

For `rights_status: pending`, creator/hash/rights fields may be null. A pending
entity or station record renders a neutral missing-picture notice, **not** an image or File link.
Its reserved title and rights/evidence details remain on Source provenance.
Do not manufacture empty records for every entity.
Shared shields are required when armored grids or a shield legend are built:
missing or pending shield metadata raises an explicit `DataError`, rather than
publishing broken images, guessing another level, or falling back to brown.
Zero-armor cells and holes never reference a shield; values above 3 are rejected.

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
CI imports only original synthetic PNGs generated inside its disposable test:
one RGB thumbnail fixture and three RGBA fixtures under the shield File titles.
It reads and decodes resized thumbnails over anonymous HTTP, including 32x32
shield fixtures, then checks actual MediaWiki-parsed shield cells and the legend
while web uploads stay disabled. Those fixtures are not game artwork or evidence
of approved game-image hashes. No image fixture is stored in Git or CI artifacts.
This does not import game images or establish that any artwork is cleared for publication.
