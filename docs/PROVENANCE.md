# Curated data and provenance

`content/facts/game.json` is a reviewed publication, not an extraction format.
The validator rejects unknown fields, duplicate JSON keys, missing references,
non-finite values, multiline strings, unsupported page/category names, and
oversized records. The entire file is limited to 512 KiB.

## Version 1 shape

The root has exactly `schema_version`, `game`, `sources`, `entities`, and `facts`.
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
Mechanics facts may target those pages or Game mechanics.

`value` permits only JSON booleans and finite numbers with magnitude at most
1,000,000,000,000,000. Include units or necessary context in `property`.
Do not turn a localized ID into an unproven gameplay identifier.
Use `name` for short factual names and `description` for original explanations,
never quotations or copied localization prose.

Text is trimmed, single-line Unicode. Names, labels, section/key identifiers,
and build strings are at most 160 characters; descriptions are at most 500.
Source paths are at most 255 characters.

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

## Build output

The builder reads exactly the named authored pages and vetted JSON. It sorts
titles, records, and evidence for deterministic output; inputs are not executed.
Structured text is enclosed in escaped `nowiki` content, then XML-escaped.
MediaWiki export 0.11 includes content byte counts and base-36 SHA-1 fields
(format requirements, not security claims).

Page/revision IDs are synthetic, local to the bundle. The fixed seed timestamp
`2000-01-01T00:00:00Z` makes output reproducible; it is **not** a publication date,
game release date, or evidence of historical research. No hostname is embedded.
