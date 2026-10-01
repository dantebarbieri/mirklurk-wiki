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
Only station targets may have `variant`. A being-targeted record may additionally
have `role: "location"`: one supplementary exterior per NPC with a reviewed
location section, or `role: "sprite"`: one supplementary overworld sprite per
being that also has an approved primary portrait. Other roles, non-being targets,
duplicate roles per being and missing location owners are rejected. Records
without a role retain their primary image behavior; portraits, icons and existing
contextual guide lookups never select a location or sprite image, regardless of
record ordering.
Evidence uses the existing source/section/key format; the SHA-256
identifies the exact separately reviewed **image** bytes, not the original game
container. Captions and rights notes are original writing.

Mechanics guides may reuse an existing approved entity image through
`image_entity` and an original `image_caption` in the guide record. This creates
no duplicate illustration record, image bytes, or import. The caption must
describe the pictured item in context, not relabel item artwork as a stat glyph.
Missing, pending, and unknown image associations are rejected explicitly.

The current reviewed batch attributes game artwork to **Edym Pixels** and
records operator-reported permission for public-wiki display, confirmed on
2026-09-25. Its notes explicitly exclude asset redistribution through this
repository. Actual image hashes and source-to-frame associations must be
reviewed individually; attribution strings are not a substitute for review.

The original metadata batch contains 323 selections: 243 items, 36 beings,
25 skills, 16 nature records, and early/later alchemy plus armor workstations.
Unarmed's internal pixel placeholder is not
used as artwork. Flax and Linen lack verified initializer image associations.
Finish Raft requests an out-of-range sprite frame; no wraparound or replacement
frame is guessed. These four item pages therefore have no image reference.

Some nature records use their associated ground tile, explicitly captioned as
not a complete mature specimen; Rift Vine uses a branch detail. Do not relabel
these crops as full procedurally assembled plants. The metadata only identifies
the reviewed selection; source files and images remain outside Git.

Three shared shield records originally brought the total to 326. They use `health_armor`, an integer restricted to 1,
2, or 3, not a fabricated entity. Each level has exactly one reserved File title:

| Armor layers | Shield | File title | Sprite frame | PNG bytes |
| --- | --- | --- | --- | --- |
| 1 | Bronze | `File:Health-armor-1.png` | 11 | 188 |
| 2 | Silver | `File:Health-armor-2.png` | 12 | 213 |
| 3 | Gold | `File:Health-armor-3.png` | 13 | 230 |

The reviewed `spr_ui_16x16` frames are native 16x16 RGBA overlays, privately
scaled to 64x64 PNG using integer nearest-neighbor scaling. The health-cell
renderer displays the original File at 32px over the existing red base and preserves
the cell dimensions. HP and armor remain in the cell's title and ARIA label
and the image's alt text; there is no additional visible armor-count chip.
The Health and armor guide owns the three-shield legend.
The frame association is cited through `hpcell_draw` in Source provenance.
Actual PNG hashes, rights, and exact evidence keys are in each metadata record.
No additional health art or other frames are included in this approval.

## Site branding

On 2026-09-28, the operator selected two supplied PNGs for the wiki logo and
browser favicon and explicitly authorized applying them to the live wiki.
They are attributed to Edym Pixels under the operator-reported public-wiki
display permission above, not licensed for redistribution through Git.

| Role | Original dimensions | PNG bytes | SHA-256 |
| --- | --- | --- | --- |
| Wiki logo / Vector 2022 icon | 256 x 256 | 16563 | `2d0fdbb12de9e09a83be6fd9742ddc40b838be1f8b2a7626b3930171f7112064` |
| Browser favicon | 184 x 184 | 5201 | `d365cdb569ecd682bbfcdbb60835d6ba10b98cf129f576b1554fa9e4ef7e9416` |

Preserve these exact originals. Privately derive a separate 128 x 128
nearest-neighbor logo for legacy skins, which otherwise crop a 256px `1x`
image. Stage the three distinct PNGs in a dedicated, backed-up read-only
branding mount with a public attribution text file, or import them with original
attribution sidecars. Verify their served bytes before configuring the runtime.
Attribution must identify the derivative's source fingerprint and resizing method.
The 184px PNG is supported directly as the favicon; do not relabel PNG bytes
as an ICO file. Vector 2022 shows the original logo in its native 50px header
slot alongside the wiki title, not as a replacement wordmark.

These are site-interface assets, not entity illustrations, and do not change
the 337-entry artwork register or any gameplay page. No branding bytes,
thumbnails or encoded image fixtures belong in Git, the application image,
CI artifacts or pull requests. Runtime paths and rollout requirements are
documented in [Deployment](DEPLOYMENT.md#site-logo-and-favicon).

## Reviewed mature-tree replacements

The acquisition and wellbeing release replaces only the existing illustration
records for Willow, Cypress, Trollgnarl, and Elderwort Shrub. All other 322 active selections,
including the three shields, stay unchanged. The replacement captions identify
representative mature compositions assembled from native trunk, branch, and
leaf sprites using reviewed growth, attachment, origin, mirroring, and draw
rules. They are healthy wind-neutral representatives, not single whole-tree
sprites or a promise to replay one random in-game specimen.

| Preserved old File title | New File title | PNG dimensions | PNG bytes |
| --- | --- | --- | --- |
| `File:Nature-4.png` | `File:Nature-4-mature.png` | 588 x 564 | 7512 |
| `File:Nature-7.png` | `File:Nature-7-mature.png` | 684 x 912 | 15112 |
| `File:Nature-17.png` | `File:Nature-17-mature.png` | 340 x 540 | 4356 |
| `File:Nature-20.png` | `File:Nature-20-mature.png` | 256 x 256 | 2441 |

The reviewed hashes and assembly evidence are in `illustrations.json`.
Elderwort is naturally a small flowering shrub, not a tall-trunk tree.
Import exactly the four new titles with their attribution sidecars through
the approved operator workflow; do not overwrite, rename, or delete the old
File pages or image bytes. That replacement retained 326 active authored
selections while reaching 330 uploaded game images after the separate import.
Guide pictures reuse existing approved File titles and require no extra
uploads or duplicate metadata. This document is not deployment authorization.

## Reviewed NPC landmarks

The 2026-09-26 selection adds exactly three native exterior frames. All 326
previous metadata records, including the three NPC portraits, remain unchanged.
These additions bring the active register to 329 and, after the separate import,
the retained uploaded game-image total to 333 before site branding. The disposable
test's 337 synthetic fixtures include three branding images and its extra
thumbnail test image; that is not a production count.

| NPC / preserved portrait | New File title | Native dimensions | PNG bytes | Source frame |
| --- | --- | --- | --- | --- |
| Ranger Bhato / `File:Being-12.png` | `File:Ranger-Bhato-hut-exterior.png` | 48 x 48 | 2850 | `spr_built_48x32`, 0 |
| Gurb-Gurb / `File:Being-26.png` | `File:Gurb-Gurb-hollow-exterior.png` | 80 x 128 | 4558 | `spr_building_80x80`, 0 |
| Ihar / `File:Being-33.png` | `File:Ihar-shipwreck-exterior.png` | 128 x 96 | 5379 | `spr_building_128x64`, 0 |

Exact native-image hashes, Edym Pixels attribution, original captions, evidence
and the operator-reported permission basis are in the three `role: "location"`
records. Gurb-Gurb's smoke is a separate runtime effect, not an overlay in the
PNG. Bhato's frame 0 is the hut, not the different frame 1 entrance.

The location sections now use the original-file integer-scaling policy below:
Bhato's hut is displayed at 192 x 192 (4x), Gurb-Gurb's hollow at 160 x 256 (2x),
and Ihar's shipwreck at 128 x 96 (1x). Approved bytes are never rewritten.
No compact icon consumer uses these exteriors. Import the three exact
titles with their attribution sidecars before the pages that embed them are
published; the sync lists every referenced File that is still missing, and an
existing File title alone is not display evidence. Do not overwrite existing
Files or upload smoke components, previews or unrelated artwork.

## Reviewed NPC overworld sprites

The 2026-10-01 selection adds exactly eight native overworld sprites for NPCs
that previously showed only a dialogue portrait. Soldier and Unwanted Guard
already use their overworld sprite as the primary image and are unchanged.
Dead Unwanted's `beingDB` entry uses `spr_blank`, so it has no overworld sprite.
All 329 previous records remain unchanged; the register is now 337, and after
the separate import the retained uploaded game-image total is 341 before site
branding (345 disposable synthetic fixtures).

Each sprite is the `beingDB[N].sprite` association from
`gml_Object_databank_Alarm_3`, frame 0, exported on its full padded canvas
(matching the existing Soldier and Unwanted Guard convention) and privately
enlarged with integer nearest-neighbor scaling. The figure follows the portrait
on the entity page, adds `notpageimage` and never becomes the page image or icon.

| NPC | New File title | Source sprite | Native | Scale | PNG bytes |
| --- | --- | --- | --- | --- | --- |
| Captain Eir | `File:Being-6-overworld.png` | `spr_captain_eir` | 48 x 40 | 5x | 1869 |
| Magus Clay | `File:Being-8-overworld.png` | `spr_clay` | 40 x 40 | 6x | 2481 |
| Ranger Bhato | `File:Being-12-overworld.png` | `spr_ranger_t` | 48 x 40 | 5x | 1641 |
| Viend | `File:Being-19-overworld.png` | `spr_viend` | 40 x 40 | 6x | 2132 |
| Commander Tain | `File:Being-20-overworld.png` | `spr_commander_tain` | 40 x 40 | 6x | 1583 |
| Gurb-Gurb | `File:Being-26-overworld.png` | `spr_gurb` | 32 x 32 | 7x | 2337 |
| Ihar | `File:Being-33-overworld.png` | `spr_ihar` | 40 x 40 | 6x | 2273 |
| Wilda | `File:Being-34-overworld.png` | `spr_wilda` | 48 x 40 | 5x | 1892 |

Exact hashes, Edym Pixels attribution, original captions and evidence are in
the eight `role: "sprite"` records. All eight were decoded and verified to
reduce exactly to their native frame. Import the eight exact titles with their
attribution sidecars before publishing pages that embed them; do not overwrite
the existing portraits.
For `rights_status: pending`, creator/hash/rights fields may be null. A pending
entity or station record renders a neutral missing-picture notice, **not** an image or File link.
Its reserved title and rights/evidence details remain on Source provenance.
Do not manufacture empty records for every entity.
Shared shields are required when armored grids or a shield legend are built:
missing or pending shield metadata raises an explicit `DataError`, rather than
publishing broken images, guessing another level, or falling back to brown.
Zero-armor cells and holes never reference a shield; values above 3 are rejected.

For `rights_status: approved`, creator, hash, rights basis, review note and
reviewed `pixel_art` geometry are required.
An approved flag is a recorded human decision, not a legal conclusion made by
the software. The builder cannot verify permission or the live file's existence.
Publish approved metadata only after the corresponding operator import is ready.

Titles are restricted to simple ASCII raster-image basenames: PNG, JPEG, or
WebP. Use stable names, not version-specific host URLs. MediaWiki resolves these
relative File references after a domain migration.

## Crisp integer-scaled presentation

Every approved record carries `pixel_art: {width, height, source_scale}`:
the exact uploaded raster dimensions and its integer nearest-neighbor
enlargement from native pixels. Dimensions must be positive, bounded integers
divisible by the scale. This is metadata, not a new asset or permission grant.
All 329 PNGs current before the overworld sprites were hash-matched and decoded during review: reducing
each by its recorded scale and re-enlarging with nearest-neighbor reproduces
every RGBA pixel exactly. Existing export receipts supply most dimensions.
The 12 active 128px nature tiles have a unique 16px/8x inverse under their
recorded export algorithm; the three workstation frames were additionally
compared pixel-for-pixel with their native frames. Source scales vary from 1x
to 8x; never assume every previous upload was 4x.

The shared `pixel_image` renderer requests ordinary `File` embeds at the
uploaded width, **not** `thumb` or `frameless`. MediaWiki therefore serves the
original, not a resampled thumbnail or density-dependent `srcset`. A shipped
inline wrapper applies `image-rendering:pixelated` and CSS
`zoom:calc(display_scale / source_scale)`. The resulting width and height are
exact integer multiples of the native grid, even when an upload had previously
been enlarged 3x, 5x or 6x. Applying pixelated CSS to a blurred thumbnail would
not restore its lost detail and is deliberately avoided. Link previews likewise
share a nearest-neighbour whole-number enlargement of the lead figure, never a
smoothed thumbnail (see [DEPLOYMENT.md](DEPLOYMENT.md#canonical-urls-descriptions-and-social-sharing)).

Main illustrations choose the largest whole native-pixel scale within a
224 x 288 box, with a minimum of 1x. Captions stay at normal text size.
Table icons use a separate 32 x 32 budget; coins use 20 x 20 (rounding down to
a whole native scale, never below 1x). Shields retain their exact 32 x 32
display over the unchanged health cells, using the original 64px upload at
2x the native 16px grid. Large native sprites are not fractionally squeezed
just to fit an icon budget.

Figure containers are bounded by their parent's width and horizontally
scroll on exceptionally narrow layouts rather than interpolating, cropping
or distorting the art. Ordinary phone layouts fit these figures without
page overflow. This content-only policy ships through the existing namespace
0/14 publisher: it needs no unshipped Common.css, site JavaScript, new runtime
deployment or artwork reimport. File-page links and alt text remain intact.

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
an RGB thumbnail fixture and distinct RGBA fixtures under the shield, contextual
guide, mature-tree, and legacy-tree File titles.
It reads and decodes resized thumbnails over anonymous HTTP, including 32x32
shield fixtures, then checks actual MediaWiki-parsed shield cells and the legend
while web uploads stay disabled. Those fixtures are not game artwork or evidence
of approved game-image hashes. No image fixture is stored in Git or CI artifacts.
This does not import game images or establish that any artwork is cleared for publication.
The same smoke checks guide images and links, mature-tree captions/references,
and byte-for-byte preservation of the four legacy tree fixtures after seeding.
Native-sized synthetic landmark fixtures also exercise the explicit 220px request,
both retained portraits and rendered exterior images, and anonymous PNG reads.
