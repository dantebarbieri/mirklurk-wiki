"""Transport-free native publication v1 protocol and private POSIX journal."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path


class JournalError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise JournalError(message)


def canonical_bytes(value):
    def check(item):
        require(type(item) in (dict, list, str, int, bool, type(None)), "Unsupported JSON value.")
        if isinstance(item, dict):
            require(all(isinstance(key, str) for key in item), "Non-string JSON key.")
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        elif type(item) is int:
            require(abs(item) <= 9007199254740991, "JSON integer outside exact interoperable range.")
    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def decode(raw):
    try:
        value = json.loads(raw)
        require(canonical_bytes(value) == raw, "Noncanonical or duplicate-key JSON.")
        return value
    except (ValueError, UnicodeError) as error:
        raise JournalError("Invalid journal JSON.") from error


def shape(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys.split()), "Unexpected record fields.")


def hex_value(value, length=64):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{" + str(length) + "}", value),
            "Invalid hash or nonce.")


def positive(value):
    require(type(value) is int and value > 0, "Expected positive integer.")


def identity(value):
    require(type(value["namespace"]) is int and value["namespace"] in (0, 14), "Unmanaged namespace.")
    title = value["title"]
    require(isinstance(title, str) and title and title == title.strip()
            and not re.search(r"[_#\x00-\x1f\x7f]", title), "Noncanonical title.")
    require((value["namespace"] == 14) == title.startswith("Category:"), "Namespace/title mismatch.")
    return value["namespace"], title


def tuple_guard(value):
    shape(value, "page_id revision_id raw_sha256")
    if value["page_id"] == 0:
        require(type(value["page_id"]) is int and type(value["revision_id"]) is int
                and value["revision_id"] == 0 and value["raw_sha256"] is None, "Invalid absence tuple.")
    else:
        positive(value["page_id"])
        positive(value["revision_id"])
        hex_value(value["raw_sha256"])


def projection(state):
    return {key: state[key] for key in ("page_id", "revision_id", "raw_sha256")}


def validate_manifest(manifest):
    shape(manifest, "schema_version kind run_nonce source runtime operator binding_sha256 corpora "
                    "prerequisites_sha256 operations preserved")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
            and manifest["kind"] == "native-publication-manifest",
            "Unsupported manifest.")
    hex_value(manifest["run_nonce"], 32)
    shape(manifest["source"], "head_sha tree_sha")
    for value in manifest["source"].values():
        hex_value(value, 40)
    shape(manifest["runtime"], "mediawiki_version primitive_sha256 fingerprint_sha256")
    require(manifest["runtime"]["mediawiki_version"] == "1.43.9", "Unreviewed MediaWiki version.")
    for key in ("primitive_sha256", "fingerprint_sha256"):
        hex_value(manifest["runtime"][key])
    shape(manifest["operator"], "id name actor_id")
    positive(manifest["operator"]["id"])
    positive(manifest["operator"]["actor_id"])
    require(isinstance(manifest["operator"]["name"], str) and manifest["operator"]["name"],
            "Missing existing operator name.")
    shape(manifest["corpora"], "previous_authored baseline authored desired")
    for value in [*manifest["corpora"].values(), manifest["binding_sha256"], manifest["prerequisites_sha256"]]:
        hex_value(value)
    require(isinstance(manifest["operations"], list) and manifest["operations"], "Empty operation list.")
    require(isinstance(manifest["preserved"], list), "Invalid preserved list.")
    seen, nonces = set(), set()
    for index, operation in enumerate(manifest["operations"], 1):
        shape(operation, "index operation_nonce namespace title expected desired_sha256 "
                         "prerequisites_sha256 prerequisites")
        require(type(operation["index"]) is int and operation["index"] == index, "Nonsequential operations.")
        key = identity(operation)
        require(key not in seen, "Duplicate managed title.")
        seen.add(key)
        hex_value(operation["operation_nonce"], 32)
        require(operation["operation_nonce"] not in nonces, "Reused operation nonce.")
        nonces.add(operation["operation_nonce"])
        tuple_guard(operation["expected"])
        hex_value(operation["desired_sha256"])
        require(operation["desired_sha256"] != operation["expected"]["raw_sha256"], "Dispatched storage no-op.")
        hex_value(operation["prerequisites_sha256"])
        require(isinstance(operation["prerequisites"], list), "Invalid prerequisites.")
        owners = set()
        for owner in operation["prerequisites"]:
            shape(owner, "namespace title raw_sha256")
            owner_key = identity(owner)
            require(owner_key not in owners, "Duplicate prerequisite.")
            owners.add(owner_key)
            hex_value(owner["raw_sha256"])
    for state in manifest["preserved"]:
        shape(state, "namespace title page_id revision_id raw_sha256")
        key = identity(state)
        require(key not in seen, "Duplicate preserved title.")
        seen.add(key)
        tuple_guard(projection(state))
        positive(state["page_id"])
    return manifest


def validate_request(manifest, request):
    shape(request, "schema_version kind manifest_sha256 run_nonce index attempt operation_nonce "
                   "worker desired_text prerequisites prerequisite_evidence_sha256 previous_accepted_sha256")
    require(type(request["schema_version"]) is int and request["schema_version"] == 1
            and request["kind"] == "native-publication-request",
            "Unsupported request.")
    require(request["manifest_sha256"] == digest(manifest) and request["run_nonce"] == manifest["run_nonce"],
            "Request manifest binding differs.")
    positive(request["index"])
    positive(request["attempt"])
    require(request["attempt"] <= 999, "Attempt limit exceeded.")
    require(request["index"] <= len(manifest["operations"]), "Unknown operation.")
    operation = manifest["operations"][request["index"] - 1]
    require(request["operation_nonce"] == operation["operation_nonce"], "Operation nonce differs.")
    shape(request["worker"], "nonce identity")
    hex_value(request["worker"]["nonce"], 32)
    require(isinstance(request["worker"]["identity"], str)
            and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", request["worker"]["identity"]), "Invalid worker identity.")
    hex_value(request["previous_accepted_sha256"])
    hex_value(request["prerequisite_evidence_sha256"])
    require(isinstance(request["desired_text"], str)
            and hashlib.sha256(request["desired_text"].encode()).hexdigest() == operation["desired_sha256"],
            "Desired bytes differ.")
    require(isinstance(request["prerequisites"], list), "Invalid request prerequisites.")
    owners = []
    for owner in request["prerequisites"]:
        shape(owner, "namespace title page_id revision_id raw_sha256")
        identity(owner)
        tuple_guard(projection(owner))
        positive(owner["page_id"])
        owners.append({key: owner[key] for key in ("namespace", "title", "raw_sha256")})
    require(owners == operation["prerequisites"], "Prerequisite bindings differ.")
    return operation


def validate_start(start):
    shape(start, "pid boot_id process_start_ticks db_connection_id")
    for key in ("pid", "process_start_ticks", "db_connection_id"):
        positive(start[key])
    require(isinstance(start["boot_id"], str)
            and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", start["boot_id"]),
            "Invalid worker boot identity.")


def validate_event(event, request, kind):
    common = "schema_version kind request_sha256 manifest_sha256 worker start"
    shape(event, common if kind == "native-publication-start" else common + " outcome stage revision error")
    require(type(event["schema_version"]) is int and event["schema_version"] == 1 and event["kind"] == kind
            and event["request_sha256"] == digest(request)
            and event["manifest_sha256"] == request["manifest_sha256"]
            and event["worker"] == request["worker"], "Worker event binding differs.")
    validate_start(event["start"])
    if kind == "native-publication-result":
        require(event["outcome"] in ("committed", "error")
                and event["stage"] in ("validated", "parent", "saving", "saved", "committed", "verified"),
                "Unknown worker outcome.")
        require((event["outcome"] == "committed") == (event["stage"] == "verified" and event["error"] is None),
                "Inconsistent worker result.")
        require(event["error"] is None or isinstance(event["error"], str), "Invalid worker error.")
        if event["outcome"] == "error":
            require(isinstance(event["error"], str) and event["error"] and event["revision"] is None,
                    "Failure must contain an explicit error and no successful revision.")


def committed_state(manifest, request, state):
    operation = manifest["operations"][request["index"] - 1]
    shape(state, "namespace title page_id revision_id parent_id raw_sha256 actor_id comment")
    require(identity(state) == identity(operation), "Committed title differs.")
    tuple_guard(projection(state))
    positive(state["page_id"])
    positive(state["revision_id"])
    require(type(state["parent_id"]) is int and state["parent_id"] >= 0, "Invalid parent identity.")
    positive(state["actor_id"])
    require(state["revision_id"] > operation["expected"]["revision_id"]
            and state["parent_id"] == operation["expected"]["revision_id"]
            and state["raw_sha256"] == operation["desired_sha256"]
            and state["actor_id"] == manifest["operator"]["actor_id"]
            and state["comment"] == "native-publication/v1:" + digest(request),
            "Not this intent's exact committed revision.")
    if operation["expected"]["page_id"]:
        require(state["page_id"] == operation["expected"]["page_id"], "Committed page identity differs.")


class Journal:
    """One exclusive coordinator; transport must independently prove quiescence."""

    def __init__(self, path, manifest=None, *, edge=None):
        require(os.name == "posix", "POSIX file and directory durability is required.")
        import fcntl
        self.path, self.edge = Path(path), edge or (lambda _: None)
        if manifest is not None:
            validate_manifest(manifest)
            self.path.mkdir(mode=0o700)
            parent = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        require(self.path.absolute() == self.path.resolve(), "Journal path contains an alias.")
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(self.fd)
            require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                    "Journal directory must be private and owned.")
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self.fd)
            if manifest is not None:
                self._publish("manifest.json", manifest)
            self.records = self._read()
            require("manifest.json" in self.records, "Missing durable manifest.")
            self.manifest = validate_manifest(self.records["manifest.json"])
            self.replay()
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _publish(self, name, value):
        raw = canonical_bytes(value)
        require(len(raw) <= 32 * 1024 * 1024, "Journal record exceeds the replay size bound.")
        temporary = "." + name + ".pending"
        file = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                       0o600, dir_fd=self.fd)
        try:
            with os.fdopen(file, "wb") as stream:
                stream.write(raw)
                stream.flush()
                self.edge("written")
                os.fsync(stream.fileno())
                self.edge("file-synced")
            # link() is atomic and cannot replace an existing acknowledged record.
            os.link(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
            self.edge("published")
            os.unlink(temporary, dir_fd=self.fd)
            self.edge("unlinked")
            os.fsync(self.fd)
            self.edge("directory-synced")
        except OSError as error:
            raise JournalError("Durable exclusive journal publication failed; stop and inspect.") from error

    def _read(self):
        records = {}
        for name in os.listdir(self.fd):
            require(name == "manifest.json" or re.fullmatch(
                r"(?:intent|start|result|evidence)-[0-9]{6}-[0-9]{3}\.json|accepted-[0-9]{6}\.json"
                r"|artifact-[0-9a-f]{64}\.json", name),
                "Unknown or interrupted journal entry; no automatic repair.")
            file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
            with os.fdopen(file, "rb") as stream:
                info = os.fstat(stream.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
                        and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 32 * 1024 * 1024,
                        "Damaged, aliased or nonprivate journal entry.")
                records[name] = decode(stream.read())
        return records

    @staticmethod
    def name(kind, request):
        return f"{kind}-{request['index']:06d}-{request['attempt']:03d}.json"

    def _put(self, name, value):
        require(name not in self.records, "An immutable record already exists.")
        self._publish(name, value)
        self.records[name] = decode(canonical_bytes(value))

    def put_artifact(self, value):
        """Durably retain an opaque, caller-reviewed guard preimage before its reference."""
        fingerprint = digest(value)
        name = f"artifact-{fingerprint}.json"
        if name in self.records:
            require(canonical_bytes(self.records[name]) == canonical_bytes(value), "Artifact digest collision.")
        else:
            self._put(name, value)
        return fingerprint

    def get_artifact(self, fingerprint):
        hex_value(fingerprint)
        name = f"artifact-{fingerprint}.json"
        require(name in self.records and digest(self.records[name]) == fingerprint, "Missing or damaged guard artifact.")
        return decode(canonical_bytes(self.records[name]))

    def expected_states(self, accepted):
        states = {identity(row): {**{key: row[key] for key in ("namespace", "title")}, **row["expected"]}
                  for row in self.manifest["operations"]}
        states.update({identity(row): row for row in self.manifest["preserved"]})
        for record in accepted:
            states[identity(record["revision"])] = record["revision"]
        return states

    def _decision(self, request, evidence, accepted):
        shape(evidence, "schema_version kind request_sha256 worker start quiescence states guard_sha256 observation_nonce")
        require(type(evidence["schema_version"]) is int and evidence["schema_version"] == 1
                and evidence["kind"] == "native-publication-observation"
                and evidence["request_sha256"] == digest(request) and evidence["worker"] == request["worker"],
                "Observation binding differs.")
        validate_start(evidence["start"])
        shape(evidence["quiescence"], "worker_exited request_finished owned_transactions_absent authority_sha256")
        require(all(evidence["quiescence"][key] is True
                    for key in ("worker_exited", "request_finished", "owned_transactions_absent")),
                "Positive worker/request/transaction quiescence is required.")
        hex_value(evidence["quiescence"]["authority_sha256"])
        hex_value(evidence["guard_sha256"])
        self.get_artifact(evidence["guard_sha256"])
        hex_value(evidence["observation_nonce"], 32)
        start = self.records.get(self.name("start", request))
        result = self.records.get(self.name("result", request))
        for event in (start, result):
            if event is not None:
                require(event["start"] == evidence["start"], "Quiescence belongs to another worker process.")
        expected = self.expected_states(accepted)
        require(isinstance(evidence["states"], list), "Missing complete fresh states.")
        actual = {}
        for state in evidence["states"]:
            require(isinstance(state, dict), "Invalid fresh state.")
            key = identity(state)
            require(key not in actual, "Duplicate fresh state.")
            tuple_guard(projection(state))
            actual[key] = state
        require(set(actual) == set(expected), "Missing or extra managed state.")
        key = identity(self.manifest["operations"][request["index"] - 1])
        changed = actual[key] != expected[key]
        if changed:
            committed_state(self.manifest, request, actual[key])
            expected[key] = actual[key]
        require(all(canonical_bytes(actual[key]) == canonical_bytes(expected[key]) for key in expected),
                "Mixed, extra or changed prefix state.")
        if result is not None and result["outcome"] == "committed":
            require(changed and result["revision"] == actual[key], "Result and fresh state disagree.")
        return ("accept" if changed else "retry"), actual[key]

    def replay(self):
        accepted, used_workers, known = [], set(), {"manifest.json"}
        for name, value in self.records.items():
            if name.startswith("artifact-"):
                require(name == f"artifact-{digest(value)}.json", "Guard artifact hash differs.")
                known.add(name)
        previous = digest(self.manifest)
        pending = False
        for operation in self.manifest["operations"]:
            index = operation["index"]
            prefix_name = f"accepted-{index:06d}.json"
            attempt = 1
            last = None
            while (name := f"intent-{index:06d}-{attempt:03d}.json") in self.records:
                require(not pending, "Intent skips an unaccepted prefix.")
                require(index == len(accepted) + 1, "Intent skips a missing prefix.")
                request = self.records[name]
                validate_request(self.manifest, request)
                self.get_artifact(request["prerequisite_evidence_sha256"])
                require(request["index"] == index and request["attempt"] == attempt
                        and request["previous_accepted_sha256"] == previous, "Intent chain differs.")
                require(request["worker"]["nonce"] not in used_workers, "Worker nonce reused.")
                used_workers.add(request["worker"]["nonce"])
                if attempt > 1:
                    require(last is not None and last[0] == "retry", "Retry lacks positive noncommit evidence.")
                known.add(name)
                for kind in ("start", "result"):
                    event_name = self.name(kind, request)
                    if event_name in self.records:
                        validate_event(self.records[event_name], request, "native-publication-" + kind)
                        if kind == "result" and self.records[event_name]["outcome"] == "committed":
                            committed_state(self.manifest, request, self.records[event_name]["revision"])
                        known.add(event_name)
                evidence_name = self.name("evidence", request)
                last = None
                if evidence_name in self.records:
                    last = self._decision(request, self.records[evidence_name], accepted)
                    known.add(evidence_name)
                attempt += 1
            if prefix_name in self.records:
                require(attempt > 1 and last is not None and last[0] == "accept", "Unproven accepted prefix.")
                record = self.records[prefix_name]
                expected_record = self._acceptance(request, last[1], previous)
                require(record == expected_record, "Accepted prefix chain is damaged.")
                accepted.append(record)
                previous = digest(record)
                known.add(prefix_name)
            elif attempt > 1:
                pending = True
        require(set(self.records) == known, "Orphaned or out-of-order journal records.")
        self.accepted = accepted
        self.previous = previous
        return accepted

    def intent(self, request):
        validate_request(self.manifest, request)
        self.get_artifact(request["prerequisite_evidence_sha256"])
        require(request["index"] == len(self.accepted) + 1 and request["previous_accepted_sha256"] == self.previous,
                "Only the next unaccepted operation can be dispatched.")
        require(request["attempt"] <= 999, "Attempt limit exceeded.")
        name = self.name("intent", request)
        require(name not in self.records, "Duplicate dispatch intent.")
        intents = [row for key, row in self.records.items() if key.startswith("intent-")]
        require(all(row["worker"]["nonce"] != request["worker"]["nonce"] for row in intents), "Worker nonce reused.")
        attempts = [row for row in intents if row["index"] == request["index"]]
        require(request["attempt"] == len(attempts) + 1, "Attempt sequence differs.")
        if attempts:
            prior = max(attempts, key=lambda row: row["attempt"])
            evidence = self.records.get(self.name("evidence", prior))
            require(evidence is not None and self._decision(prior, evidence, self.accepted)[0] == "retry",
                    "Retry lacks positive noncommit evidence.")
        self._put(name, request)
        return digest(request)

    def event(self, request, event):
        require(self.records.get(self.name("intent", request)) == request, "Intent must be durable before dispatch.")
        require(request["index"] == len(self.accepted) + 1, "Late event for an accepted operation.")
        kind = event.get("kind")
        require(kind in ("native-publication-start", "native-publication-result"), "Unexpected worker event.")
        validate_event(event, request, kind)
        if kind == "native-publication-result" and event["outcome"] == "committed":
            committed_state(self.manifest, request, event["revision"])
        other_kind = "start" if kind == "native-publication-result" else "result"
        other = self.records.get(self.name(other_kind, request))
        require(other is None or other["start"] == event["start"], "Worker event process identity differs.")
        self._put(self.name(kind.removeprefix("native-publication-"), request), event)

    def observe(self, request, evidence):
        require(self.records.get(self.name("intent", request)) == request, "Unknown intent.")
        require(request["index"] == len(self.accepted) + 1, "Observation is not for the pending operation.")
        decision, _ = self._decision(request, evidence, self.accepted)
        self._put(self.name("evidence", request), evidence)
        return decision

    def _acceptance(self, request, revision, previous):
        result = self.records.get(self.name("result", request))
        evidence = self.records[self.name("evidence", request)]
        return {"schema_version": 1, "kind": "native-publication-accepted", "index": request["index"],
                "request_sha256": digest(request), "previous_accepted_sha256": previous,
                "evidence_sha256": digest(evidence), "result_sha256": digest(result) if result is not None else None,
                "revision": revision, "states_sha256": digest(evidence["states"])}

    def accept(self, request):
        evidence = self.records[self.name("evidence", request)]
        decision, revision = self._decision(request, evidence, self.accepted)
        require(decision == "accept" and request["index"] == len(self.accepted) + 1, "No next committed prefix.")
        record = self._acceptance(request, revision, self.previous)
        self._put(f"accepted-{request['index']:06d}.json", record)
        self.accepted.append(record)
        self.previous = digest(record)
        return record

    def verify_resume(self, states):
        require(isinstance(states, list) and len(states) == len(self.expected_states(self.accepted)),
                "Incomplete resumed prefix.")
        actual = {identity(row): row for row in states}
        expected = self.expected_states(self.accepted)
        require(len(actual) == len(states) and set(actual) == set(expected)
                and all(canonical_bytes(actual[key]) == canonical_bytes(expected[key]) for key in expected),
                "Fresh state differs from the accepted prefix; reconcile pending intent first.")
