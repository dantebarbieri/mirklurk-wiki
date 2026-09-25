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
63 merchant, 96 recipe, 70 loot, and 33 algorithm records. There are no
illustration records or approved artwork.

The separate observed menu label `0.8.1.5` is documented with explicit source
field citations in Game mechanics; it does not replace null release metadata.
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
game release date, or evidence of historical research. No hostname is embedded.
