---
name: game-update
description: >-
  Documents a new MirkLurk game version on mirklurk.wiki: the Version changelog page, the build bump, new source fingerprints,
  amended facts, new items and their art, test pins, then a squash-merged PR that publishes and a live check. Use when a MirkLurk
  patch is out and the wiki must catch up, or when the mirklurk-game-update coordinator hands this repo a patch report.
---

# Game update (wiki)

**Goal:** one squash-merged PR, titled `Document MirkLurk patch <v>`, after which mirklurk.wiki shows `<v>` everywhere, has a
**Version `<v>`** changelog, and every fact the patch changed is amended and cited to the new build.

The personal coordinator skill `mirklurk-game-update` (`~/.copilot/skills/mirklurk-game-update/`) owns the shared work: backing
up `data.win`, the Steam patch notes, decompiling and diffing, and the findings report. Start from its report. MirkMap
(`dantebarbieri/mirklurk-map`) has its own `game-update` skill and session.

Below, `<v>` is the new version (`0.9.1.0`), `<p>` the previous one, and `<d>` the version digits (`0910`).

| Precedent | Shape |
| --- | --- |
| #66 (0.9.1.0) | New items with art, recipes and treasure pools; amended recipes; `Items`/`UI` fingerprints. Start here for new items. |
| #64 (0.9.0.2) | Fixes only: Version page, build bump, `game-data-0902`. Start here for a fixes-only patch. |
| #62 (0.9.0.1) | Amended facts, new `.ini` fingerprints, an item rename with redirect and File moves. |
| #52 (0.9.0.0) | Release relabel; old `Version 0.8.9.9` title redirected by `tools/wiki_render.py`. |
| #45 (0.8.9.9) | 24 new entities with profiles, entries, acquisition rows and art; two renames. |

## Rules

- Never commit or paste dumps, decompiled code, game text, `.ini` files or images, in the repo, PR text or commits. Cite code
  as section = entry or function name, key = field ([source identity](../../../docs/PROVENANCE.md#source-identity)).
  `tools/check_publication.py` also rejects personal absolute paths and lines shaped like decompiled functions.
- Never modify anything in the game folder.
- Verify every claim in the new dump, reading the whole function, not just the hunk. Label changes the patch notes omit with
  "Not in the patch notes:". Write reader prose as [CONTRIBUTING](../../../CONTRIBUTING.md#reader-facing-prose) asks.

## 1. Inputs

From the coordinator: `patch-<v>-report.md`, `patch-<v>-analysis.md`, `steam-notes-<v>.md`, `code.diff`, `strings.diff`,
`dump-<v>\` and `dump-<p>\`, `Languages-<v>\English\*.ini`, and the SHA-256 of `data.<v>.win`.

**No report?** If the coordinator skill is installed, run its script and write the report from its `report-template.md`:

```powershell
& "$HOME\.copilot\skills\mirklurk-game-update\analyze-patch.ps1" -OutDir "<this session's files folder>"
```

Otherwise do it by hand, outside the repo: copy `data.win` to `data.<v>.win` beside it (never overwrite a backup), decompile
both builds with the UndertaleModTool CLI, `UndertaleModCli.exe dump <data.win> -o <files>\dump-<v> -c UMT_DUMP_ALL -s`, and
`git diff --no-index` the two dumps. Launch the game once first: it rewrites `Languages\English\*.ini` on launch, and the
wiki fingerprints those files. The report must give, with entry names: the version strings; every changed item, being, recipe,
loot, merchant, skill, quest and world-generation value as before → after; new and renamed names; which `.ini` hashes changed;
the patch-note ↔ code cross-check; and changes the notes omit. Tell the user that MirkMap needs its own session.

## 2. Before editing

- `get_sessions_status`: list other mirklurk-wiki sessions and the files they touch. Whoever merges second rebases and
  re-pins. The user asked that no session block another's deploy without checking with it first.
- Branch from a fresh `origin/main`.
- `python` may be the Windows Store alias. Use `uv run --no-project python`. Don't use WSL git on this Windows worktree,
  and never run the tests with `GIT_DIR` or `GIT_WORK_TREE` exported: `test_safety`'s temporary repository then rewrites the
  real index and sets `core.worktree`.
- Write files with LF line endings. `game.json` and `entity_details.json` round-trip through
  `json.dumps(..., indent=2, ensure_ascii=False)` plus a newline. `catalog.json`, `acquisition.json` and `illustrations.json`
  mix compact rows, so splice them as exact text with count asserts; `entry_links` and `entry_display` both key rows by
  `entry`, so anchor each splice to its section.

## 3. Every update

Follow #64's diff (`git show ca380e7`):

1. **Changelog** `content/pages/Version_<v>.wiki`. Open with `'''Version <v>''' is the patch released on <d Month yyyy>, ...`,
   using the Steam post's UTC date
   (`https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=3972980&count=3&maxlength=0`; 0.9.1.0 posted at
   06:57 UTC on 21 October, which Steam's Pacific-time pages show as the 20th), and say "This wiki shows `<v>` values."
   Use `== New content ==`, `== Changes ==` and `== Fixes ==` with `===` subsections, add a spoiler line when it names
   late-story content, and end with `[[Game mechanics]] | [[Main Page]]`. `tools/wiki_render.py` gives every page linked
   under the top-level New content or Changes headings a "New in" or "Changed in" footer, which changes those pages and
   some pins; links under other top-level headings, such as Fixes, get none. Link existing pages from Changes, never from
   New content. A change that no page documents (a splash screen, say) goes on the Version page only.
2. **Register it:** add `!/content/pages/Version_<v>.wiki` to `.gitignore`, which is an allowlist,
   `"Version <v>": "Version_<v>.wiki"` to `PAGE_FILES` in `tools/wiki_data.py` (the publication check allows it from there),
   and the title to the `added` set in `tests/test_views.py`.
3. **Build:** `game.build` in `content/facts/game.json`; `currency.documented_build` in `catalog.json`, with the version,
   the confirmation sentence and both evidence rows (`obj_menu_Create_0`/`versionString` and `obj_menu_Step_0`/`versionCheck`)
   re-cited to `game-data-<d>`; and `build` plus the "Not obtainable in `<v>`" and "Acquisition in `<v>`" notes for items
   40, 48 and 49 in `acquisition.json`.
4. **Sources:** append `game-data-<d>` (`data.win`, lowercase SHA-256, build `<v>`) to `sources` in `game.json`. For each
   `.ini` whose hash is not recorded yet, add `items-en-<d>` (`Items.ini`), `beings-en-<d>` (`Bestiary.ini`) or `ui-en-<d>`
   (`UI.ini`), with the path `Languages\\English\\<file>`. `Nature.ini` has never changed (`nature-en`). Unchanged records
   keep their old citations.
5. **Version mentions:** the "Current version" line on `Main_Page.wiki`; the `== Version ==` paragraph of
   `Game_mechanics.wiki`, which lists every Version page; "This guide covers" in `World_generation.wiki`; and the previous
   Version page, whose lead drops "This wiki shows `<p>` values" and points on ("The wiki now shows values from
   [[Version `<v>`]] ..."). Then run `git grep -n "<p>" -- content tools tests docs README.md` for any others.
6. **Docs:** add a paragraph for the patch to the README after the previous one, linking `docs/PROVENANCE.md#version-<d>-update`,
   and fix its totals if counts changed. Add `## Version <v> update` to `docs/PROVENANCE.md` before `## Build output`,
   covering the date, the code entries changed, new sources, each amended record and the entries cited.

## 4. Amended facts and renames

- Amend the record in place and re-cite it to `game-data-<d>` (section = code entry, key = field) or to the new `.ini`
  source. Keep the [confidence](../../../docs/PROVENANCE.md#confidence-semantics) honest. Append new entries at the end of
  `entries`. The first 293 entries are a pinned handoff, so an amended one also joins the `amended` set in
  `test_expanded_snapshot_preserves_the_complete_vetted_handoff` (`tests/test_wiki.py`), as #66's seed recipes did.
- Follow each value everywhere it appears: catalog prose (`entry_display`, guides, topics), `entity_details.json` profiles
  and grids, recipes, and `acquisition.json`. Treasure-pool eligibility depends on price, so a price change can move an item
  between pools (in 0.9.0.1 Poison Arrow II became a Survivor-corpse find). The `databank_Alarm_1` recipe pass recomputes
  crafted items: weight = round(sum of component weights × 70) / 100, and value only when it is below 1.25 × the components'
  total. The wiki keeps the literal weight with a generic note and adds a `value` profile only when the value changes.
- **Renamed names:** update the entity name and its citation, set the new catalog page `title` and put the old one in
  `aliases`, which makes it a redirect. Update taxonomy members, summaries and related entities. File titles follow page
  titles ([File titles](../../../docs/IMAGES.md#file-titles)), so change `file_title` and `cropped_from.file_title` too.
  The live Files must then move before the merge (section 7).

## 5. New items and entities

Mirror #66's Flint (Large) and Flint Dagger (`item-276`, `item-277`), or a sibling item (Shoddy Dagger for weapons, Flint
for stones), across:

- `game.json`: the entity after the last item (before `being-36`), cited to `ItemTitles`/`<N>` in `items-en-<d>`; its
  recipe and loot entries go at the end of `entries`;
- `catalog.json`: page, taxonomy groups and tags by name, guides (at most 16 evidence refs each), and `item_effects` for
  non-obvious behavior (1 to 4 literal paragraphs of up to 1,200 characters, no links);
- `entity_details.json`, from `itemDB[<N>]` in `databank_Alarm_1`: the literal initializer values, attack-pattern totals,
  equip cost (width × height × 0.4 for equippables), range (`tileRange`) and a melee grid;
- `acquisition.json`: rows, pool membership and `existing_entry_ids`;
- hand-kept lists in `tools/`: `HANDS` in `wiki_items.py` (weapons' hands info) and `browse_order` in `wiki_portal.py`.

Rules: [PROVENANCE](../../../docs/PROVENANCE.md), [TEMPLATES](../../../docs/TEMPLATES.md),
[readable identifiers](../../../CONTRIBUTING.md#reusable-displays).

- Title each page with the exact in-game name. MirkMap links pages by that title and bundles
  `File:<Title> icon (cropped).png`, falling back to `File:<Title> icon.png`.
- **Treasure pools:** model `treasure_get_lootarray` and confirm that it reproduces all 11 existing pools exactly before
  adding new IDs. Loot types 0, 2, 4 and 5 exclude item types 14, 18 and 19; type 4 rejects items of 4 or more cells and
  type 5 takes only one-cell items; each pool has a minimum value (often a quarter of its budget) that type 25 bypasses.
  When item IDs grow, update the `irandom(N)` evidence keys and steps of `loot-amount-distribution`.
- **Art:** outside the repo, export the frame that `itemDB[<N>].sprite/pic` names from the new `data.win` with the UTMT
  CLI (`UndertaleModCli.exe load <data.win> -s <script>.csx`, calling `TextureWorker.ExportAsPNG`). Scale it by
  min(8, floor(256 / longest side)) with nearest-neighbor, zero fully transparent pixels, crop by the transparent-margin
  rule, and check both files with an independent decoder ([0.8.9.9 additions](../../../docs/IMAGES.md#version-0899-additions-and-the-finished-raft),
  [File titles](../../../docs/IMAGES.md#file-titles)). Write each `.txt` sidecar with "== Summary ==" and "== Credit ==",
  copying the developer-approval wording from a live File page such as `File:Bat Hide icon (cropped).png`.
- **Import before merging,** so the publish reports no missing Files. First confirm the nightly backup
  (`/backups/.last-success` in the `mirklurk-backup` container) and review recent changes since it, or take a paired backup.
  Run the [operator workflow](../../../docs/IMAGES.md#operator-only-mediawiki-143-workflow)'s `importImages` command on the
  wiki host (the operator's SSH alias `server`, from the homeserver's Compose directory), with `--dry` first. Confirm
  through API `imageinfo` that each served file matches its record's bytes and was uploaded by `WikiAdmin`.
- `illustrations.json`: the cropped record carries the developer rights wording, a compact `pixel_art` inside
  `cropped_from`, and evidence `itemDB[<N>].sprite/pic` plus `items-en-<d>`. Add the new entity IDs to the `later` set in
  `tests/test_catalog.py`, and a `## Version <v> ...` section with the new register count to `docs/IMAGES.md`.

## 6. Validate

```powershell
uv run --no-project python -m unittest discover -s tests
git add -A; uv run --no-project python tools/check_publication.py   # audits the Git index, not the working tree
```

- Update pins only for deliberate changes, and copy each new value from the failure: the build strings, `These guides cover`
  and the source, entity, fact and entry counts (`test_wiki.py`); page counts (`test_wiki.py`, `test_catalog.py`); the
  `Version …` titles set in `test_views.py`; and the hashes in `test_catalog.py` (`game.json` with its build blanked),
  `test_acquisition.py`, `test_wiki.py` and `test_followup.py`. New items also move the item, recipe and attack-grid counts
  in `test_display.py`, the illustration counts in `test_landmarks.py` and `test_views.py`, and the pool and effect counts in
  `test_views.py`. The Docker smoke, which runs only in CI, keeps its own copies of some values, such as the health-grid
  totals and the summary counts in `tools/smoke_display.py`; grep `tools/smoke_*.py` for anything you change.
- Each published file has a byte cap in `ALLOWED_FILES` (`tools/check_publication.py`). #62 and #66 had to raise
  `docs/PROVENANCE.md`, `tests/test_catalog.py`, `tests/test_views.py` and `tools/wiki_portal.py`, and `tools/wiki_render.py`
  and `tests/test_acquisition.py` are close to theirs. Keep pin edits the same length, trim, or raise a cap deliberately
  and say so in the PR.

## 7. PR, merge and publish

1. Commit, push and open a ready-for-review PR titled `Document MirkLurk patch <v>`. CI runs the publication job (about
   2 minutes), the Docker smoke (12 to 40 minutes) and a read-only preview of the live changes; the preview should show
   0 skipped pages and no missing Files. If the smoke flakes on cache timing ("did not invalidate the cached reader"),
   `gh run rerun <id> --failed`. The main run can flake the same way, which skips the publish; rerun it there too.
2. **File moves** (renames only), before merging and after a paired database and images backup:
   `uv run --no-project python tools/plan_file_moves.py --base origin/main --output <files>\moves.txt` writes the moves,
   but it rejects records with other edits, such as a caption change; then list the moves by hand. Moving Files needs the
   `movefile` right, which the MediaWiki MCP account lacks, so use the operator's `moveBatch --noredirects`
   ([Renaming Files](../../../docs/IMAGES.md#renaming-files)). Check the moved hashes against `illustrations.json`.
3. **Deploy window:** no other wiki session is merging or publishing; `gh run list --branch main --limit 3` has nothing in
   progress; the wiki is not read-only (`readonly` in
   `https://mirklurk.wiki/api.php?action=query&meta=siteinfo&siprop=general&format=json`); and the PR is mergeable.
4. `gh pr merge <n> --squash`, then `gh run watch <run> --exit-status` on the main run. Its publish job summary lists
   pages created, updated and skipped. A timed-out dependent refresh fails the job after its writes; rerun the failed job.
   Skipped pages were edited by a person ([PUBLISHING](../../../docs/PUBLISHING.md#when-a-person-edits-a-generated-page)).
5. **Live check:** read `Version <v>`, `Main Page`, every changed or new page and each renamed title's redirect from
   `https://mirklurk.wiki/api.php?action=parse&page=<Title>&prop=wikitext|images&format=json&formatversion=2`, and confirm
   new images are present. Article URLs are `https://mirklurk.wiki/w/<Title>`, not `/wiki/`.
6. **Report:** send the MirkMap session every new or renamed page title and icon File so it can run `deno task wiki`, then
   send the coordinator the PR link, those titles and a short player-facing summary.
