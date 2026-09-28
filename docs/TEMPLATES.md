# Native display templates

These ordinary MediaWiki templates use `Module:Display` (Scribunto Lua). Edit
their pages normally on the wiki; MediaWiki tracks transclusion dependencies
and refreshes readers through its job queue, without reseeding. Repository
copies live in `content/templates/` and `content/modules/`; the publisher
preserves human edits. No Item, Recipe, Ware, Acquisition or Collapsible
templates are part of this feature.

## Coins

`{{Coins|1234}}` displays **1 gold 2 silver 34 copper**, with the approved
denomination icons and accessible coin names. Input is total copper, not silver:
one gold = 1000 copper; one silver = 100 copper. Zero shows **0 copper**, and
other zero denominations are omitted. Icons are decorative/nonlinked, as in
the original price display; item and currency article links remain outside.

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

`Module:Display assets` is generated from the existing approved
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
