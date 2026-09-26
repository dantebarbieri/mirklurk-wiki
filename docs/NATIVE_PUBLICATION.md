# Native publication v1

This is a generic, transport-free primitive, not deployment permission or a
batch executor. The owning coordinator must bind the approved source, runtime,
existing operator, four corpora, preservation guards and prerequisite contracts.
Only that coordinator can authorize an invocation. Neither an opaque digest nor
disposable CI evidence proves production readiness.

`tools/native_publication.php` runs through MediaWiki 1.43.9's
`maintenance/run.php`, with `--manifest` and `--request` pointing to private
files **outside the document root**. Exactly one operation runs per process.
The primitive does not create users/actors, initialize missing edit counts,
resolve conflicts, purge, touch, retry, manage a server, or override read-only
configuration. Supply an already existing user ID, exact name and actor ID.
The worker must have the independently approved writable CLI configuration.
Public PHP must be stopped and positively drained; a final-capable private
observer remains read-only. There is no write-enabled Apache helper.

## Exact wire format

Every input and journal record is UTF-8 canonical JSON: object keys sorted,
compact separators, unescaped Unicode and `/`, no BOM or final newline.
Integers, booleans, null, strings, lists and objects only; no floats. Integers
must be within the exact interoperable 53-bit range. Duplicate keys,
noncanonical encodings and field aliases are rejected. SHA256 means 64 lowercase
hex characters; SHA1 commits/trees use 40, nonces use 32.
`publication_journal.canonical_bytes`, `validate_manifest` and `validate_request`
are the normative Python constructors/validators. Do not normalize page text.

Manifest fields (all required; no extra fields):

| Field | Exact value/shape |
| --- | --- |
| `schema_version`, `kind` | `1`, `"native-publication-manifest"` |
| `run_nonce` | Unique run nonce |
| `source` | `{head_sha, tree_sha}` |
| `runtime` | `{mediawiki_version:"1.43.9", primitive_sha256, fingerprint_sha256}` |
| `operator` | `{id, name, actor_id}`; positive IDs, existing exact identities |
| `binding_sha256` | Independently validated deployment/approval/preservation binding |
| `corpora` | `{previous_authored, baseline, authored, desired}`; exact caller-approved hashes |
| `prerequisites_sha256` | Static approved requirement/contract digest, not future revision evidence |
| `operations` | Ordered operation objects below |
| `preserved` | Exact unchanged managed states: `{namespace,title,page_id,revision_id,raw_sha256}` |

An operation has exactly `index` (1-based), `operation_nonce`, `namespace`
(only 0 or 14), canonical `title`, `expected`, `desired_sha256`,
`prerequisites_sha256`, and `prerequisites`.
`expected` is exactly `{page_id,revision_id,raw_sha256}`: `(0,0,null)` for absence
or positive IDs plus SHA256 for an existing raw main slot. No partial absence.
Each title and operation nonce occurs once. Unchanged/storage-noop pages are
never dispatched. Each static prerequisite is `{namespace,title,raw_sha256}`;
its hash can be approved baseline B or desired D, according to the specific
consumer's reviewed compatibility policy. No global D-only rule is imposed.

A request has exactly:

| Field | Meaning |
| --- | --- |
| `schema_version`, `kind` | `1`, `"native-publication-request"` |
| `manifest_sha256`, `run_nonce` | Exact immutable manifest binding |
| `index`, `operation_nonce` | Exactly one manifest operation |
| `attempt` | 1-based ordinal, maximum 999, never reused |
| `worker` | `{nonce,identity}`; fresh nonce per attempt, nonsecret identity matching `[A-Za-z0-9_.:-]{1,160}` |
| `desired_text` | Exact D, SHA256 must match operation |
| `prerequisites` | Ordered exact `{namespace,title,page_id,revision_id,raw_sha256}` read set matching static requirements |
| `prerequisite_evidence_sha256` | Fresh independently accepted guard/capture evidence |
| `previous_accepted_sha256` | Prior accepted record hash, or manifest hash before operation 1 |

The native worker checks its own file digest and MW version. The broader runtime
fingerprint, source, corpus, deployment binding and selector/preservation
semantics are **caller-validated**, not independently measured by PHP.
The native prerequisite read set is checked against fresh primary revisions;
the coordinator must exclude concurrent writers for the entire operation.

## Save and result

Core permission checks explicitly include edit/create, blocks, namespace,
page/title and cascading protection (`PermissionManager::RIGOR_SECURE`).
On the same `PageUpdater`, `grabParentRevision()` fixes the CAS token and the
exact expected page/revision/raw tuple is compared. `setContent()` and
`saveRevision()` use explicit `EDIT_NEW`/`EDIT_UPDATE`, never merge.
The operation's cancellable atomic section is not a batch transaction.
Status, revision creation, parent, actor, comment and exact stored D are checked.
Ordinary commit and deferred updates precede a fresh primary raw revision read.
A null/no-op save is an error, even if core reports an OK status.

The exact revision comment is `native-publication/v1:<request_sha256>`.
Reconciliation must never adopt another request's identical text.

Stdout contains JSON-line start/result events (whitespace is not a wire pin;
the coordinator canonicalizes each event before journaling).
Both contain `schema_version:1`, `kind`, `request_sha256`, `manifest_sha256`,
`worker` and `start:{pid,boot_id,process_start_ticks,db_connection_id}`.
Start kind is `native-publication-start`; result kind is
`native-publication-result`, additionally containing:

* `outcome`: `committed` or `error`;
* `stage`: `validated`, `parent`, `saving`, `saved`, `committed`, or `verified`;
* `revision`: null on error, otherwise exactly
  `{namespace,title,page_id,revision_id,parent_id,raw_sha256,actor_id,comment}`;
* `error`: null on success or explicit failure code/type.

Only `committed` at stage `verified` is a verified worker result. It is still
**not** an accepted prefix or proof the process/DB request has quiesced.
Validation failures before start can have no event. Missing stdout, timeout,
lost SSH, exit/error, absent result and save-returned are never noncommit proof.

## Private filesystem journal

`Journal(path, manifest)` creates a new private run directory. `Journal(path)`
locks/reopens it; use a context manager or `close()`. POSIX owner-only directory
mode 0700 and files 0600 are mandatory. Windows/non-POSIX is explicitly
unsupported. Symlink paths, hardlinked records, unknown files, malformed JSON,
gaps and inconsistent chains fail closed.

Publication creates an exclusive temporary file, writes/flushes/fsyncs it,
atomically links the final name without replacement, removes the temporary
name and fsyncs the directory. Creation also fsyncs the parent directory.
Unsupported fsync/link/locking durability is an error, not a successful fallback.
A crash leaving `.pending` data or a two-link publication is deliberately
fail-closed: preserve it for independent forensic repair, never silently delete,
rewrite, dispatch or adopt it. A fully published record visible after restart
is re-fsynced before replay. No acknowledged record is overwritten.

Public methods:

`put_artifact(value)` durably writes opaque canonical JSON as
`artifact-<sha256>.json` and returns its digest; `get_artifact(sha256)` returns
the hash-verified preimage. Same-content puts are idempotent, never overwrites.
Replay verifies every artifact's filename/content digest. An artifact is at most
32 MiB; larger guard sets should retain separate captures plus a manifest of
their digests. The coordinator retains its full private guard preimages,
including capture/trace, account/log/history/File chronology, price review and
barrier evidence; a digest alone is not enough to reconstruct restart guards.
There is no domain-specific guard interpretation in this store.
The prerequisite evidence artifact must exist **before** `intent()`, and the
fresh preservation guard artifact must exist **before** `observe()`/acceptance.

1. `intent(request)` durably records `intent-NNNNNN-AAA.json` **before dispatch**.
2. `event(request,event)` records immutable `start-...` / `result-...`.
3. `observe(request,evidence)` records immutable `evidence-...`; returns
   `accept` or `retry`, without dispatching either.
4. `accept(request)` publishes `accepted-NNNNNN.json`, extending the hash chain.
5. `verify_resume(states)` compares a fresh complete managed state against only
   replayed accepted records. Pending commits require reconciliation first.

Observation has exactly `schema_version:1`,
`kind:"native-publication-observation"`, `request_sha256`, `worker`, `start`,
`quiescence`, `states`, `guard_sha256`, and `observation_nonce`.
`quiescence` is exactly `{worker_exited:true,request_finished:true,
owned_transactions_absent:true,authority_sha256}`.
It is supplied by the coordinator's **positive**, independently verified
process/request/owned-DB-session evidence, never timeout inference.
If start stdout was lost, the coordinator must recover the exact process and
connection identities independently or stop. The scoped observer must have
enough existing visibility; this module grants no DB privileges.
`states` contains every operation and preserved title, no duplicates/extras.
Old/preserved entries use `{namespace,title,page_id,revision_id,raw_sha256}`;
accepted entries use the full revision shape above. `guard_sha256` binds the
coordinator's successful fresh corpus/preservation/semantic guard evidence.

Only the exact marker/actor/parent/D-bound next revision with the full expected
prefix permits acceptance without resending. Only the completely unchanged
old prefix plus positive quiescence permits a new attempt. Mixed/extra states,
foreign identical-text revisions and result/state disagreement stop.
Run/op nonces stay fixed on retry; request/worker nonce and ordinal change.
Accepted records bind request, previous acceptance, result (or null), observation,
revision and full observed-state digest. Replay validates all records but
advances progress **only** through accepted records.

## Evidence boundary

The existing materialization receipt remains schema 2: A0/A1 unchanged pages
retain exact B with no PST/write; changed pages materialize D through actual
PST. Raw schema-1 prefix/endpoint/price evidence, discrepancies, per-consumer
self omissions and block flags remain unchanged. The native/recovery proof is
additional, not replacement approval. Synthetic accounts/images and isolated
SQL/image restore belong only to disposable smoke resources; no production
backup, game image, account data or private capture is published.

MediaWiki source references:
[PageUpdater](https://doc.wikimedia.org/mediawiki-core/1.43.9/php/classMediaWiki_1_1Storage_1_1PageUpdater.html)
documents both CAS after `grabParentRevision()` and the absence of permission
checks. Core `PermissionManager`, `RevisionStore`, `UserEditTracker` and
`DeferredUpdates` distinguish secure permission reads, primary revision reads,
lazy edit-count initialization and ordinary commit/deferred lifecycle.
