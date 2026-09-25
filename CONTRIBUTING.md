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
descriptions, and explicitly state unverified interpretations. Catalogues may
contain spoilers; preserve the existing warnings.

Names in structured data are rendered as literal text, not as executable wiki
markup. Authored `.wiki` pages are trusted editorial content and must also be
reviewed for misleading links or inappropriate markup.

## Review and validation

1. Make the smallest evidence-backed change. Update directly related prose.
2. Run `python -m unittest discover -s tests -v`. For runtime changes, also run
   `php tests/test_runtime.php` and the opt-in disposable Docker smoke test.
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

The repository is a seed and editorial source, not an authoritative mirror that
overwrites the community wiki. Existing pages are merged manually through the
normal revision workflow. Additive imports exclude every existing title.
See [IMPORTING.md](docs/IMPORTING.md).

You must have the right to submit your own contributions. No contribution here
grants rights to the game's creative content.
