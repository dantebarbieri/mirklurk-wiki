"""Synthetic protocol/durability tests; no wiki or deployment authority."""

import copy
import hashlib
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from publication_journal import (
    Journal, JournalError, canonical_bytes, decode, digest, validate_manifest, validate_request,
)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fixtures():
    manifest = {
        "schema_version": 1, "kind": "native-publication-manifest", "run_nonce": "a" * 32,
        "source": {"head_sha": "a" * 40, "tree_sha": "b" * 40},
        "runtime": {"mediawiki_version": "1.43.9", "primitive_sha256": "c" * 64, "fingerprint_sha256": "d" * 64},
        "operator": {"id": 1, "name": "Synthetic operator", "actor_id": 2},
        "binding_sha256": "e" * 64,
        "corpora": dict.fromkeys(("previous_authored", "baseline", "authored", "desired"), "f" * 64),
        "prerequisites_sha256": "1" * 64,
        "operations": [{"index": 1, "operation_nonce": "b" * 32, "namespace": 0, "title": "Example",
                        "expected": {"page_id": 7, "revision_id": 8, "raw_sha256": sha("Old")},
                        "desired_sha256": sha("New"), "prerequisites_sha256": "2" * 64, "prerequisites": []}],
        "preserved": [{"namespace": 0, "title": "Preserved", "page_id": 9, "revision_id": 10, "raw_sha256": sha("Keep\n")}],
    }
    request = {
        "schema_version": 1, "kind": "native-publication-request", "manifest_sha256": digest(manifest),
        "run_nonce": manifest["run_nonce"], "index": 1, "attempt": 1, "operation_nonce": "b" * 32,
        "worker": {"nonce": "c" * 32, "identity": "synthetic-worker"}, "desired_text": "New",
        "prerequisites": [], "prerequisite_evidence_sha256": "3" * 64, "previous_accepted_sha256": digest(manifest),
    }
    start = {"pid": 123, "boot_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
             "process_start_ticks": 100, "db_connection_id": 77}
    revision = {"namespace": 0, "title": "Example", "page_id": 7, "revision_id": 11, "parent_id": 8,
                "raw_sha256": sha("New"), "actor_id": 2, "comment": "native-publication/v1:" + digest(request)}
    evidence = {
        "schema_version": 1, "kind": "native-publication-observation", "request_sha256": digest(request),
        "worker": request["worker"], "start": start,
        "quiescence": {"worker_exited": True, "request_finished": True, "owned_transactions_absent": True,
                       "authority_sha256": "4" * 64},
        "states": [revision, *manifest["preserved"]], "guard_sha256": "5" * 64, "observation_nonce": "d" * 32,
    }
    return manifest, request, evidence


def crash_writer(path, request, edge):
    with Journal(path, edge=lambda point: os._exit(91) if point == edge else None) as journal:
        journal.intent(request)


class ProtocolTests(unittest.TestCase):
    def test_canonical_json_is_exact_and_rejects_duplicates_floats_and_large_integers(self):
        self.assertEqual(canonical_bytes({"b": "\u00e9/\u2028\n", "a": []}),
                         b'{"a":[],"b":"\xc3\xa9/\xe2\x80\xa8\\n"}')
        for raw in (b'{"a":1,"a":1}', b'{"a": 1}', b'{}\n', b'{"a":1.0}', b'{"a":9007199254740992}'):
            with self.assertRaises(JournalError):
                decode(raw)
        self.assertNotEqual(digest([]), digest({}))

    def test_absence_and_source_unchanged_noops_are_not_dispatched(self):
        manifest, request, _ = fixtures()
        validate_manifest(manifest)
        validate_request(manifest, request)
        for invalid in ({"page_id": 0, "revision_id": 2, "raw_sha256": None},
                        {"page_id": True, "revision_id": 2, "raw_sha256": sha("Old")},
                        {"page_id": 0, "revision_id": False, "raw_sha256": None}):
            candidate = copy.deepcopy(manifest)
            candidate["operations"][0]["expected"] = invalid
            with self.assertRaises(JournalError):
                validate_manifest(candidate)
        manifest["operations"][0]["desired_sha256"] = sha("Old")
        with self.assertRaisesRegex(JournalError, "no-op"):
            validate_manifest(manifest)

    def test_prerequisite_bytes_and_request_are_exact(self):
        manifest, request, _ = fixtures()
        request["desired_text"] += "\n"
        with self.assertRaisesRegex(JournalError, "Desired"):
            validate_request(manifest, request)
        request["desired_text"] = "New"
        request["prerequisites"] = [{"namespace": 0, "title": "Unknown", "page_id": 1,
                                     "revision_id": 2, "raw_sha256": sha("Old")}]
        with self.assertRaisesRegex(JournalError, "Prerequisite"):
            validate_request(manifest, request)


@unittest.skipUnless(os.name == "posix", "POSIX durability is intentionally unsupported on Windows")
class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "run"
        self.manifest, self.request, self.evidence = fixtures()

    def test_lost_committed_response_reconciles_without_resending(self):
        with Journal(self.path, self.manifest) as journal:
            journal.intent(self.request)
            with self.assertRaises(JournalError):
                journal.intent(self.request)
            self.assertEqual(journal.observe(self.request, self.evidence), "accept")
            accepted = journal.accept(self.request)
            self.assertIsNone(accepted["result_sha256"])
        with Journal(self.path) as reopened:
            self.assertEqual(len(reopened.accepted), 1)
            reopened.verify_resume(self.evidence["states"])
            with self.assertRaises(JournalError):
                reopened.accept(self.request)

    def test_missing_stdout_timeout_and_false_quiescence_cannot_retry(self):
        with Journal(self.path, self.manifest) as journal:
            journal.intent(self.request)
            retry = {**self.request, "attempt": 2, "worker": {"nonce": "e" * 32, "identity": "retry-worker"}}
            with self.assertRaisesRegex(JournalError, "noncommit"):
                journal.intent(retry)
            for flag in ("worker_exited", "request_finished", "owned_transactions_absent"):
                evidence = copy.deepcopy(self.evidence)
                evidence["quiescence"][flag] = False
                with self.assertRaisesRegex(JournalError, "quiescence"):
                    journal.observe(self.request, evidence)
            self.assertEqual(len(journal.accepted), 0)

    def test_positive_old_state_permits_fresh_attempt_but_not_reused_nonce(self):
        with Journal(self.path, self.manifest) as journal:
            journal.intent(self.request)
            self.evidence["states"] = list(journal.expected_states([]).values())
            self.assertEqual(journal.observe(self.request, self.evidence), "retry")
            with self.assertRaises(JournalError):
                journal.accept(self.request)
            with self.assertRaisesRegex(JournalError, "nonce"):
                journal.intent({**self.request, "attempt": 2})
            journal.intent({**self.request, "attempt": 2,
                            "worker": {"nonce": "e" * 32, "identity": "retry-worker"}})
        with Journal(self.path) as journal:
            self.assertEqual(len(journal.accepted), 0)
            self.assertEqual(sum(name.startswith("intent-") for name in journal.records), 2)

    def test_foreign_identical_text_and_mixed_preservation_fail_closed(self):
        with Journal(self.path, self.manifest) as journal:
            journal.intent(self.request)
            for field, value in (("comment", "Somebody else's identical edit"), ("parent_id", 4),
                                 ("actor_id", 3), ("page_id", 22), ("parent_id", True)):
                evidence = copy.deepcopy(self.evidence)
                evidence["states"][0][field] = value
                with self.assertRaises(JournalError):
                    journal.observe(self.request, evidence)
            for states in (self.evidence["states"][:-1], self.evidence["states"] * 2):
                with self.assertRaises(JournalError):
                    journal.observe(self.request, {**self.evidence, "states": states})
            evidence = copy.deepcopy(self.evidence)
            evidence["states"][1]["revision_id"] = 55
            with self.assertRaisesRegex(JournalError, "Mixed"):
                journal.observe(self.request, evidence)

    def test_result_and_observation_bind_same_process(self):
        with Journal(self.path, self.manifest) as journal:
            journal.intent(self.request)
            event = {key: self.evidence[key] for key in ("schema_version", "request_sha256", "worker", "start")}
            event.update(kind="native-publication-start", manifest_sha256=digest(self.manifest))
            journal.event(self.request, event)
            evidence = copy.deepcopy(self.evidence)
            evidence["start"]["db_connection_id"] += 1
            with self.assertRaisesRegex(JournalError, "another worker"):
                journal.observe(self.request, evidence)
            journal.event(self.request, {**event, "kind": "native-publication-result", "outcome": "committed",
                                        "stage": "verified", "revision": self.evidence["states"][0], "error": None})
            journal.observe(self.request, self.evidence)
            journal.accept(self.request)
        with Journal(self.path) as journal:
            self.assertEqual(len(journal.accepted), 1)

    def test_exclusive_lock_and_no_overwrite(self):
        with Journal(self.path, self.manifest) as journal:
            with self.assertRaises(BlockingIOError):
                Journal(self.path)
            journal.intent(self.request)
            raw = (self.path / Journal.name("intent", self.request)).read_bytes()
            with self.assertRaises(JournalError):
                journal.intent(self.request)
            self.assertEqual((self.path / Journal.name("intent", self.request)).read_bytes(), raw)

    def test_aliases_damage_and_unknown_records_are_rejected(self):
        with Journal(self.path, self.manifest):
            pass
        os.link(self.path / "manifest.json", self.path.parent / "alias")
        with self.assertRaisesRegex(JournalError, "aliased"):
            Journal(self.path)
        (self.path.parent / "alias").unlink()
        (self.path / "unknown").write_text("not accepted")
        with self.assertRaisesRegex(JournalError, "Unknown"):
            Journal(self.path)
        (self.path / "unknown").unlink()
        (self.path / "manifest.json").write_bytes(b'{"bad":true}')
        with self.assertRaises(JournalError):
            Journal(self.path)

    def test_process_crashes_at_each_publication_edge_never_invent_progress(self):
        for edge in ("written", "file-synced", "published", "unlinked", "directory-synced"):
            path = self.path.parent / edge
            with Journal(path, self.manifest):
                pass
            process = multiprocessing.get_context("fork").Process(
                target=crash_writer, args=(path, self.request, edge))
            process.start()
            process.join(10)
            self.assertEqual(process.exitcode, 91)
            if edge in ("written", "file-synced", "published"):
                with self.assertRaisesRegex(JournalError, "Unknown|aliased"):
                    Journal(path)
            else:
                with Journal(path) as journal:
                    self.assertEqual(len(journal.accepted), 0)
                    self.assertIn(Journal.name("intent", self.request), journal.records)


if __name__ == "__main__":
    unittest.main()
