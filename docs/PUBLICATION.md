# Public-repository safety

## Layers

The root `.gitignore` starts with a deny-all rule. Directory exceptions permit
traversal only; each allowed file is named separately. Additional exclusions
cover game binaries/media, INIs, GML, language/save directories, raw research,
tool dumps/exports, UTMT binaries, secrets, runtime state, databases, uploads,
and backups.

**Git ignores do not protect files already tracked or added with `--force`.**
They are an accident-prevention layer, not a security boundary.

`tools/check_publication.py` independently examines `git ls-files --stage` and
reads each object by its staged Git object ID. It does not trust a cleaned-up
working copy. It rejects:

- Paths outside its exact-file allowlist, forbidden names, and malformed paths.
- Symlinks, submodules, executable modes, unresolved index conflicts, and an empty index.
- Oversized files, non-UTF-8 data, binary/control characters, and byte-order marks.
- Selected private-key/provider-token patterns, credential-bearing URLs,
  likely literal secret assignments, personal absolute paths, and decompiled
  function definitions.
- Structured facts that do not satisfy the strict provenance schema.
- Catalog, profile, or illustration references that disagree with the staged
  `game.json`; supplemental validation reads staged blobs, not working copies.

Diagnostics name the rule and line, not the matched secret. The scanner is
deliberately conservative about ordinary documentation: discussing a password
file or a forbidden asset name is not itself a leak.

The Docker build context has its own deny-by-default `.dockerignore`: only the
five named runtime/build files are sent to Docker. Local game files, Git history,
secrets, and research cannot be included by a broad `COPY .`.

## Before committing or pushing

Run tests, stage only intended files, run the index checker, and review the
complete staged diff. On updates, also review the commits being pushed, not
merely the last worktree state. Generated XML is for a private handoff, not Git.
Check any attachments and command logs separately.

Pull requests run the publication gate, Python tests and PHP runtime checks.
The full disposable Docker smoke runs on pushes to `main` or explicit manual
dispatch, not on pull requests or feature-branch pushes. Workflow/ref concurrency
cancels obsolete runs. A skipped pull-request smoke job is **not** smoke evidence:
a release still requires a successful full run bound to its exact merged source.
CI is **after publication** and cannot prevent an initial
leak. The local pre-publication gate is mandatory. No check can automatically
establish authorship, fair use, or that an arbitrary new secret pattern is absent.

The current gate checks the index, not every historical commit. A committed
leak is not fixed merely by adding an ignore rule or deleting its latest copy.
Stop publication, revoke affected credentials if relevant, and coordinate a
reviewed history-remediation plan. Do not force-push or rewrite collaborators'
history casually.

## Updating policy

Add only a specific authored file with a clear purpose and bounded size.
Update both allowlists and representative `git check-ignore` tests. Keep final
hard exclusions after positive exceptions. Never allow an entire directory's
contents, use force-add as a workaround, relax binary checks for an asset, or
introduce a fixture containing a real secret.

The catalog validator's named-file cap is 48 KiB, including the bounded
recipe-input/source joins used to derive acquisition browsing without another
stored dataset. `tests/test_catalog.py` retains its 66 KiB cap;
`tools/smoke_prefix.py` has a 70 KiB cap for the explicit incremental hooks.
The incremental disposable adapter and its synthetic controls have
exact exceptions for `tools/smoke_incremental.py` (48 KiB) and
`tests/test_incremental.py` (44 KiB). No private input, XML, measurement, artwork,
or broad directory exception is allowed.

Runtime files belong outside the checkout, even when ignored. Actual
`LocalSettings.php` is forbidden; `deploy/LocalSettings.template.php` is original
nonsecret source that reads mounted files and is copied into the image under
the runtime name.
