# MirkLurk Wiki

An independent MediaWiki foundation for **MirkLurk**, built from original writing,
short factual names, and carefully qualified mechanics observations. This
repository does **not** contain the game, its assets, its localization prose, or
decompiled source.

The initial curated snapshot contains 336 name records and 79 numeric facts
supported by five source-file fingerprints. Names establish source associations,
not availability or combat behavior. The 28 localization-described mechanics have
not been runtime-verified; the other 51 facts are qualified initializer
observations. The operator confirmed the installed build as **0.8.1.5**,
corroborating the inspected menu label. The claim that this is the latest patch
is operator-reported, not an independent release-feed check.

The expanded reference retains that baseline and now contains **107 numeric facts
and 293 structured entries**: 31 quest/journal notes, 63 merchant offers,
96 station-specific recipe variants, 70 conditional loot entries, and 33
original algorithm/skill summaries. The encyclopedia presentation generates
364 main-namespace pages: 331 individual item, being, nature, skill, and damage-type pages,
plus workstation articles, topic guides/indexes, provenance, and a compatibility
redirect. Another 44 ordinary MediaWiki category pages support grouped browsing.
Only `game.build` changed in the original dataset; all source
fingerprints, entities, facts, and research entries remain unchanged.

Supplemental source-scoped profiles preserve **2,559 scalar values**
in 475 profiles across 297 entities: 245 items, 36 beings, and 16 nature records.
Their 49 shared property definitions distinguish literal initializer values,
computed attack-pattern totals, and unresolved runtime effects. Flax and Linen
have localized names but no reviewed initializer profile; no stats are invented
for them. The original 372 profiles are unchanged; 103 additions document
equipment AP costs separately from attack/use costs.

The 118 curated grids preserve 36 base health shapes and 82 attack patterns,
including holes, orientation, armor layers, and occupied zero-to-one cells.
Original accessible HTML/CSS tables reference three separately approved shield
sprites for armored health cells; image bytes remain outside Git. Health cells
represent one HP with separate armor; summed attack ranges are not maximum
actual damage. Damage pages explain initial-hit versus spreading status
effects and link to their weapons, attacks, skills, and remedies.
Explicit projectile evidence adds poison-ammunition and thrown-flask links,
including the flasks' armor-bypass exceptions. Ammunition bonus ranges are
decoded per attack cell, not shown as misleading fractional damage.

The metadata-only artwork register covers 326 reviewed selections: 243 items,
36 beings, 25 skills, 16 nature records, and three workstation variants.
Three shared health shields show
bronze for 1 armor layer, silver for 2, and gold for 3 at a compact 32px size.
Four item images are deliberately
omitted rather than replaced with placeholders or guessed frames. Willow, Cypress, and Trollgnarl now use distinct reviewed mature compositions
assembled from native parts and the verified tree rules. Only their three
metadata records change; the other 323 selections are preserved. Older tree
File pages and bytes remain live history, not overwritten artwork. Other nature
pictures retain their explicit ground-tile or branch qualifications. Image bytes
stay in separately approved server storage.

Separate Satiation, Stamina, Focus, Temperature, Wellbeing, Foods, and Resting
guides explain the survival meters, threshold effects, recovery, weather
exposure, and combat-healing distinction. They reuse approved item pictures in
context, not invented stat icons. Meter-specific rates stay on meter pages,
combined effects on Wellbeing, bed recovery and natural healing on Resting,
and ten reviewed consumption effects on their item owners.

Gameplay pages use compact tables and ordinary names, with machine IDs and
citations kept in Source provenance. Each detail has **one editable wiki owner**:
recipes on output items, offers on merchants, quest prose in the journal, and
workstation behavior on its own page. Identical recipes across stations share
one row; 96 original variants form 77 condition-preserving recipe groups.
Workstations show the complete applicable recipe rows by selective transclusion
from their output-item owners; editing ingredients or AP there updates every
station view. Item acquisition sections likewise select seller availability
from merchant-owned rows without copying stock or conditions.

Thirty-six verified standard unit prices cover 52 of 63 offers. Each offered
item owns one `<onlyinclude>` price value (unknown where unresolved), and
merchant tables transclude it rather than copying prices.
The Currency and trading guide likewise transcludes coin-owned denomination,
weight, and stack tables. The bundled ParserFunctions extension selects named recipe and seller views;
no new namespace, recipe subpage, synchronization service, or hidden data store
is required. Unparameterized item and coin inclusions retain their original
price-only and coin-summary contracts. Live edits to the owner propagate to
readers of that information.
Exact decimal price formatting uses gold, silver, and copper with the fewest
whole coins, preserving the item-owned selective blocks. Initializer values
remain explicitly distinct from shop prices and finalized recipe weights.
Semantic units show chances and insulation/waterproofing as percentages,
verified weight as kg/g, and action/equip costs as linked AP.

The additive research format supports original quest/journal paraphrases,
merchant offers, station-specific recipes, loot-selection observations, and
weather, progression, skill, and world-seed summaries. Each narrow claim carries
evidence and confidence. New topic pages appear only when backed by reviewed
entries or facts; schema support is not a claim that a subsystem is fully documented.
Reviewed death-handler cases now document base creature loot, and lit campfire/
field-kit menus are traced. Runtime harvesting/recovery modifiers, some merchant
locations and prices, and world-seed reproducibility remain limited or unverified.
The current loot reference is not an exhaustive loot-table catalogue.

## Contents

| Location | Purpose |
| --- | --- |
| `content/pages` | Original wikitext introductions, navigation, policies, and caveats |
| `content/facts/game.json` | Vetted names, numeric facts, structured research, and provenance, not raw research |
| `content/facts/catalog.json` | Stable ordinary page titles, evidence-backed classifications, and editorial crosslinks |
| `content/facts/entity_details.json` | Bounded typed profiles with shared original property explanations |
| `content/facts/illustrations.json` | Individually reviewed, server-only image references and rights metadata |
| `tools/build_wiki.py` | Deterministic MediaWiki XML for reviewed seeding |
| `tools/wiki_views.py` | Named selective-view contracts and explicit dependencies |
| `tools/plan_migration.py` | Three-way review report that never modifies a wiki |
| `tools/check_publication.py` | Exact-file, size, text, secret-pattern, and Git-index checks |
| `deploy` | Digest-pinned MediaWiki image, nonsecret runtime template, development Compose |
| `tests` | Publication, facts, escaping, deterministic export, and runtime-policy tests |

## Work locally

The content tools require Python 3.11+ and Git, with no third-party Python
packages. From PowerShell:

```powershell
python -m unittest discover -s tests -v
python tools\build_wiki.py --fresh --output .local\seed.xml
git add -- .gitignore .gitattributes .dockerignore README.md CONTRIBUTING.md docs content tools tests deploy .github
python tools\check_publication.py
```

If `python` is the Windows Store alias and Ubuntu WSL is already installed, use
`wsl --distribution Ubuntu --exec python3` instead of `python`. For the builder,
use `--output seed.xml` from that runtime; the default deny rule also ignores that
output. No package installation is necessary. Python commands work on other
platforms with their usual path separators.

The builder requires an explicit fresh/additive mode, refuses to overwrite an
output file, and never connects to a wiki. **Do not import a fresh seed into an
existing community wiki.** Follow [the import procedure](docs/IMPORTING.md).

Entity pages use ordinary names; only collisions are qualified, such as
**Turnip (item)** and **Turnip (nature)**. NPCs are indexed separately from
creatures, without assuming either grouping guarantees peacefulness or
hostility. Skill-specific facts and summaries live on individual skill pages;
old aggregate anchors remain as links. Initial research records are unchanged.

## Operate a wiki

[Deployment instructions](docs/DEPLOYMENT.md) describe the reusable image and
secret-file interface. The default policy is public reading, open registration,
logged-in editing, no anonymous edits, and no uploads. Required QuestyCaptcha
questions and shared-cache rate limits provide a baseline against signup spam;
they are not a substitute for moderation. Email and email-based resets are
disabled.

Optional [illustration references](docs/IMAGES.md) keep all image bytes outside
Git. Only separately rights-approved pictures may be imported by an operator
into MediaWiki storage; pending references never embed artwork, and public web
uploads remain disabled.

The hostname is supplied at runtime. This repository does not configure DNS,
certificates, a reverse proxy, a homeserver, or any existing credentials.
Development Compose binds only to loopback and is **not** a production stack.

## Publication and rights

Read [CONTRIBUTING.md](CONTRIBUTING.md), the
[provenance format](docs/PROVENANCE.md), and the
[publication checklist](docs/PUBLICATION.md) before adding anything.

The root ignore file denies everything except individually named authored files.
**Ignore rules do not protect tracked files or files added with `git add --force`.**
Run the staged-blob checker and inspect the staged diff before every commit.

This is an unofficial reference. Game material and names remain subject to their
owners' rights. No blanket license to game content is granted, and no
repository-wide redistribution license is asserted. Public visibility is not a
claim of ownership or permission to redistribute third-party material.
