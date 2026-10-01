# Contributing

Contribute original writing and narrowly curated facts. Do not treat this public
repository as a workspace for extracting or storing the game.

## Content boundaries

Allowed contributions include short entity names, numeric or boolean mechanics
facts, precise evidence identifiers, source hashes, and original explanations
of what those facts do and do not establish.

Never submit game binaries, assets, media, fonts, maps, save data, configuration
files from the game, localization descriptions, dialogue, decompiled code,
UTMT binaries, dumps, or bulk tool exports. This also applies to issue attachments,
pull-request text, screenshots, generated XML, and Git history. Do not put secrets,
personal paths, database dumps, uploads, backups, or runtime configuration here.

Keep source files and raw analysis in a private location outside the checkout.
Separately approved server-only illustrations use [the operator workflow](docs/IMAGES.md);
this never permits image bytes in Git or enables public web uploads. Artwork
publication remains pending until redistribution rights are confirmed.
Do not copy a paragraph to demonstrate a numeric value: reference its section and
key, then summarize the narrow fact in your own words. If a contribution needs
more than this policy permits, seek permission rather than broadening the policy
by assumption.

## Evidence and editorial review

Use [the versioned facts format](docs/PROVENANCE.md). Record an exact source
fingerprint, an installation-relative path, and section/key identifiers.
Keep unknown builds null. Distinguish source observations, inferences, and
localization-described behavior. Evidence from an initializer does not establish
the effective gameplay value after skills, state, or other modifiers.

Do not classify every bestiary entry as an enemy. Do not infer reachability,
units, drop tables, stacking, or unlock conditions from a name. Use original
descriptions, and retain meaningful uncertainty. Catalogues may
contain spoilers; preserve the existing warnings.

Names in structured data are rendered as literal text, not as executable wiki
markup. Authored `.wiki` pages are trusted editorial content and must also be
reviewed for misleading links or inappropriate markup.

## Reader-facing prose

Write short, direct game guidance. Keep amounts, prerequisites, exceptions and
relevant versions; cut repeated introductions, hedging and explanations of how
the wiki is built. Keep actual quest research and in-game evidence: this policy
targets wiki commentary, not game content. Do not publish evidence ledgers, research status, source paths,
verification instructions or missing-image notices in articles, categories,
navigation, captions or tooltips. Provenance stays in the structured inputs and
the local `wiki_render.audit_report()` output, never in `build_pages()`.

Use `{{Unverified}}` immediately after a genuinely unconfirmed claim, not on
every extracted fact or whole page. Use **Unknown** for an unknown value and
**Not documented** for an absent description; neither means zero or impossible.
Do not remove an essential qualification to make a sentence shorter.

Edit authored pages and catalog presentation fields, not immutable source
records. `entry_display` and `fact_display` provide prose overrides; fact
overrides cannot change values, units or confidence. Keep selective-view
ownership and filters intact. Review full pages and their transcluded views,
not just source-word matches. The staged publication gate rebuilds from indexed
files, and the disposable smoke checks every rendered reader page.

## Review and validation

1. Make the smallest evidence-backed change. Update directly related prose.
2. Run `python -m unittest discover -s tests -v`. For runtime changes, also run
   `php tests/test_runtime.php`. Pull-request CI runs the disposable Docker smoke
   (`python tools/smoke_deploy.py --run`) and previews the live pages that change.
3. Stage only the intended files, then run `python tools/check_publication.py`.
   This examines the **Git index**, even if the working copy looks different.
4. Inspect `git diff --cached --stat` and `git diff --cached`. Check provenance,
   rights, original wording, secrets, and whether any claims exceed their evidence.
5. For a new authored file, deliberately add its exact path to both `.gitignore`
   and `ALLOWED_FILES` in the checker, plus an appropriate size limit and tests.
   Never add a directory-wide content exception.

The tests fingerprint the original snapshot to preserve its records while new
research is appended. Change existing evidence deliberately, with explicit review.
Passing automated checks is not a legal review, a comprehensive secret scan, or
proof that prose is original. Human pre-publication review remains required.

## Live wiki edits

Readers can use **Editing help** in the native sidebar after the operator has
activated it and the separate `Help:Editing` article has been published. For
navigation changes, propose edits to `content/interface/Sidebar.wiki`; do not
copy a menu onto every article. The sidebar is a reviewed operator-installed
exception to automatic publication: see [Native sidebar](docs/PUBLISHING.md#native-sidebar).
Ordinary contributors do not need interface-editing permissions.

Signed-in editors can use **Edit** (VisualEditor) or **Edit source**. Pages that
supply shared recipe, price, merchant, loot or coin data to other pages offer
only **Edit source**, because the visual editor would rearrange their inclusion
markers; see [Visual editing](docs/DEPLOYMENT.md#visual-editing). On talk pages,
use **Reply** under a comment or **Add topic**; they indent and sign for you.

Merging to `main` publishes the generated pages automatically, but only onto
pages whose latest revision came from the publishing automation. A page someone
edited on the wiki is skipped and reported on every run; port useful edits into
the repository, then hand the page back as described in
[PUBLISHING.md](docs/PUBLISHING.md). The sync never deletes pages; retire old
titles with managed redirects to useful reader pages.

You must have the right to submit your own contributions. No contribution here
grants rights to the game's creative content.

## Reusable displays

Use the native `{{Coins|...}}`, `{{Health grid|...}}`,
`{{Attack grid|...}}`, `{{Creature|Sceetler}}`, `{{Item|Iron Hand Axe}}`,
Recipe row and Ware row syntax described in [TEMPLATES.md](docs/TEMPLATES.md).
Keep prices in item-owned views and preserve curated grid geometry; do not
copy display HTML or prices into readers. Row templates stay inside the
owner's literal selective-view filters; standard-price gates stay on merchants,
not inside Ware row. Content-only Lua/template changes use the already deployed
Scribunto runtime; runtime changes require the deployment prerequisites in that guide.
