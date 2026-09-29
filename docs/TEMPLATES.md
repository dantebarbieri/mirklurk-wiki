# Native display templates

These ordinary MediaWiki templates compose rows and use `Module:Display` (Scribunto Lua) for displays. Edit
their pages normally on the wiki; MediaWiki tracks transclusion dependencies
and refreshes readers through its job queue, without reseeding. Repository
copies live in `content/templates/` and `content/modules/`; the publisher
preserves human edits. The display templates are Coins, Health grid,
Attack grid, Creature, Item, Recipe row and Ware row. Unverified is a plain
wikitext marker, with no new runtime dependency. There is no Merchant
infobox, central recipe database, Acquisition or Collapsible template.

## Visual editor fields and source fallback

After the separately authorized [editor runtime rollout](DEPLOYMENT.md#visual-editing-and-rest),
**Edit** opens VisualEditor and **Edit source** keeps the classic wikitext editor.
The ordinary wiki article **Help:Editing** is the short contributor starting point.
All eight templates, including Unverified, carry TemplateData inside `noinclude`;
field documentation is never part of transcluded output. Select a simple
template and choose Edit to see labels, descriptions and examples. Examples
are not automatic values. Defaults describe existing behavior, not new facts.
Copper totals and quantities use string fields to retain exact 18-digit values;
the display module still validates them and reports invalid input.

Use visual editing for prose and simple Item, Creature, Coins and grid arguments.
Inspect the source diff before saving a template change. Unknown names, malformed
grids and invalid numbers still produce visible errors; field metadata does not
replace validation.

**Edit source is the supported workflow for Recipe row/Ware row inside selective
owners**, nested wikitext, literal price gates, `onlyinclude`/`noinclude`/`includeonly`,
`#switch`/`#if` filters and stable anchors. Row metadata explains these fields
without claiming the visual dialog can safely restructure them. Template and Lua
definitions also stay source-edited. Missing optional Ware row arguments omit
columns; inserting blank/default fields can change table geometry. Preserve the
owner's headers and do not paste rendered rows into workstations or seller views.

The disposable editor smoke checks no-change Parsoid round trips for generated
Iron Hand Axe, Copper Coin, Gurb-Gurb and Bandage, with all native displays and
synthetic selective fixtures. Ordinary browser template edits and source
preview/save with filtered AP propagation pass. **Modified visual editing of
existing recipe owners is not yet safe to release**, including prose-only edits:
each save adds another empty `onlyinclude` pair before the raw table. The strict
second-save assertion exposes this unresolved problem.

Synthetic complete-table wrappers pass two prose saves without source churn;
synthetic flat recipe templates pass two labeled quantity/AP edits without
changing other source or selective projections. Neither experiment changes the
production templates or factual owners. The flat prototype still exposes raw
view/filter routing fields and does not prove multi-row editing or automatic
discovery of new recipes. The production editor/migration design remains
pending; do not deploy this draft or infer arbitrary table/filter safety.

## Unverified

For uncertainty, put `{{Unverified}}` directly after the specific unconfirmed
claim. It renders a small **[unverified]** with a short tooltip, no category or
research-page link. Do not apply it merely because a fact came from extraction.
Unknown numbers remain **Unknown**, never zero. The marker is registered in
the same exact-file and publication namespace allowlists as display templates.

## Item

`{{Item|Iron Hand Axe}}` displays its reviewed icon and linked item name.
`{{Item|Plant Fiber|quantity=4}}` adds an exact positive integer quantity
(1 to 18 digits, no leading zeros); omit quantity for an ordinary list entry.
Ranges and source-specific quantity conditions stay in their existing cells,
not a guessed scalar. Use the **canonical page title**, for example
`{{Item|Turnip (item)}}`, retaining the displayed localized name `Turnip`.
Source IDs, source prefixes, arbitrary aliases, ambiguous names such as
`Turnip`, creatures, NPCs and construction actions produce visible errors.
Spaces, underscores and first-letter normalization follow MediaWiki, as for
Creature; remaining case is significant.

The generated registry contains 246 items from the existing item classification
and canonical page map. It explicitly excludes the catalog's **Finish Raft**
in-place construction action. Known items with missing/unapproved art show their
linked name without an icon (currently Flax, Linen and Unarmed); no filename,
subpage, duplicate stats or independent artwork registry is introduced.
Icons retain the 32px budget and integer-native scaling, even when native art
exceeds that budget. Icon and name line boxes are centered together; long names
can wrap, rather than clipping images into a fixed-height row.

The generated Items index, existing authored item category lists, capacity and
ingredient tables, recipe inputs/outputs, wares, acquisition/loot rows and
suitable reverse-reference lists actually use Item.
Canonical source descriptions, exact ranges, conditions, anchors, groupings and
native automatic category links are unchanged. Simple narrative/section links
are still links, not every mention of an item needs an icon.
In particular, the 538 dense random-treasure eligibility memberships retain
compact text links and their existing selectors: expanding icons through all
of those nested views exceeded MediaWiki's template include-size limit.
Their complete membership/order and compact item-side references are checked
in the real parser without raising runtime limits or omitting any candidates.

## Composable rows

These are **presentation**, not new factual owners. Keep the literal
`onlyinclude` / `#switch` selectors and `station` or `item` filters on the
owning article, with the row invocation **inside** them. Template arguments do
not inherit the caller's view/filter parameters. Stable variant anchors are
passed with `anchors`; merged variants retain all original anchors.

Syntax example (illustrative, not a verified recipe):

```text
{{Recipe row
|ingredients={{Item|Plant Fiber|quantity=4}}
|output={{Item|Bandage|quantity=1}}
|methods=[[Inventory crafting]]
|ap=2
|conditions=Use the documented requirements.
}}
```

Separate multiple inputs/outputs with `<br />`. `ap` accepts the documented
base cost, including fractional AP; `cost` preserves other units. Missing
cost/output/method/conditions say **Unknown**, never zero. `output`
may instead describe an in-place completion. The existing 96 recipe variants
remain 77 condition-preserving groups plus one construction row.
Workstations still transclude the output items' filtered recipe rows.

```text
{{Ware row
|seller=[[Magus Clay]]
|item=Iron Hand Axe
|price=<noinclude>{{:Iron Hand Axe}}</noinclude>
}}
```

Ware row calls Item itself. Optional `quantity`, `price`, `currency`, `location`
and `conditions` add cells in that order, matching the owner's table headers.
When a column exists but a value is unknown, pass **Unknown**; omit a
field only when its column is absent. Location, story availability and stock
disclosures shared by a section stay once on the owner, not copied per row.

**Keep the literal price gate on the merchant, not inside Ware row.** On the
merchant's full page the item transclusion supplies its price, ultimately
`{{Coins|...}}`. An item's filtered sellers view must omit that column and
must not transclude the item again. The header uses the matching `noinclude`
gate. For a genuinely mixed-price table, keep the column and use the existing
owner-level `includeonly` link to `Item title#price-item-id` for standard rows;
a vendor-specific exception may supply `{{Coins|1900}}` on its merchant row.
All 63 offers keep their six merchant owners; all 42 standard price blocks
stay on items. Shared stock/funds remain on Currency and trading.

## Creature

`{{Creature|Sceetler}}` or `{{Creature|Nightmare}}` displays a compact reviewed
portrait and linked canonical name. Both portrait and name link to the
creature's article, with useful portrait alt text, a name tooltip and an
accessible label. It does **not** copy health, attacks or loot, and is not a
full creature infobox. There are no per-creature template pages.

Use a creature's ordinary page title, not an entity ID or guessed filename.
Titles use MediaWiki normalization (surrounding spaces, underscores and the
first letter); the rest of the title's case remains significant. Only the
25 catalog-classified creatures are registered, not the 11 NPCs. Unknown
names, NPC names, namespaces, section fragments, empty input and titles over
160 bytes produce visible errors. A registered creature with absent or
unapproved art keeps its canonical name link without a missing-image notice;
it never guesses a file.

The lookup is generated from existing catalog classifications, canonical
page locations and approved role-less illustration metadata. It uses
`pixel_image()` with the existing 32-by-32 compact icon **budget**, never
forced resampling: larger native art is not shrunk below native resolution.
No second image registry or sizing policy is maintained.

Bestiary and the **existing authored lists** on faction and other creature
category pages now call this template, retaining their order, membership,
anchors and destinations. MediaWiki's automatically generated category member
labels remain plain text links; templates cannot change those native labels.
No skin hooks, JavaScript or duplicate member directory is added.

## Coins

`{{Coins|1234}}` displays **1 gold 2 silver 34 copper**, with the approved
denomination icons and accessible coin names. Input is total copper, not silver:
one gold = 1000 copper; one silver = 100 copper. Zero shows **0 copper**, and
other zero denominations are omitted. Icons are decorative/nonlinked, as in
the original price display; item and currency article links remain outside.
Each denomination is an inline-flex icon/text unit, centered by its line box
rather than the image baseline. Spaces between denominations allow wrapping;
there is no fixed-height crop, global image alignment change or raster resize.

Accept 1 to 18 ASCII digits, from 0 through **999999999999999999**, optionally
surrounded by whitespace. Leading zeros are accepted within the digit limit.
No negatives, signs, fractions, exponents, commas or other separators. Decimal
string splitting keeps the entire accepted domain exact; it does not claim
unbounded floating-point precision.

The generator still reads exact silver-equivalent `Decimal` prices and
multiplies by 100, rejecting sub-copper precision or out-of-domain totals.
Items own their selective `price` blocks and default price-only transclusions.
Merchants still include those item views, never copied prices. Coin articles
retain their own default value/weight/stack summary contracts.

## Health grid

`{{Health grid|1,1,1;1,4,1;1,1,1}}` is a **generic nine-HP square**.
It is not Sceetler's shape. The curated examples are:

```text
Sceetler (five HP, three armor layers on the center):
{{Health grid|0,1,0;1,4,1;0,1,0}}

Nightmare (seven rows, three columns, fourteen HP):
{{Health grid|1,1,0;0,1,1;1,1,0;0,1,1;1,1,0;0,1,1;1,1,0}}
```

| Scalar | Meaning |
| --- | --- |
| 0 | Hole; retains its position, no HP or shield |
| 1 | One HP, no armor |
| 2 | One HP, one armor layer (bronze shield) |
| 3 | One HP, two armor layers (silver shield) |
| 4 | One HP, three armor layers (gold shield) |

Shields never increase a cell's HP. Red backgrounds and 3em cell geometry are
preserved, with the accessible shield legend on **Health and armor**.

## Attack grid

Nightmare's pattern:
`{{Attack grid|0-1,0,0-1;0,1-2,0;0-1,0,0-1}}`.

Literal **0 is a gap**, but **0-1 is occupied** and can roll zero. A cell can
be an integer 1 through 1000 or a hyphen range with integer endpoints
0 through 1000, lower no greater than upper, and a positive upper endpoint.
Use `1-4`, not `1:4` or the game's encoded decimal representation. An entirely
empty attack pattern is allowed; an entirely empty health grid is not.
The sum of occupied-cell ranges is **not maximum actual damage**: target
overlap, armor and modifiers affect the result. The template retains this
caveat and links to the mechanics explanation.

The optional `label` is exactly `Attack pattern` (default), `Melee attack` or
`Ranged attack`. Article section headings and stable `grid-...` anchors remain
outside the template so melee/ranged navigation is unchanged.

## Geometry, accessibility and errors

Commas separate cells; semicolons separate rows. Read top to bottom, left to
right. Dimensions are inferred, up to **32 rows by 32 columns**. All rows must
have the same width. ASCII whitespace around cells is trimmed, but empty cells
or rows are never dropped. Do not put whitespace inside a range. Inputs are
bounded to **16384 bytes**, before splitting or rendering, as well as the
per-cell and geometry limits. Coins also apply this initial byte limit.

Every occupied cell has both a hover `title` and an `aria-label` stating its
row, column and HP/armor or damage. Holes retain explicit coordinate/empty
labels. Tables retain captions and horizontal overflow. Malformed, ragged,
empty, inverted, unsupported or oversized input renders a visible
`Display error:` alert, not an empty success-shaped table. User input is not
reflected into error HTML or arbitrary attributes.

`Module:Display assets` (including the item and creature lookups) is generated from the existing approved
`illustrations.json` metadata using the **same `pixel_image()` formatter** as
other illustrations. It contains exact escaped markup, not a second image
registry or Lua sizing policy. Coins use the 20px budget (16px native display);
shields use the 32px budget (2x native display). Both use original uploads,
integer-native zoom and no thumbnail/srcset. Image bytes stay outside Git.

## Runtime and publishing

Before any rollout, an operator must separately authorize, rebuild and deploy
the image enabling bundled Scribunto with `luastandalone`; merging content is
not deployment authorization. See [DEPLOYMENT.md](DEPLOYMENT.md) and
[PUBLISHING.md](PUBLISHING.md). Do not disable Scribunto while any live page
still depends on these templates.

TemplateData must also be deployed before publishing template metadata.
The publisher preflights extension/namespace/content-model registration and,
on apply, compiles the unsaved Lua modules and probes actual engine execution
through Scribunto's console API before **any page edits**. This only creates
an ephemeral console cache entry. Missing runtime, invalid Lua or wrong live
module models abort the run. The PR preview performs public reads only, with
no login, console execution or edits.

Modules precede templates, which precede readers; `mw.loadData` edges are
explicit dependencies. A failed or divergent human-edited display definition
blocks new/changed readers that depend on it (including transitive readers).
It is not overwritten: port and explicitly adopt the definition as described
in the publishing guide. Unchanged readers and human edits remain on the wiki.
Module changes trigger the same transitive refresh handling as selective views.
All 118 curated grids are checked for value/geometry parity, and disposable
MediaWiki tests cover parsed markup, limits, propagation and image semantics.
They also check all 25 creature icon identities and the actual parsed Bestiary
and faction lists; native category membership remains checked separately.
All 246 item lookups, authored lists, nested row arguments, exact prices,
filtered rows and ordinary template-edit propagation are parsed by MediaWiki.
The disposable browser runner uses the deployed Vector 2022 skin at desktop/mobile widths after
fonts and images load. It reproduces the old baseline error, measures coin
and item icon/text centers (at most 0.5 CSS px rounding error), checks native
16px coins, narrow wrapping and unchanged health cells, and saves synthetic-only
screenshots plus `geometry.json` in the CI `vector-layout` artifact.
