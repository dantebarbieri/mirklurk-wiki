"""Real native-worker and recovery proof, exclusively inside disposable Compose."""

import base64
import hashlib
import io
import json
import multiprocessing
import os
import re
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


def maintenance_program(code):
    # MediaWiki readconsole() reads at most 1023 bytes before eval()ing each line.
    encoded = base64.b64encode(code.encode()).decode()
    lines = ["$nativeSmokeProgram='';"]
    lines.extend("$nativeSmokeProgram.='" + encoded[offset:offset + 720] + "';"
                 for offset in range(0, len(encoded), 720))
    lines.append("eval(base64_decode($nativeSmokeProgram,true));")
    return ("\n".join(lines) + "\n").encode()


def php_json(value):
    encoded = base64.b64encode(canonical_bytes(value)).decode()
    return "json_decode(base64_decode('" + encoded + "'),true,512,JSON_THROW_ON_ERROR)"


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
                        input_bytes=maintenance_program(code))

    def operator(self, name="WikiAdmin"):
        code = (
            "$s=MediaWiki\\MediaWikiServices::getInstance();$d=$s->getConnectionProvider()->getPrimaryDatabase();"
            "$u=$d->newSelectQueryBuilder()->select(['user_id','user_name','user_editcount'])->from('user')"
            "->where(['user_name'=>" + php_json(name) + "])->caller(__METHOD__)->fetchRow();"
            "if(!$u || $u->user_editcount===null){throw new RuntimeException('fixture-operator-not-ready');}"
            "$a=$d->newSelectQueryBuilder()->select('actor_id')->from('actor')->where(['actor_user'=>$u->user_id,"
            "'actor_name'=>$u->user_name])->caller(__METHOD__)->fetchField();"
            "if(!$a){throw new RuntimeException('fixture-actor-missing');}"
            "echo json_encode(['id'=>(int)$u->user_id,'name'=>$u->user_name,'actor_id'=>(int)$a]);"
        )
        return json.loads(self.evaluate(code))

    def manifest(self, operations, preserved=(), corpora=None, operator=None):
        if corpora is None:
            raise RuntimeError("Explicit canonical corpus-map digests are required.")
        return {
            "schema_version": 1, "kind": "native-publication-manifest", "run_nonce": secrets.token_hex(16),
            "source": {"head_sha": self.source_head, "tree_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=self.root, text=True).strip()},
            "runtime": {"mediawiki_version": "1.43.9", "primitive_sha256": sha(
                (self.root / "tools" / "native_publication.php").read_bytes()), "fingerprint_sha256": digest(self.runtime)},
            "operator": operator or self.operator(), "binding_sha256": digest({"scope": "disposable", "runtime": self.runtime}),
            "corpora": corpora,
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
        code = (
            "$s=MediaWiki\\MediaWikiServices::getInstance();$d=$s->getConnectionProvider()->getPrimaryDatabase();$out=[];"
            "foreach(" + php_json(sorted(expected)) + " as $name){"
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
        dispatch_id = request["worker"]["nonce"] + ("" if record_intent else "-duplicate-" + secrets.token_hex(4))
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

    def effects(self):
        keys = {"revision": ["rev_id"], "slots": ["slot_revision_id", "slot_role_id"],
                "content": ["content_id"], "text": ["old_id"], "actor": ["actor_id"], "logging": ["log_id"],
                "archive": ["ar_id"], "image": ["img_name"], "oldimage": ["oi_name", "oi_timestamp"],
                "filearchive": ["fa_id"], "comment": ["comment_id"], "user_groups": ["ug_user", "ug_group"]}
        code = (
            "$s=MediaWiki\\MediaWikiServices::getInstance();$d=$s->getConnectionProvider()->getPrimaryDatabase();"
            "$out=['tables'=>[],'pages'=>[],'users'=>[],'slot_content'=>[],'content_address'=>[],'original_files'=>[]];"
            "$keys=" + php_json(keys) + ";"
            "foreach($keys as $table=>$columns){$rows=[];"
            "foreach($d->newSelectQueryBuilder()->select('*')->from($table)->caller(__METHOD__)->fetchResultSet() as $r){"
            "$v=(array)$r;ksort($v);$id=implode(':',array_map(static fn($c)=>$v[$c],$columns));"
            "$rows[$id]=hash('sha256',serialize($v));"
            "if($table==='slots'){$out['slot_content'][$id]=(int)$r->slot_content_id;}"
            "if($table==='content'){$out['content_address'][$id]=$r->content_address;}"
            "if($table==='image'){$f=$s->getRepoGroup()->findFile(MediaWiki\\Title\\Title::newFromText('File:'.$r->img_name));"
            "if(!$f){throw new RuntimeException('preserved-original-file-missing');}"
            "$out['original_files'][$r->img_name]=hash_file('sha256',$f->getLocalRefPath());}"
            "}$out['tables'][$table]=(object)$rows;}"
            "foreach($d->newSelectQueryBuilder()->select(['page_id','page_namespace','page_title','page_latest','page_touched',"
            "'page_content_model','page_is_redirect','page_len'])->from('page')->caller(__METHOD__)->fetchResultSet() as $r){"
            "$v=(array)$r;unset($v['page_touched']);"
            "$out['pages'][$r->page_id]=['namespace'=>(int)$r->page_namespace,'title'=>$r->page_title,"
            "'revision_id'=>(int)$r->page_latest,'touched'=>$r->page_touched,'metadata_sha256'=>hash('sha256',serialize($v))];}"
            "foreach($d->newSelectQueryBuilder()->select('*')->from('user')->caller(__METHOD__)->fetchResultSet() as $r){"
            "$v=(array)$r;unset($v['user_editcount']);ksort($v);"
            "$out['users'][$r->user_id]=['name'=>$r->user_name,'editcount'=>$r->user_editcount===null?null:(int)$r->user_editcount,"
            "'metadata_sha256'=>hash('sha256',serialize($v))];}"
            "$out['main_role_id']=(int)$d->newSelectQueryBuilder()->select('role_id')->from('slot_roles')"
            "->where(['role_name'=>'main'])->caller(__METHOD__)->fetchField();"
            "foreach(['pages','users','slot_content','content_address','original_files'] as $k){$out[$k]=(object)$out[$k];}"
            "echo json_encode($out,JSON_THROW_ON_ERROR);"
        )
        return json.loads(self.evaluate(code))

    @staticmethod
    def check_effects(before, after, revision, operator):
        if revision is None:
            if canonical_bytes(before) != canonical_bytes(after):
                raise RuntimeError("Rejected operation changed history/log/account/File state.")
            return {"operator_delta": 0, "history_rows_added": {}}
        if before["main_role_id"] != after["main_role_id"]:
            raise RuntimeError("Main slot identity changed.")
        if before["original_files"] != after["original_files"]:
            raise RuntimeError("An original image file changed during native publication.")
        additions = {}
        for table, rows in before["tables"].items():
            actual = after["tables"][table]
            if any(actual.get(key) != value for key, value in rows.items()):
                raise RuntimeError("An existing history/log/account/File row changed: " + table)
            additions[table] = sorted(actual.keys() - rows.keys())
        expected_exact = {
            "revision": [str(revision["revision_id"])],
            "slots": [f"{revision['revision_id']}:{after['main_role_id']}"],
            "actor": [], "archive": [], "image": [], "oldimage": [], "filearchive": [], "user_groups": [],
        }
        if any(additions[table] != expected for table, expected in expected_exact.items()):
            raise RuntimeError("A native revision has extra or missing history/actor/File rows.")
        if len(additions["comment"]) != 1 or len(additions["logging"]) != (1 if revision["parent_id"] == 0 else 0):
            raise RuntimeError("Native comment/create-log delta differs.")
        content_id = after["slot_content"][expected_exact["slots"][0]]
        address = after["content_address"][str(content_id)]
        if (len(additions["content"]) > 1 or len(additions["text"]) > 1
                or any(key != str(content_id) for key in additions["content"])
                or any(address != "tt:" + key for key in additions["text"])):
            raise RuntimeError("Native content/text additions are not the saved main slot.")
        page_id = str(revision["page_id"])
        expected_pages = {key: {field: item for field, item in value.items() if field != "touched"}
                          for key, value in before["pages"].items() if key != page_id}
        actual_pages = {key: {field: item for field, item in value.items() if field != "touched"}
                        for key, value in after["pages"].items() if key != page_id}
        if (expected_pages != actual_pages or after["pages"][page_id]["revision_id"] != revision["revision_id"]
                or after["pages"][page_id]["namespace"] != revision["namespace"]):
            raise RuntimeError("Native page pointers changed outside the target.")
        expected_users = json.loads(json.dumps(before["users"]))
        count = expected_users[str(operator["id"])]["editcount"]
        if type(count) is not int:
            raise RuntimeError("Operator edit count was not initialized before dispatch.")
        expected_users[str(operator["id"])]["editcount"] = count + 1
        if canonical_bytes(expected_users) != canonical_bytes(after["users"]):
            raise RuntimeError("Native operator/account delta is incomplete or unexpected.")
        return {"operator_delta": 1, "history_rows_added": additions}

    def collect(self, journal, request, name, *, lose_result=False, allow_error=False):
        status = self.wait(name)
        if status["Status"] != "exited" or status["Pid"] != 0:
            raise RuntimeError("Worker process is not positively exited.")
        events = [json.loads(line) for line in docker("logs", name).decode().splitlines() if line.startswith("{")]
        starts = [row for row in events if row.get("kind") == "native-publication-start"]
        results = [row for row in events if row.get("kind") == "native-publication-result"]
        if len(starts) != 1:
            raise RuntimeError("Native worker failed before identifiable start: " + docker("logs", name).decode())
        def retain(event, kind):
            prior = journal.records.get(journal.name(kind, request))
            if prior is None:
                journal.event(request, event)
            elif canonical_bytes(prior) != canonical_bytes(event):
                raise RuntimeError("Retained worker event changed on restart.")
        retain(starts[0], "start")
        if not lose_result:
            for result in results:
                retain(result, "result")
        if not allow_error and (status["ExitCode"] != 0 or len(results) != 1 or results[0]["outcome"] != "committed"):
            raise RuntimeError("Native worker did not commit: " + docker("logs", name).decode())
        connection = starts[0]["start"]["db_connection_id"]
        remaining = self.root_sql(
            f"SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID={connection};"
            f"SELECT COUNT(*) FROM information_schema.INNODB_TRX WHERE trx_mysql_thread_id={connection};")
        if remaining.split() != [b"0", b"0"]:
            raise RuntimeError("Exited worker still has an owned DB request/transaction.")
        container = json.loads(docker("inspect", "--format",
                                     '{"id":{{json .Id}},"image":{{json .Image}}}', name))
        if container["image"] != self.runtime["runtime_image_id"]:
            raise RuntimeError("Worker container used a different runtime image.")
        completion = {"schema_version": 1, "kind": "disposable-native-completion",
                      "request_sha256": digest(request), "worker": request["worker"], "start": starts[0]["start"],
                      "container": {**container, "name": name}, "state": status,
                      "owned_db_counts": {"requests": 0, "transactions": 0}}
        evidence = {
            "schema_version": 1, "kind": "native-publication-observation", "request_sha256": digest(request),
            "worker": request["worker"], "start": starts[0]["start"],
            "quiescence": {"worker_exited": True, "request_finished": True, "owned_transactions_absent": True,
                           "authority_sha256": journal.put_artifact(completion)},
            "states": self.states(journal.manifest, journal.accepted),
            "guard_sha256": "",
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
        if len(operations) != 459 or len(preserved) != 12:
            raise RuntimeError("Native release coverage differs from 459 writes plus 12 preserved pages.")
        manifest = self.manifest(operations, preserved, corpora)
        journal = Journal(self.workspace / "native-release-journal", manifest)
        self.release_journal = journal
        previous_effects = self.effects()
        journal.put_artifact(previous_effects)
        pending = None

        def save(title, metadata, text, probes):
            nonlocal pending
            if pending is not None:
                raise RuntimeError("Previous native dispatch has not passed its prefix guards.")
            index = len(journal.accepted) + 1
            if operations[index - 1]["title"] != title:
                raise RuntimeError("Native dispatch differs from the frozen full-prefix order.")
            prerequisites = [{"namespace": owner["namespace"], "title": owner["title"],
                              "page_id": metadata[owner["title"]]["pageid"],
                              "revision_id": metadata[owner["title"]]["revid"],
                              "raw_sha256": metadata[owner["title"]]["raw_sha256"]}
                             for owner in operations[index - 1]["prerequisites"]]
            request = self.request(manifest, journal, index, text, prerequisites, {
                "probes": probes, "effects_before_sha256": journal.put_artifact(previous_effects)})
            name = self.launch(journal, request)
            evidence, results = self.collect(journal, request, name)
            pending = (request, evidence, results[0], name)
            return results[0]["revision"]["revision_id"]

        def accept(index, guards):
            nonlocal pending, previous_effects
            if pending is None or pending[0]["index"] != index:
                raise RuntimeError("No matching guarded native dispatch.")
            request, evidence, result, name = pending
            guards = json.loads(canonical_bytes(guards))
            current_effects = self.effects()
            delta = self.check_effects(previous_effects, current_effects, result["revision"], manifest["operator"])
            evidence["states"] = self.states(manifest, journal.accepted)
            guard = {"prefix_guards": guards, "effects_before_sha256": journal.put_artifact(previous_effects),
                     "effects_after_sha256": journal.put_artifact(current_effects), "delta": delta}
            evidence["guard_sha256"] = journal.put_artifact(guard)
            if journal.observe(request, evidence) != "accept":
                raise RuntimeError("Native full-prefix operation did not advance.")
            accepted = journal.accept(request)
            self.proof["operations"].append({"index": index, "request_sha256": digest(request), "result": result,
                                            "guard_sha256": digest(guard), "accepted_sha256": digest(accepted),
                                            "effects": delta, "prefix_guards": guards})
            previous_effects = current_effects
            pending = None
            docker("rm", name)
            self.containers.remove(name)
        return save, accept

    def prepare_thumbnails(self, *corpora):
        operator = self.operator()
        default_width = int(self.evaluate(
            "$s=MediaWiki\\MediaWikiServices::getInstance();$u=$s->getUserFactory()->newFromId("
            + str(operator["id"]) + ");$limits=$s->getMainConfig()->get('ThumbLimits');"
            "echo $limits[$s->getUserOptionsLookup()->getOption($u,'thumbsize')];"))
        widths = {}
        for corpus in corpora:
            for text in corpus.values():
                for filename, options in re.findall(r"\[\[(File:[^|\]]+)\|([^\]]*)", text):
                    explicit = re.search(r"(?:^|\|)([0-9]+)px(?:\||$)", options)
                    width = int(explicit[1]) if explicit else default_width if "thumb" in options.split("|") else None
                    if width is not None:
                        for scaled in (width, (width * 3 + 1) // 2, width * 2):
                            widths.setdefault(scaled, set()).add(filename)
        requested = {}
        for width, titles in sorted(widths.items()):
            for title in titles:
                requested.setdefault(title, []).append(width)
        code = (
            "$s=MediaWiki\\MediaWikiServices::getInstance();$out=[];"
            "foreach(" + php_json(requested) + " as $name=>$widths){"
            "$f=$s->getRepoGroup()->findFile(MediaWiki\\Title\\Title::newFromText($name));"
            "if(!$f || $f->getRepo()!==$s->getRepoGroup()->getLocalRepo()){throw new RuntimeException('fixture-file-not-local');}"
            "$repo=$f->getRepo();$widths[]=$f->getWidth();"
            "foreach(array_unique($widths) as $width){$p=['width'=>$width];"
            "if(!$f->getHandler()->normaliseParams($f,$p)){throw new RuntimeException('fixture-transform-parameters');}"
            "$namePart=$f->thumbName($p);$dest=$f->getThumbPath($namePart);"
            "$t=$f->transform($p,File::RENDER_NOW);"
            "if(!$t || $t->isError()){throw new RuntimeException('fixture-transform-error');}"
            "$copied=false;if(!$repo->fileExists($dest)){"
            "if(!$t->fileIsSource() || $dest===$f->getPath()){throw new RuntimeException('fixture-unexpected-transform');}"
            "$status=$repo->quickImport($f->getLocalRefPath(),$dest,$f->getThumbDisposition($namePart));"
            "if(!$status->isOK()){throw new RuntimeException('fixture-source-sized-copy-failed');}$copied=true;}"
            "$local=$repo->getLocalReference($dest);"
            "if(!$local){throw new RuntimeException('fixture-derivative-missing');}"
            "$hash=hash_file('sha256',$local->getPath());"
            "if($copied && $hash!==hash_file('sha256',$f->getLocalRefPath())){throw new RuntimeException('fixture-original-copy-differs');}"
            "$out[]=['title'=>$name,'width'=>$p['width'],'source_sized_copy'=>$copied,'sha256'=>$hash];}}"
            "echo json_encode($out,JSON_THROW_ON_ERROR);"
        )
        prepared = json.loads(self.evaluate(code))
        if not prepared:
            raise RuntimeError("No declared synthetic derivatives were prepared.")
        self.proof["thumbnail_preparation"] = {
            "default_width": default_width, "transforms": prepared,
            "declared_widths_sha256": digest({str(width): sorted(titles) for width, titles in widths.items()}),
            "scope": "Synthetic derivatives prepared before barrier; no page save, purge or touch.",
        }

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
                 edge=None, retry_after=False, prerequisites=(), partial_effects=False, crash_before_guard=False):
            desired = text if text is not None else "Native desired " + label
            initial = state_for(title)
            static_owners = [{key: owner[key] for key in ("namespace", "title", "raw_sha256")} for owner in prerequisites]
            operation = self.operation(1, title, expected if expected is not None else initial, desired, static_owners)
            before_corpus = {}
            if initial["page_id"]:
                current_page = next(iter(self.api({"action": "query", "titles": title, "prop": "revisions",
                    "rvprop": "content", "rvslots": "main"})["query"]["pages"].values()))
                before_corpus[title] = current_page["revisions"][0]["slots"]["main"]["*"]
            manifest = self.manifest([operation], corpora={
                "previous_authored": digest(before_corpus), "baseline": digest(before_corpus),
                "authored": digest({title: desired}), "desired": digest({title: desired}),
            }, operator=actor or operator)
            before_effects = self.effects()
            with Journal(self.workspace / ("case-" + label), manifest) as journal:
                request = self.request(manifest, journal, 1, desired, prerequisites,
                                       {"effects_before_sha256": journal.put_artifact(before_effects)})
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
                if crash_before_guard:
                    journal.close()
                    del evidence, results, before_effects, request, name
                    journal = Journal(journal.path)
                    request = journal.records["intent-000001-001.json"]
                    before_effects = journal.get_artifact(
                        journal.get_artifact(request["prerequisite_evidence_sha256"])["effects_before_sha256"])
                    name = "native-smoke-" + request["worker"]["nonce"]
                    if journal.accepted:
                        raise RuntimeError("A save result advanced an unverified prefix.")
                    try:
                        journal.intent(self.request(manifest, journal, 1, desired, attempt=2))
                    except JournalError:
                        pass
                    else:
                        raise RuntimeError("A committed but unverified prefix permitted a new dispatch.")
                    evidence, results = self.collect(journal, request, name)
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
                after_effects = self.effects()
                revision = next((row for row in evidence["states"]
                                 if row["title"] == title and "comment" in row
                                 and row["comment"] == "native-publication/v1:" + digest(request)), None)
                delta = None
                if during is None:
                    try:
                        delta = self.check_effects(before_effects, after_effects, revision, manifest["operator"])
                    except RuntimeError as effects_error:
                        if not partial_effects or str(effects_error) != "Native operator/account delta is incomplete or unexpected.":
                            raise
                        recovery_decision = "blocked-incomplete-deferred-effects"
                        observe = False
                    else:
                        if partial_effects:
                            raise RuntimeError("Postcommit/pre-deferred crash did not demonstrate the intended incomplete effects.")
                guard = {"scope": "synthetic-native-case", "effects_before": before_effects, "effects_after": after_effects,
                         "delta": delta, "concurrent_fixture_mutation": during is not None}
                evidence["guard_sha256"] = journal.put_artifact(guard)
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
                        retry_effects = self.effects()
                        retry_delta = self.check_effects(after_effects, retry_effects, retry_results[0]["revision"],
                                                        manifest["operator"])
                        retry_evidence["guard_sha256"] = journal.put_artifact({
                            "effects_before": after_effects, "effects_after": retry_effects, "delta": retry_delta})
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
                                           "states_sha256": digest(evidence["states"]), "guards": guard})
                docker("rm", name)
                self.containers.remove(name)
                if crash_before_guard:
                    journal.close()
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
        case("protected-creation", actor=ordinary, error="permission-denied-edit")
        self.api({"action": "protect", "title": title, "protections": "create=all", "expiry": "infinite",
                  "token": csrf}, post=True)
        case("wrong-create-rights", actor=ordinary, deny_rights="createpage", error="permission-denied-edit")
        case("after-grab-create-race", stage="after-parent", observe=False, error="save-failed-or-null", during=lambda: self.api(
            {"action": "edit", "title": title, "text": "Competing create", "token": csrf}, post=True))
        self.api({"action": "delete", "title": title, "reason": "Reset synthetic creation fixture", "token": csrf}, post=True)
        case("ordinary-create", actor=ordinary, success=True)
        case("unicode-roundtrip", text="Synthetic \u00e9 / \u2028 exact bytes", success=True)
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
        case("partial-postcommit-effects", stage="after-commit", lose=True, kill=True, success=True, partial_effects=True)
        if case("lost-final-response", stage="after-effects", lose=True, kill=True, success=True) != "accept":
            raise RuntimeError("Lost final response with complete effects was not reconciled.")
        case("result-before-guard-crash", success=True, crash_before_guard=True)
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
