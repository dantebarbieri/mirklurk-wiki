"""Real native-worker and recovery proof, exclusively inside disposable Compose."""

import hashlib
import io
import json
import multiprocessing
import os
import secrets
import subprocess
import tarfile
import time
from pathlib import Path

from publication_journal import Journal, JournalError, canonical_bytes, digest, projection
from wiki_views import transclusions


RECOVERY_TABLES = ("page", "revision", "slots", "content", "text", "actor", "logging",
                   "archive", "user", "image", "oldimage", "filearchive", "comment")


def sha(raw):
    return hashlib.sha256(raw.encode() if isinstance(raw, str) else raw).hexdigest()


def docker(*args, input_bytes=None, timeout=120):
    return subprocess.run(["docker", *args], input=input_bytes, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, timeout=timeout).stdout


def crash_acceptance(path, request, edge):
    with Journal(path, edge=lambda point: os._exit(91) if point == edge else None) as journal:
        journal.accept(request)


class NativeSmoke:
    def __init__(self, root, workspace, run, api, runtime, source_head):
        self.root, self.workspace, self.run, self.api = root, workspace, run, api
        self.runtime, self.source_head = runtime, source_head
        self.containers = []
        self.proof = {"schema_version": 1, "kind": "disposable-native-publication-proof",
                      "source_head_sha": source_head, "runtime": runtime, "cases": [], "operations": []}

    def evaluate(self, code):
        return self.run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "eval", "--quiet",
                        input_bytes=code.encode())

    def operator(self, name="WikiAdmin"):
        code = (
            "$s=MediaWiki\\MediaWikiServices::getInstance();$d=$s->getConnectionProvider()->getPrimaryDatabase();"
            "$u=$d->newSelectQueryBuilder()->select(['user_id','user_name','user_editcount'])->from('user')"
            "->where(['user_name'=>" + json.dumps(name) + "])->caller(__METHOD__)->fetchRow();"
            "if(!$u || $u->user_editcount===null){throw new RuntimeException('fixture-operator-not-ready');}"
            "$a=$d->newSelectQueryBuilder()->select('actor_id')->from('actor')->where(['actor_user'=>$u->user_id,"
            "'actor_name'=>$u->user_name])->caller(__METHOD__)->fetchField();"
            "if(!$a){throw new RuntimeException('fixture-actor-missing');}"
            "echo json_encode(['id'=>(int)$u->user_id,'name'=>$u->user_name,'actor_id'=>(int)$a]);"
        )
        return json.loads(self.evaluate(code))

    def manifest(self, operations, preserved=(), corpora=None, operator=None):
        return {
            "schema_version": 1, "kind": "native-publication-manifest", "run_nonce": secrets.token_hex(16),
            "source": {"head_sha": self.source_head, "tree_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=self.root, text=True).strip()},
            "runtime": {"mediawiki_version": "1.43.9", "primitive_sha256": sha(
                (self.root / "tools" / "native_publication.php").read_bytes()), "fingerprint_sha256": digest(self.runtime)},
            "operator": operator or self.operator(), "binding_sha256": digest({"scope": "disposable", "runtime": self.runtime}),
            "corpora": corpora or dict.fromkeys(("previous_authored", "baseline", "authored", "desired"), digest(operations)),
            "prerequisites_sha256": digest([row["prerequisites"] for row in operations]),
            "operations": operations, "preserved": list(preserved),
        }

    @staticmethod
    def operation(index, title, expected, text, prerequisites=()):
        return {"index": index, "operation_nonce": secrets.token_hex(16),
                "namespace": 14 if title.startswith("Category:") else 0, "title": title, "expected": expected,
                "desired_sha256": sha(text), "prerequisites_sha256": digest(list(prerequisites)),
                "prerequisites": list(prerequisites)}

    @staticmethod
    def request(manifest, journal, index, text, prerequisites=(), evidence=None, attempt=1):
        operation = manifest["operations"][index - 1]
        return {
            "schema_version": 1, "kind": "native-publication-request", "manifest_sha256": digest(manifest),
            "run_nonce": manifest["run_nonce"], "index": index, "attempt": attempt,
            "operation_nonce": operation["operation_nonce"],
            "worker": {"nonce": secrets.token_hex(16), "identity": "disposable-cli"},
            "desired_text": text, "prerequisites": list(prerequisites),
            "prerequisite_evidence_sha256": journal.put_artifact(evidence or []), "previous_accepted_sha256": journal.previous,
        }

    def states(self, manifest, accepted=()):
        expected = {row["title"]: {**row["expected"], "namespace": row["namespace"], "title": row["title"]}
                    for row in manifest["operations"]}
        expected.update({row["title"]: row for row in manifest["preserved"]})
        expected.update({row["revision"]["title"]: row["revision"] for row in accepted})
        titles = json.dumps(sorted(expected))
        code = (
            "$s=MediaWiki\\MediaWikiServices::getInstance();$d=$s->getConnectionProvider()->getPrimaryDatabase();$out=[];"
            "foreach(json_decode(" + json.dumps(titles) + ",true) as $name){"
            "$t=MediaWiki\\Title\\Title::newFromText($name);"
            "$r=$s->getRevisionStore()->getRevisionByTitle($t,0,Wikimedia\\Rdbms\\IDBAccessObject::READ_LATEST);"
            "$v=['namespace'=>$t->getNamespace(),'title'=>$name,'page_id'=>$r?$r->getPageId():0,"
            "'revision_id'=>$r?$r->getId():0,'raw_sha256'=>$r?hash('sha256',$r->getContent('main',"
            "MediaWiki\\Revision\\RevisionRecord::RAW)->serialize()):null];"
            "if($r){$v['parent_id']=$r->getParentId();$v['comment']=$r->getComment(MediaWiki\\Revision\\RevisionRecord::RAW)->text;"
            "$v['actor_id']=(int)$d->newSelectQueryBuilder()->select('rev_actor')->from('revision')"
            "->where(['rev_id'=>$r->getId()])->caller(__METHOD__)->fetchField();}$out[]=$v;}echo json_encode($out);"
        )
        actual = json.loads(self.evaluate(code))
        return [{key: row[key] for key in expected[row["title"]]}
                if projection(row) == projection(expected[row["title"]]) else row for row in actual]

    def launch(self, journal, request, fixture_stage=None, deny_rights=None, *, record_intent=True):
        if record_intent:
            journal.intent(request)
        dispatch_id = request["worker"]["nonce"] + "-" + secrets.token_hex(4)
        folder = self.workspace / ("native-" + dispatch_id)
        folder.mkdir(mode=0o700)
        (folder / "manifest.json").write_bytes(canonical_bytes(journal.manifest))
        (folder / "request.json").write_bytes(canonical_bytes(request))
        name = "native-smoke-" + dispatch_id
        args = ["run", "-d", "--no-deps", "--name", name, "--env", "MW_READ_ONLY=",
                "--volume", f"{folder}:/native-input:ro"]
        script = "/native/tools/native_publication.php"
        if fixture_stage:
            args += ["--env", "NATIVE_DISPOSABLE_FIXTURE=1"]
            script = "/native/tests/native_worker_fixture.php"
        args += ["mirklurk", "php", "maintenance/run.php", script,
                 "--manifest", "/native-input/manifest.json", "--request", "/native-input/request.json"]
        if fixture_stage:
            args += ["--fixture-stage", fixture_stage]
        if deny_rights:
            if deny_rights not in ("edit", "createpage"):
                raise RuntimeError("Unknown synthetic rights case.")
            (folder / "denied.php").write_text(
                "<?php require '/var/www/html/LocalSettings.php';"
                "$wgRevokePermissions['user'][" + json.dumps(deny_rights) + "] = true;\n", encoding="utf-8")
            args += ["--conf", "/native-input/denied.php"]
        self.run(*args)
        self.containers.append(name)
        return name

    def wait(self, name, checkpoint=None):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state = json.loads(docker("inspect", "--format", "{{json .State}}", name))
            logs = docker("logs", name).decode()
            if checkpoint and any(json.loads(line).get("fixture_checkpoint") == checkpoint
                                  for line in logs.splitlines() if line.startswith("{")):
                if not state["Running"]:
                    raise RuntimeError("Native fixture exited instead of pausing.")
                return state
            if not state["Running"]:
                if checkpoint:
                    raise RuntimeError("Native checkpoint not reached: " + logs)
                return state
            time.sleep(0.1)
        raise RuntimeError("Native worker is still unknown/running; no retry is authorized.")

    def root_sql(self, query=None, *, database="mirklurk", input_bytes=None, dump=False, tables=()):
        program = "mariadb-dump" if dump else "mariadb"
        options = ("--single-transaction --skip-comments --skip-dump-date --skip-extended-insert "
                   "--order-by-primary --hex-blob " if dump else "--batch --skip-column-names ")
        command = ('exec ' + program + ' -uroot --password="$(cat /run/secrets/MIRKLURK_DB_ROOT_PASSWORD)" '
                   + options + database + (" " + " ".join(tables) if tables else ""))
        return self.run("exec", "-T", "mirklurk-db", "sh", "-c", command,
                        input_bytes=query.encode() if query is not None else input_bytes)

    def collect(self, journal, request, name, *, lose_result=False, allow_error=False):
        status = self.wait(name)
        events = [json.loads(line) for line in docker("logs", name).decode().splitlines() if line.startswith("{")]
        starts = [row for row in events if row.get("kind") == "native-publication-start"]
        results = [row for row in events if row.get("kind") == "native-publication-result"]
        if len(starts) != 1:
            raise RuntimeError("Native worker failed before identifiable start: " + docker("logs", name).decode())
        journal.event(request, starts[0])
        if not lose_result:
            for result in results:
                journal.event(request, result)
        if not allow_error and (status["ExitCode"] != 0 or len(results) != 1 or results[0]["outcome"] != "committed"):
            raise RuntimeError("Native worker did not commit: " + docker("logs", name).decode())
        connection = starts[0]["start"]["db_connection_id"]
        remaining = self.root_sql(
            f"SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID={connection};"
            f"SELECT COUNT(*) FROM information_schema.INNODB_TRX WHERE trx_mysql_thread_id={connection};")
        if remaining.split() != [b"0", b"0"]:
            raise RuntimeError("Exited worker still has an owned DB request/transaction.")
        evidence = {
            "schema_version": 1, "kind": "native-publication-observation", "request_sha256": digest(request),
            "worker": request["worker"], "start": starts[0]["start"],
            "quiescence": {"worker_exited": True, "request_finished": True, "owned_transactions_absent": True,
                           "authority_sha256": digest({"container": name, "state": status, "owned_remaining": [0, 0]})},
            "states": self.states(journal.manifest, journal.accepted),
            "guard_sha256": journal.put_artifact({"scope": "disposable-fresh-managed-state",
                                                 "manifest": digest(journal.manifest)}),
            "observation_nonce": secrets.token_hex(16),
        }
        return evidence, results

    def full_run(self, rehearsal, corpora):
        rehearsal.refresh_metadata()
        metadata = rehearsal.metadata
        current = dict(rehearsal.baseline)
        operations = []
        for index, title in enumerate(rehearsal.order, 1):
            owners = sorted({owner for owner, _ in transclusions(rehearsal.desired[title])})
            prerequisites = [{"namespace": 14 if owner.startswith("Category:") else 0,
                              "title": owner, "raw_sha256": sha(current[owner])} for owner in owners]
            expected = ({"page_id": metadata[title]["pageid"], "revision_id": metadata[title]["revid"],
                         "raw_sha256": metadata[title]["raw_sha256"]} if title in metadata
                        else {"page_id": 0, "revision_id": 0, "raw_sha256": None})
            operations.append(self.operation(index, title, expected, rehearsal.desired[title], prerequisites))
            current[title] = rehearsal.desired[title]
        preserved = [{"namespace": 14 if title.startswith("Category:") else 0, "title": title,
                      "page_id": row["pageid"], "revision_id": row["revid"], "raw_sha256": row["raw_sha256"]}
                     for title, row in sorted(metadata.items()) if title not in rehearsal.order]
        if len(operations) != 449 or len(preserved) != 16:
            raise RuntimeError("Native release coverage differs from 449 writes plus 16 preserved pages.")
        manifest = self.manifest(operations, preserved, corpora)
        journal = Journal(self.workspace / "native-release-journal", manifest)
        self.release_journal = journal

        def save(title, metadata, text, probes):
            index = len(journal.accepted) + 1
            if operations[index - 1]["title"] != title:
                raise RuntimeError("Native dispatch differs from the frozen full-prefix order.")
            prerequisites = [{"namespace": owner["namespace"], "title": owner["title"],
                              "page_id": metadata[owner["title"]]["pageid"],
                              "revision_id": metadata[owner["title"]]["revid"],
                              "raw_sha256": metadata[owner["title"]]["raw_sha256"]}
                             for owner in operations[index - 1]["prerequisites"]]
            request = self.request(manifest, journal, index, text, prerequisites, probes)
            name = self.launch(journal, request)
            evidence, results = self.collect(journal, request, name)
            if journal.observe(request, evidence) != "accept":
                raise RuntimeError("Native full-prefix operation did not advance.")
            accepted = journal.accept(request)
            self.proof["operations"].append({"index": index, "request_sha256": digest(request),
                                            "result": results[0], "accepted_sha256": digest(accepted)})
            docker("rm", name)
            self.containers.remove(name)
            return results[0]["revision"]["revision_id"]
        return save

    def faults(self, csrf):
        title = "Native synthetic target"
        warm = self.api({"action": "edit", "title": title, "text": "Native fixture baseline", "token": csrf}, post=True)
        if warm.get("edit", {}).get("result") != "Success":
            raise RuntimeError("Synthetic fixture setup failed.")
        operator = self.operator()
        self.api({"action": "edit", "title": "Native synthetic editor", "text": "Actor fixture", "token": csrf}, post=True)
        # Explicit disposable bootstrap; the publication primitive never creates actors/counters.
        user_code = (
            "$s=MediaWiki\\MediaWikiServices::getInstance();$u=$s->getUserFactory()->newFromName('TestEditor');"
            "$d=$s->getConnectionProvider()->getPrimaryDatabase();"
            "$s->getActorNormalization()->acquireActorId($u,$d);"
            "$d->newUpdateQueryBuilder()->update('user')->set(['user_editcount'=>0])->where(['user_id'=>$u->getId(),"
            "'user_editcount'=>null])->caller(__METHOD__)->execute();"
        )
        self.evaluate(user_code)
        ordinary = self.operator("TestEditor")

        def state_for(name):
            row = next(iter(self.api({"action": "query", "titles": name, "prop": "revisions",
                                     "rvprop": "ids|content", "rvslots": "main"})["query"]["pages"].values()))
            if "missing" in row:
                return {"page_id": 0, "revision_id": 0, "raw_sha256": None}
            revision = row["revisions"][0]
            return {"page_id": row["pageid"], "revision_id": revision["revid"],
                    "raw_sha256": sha(revision["slots"]["main"]["*"])}

        def case(label, *, stage=None, during=None, text=None, expected=None, actor=None, success=False,
                 lose=False, kill=False, observe=True, deny_rights=None, error=None, duplicate=False,
                 edge=None, retry_after=False, prerequisites=()):
            desired = text if text is not None else "Native desired " + label
            initial = state_for(title)
            static_owners = [{key: owner[key] for key in ("namespace", "title", "raw_sha256")} for owner in prerequisites]
            operation = self.operation(1, title, expected if expected is not None else initial, desired, static_owners)
            manifest = self.manifest([operation], operator=actor or operator)
            with Journal(self.workspace / ("case-" + label), manifest) as journal:
                request = self.request(manifest, journal, 1, desired, prerequisites)
                name = self.launch(journal, request, stage, deny_rights)
                if stage:
                    self.wait(name, stage)
                    if during:
                        during()
                    if kill:
                        docker("kill", "--signal", "KILL", name)
                    else:
                        docker("exec", name, "php", "-r", "file_put_contents('/tmp/native-fixture-release','1');")
                evidence, results = self.collect(journal, request, name, lose_result=lose, allow_error=not success or kill)
                if not success and not kill and (len(results) != 1 or results[0]["outcome"] != "error"):
                    raise RuntimeError("Native negative case did not report failure: " + label)
                if error is not None and (len(results) != 1 or results[0]["error"] != error):
                    raise RuntimeError("Native negative case reached the wrong guard: " + label + ": " + repr(results))
                current = state_for(title)
                if success and current["raw_sha256"] != sha(desired):
                    raise RuntimeError("Native success did not store exact bytes.")
                if not success and not during and current != initial:
                    raise RuntimeError("Rejected native operation changed target state: " + label)
                decision = None
                recovery_decision = None
                damaged = False
                if observe:
                    decision = journal.observe(request, evidence)
                    if decision == "accept":
                        if edge:
                            journal.close()
                            process = multiprocessing.get_context("fork").Process(
                                target=crash_acceptance, args=(journal.path, request, edge))
                            process.start()
                            process.join(15)
                            if process.is_alive():
                                process.terminate()
                                process.join()
                                raise RuntimeError("Disposable journal crash fixture did not stop.")
                            if process.exitcode != 91:
                                raise RuntimeError("Disposable journal crash edge was not reached.")
                            damaged = edge in ("written", "file-synced", "published")
                            recovery_decision = "fail-closed-damaged-journal" if damaged else "accepted-after-restart"
                        else:
                            journal.accept(request)
                    elif retry_after:
                        retry = self.request(manifest, journal, 1, desired, prerequisites, attempt=2)
                        retry_name = self.launch(journal, retry)
                        retry_evidence, retry_results = self.collect(journal, retry, retry_name)
                        recovery_decision = journal.observe(retry, retry_evidence)
                        if recovery_decision != "accept":
                            raise RuntimeError("Positively quiesced retry did not commit.")
                        journal.accept(retry)
                        results.extend(retry_results)
                        docker("rm", retry_name)
                        self.containers.remove(retry_name)
                if duplicate:
                    duplicate_name = self.launch(journal, request, record_intent=False)
                    duplicate_status = self.wait(duplicate_name)
                    duplicate_results = [json.loads(line) for line in docker("logs", duplicate_name).decode().splitlines()
                                         if line.startswith("{") and json.loads(line).get("kind") == "native-publication-result"]
                    if (duplicate_status["ExitCode"] == 0 or len(duplicate_results) != 1
                            or duplicate_results[0]["error"] != "expected-parent-mismatch" or state_for(title) != current):
                        raise RuntimeError("Actual duplicate dispatch was not rejected by strict CAS.")
                    self.proof["cases"].append({"name": "actual-duplicate-dispatch", "result": duplicate_results[0]})
                    docker("rm", duplicate_name)
                    self.containers.remove(duplicate_name)
                self.proof["cases"].append({"name": label, "decision": decision, "results": results,
                                           "recovery_decision": recovery_decision, "quiescence": evidence["quiescence"],
                                           "states_sha256": digest(evidence["states"])})
                docker("rm", name)
                self.containers.remove(name)
            if damaged:
                try:
                    with Journal(self.workspace / ("case-" + label)):
                        pass
                except JournalError:
                    pass
                else:
                    raise RuntimeError("Interrupted journal publication was silently adopted.")
            else:
                with Journal(self.workspace / ("case-" + label)) as reopened:
                    if reopened.accepted:
                        reopened.verify_resume(self.states(manifest, reopened.accepted))
            return decision

        case("ordinary-update", actor=ordinary, success=True, duplicate=True)
        case("wrong-edit-rights", actor=ordinary, deny_rights="edit", error="permission-denied-edit")
        case("create-already-exists", expected={"page_id": 0, "revision_id": 0, "raw_sha256": None},
             observe=False, error="expected-parent-mismatch")
        case("before-grab-race", stage="before-parent", observe=False, error="expected-parent-mismatch", during=lambda: self.api(
            {"action": "edit", "title": title, "text": "Competing before parent", "token": csrf}, post=True))
        case("after-grab-race", stage="after-parent", observe=False, error="save-failed-or-null", during=lambda: self.api(
            {"action": "edit", "title": title, "text": "Competing after parent", "token": csrf}, post=True))
        case("update-gone-missing", stage="before-parent", observe=False, error="expected-parent-mismatch", during=lambda: self.api(
            {"action": "delete", "title": title, "reason": "Disposable create/update mismatch", "token": csrf}, post=True))
        self.api({"action": "protect", "title": title, "protections": "create=sysop", "expiry": "infinite",
                  "token": csrf}, post=True)
        case("protected-creation", actor=ordinary, error="permission-denied-create")
        self.api({"action": "protect", "title": title, "protections": "create=all", "expiry": "infinite",
                  "token": csrf}, post=True)
        case("wrong-create-rights", actor=ordinary, deny_rights="createpage", error="permission-denied-create")
        case("after-grab-create-race", stage="after-parent", observe=False, error="save-failed-or-null", during=lambda: self.api(
            {"action": "edit", "title": title, "text": "Competing create", "token": csrf}, post=True))
        self.api({"action": "delete", "title": title, "reason": "Reset synthetic creation fixture", "token": csrf}, post=True)
        case("ordinary-create", actor=ordinary, success=True)
        self.api({"action": "protect", "title": title, "protections": "edit=sysop", "expiry": "infinite", "token": csrf}, post=True)
        case("protected-target", actor=ordinary, error="permission-denied-edit")
        self.api({"action": "protect", "title": title, "protections": "edit=all", "expiry": "infinite", "token": csrf}, post=True)
        self.api({"action": "block", "user": "TestEditor", "expiry": "1 hour", "reason": "Disposable native block test",
                  "token": csrf}, post=True)
        case("blocked-operator", actor=ordinary, error="operator-blocked")
        self.api({"action": "unblock", "user": "TestEditor", "token": csrf}, post=True)
        case("stale-prerequisite", prerequisites=[{"namespace": 0, "title": "Native synthetic editor",
             **state_for("Native synthetic editor"), "raw_sha256": sha("Stale owner")}], error="expected-parent-mismatch")
        case("pst-byte-mismatch", text="Native changed trailing LF\n", error="saved-revision-mismatch")
        current = state_for(title)
        raw = next(iter(self.api({"action": "query", "titles": title, "prop": "revisions",
                                 "rvprop": "content", "rvslots": "main"})["query"]["pages"].values()))["revisions"][0]["slots"]["main"]["*"]
        case("pst-null-save", text=raw + "\n", error="save-failed-or-null")
        if state_for(title) != current:
            raise RuntimeError("Null save was not rejected.")
        if case("lost-before-commit", stage="before-commit", lose=True, kill=True, retry_after=True) != "retry":
            raise RuntimeError("Quiesced precommit crash is not retryable.")
        if case("lost-after-commit", stage="after-commit", lose=True, kill=True, success=True) != "accept":
            raise RuntimeError("Postcommit lost response was not reconciled.")
        case("fresh-postcommit-mismatch", stage="after-commit", observe=False, error="fresh-revision-mismatch",
             during=lambda: self.api({"action": "edit", "title": title, "text": "Foreign postcommit revision",
                                     "token": csrf}, post=True))
        for edge in ("written", "file-synced", "published", "unlinked", "directory-synced"):
            case("journal-edge-" + edge, success=True, edge=edge)
        for name in (title, "Native synthetic editor"):
            self.api({"action": "delete", "title": name, "reason": "Remove disposable native fixture", "token": csrf}, post=True)

    def recovery(self):
        for name in self.containers:
            if json.loads(docker("inspect", "--format", "{{json .State}}", name))["Running"]:
                raise RuntimeError("Recovery proof cannot run with an active worker.")
        before = self.root_sql(dump=True)
        table_hashes = {table: sha(self.root_sql(dump=True, tables=(table,))) for table in RECOVERY_TABLES}
        counts = {table: int(self.root_sql(f"SELECT COUNT(*) FROM `{table}`;")) for table in RECOVERY_TABLES}
        if any(counts[table] <= 0 for table in ("page", "revision", "slots", "content", "text", "actor",
                                               "logging", "archive", "user", "image", "comment")):
            raise RuntimeError("SQL restore coverage lacks populated core tables.")
        self.root_sql("CREATE DATABASE native_disposable_restore;")
        self.root_sql(database="native_disposable_restore", input_bytes=before)
        restored = self.root_sql(database="native_disposable_restore", dump=True)
        restored_tables = {table: sha(self.root_sql(database="native_disposable_restore", dump=True, tables=(table,)))
                           for table in RECOVERY_TABLES}
        if before != restored or table_hashes != restored_tables:
            raise RuntimeError("Actual disposable SQL restore differs from its backup.")
        image_backup = self.run("run", "--rm", "--no-deps", "--entrypoint", "tar", "mirklurk",
                                "-C", "/var/www/html/images", "-cf", "-", ".")
        restored_images = self.run(
            "run", "--rm", "--no-deps", "-T", "--entrypoint", "sh", "mirklurk", "-c",
            "mkdir /tmp/native-image-restore && tar -xf - -C /tmp/native-image-restore "
            "&& tar -C /tmp/native-image-restore -cf - .", input_bytes=image_backup)

        def files(payload):
            with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
                return {row.name: sha(archive.extractfile(row).read()) for row in archive if row.isfile()}
        if not files(image_backup) or files(image_backup) != files(restored_images):
            raise RuntimeError("Actual disposable image restore differs from its backup.")
        return {"schema_version": 1, "kind": "disposable-native-recovery-proof", "source_head_sha": self.source_head,
                "sql_backup_sha256": sha(before), "sql_restored_sha256": sha(restored),
                "table_backup_sha256": table_hashes, "table_restored_sha256": restored_tables,
                "table_rows": counts,
                "image_backup_manifest_sha256": digest(files(image_backup)),
                "image_restored_manifest_sha256": digest(files(restored_images)), "image_files": len(files(image_backup)),
                "scope": "Actual isolated synthetic SQL and image restore; no production backup data retained."}

    def close(self):
        if hasattr(self, "release_journal"):
            self.release_journal.close()
        for name in self.containers:
            docker("rm", "-f", name)
