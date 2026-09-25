# Curated data and provenance

`content/facts/game.json` is a reviewed publication, not an extraction format.
The validator rejects unknown fields, duplicate JSON keys, missing references,
non-finite values, multiline strings, unsupported page/category names, and
oversized records. The entire file is limited to 640 KiB (655360 bytes).
This bounded allowance covers the vetted expanded reference; every other
publication path and size limit remains unchanged.

## Version 1 shape

The root requires `schema_version`, `game`, `sources`, `entities`, and `facts`.
Optional additive arrays `entries` and `illustrations` default to empty when
absent; the original version-1 dataset remains valid without them.
`schema_version` is integer `1`; booleans are not accepted in integer fields.

| Record | Required fields |
| --- | --- |
| `game` | `name` = `MirkLurk`, `developer` = short name or null, `build` = identifier or null, `steam_app_id` = `3972980` |
| Source | `id`, `path`, `sha256`, `build` |
| Entity | `id`, `category`, `name`, `confidence`, `evidence` |
| Skill entity only | Also `group`, referencing an existing `skill_group` entity |
| Fact | `id`, `page`, `entity`, `property`, `value`, `description`, `confidence`, `evidence` |
| Evidence reference | `source`, `section`, `key` |

Arrays may be empty during authoring. Every published entity and fact must cite
one to eight distinct evidence references. Stable record IDs are unique within
their respective arrays and match `[a-z0-9][a-z0-9_.-]{0,79}`.

Categories are `item`, `being`, `nature`, `skill_group`, `skill`, and
`damage_class`. They map to Items, Bestiary, Nature, Skills, and Damage types.
Mechanics facts may target those pages, Game mechanics, or any researched topic
listed below.

`value` permits only JSON booleans and finite numbers with magnitude at most
1,000,000,000,000,000. Include units or necessary context in `property`.
Do not turn a localized ID into an unproven gameplay identifier.
Use `name` for short factual names and `description` for original explanations,
never quotations or copied localization prose.

Text is trimmed, single-line Unicode. Names, labels, section/key identifiers,
and build strings are at most 160 characters; descriptions are at most 500.
Source paths are at most 255 characters.

## Structured research entries

Every entry requires `id`, `kind`, `title`, `summary`, `conditions`, `confidence`,
`evidence`, and `details`. `summary` is original prose of at most 1200 characters;
`conditions` is original text of at most 500 characters or null. Evidence and
confidence cover **every claim in that narrow record**. Split records when the
claims need different evidence or confidence; do not cite one branch of a
function for an entire inferred system.

| `kind` | Required `details` fields |
| --- | --- |
| `quest` | `quest_id`: short source identifier; `stage`: short label or null |
| `merchant` | `merchant`: being entity ID; `item`: item entity ID; `quantity`: positive integer or null; `price`: nonnegative number or null; `currency`: label or null; `location`: original text or null |
| `recipe` | `station`: short label; `inputs` and `outputs`: arrays of `{item, quantity}`; `cost`: `{amount, unit}` or null |
| `loot` | `table`: short trace identifier; `outcome`: item entity ID or null for an explicit empty result; `quantity`: `{min, max}` or null; `weight`: nonnegative number or null; `probability`: number from 0 to 1 or null; `rolls`: `{min, max}` or null |
| `algorithm` | `page`: Weather, Level progression, World seed logic, Skills, Crafting, or Loot tables; `steps`: one to twenty original prose steps; `fact_ids`: references to existing numeric/boolean fact IDs |

Quest entries paraphrase a **single** localized journal stage. A summary is not
a quotation, and a localized objective alone does not prove a runtime trigger.

Merchant records describe one offer. Random stock quantities may remain null
with the supported range explained precisely in the conditions/summary. A
known numeric price requires a currency/unit label; do not imply a final price
when only a base field is known. Locations may be unknown.

Recipe quantities are positive integers referencing existing item entities.
Inputs may be an empty array only for a documented recipe with no item inputs;
at least one output is required. Repeated input/output items must be combined,
and alternate output variants are separate records. Costs carry an explicit unit.

Loot quantity and roll ranges use nonnegative integers with `min <= max`.
An explicit empty outcome has null quantity or an explicitly recorded zero-to-zero
quantity range. Any positive quantity is rejected for an empty outcome. Weight is rendered as reported:
the builder **never derives or normalizes probabilities**. A numeric probability
requires supporting evidence for that conditional fraction; otherwise use null
and explain the observed selection semantics in original prose. Do not infer
independent rolls or completeness from a partial table.

Algorithm steps describe only the supported trace, not executable code.
Function symbols and field identifiers belong in evidence references; numeric
facts retain their own citations and are linked through stable anchors.

In all these fields, null means **not established**, not zero or no cost.
The exception is the expressly defined null loot outcome, which means a
documented empty result. Do not use it for an unknown item.

Entries map to Quests and journal, Merchants, Crafting, Loot tables, and the
algorithm page. New topic pages and navigation are generated only when at least
one validated entry or fact supports that page. Their authored introductions
are not published as empty completion-shaped placeholders.

Optional illustration metadata and its pending/approved rights gate are
specified in [IMAGES.md](IMAGES.md). Image bytes remain outside Git.

## Source identity

Each source gives an installation-relative INI path or `data.win` and the
lowercase, 64-character SHA-256 of the exact original file bytes. Backslash or
slash separators are accepted and displayed as slashes. Rooted paths, drive
prefixes, empty components, and parent traversal are rejected. The original
file is never committed, embedded in XML, or needed by the builder.

Source hashes are identifiers, not release numbers or licenses. A null `build`
means that the build is unknown. Do not infer a marketed release from an
internal GameMaker project name. Game-level and source-level build fields may
both remain null even when a file's hash is known.

Evidence `section` and `key` identify the original location. An INI citation uses
its section and key. A narrowly reviewed initializer observation may cite a
function **symbol** as section and a field identifier as key; these are location
identifiers, not copied code. The initial snapshot uses private local inspection
only; no decompiled text or extraction dump is part of this repository.

## Confidence semantics

| Value | Meaning |
| --- | --- |
| `observed` | Name or value observed in the cited source; not automatically a gameplay test |
| `localization-described` | Original summary of a mechanic described in local explanatory text, not a runtime-verified formula |
| `inferred` | Qualified interpretation needing confirmation, including literal initializer fields whose effective behavior is untested |

The first snapshot contains 336 entities: 247 items, 36 beings, 16 nature names,
25 skills, five skill groups, and seven damage classes. Its 79 numeric facts
comprise 28 localization-described summaries and 51 initializer observations.
Those counts describe the curated dataset, not the game's reachable content.

The first expanded handoff appends 28 numeric facts and 249 entries without
modifying the original records. It includes 31 quest/journal notes (28 localized
stage paraphrases and three separately qualified runtime notes), 63 merchant
offers, 96 base recipe variants, 27 conditional loot entries, and 32 algorithm
summaries (25 original skill descriptions and seven runtime/topic summaries).
A final bounded death-handler supplement adds 43 qualified base-loot entries and
one algorithm summary, preserving every prior record. Current totals are five
source fingerprints, 336 entities, 107 facts, and 293 entries: 31 quest/journal,
63 merchant, 96 recipe, 70 loot, and 33 algorithm records. Those immutable
records remain in `game.json`; the encyclopedia adds separately reviewed
presentation, profiles, and server-only image metadata.

The wiki operator confirmed installed build `0.8.1.5`, matching the menu label.
Only the formerly null `game.build` metadata field changes; reverting that
field restores the exact earlier file fingerprint. The operator's
latest-patch assertion is recorded as a user report in Source provenance,
not an independent global release check. Source record build fields/hashes,
all entities, and every historical fact/entry remain unchanged.
Coverage gaps are stated on the relevant pages. Reviewed creature death handlers
are documented, but base generation is not a guaranteed harvested yield;
runtime harvesting/recovery modifiers, some merchant locations/prices, and
world-seed reproducibility remain limited or unverified.

## Build output

The builder reads exactly the named authored pages and vetted JSON. It sorts
titles, records, and evidence for deterministic output; inputs are not executed.
Structured text is enclosed in escaped `nowiki` content, then XML-escaped.
MediaWiki export 0.11 includes content byte counts and base-36 SHA-1 fields
(format requirements, not security claims).

Page/revision IDs are synthetic, local to the bundle. The fixed seed timestamp
`2000-01-01T00:00:00Z` makes output reproducible; it is **not** a publication date,
game release date, or evidence of historical research. No deployment hostname
is embedded; entity and File links are relative MediaWiki links.

## Encyclopedia identities and ownership

`content/facts/catalog.json` (128 KiB maximum) contains `schema_version: 1`,
`pages`, `classifications`, and `entry_links`, with reviewed `entry_display`,
`stations`, `unit_prices`, and `currency` additions. It changes presentation
without rewriting historical evidence:

- `pages`: `{entity, title, aliases}` for every item, being, nature record,
  and skill, exactly once. Titles are locked ordinary names. Only collisions
  receive qualifiers: `Turnip (item)` and `Turnip (nature)`. Do not redirect
  ambiguous `Turnip` to just one record. Aliases are explicit previous
  titles, emitted as redirects; none may collide with a canonical title,
  another alias, or an authored index. Namespace syntax, fragments, markup,
  noncanonical spaces/underscores, and duplicate titles are rejected.
- `classifications`: `{entity, kind, confidence, evidence, note}`, where
  `kind` is `npc`, `creature`, or `unclassified`. Name/dialogue/database
  evidence supports this navigation grouping, not universal hostility,
  friendliness, survival, or reachability. A missing classification remains
  visibly unclassified; it is never silently labeled an enemy.
- `entry_links`: `{entry, entities}` for reviewed editorial crosslinks to
  existing records. These are see-also relationships, not a place to add a
  mechanic or unsupported semantic claim.
- `entry_display`: `{entry, title?, summary?, conditions?, steps?}` gives
  bounded original reader wording for an existing entry. Omitted fields keep
  their original value; conditions alone may be null. Technical stage/table
  labels can be replaced by reviewed descriptive titles without changing IDs,
  ordering, source evidence, or the underlying record. No guessed names for
  unidentified categories are introduced.

Five skill groups remain sections of Skills; seven damage classes remain on
Damage types. Other entities have dedicated pages. Facts with an exact,
unambiguous entity-name/category match move to that entity's page; ambiguous
matches fail. In particular, legacy skill facts retain `page: Game mechanics`
in the immutable data but are rendered only on their skill owners.

Merchant offers are primarily owned by the merchant. Recipes belong to the
output item (lowest stable item ID if a future recipe has several outputs).
Loot belongs to its uniquely identity-cited being, otherwise its outcome item;
unassigned/empty outcomes and general loot rules use Loot mechanics.
Skill mechanics entries use
the exact existing `<skill-id>-mechanics` association. Other algorithms and
quests retain their topic owner. Generic skill allocation is on Level
progression, not the Skills directory. Crafting is a workstation directory;
Inventory crafting owns general carried-tool requirements. Station-specific
behavior lives on the relevant workstation, with links to skills instead of
copied skill formulas.

Typed merchant/item/input/output/outcome references and exact matching entity
identity evidence produce bidirectional links. No substring guessing or
weight-to-probability normalization is used. Each complete record has one
primary editable wiki owner. Acquisition, ingredient, NPC, and workstation
catalog links do not repeat prices, ingredient quantities, AP costs, or quest
prose. Identical recipes may share one row with all applicable stations, but
different inputs, outputs, costs, or conditions remain distinct. Legacy
`entity-`, `fact-`, and `entry-` anchors remain
on old indexes as links, so old bookmarks are not silently broken.

Source provenance keeps IDs, hashes, confidence, evidence references, and
methodology. It points to the editable gameplay owner rather than duplicating
its values or prose. Reader pages contain invisible stable anchors, not
visible machine labels or repeated citation columns. Exact duplicate legacy
initializer facts and profile fields can share the same value row and retain
both anchors. Base, conditional, and potential values are not summed or
converted into invented final stats.

The CLI and Docker smoke load the checked-in registry and supplemental files
explicitly. `build_pages` also supports small caller-supplied datasets: omitted
catalog/profile arguments use a generated title proposal and no profiles.
Publication must use the reviewed inputs, not an automatically renamed
registry. Tests reject title collisions and verify complete record coverage.

## Workstations and user reports

Station rows contain `{id, title, entity, methods, summary, acquisition,
confidence, evidence}`. `entity` is either the existing canonical item ID
(the title must match) or null for a non-item workstation. `methods` account
for every exact source recipe-method label, without creating fake item IDs.
Optional `notes`, `related_entities`, and `quest_entries` provide original
station behavior and verified crosslinks. Optional `variants` have `{id,title}`.

One Alchemy workstation article covers early-game and later-game variants,
with a shared illustrated output catalog; both variants' identical recipes
are fully documented only on output-item pages. Armor workstation is identified
at Bhato's hideout with an evidenced follow-up-conversation unlock; it is not
marked unused merely because the item-title table lacks an entry.

Optional station `reports` are `{id, section, text, attribution, recorded_on}`.
The section is null or a known variant ID; attribution must be `Wiki operator`
and the date is ISO format. These are explicitly user-reported gameplay in
technical provenance, distinct from source-file evidence. Personal
correspondence and private identities are never included.

## Item-owned prices and currency

`unit_prices` contains version, verified unit, bounded original context,
`prices`, and exact `covered_offers` / `unresolved_offers` ID sets. Each price
is `{entity,value,confidence,evidence}` for a known item. Values are nonnegative
finite numbers, never booleans. The reviewed unit is silver coin equivalents.
The offer coverage is validated against actual merchant-to-item references.

The 36 verified standard prices do not depend on unresolved recipe-price
postprocessing; they cover 52 offers, leaving 11 offers unresolved. The
42 distinct offered items each own one selective `<onlyinclude>` price value.
The same item's matching raw initializer-value row is folded into it rather
than rendered twice. Merchant wares use `{{:Canonical item title}}`; the rest
of the item article is not transcluded. Actual vendor-specific prices, if
separately documented, remain owned by the vendor offer instead.

`currency` preserves the reviewed build confirmation, three coin definitions,
and seven original rule explanations with evidence and confidence. It
validates positive value/weight fields, coin identity, gram/kilogram agreement,
and exact agreement with existing profile values. Coin pages alone own value,
weight, and stack limits in selective summary tables; Currency and trading
transcludes those tables instead of hardcoding conversion/weight duplicates.

The guide distinguishes purchase value from condition-adjusted resale.
Fuel-based reduction replaces durability reduction when the required fields
exist; they are not multiplied. Rounded copper change is not claimed to
guarantee perfect sub-copper value preservation or globally optimal coin count.
The builder reports these reviewed rules; it does not execute game logic or
claim that a local arithmetic mirror was a gameplay test.

## Compact typed profiles

`content/facts/entity_details.json` (512 KiB maximum) has:

```json
{
  "schema_version": 1,
  "properties": [
    {
      "id": "example-property",
      "label": "Original property label",
      "unit": null,
      "description": "Original explanation of the field and its interpretation."
    }
  ],
  "profiles": []
}
```

Each profile is `{id, entity, context, confidence, evidence, values}`.
`values` is an object mapping one to 64 declared property IDs to finite
numbers, booleans, or null. Numeric magnitudes cannot exceed 10^15. Null
means unknown, never zero; strings, arrays, undeclared properties, duplicate
IDs, and missing/invalid evidence fail validation.

The profile's context, evidence, and confidence cover **every included value**.
Split profiles when evidence differs. Distinguish a literal initializer from
later postprocessing or a runtime measurement, particularly for weight, price,
damage, and availability. Shared labels/units/descriptions are original,
bounded prose, not copied item descriptions. Profiles supplement historical
facts rather than silently replacing them or claiming complete mechanics.

The reviewed profile snapshot contains 48 property definitions, 372 profiles,
and 2,456 scalar values for 297 entities (245 items, 36 beings, 16 nature
records). Seventy-five profiles separately describe the initializer's computed
attack-pattern totals. HP-grid dimensions are not presented as an invented
total HP. Literal weight/value fields are explicitly before recipe
postprocessing and trade/runtime changes. Flax and Linen retain source-known
name pages but have no invented initializer profile.

Image metadata has its own exact allowlist and schema, described in
[IMAGES.md](IMAGES.md). Neither supplemental file changes `game.json`, carries
image bytes, runs extraction, or authorizes deployment.
