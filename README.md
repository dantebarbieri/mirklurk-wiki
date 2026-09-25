# MirkLurk Wiki

An independent MediaWiki foundation for **MirkLurk**, built from original writing,
short factual names, and carefully qualified mechanics observations. This
repository does **not** contain the game, its assets, its localization prose, or
decompiled source.

The initial curated snapshot contains 336 name records and 79 numeric facts
supported by five source-file fingerprints. Names establish source associations,
not availability or combat behavior. The 28 localization-described mechanics have
not been runtime-verified; the other 51 facts are qualified initializer
observations. The installed game release is **unidentified**.

The expanded reference retains that baseline and now contains **107 numeric facts
and 293 structured entries**: 31 quest/journal notes, 63 merchant offers,
96 station-specific recipe variants, 70 conditional loot entries, and 33
original algorithm/skill summaries. It generates 18 main-namespace pages.
The observed menu label `0.8.1.5` is cited separately, not treated as a confirmed
release identifier.

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
| `tools/build_wiki.py` | Deterministic MediaWiki XML for reviewed seeding |
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
