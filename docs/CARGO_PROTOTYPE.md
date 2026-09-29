# Disposable shared-record experiment

**Design evidence, not an installation or migration approval.** PR #34 remains
draft: the original raw-table/`onlyinclude` repeated-save regression is unchanged.
This experiment does not modify the production Dockerfile, LocalSettings, corpus,
generators, publication ownership rules, or live wiki.

The focused [evidence run](https://github.com/dantebarbieri/mirklurk-wiki/actions/runs/36618683087)
completed its assertions on MediaWiki **1.43.9** and MariaDB **11.4.13**.
Its JSON status is deliberately **`completed_with_limitations`**, not rollout-ready.
`cargo-prototype.json` and the synthetic field-dialog screenshot are CI artifacts.
The full original editor suite remains separately blocked.

## Pin and authority

Cargo **3.9.4**, commit `b3cc797aa8a1575f7ce4a7c5b0a1979698d582f5`,
is GPL-2.0-or-later and declares MediaWiki >=1.42 compatibility.
The downloaded archive's SHA-256 is
`005301a0f0fac395a9cec340fac0f229d9226974c3c26e80fff3c16015bd21af`.
The experiment retains the extension's license in its temporary build context.
Cargo tables live in the disposable wiki database; no external service is used.
Actual MariaDB execution, rather than a generic MySQL compatibility claim, is
the evidence for this particular combination.

An ordinary template invocation in the **current owner page revision** is the
only editable fact source. Cargo is a disposable derived index. Query readers
use a different, non-storing display template and link **Edit data** to that
owner's visual editor. They never need a Git-maintained list of owner pages.

The synthetic author shape is:

```wikitext
{{Prototype record|variant=base|product=Synthetic salve|quantity=1|ap=2|ingredients=Synthetic fiber = 4
Synthetic resin = 2
Synthetic water = 1
Synthetic salt = 1
Synthetic leaf = 3|stations=Prototype bench;Prototype camp|merchants=Prototype trader|condition=Only while the synthetic quest is active.}}
```

The dialog exposes meaningful labeled fields, not `view`, `filter`, or `#switch`
routing. The fixture has five ingredients to avoid treating the existing
corpus's observed four-input maximum as a universal constraint. Its Lua reader
accepts any number of ingredient lines; this is **not** a proposed production
schema, validation policy, or cardinality limit.

## Observed behavior

| Contract | Result |
| --- | --- |
| Ordinary native visual edit | Clicking a reader's Edit data link opened the correct owner. Quantity `1 -> 2` and AP `2 -> 7 -> 8` survived two real dialog/review/save cycles, with the ordinary editor, summaries, revisions and visual-editor tags verified. No unrelated source changed or include markers accumulated. |
| Multiple records and relations | Two variants, five paired ingredient quantities, conditions, two stations and a merchant were indexed. Workstation, ingredient and merchant queries rendered results without owner lists. |
| Previously unknown owner | A self-registered ordinary editor created another page and new station relationship through the wiki Action API. The index discovered it without repository changes. Cached readers needed the intervention described below. |
| Change and removal | An ordinary wiki edit changed a station and ingredient/quantity and removed one variant. Old index results disappeared and new relations appeared. |
| Preview and draft | Real source preview, unsaved visual changes, anonymous arbitrary parsing and old-revision rendering left both index and owner revision unchanged. Anonymous edit rights remained absent; signup used the existing CAPTCHA. |
| Reuse | Saving a query-only reader did not create records. **Negative control:** raw `{{:Owner}}` transclusion created two extra indexed rows under the reader. Removing that synthetic reader removed the copies. |
| Human ownership | The real source-unchanged sync skipped the human-edited owner, leaving its revision and records untouched despite stale proposed repository text. |
| Rebuild | Cargo's recreate command dropped/recreated the derived table from current canonical wiki revisions. All records and list fields matched exactly afterward; owner source, revision IDs, authors and summaries were unchanged. |

**Native UX is only partially proved.** Scalar field editing works, but adding
and removing whole records were tested through the ordinary editor's wiki API,
not a native add/remove GUI. Ingredients still use `Item = quantity` lines,
stations/merchants use semicolon-separated names, and uniqueness/production
validation is not designed. This is better than nested row wikitext but is not
yet a complete beginner-friendly repeated-row editor.

## Cache and lifecycle findings

Cargo's result backlinks successfully invalidated a reader **saved while it
already had matching records**: value changes and removal were visible
immediately. However, previously empty readers stayed stale when the first or
a newly matching owner appeared, even after bounded job execution. Re-rendering
after an ordinary purge did not establish equivalent durable dependencies for
the tested formerly empty readers. Each needed an explicit API `purge` again
after subsequent relation/value changes. All such interventions are recorded
separately as `before_jobs`, `after_jobs`, and `after_explicit_purge`; none is
counted as automatic freshness. Job output and reported queue counts are retained.

Owner movement initially returned the old indexed title in this run. After jobs
ran, Cargo used the new owner title with the **same page ID**, and the source
was unchanged. The old title became a redirect. Query-rendered labels and Edit
data URLs derive from `_pageName`: they target the new owner after index refresh
and reader purge. Deletion immediately removed the owner's rows, but the tested
cached reader still needed purging.

**Restore did not repopulate records**, immediately or after jobs. A deliberate
Cargo rebuild recovered them from the restored current wiki revision, followed
by reader purge. A second full rebuild reproduced those records exactly. The
already-correct cached outputs remained correct after this no-change rebuild;
this does not prove invalidation for a rebuild that changes results.

Referenced product/station/ingredient names are separate data fields: the owner
move test does not establish automatic rewriting of those fields when a
referenced page is renamed. Redirect/alias handling needs its own acceptance
cases before migration. No source title, variant or condition was silently changed.

The final two-record rebuild took **0.483 seconds**; ten local Cargo API queries
took **15.8-20.5 ms** each. These are small synthetic-fixture measurements, not
production-scale or concurrent-editor performance claims.

## Recommendation and approval boundaries

Continue with **ordinary author-owned records plus a rebuildable Cargo index**
as the preferred architecture to evaluate, rather than hidden selector arguments
or a second independently editable database. Do **not** migrate or enable it
yet: empty/new-result cache invalidation and restore indexing are concrete
operational gaps. Simply installing Cargo alongside current transclusions is
unsafe. Reused views must use non-storing query renderers or compatibility
adapters proven not to execute storage; raw owner transclusion is not one.

Page Forms could later provide repeatable ingredient/record controls and
autocomplete over the same owner revision. It is a UX layer, not the index,
and it has not been installed or tested here. Cargo is not needed merely to
edit template fields; a shared query index is needed for this design's dynamic
cross-page discovery without manually maintained owner lists.

Subject to explicit approval, separate follow-up PRs should cover:

1. **Index lifecycle and operations:** pinned runtime dependency, schema health,
   background jobs, restore repopulation, and invalidation for newly matching
   queries, moves, deletions and rebuilds. Prefer an upstream fix or a narrow
   reviewed integration; do not disable caching globally or require novices to
   know about purges. Re-run lifecycle/concurrency and representative-scale cases.
2. **Authoring and reader contracts:** production recipe/price/ware schemas,
   exact quantities/copper, variants/conditions, stable record anchors,
   meaningful TemplateData, non-storing query renderers, and native GUI add/remove
   acceptance. Evaluate Page Forms only if that UX remains inadequate.
3. **Revision-aware migration and publisher support:** dry-run transformations
   from current wiki revisions, not stale Git facts; preserve existing titles,
   anchors, prose, human ownership, and default/named/filtered/price-gated read
   contracts through explicit adapters. Require semantic projection comparisons
   and revision-conflict checks; stop on unfamiliar human structures. Rebuild
   only from the resulting current owner revisions. Keep source-unchanged bot
   safeguards and a reversible, separately authorized rollout.

No follow-up PR, extension rollout or corpus migration is authorized by the
experiment itself.

## Reproduction and primary references

With Docker and Playwright 1.55.0 available, run
`python3 tools/prototype_cargo.py --run --artifacts <outside-repo-directory>`.
The helper uses unique Compose resources and deletes its disposable volumes.
It does not accept a remote wiki URL. Production config is copied into a private
temporary context; Cargo, exception diagnostics and disabled opportunistic jobs
are appended only there. Explicit job runs distinguish immediate from queued
behavior without weakening permissions, CAPTCHA or rate limits.

Alternatively, dispatch **`cargo-prototype.yml` directly** on this draft branch.
It emits only the uniquely named `cargo-prototype` check. Do not use the previous
`validate.yml` prototype input: it has been removed because skipped jobs with
required-check names could falsely satisfy branch protection. The normal
`publication` and `docker-smoke` jobs remain unconditional full validation;
focused experiments do not create even skipped instances of those contexts.

Primary references:
[Cargo compatibility](https://www.mediawiki.org/wiki/Extension:Cargo),
[storage and rebuild commands](https://www.mediawiki.org/wiki/Extension:Cargo/Storing_data),
[pinned extension metadata/license](https://github.com/wikimedia/mediawiki-extensions-Cargo/blob/b3cc797aa8a1575f7ce4a7c5b0a1979698d582f5/extension.json),
[save/move/delete hooks](https://github.com/wikimedia/mediawiki-extensions-Cargo/blob/b3cc797aa8a1575f7ce4a7c5b0a1979698d582f5/CargoHooks.php),
and [result backlinks](https://github.com/wikimedia/mediawiki-extensions-Cargo/blob/b3cc797aa8a1575f7ce4a7c5b0a1979698d582f5/includes/CargoBackLinks.php).
