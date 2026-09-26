"""Synthetic/offline controls, never substitutes for measured MediaWiki evidence."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import smoke_deploy as checks
from build_wiki import build_pages, build_xml
from smoke_incremental import (
    DEFAULT_POLICY, IncrementalRehearsal, archive_source, catalog_pins, coverage, default_approval,
    default_blocks, default_registry, default_source_contracts, digest, incremental_order,
    load_incremental_inputs, pinned_bytes, reviewed_drift, source_pin,
    validate_native_plan, validate_owned, validate_prefix_guard, verify_native_completion,
)
from smoke_native import HISTORICAL_OPERATIONS, HISTORICAL_PRESERVED, NativeSmoke, require_historical_coverage
from smoke_prefix import PendingConsumerUpdate, Rehearsal, materialize_desired
from plan_migration import read_snapshot
from publication_journal import Journal, JournalError
from wiki_details import load_publication_inputs
from wiki_views import available_views, selective_view, transclusions


ROOT = Path(__file__).resolve().parents[1]


def metadata(pages):
    return {title: {"title": title, "pageid": index, "revid": index, "parentid": 0,
                    "raw_sha256": hashlib.sha256(text.encode()).hexdigest()}
            for index, (title, text) in enumerate(sorted(pages.items()), 1)}


def small_rehearsal():
    baseline = {"Owner": selective_view("Old", "stock"), "Consumer": "Before {{:Owner|view=stock}}", "Keep": "Keep"}
    desired = {**baseline, "Owner": selective_view("New", "stock"), "Consumer": "After {{:Owner|view=stock}}", "Create": "New"}
    return SimpleNamespace(baseline=baseline, desired=desired, order=incremental_order(baseline, desired),
                           metadata=metadata(baseline), binding={"input_sha256": "a" * 64}, incremental=True)


def plan(rehearsal):
    current = dict(rehearsal.baseline)
    operations = []
    for index, title in enumerate(rehearsal.order, 1):
        before = rehearsal.metadata.get(title)
        expected = ({"page_id": before["pageid"], "revision_id": before["revid"], "raw_sha256": before["raw_sha256"]}
                    if before else {"page_id": 0, "revision_id": 0, "raw_sha256": None})
        prerequisites = [{"namespace": 14 if owner.startswith("Category:") else 0, "title": owner,
                          "raw_sha256": hashlib.sha256(current[owner].encode()).hexdigest()}
                         for owner in sorted({owner for owner, _ in transclusions(rehearsal.desired[title])})]
        operations.append(NativeSmoke.operation(index, title, expected, rehearsal.desired[title], prerequisites))
        current[title] = rehearsal.desired[title]
    preserved = [{"namespace": 14 if title.startswith("Category:") else 0, "title": title,
                  "page_id": row["pageid"], "revision_id": row["revid"],
                  "raw_sha256": row["raw_sha256"]} for title, row in sorted(rehearsal.metadata.items())
                 if title not in rehearsal.order]
    return operations, preserved


class IncrementalInputsTests(unittest.TestCase):
    def test_real_pinned_source_generators_and_catalogs_roundtrip(self):
        """Synthetic B, actual Git source/generators; no MediaWiki/production claim."""
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            root = directory / "checkout"
            subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(root)], check=True)
            previous_head = "899a3f20a00aea7ca35a80aa49c0b6247e8c7a57"
            previous_source = directory / "previous"
            archive_source(root, previous_head, previous_source)
            a0_path = directory / "a0.xml"
            subprocess.run([sys.executable, str(previous_source / "tools" / "build_wiki.py"),
                            "--fresh", "--output", str(a0_path)], check=True, stdout=subprocess.PIPE)
            previous = read_snapshot(a0_path)
            baseline = {title: text.rstrip("\r\n") for title, text in previous.items()}
            authored = build_pages(root, *load_publication_inputs(root))
            (directory / "b.xml").write_bytes(build_xml(baseline))
            (directory / "a1.xml").write_bytes(build_xml(authored))
            (directory / "provenance.json").write_text('{"kind":"synthetic-unit-fixture"}')
            def pin(name):
                raw = (directory / name).read_bytes()
                return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            def git(expression):
                return subprocess.check_output(["git", "rev-parse", expression], cwd=root, text=True).strip()
            binding = {
                "schema_version": 1, "kind": "disposable-incremental-inputs",
                "previous_source": {"head_sha": previous_head, "tree_sha": git(previous_head + "^{tree}")},
                "candidate_source": {"head_sha": git("HEAD"), "tree_sha": git("HEAD^{tree}")},
                "previous_authored": pin("a0.xml"), "baseline": pin("b.xml"), "authored": pin("a1.xml"),
                "provenance": pin("provenance.json"), "owned_titles": sorted(previous), "community_titles": ["Community page"],
                "reviewed_drift_sha256": digest(reviewed_drift(previous, baseline)),
                "catalog_inputs": {"previous": catalog_pins(previous_source), "candidate": catalog_pins(root)},
            }
            path = directory / "inputs.json"
            path.write_text(json.dumps(binding))
            workspace = directory / "positive"
            workspace.mkdir()
            pages, payloads, previous_inputs, public = load_incremental_inputs(root, workspace, path)
            self.assertEqual(pages, {"previous_authored": previous, "baseline": baseline, "authored": authored})
            self.assertNotIn("path", public["baseline"])
            self.assertTrue(any(isinstance(row["value"], Decimal) for row in previous_inputs[1]["unit_prices"]["prices"]))
            for field in ("catalog_inputs", "authored", "previous_authored"):
                changed = copy.deepcopy(binding)
                if field == "catalog_inputs":
                    changed[field]["previous"]["catalog.json"] = "0" * 64
                else:
                    altered = dict(pages[field], **{"Main Page": "Rebound but wrong source"})
                    name = "wrong-" + field + ".xml"
                    (directory / name).write_bytes(build_xml(altered))
                    changed[field] = pin(name)
                    if field == "previous_authored":
                        changed["reviewed_drift_sha256"] = digest(reviewed_drift(altered, baseline))
                path.write_text(json.dumps(changed))
                workspace = directory / field
                workspace.mkdir()
                with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "source|catalog"):
                    load_incremental_inputs(root, workspace, path)

    def test_owned_projection_drift_and_community_are_explicit(self):
        previous = {"Owned": "Source\n"}
        baseline = {"Owned": "Exact stored"}
        authored = {**previous, "Create": "New"}
        arguments = (previous, baseline, authored, ["Owned"], ["Community"], digest(reviewed_drift(previous, baseline)))
        validate_owned(*arguments)
        for position, value in ((1, {}), (1, {**baseline, "Unknown": "Collision"}), (2, {}),
                                (3, []), (3, ["Owned", "Owned"]), (4, ["Create"]), (4, ["Owned"]), (4, [""]), (5, "0" * 64)):
            changed = list(arguments)
            changed[position] = value
            with self.subTest(position=position, value=value), self.assertRaises(RuntimeError):
                validate_owned(*changed)

    def test_pinned_file_rejects_hash_size_and_unsupported_shapes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private.json"
            path.write_bytes(b"{}")
            pin = {"path": path.name, "bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}
            self.assertEqual(pinned_bytes(path.parent, pin)[1], b"{}")
            for bad in ({**pin, "sha256": "0" * 64}, {**pin, "bytes": 3}, {**pin, "bytes": True},
                        {**pin, "extra": 1}, {**pin, "path": "absent.json"}):
                with self.assertRaises(RuntimeError):
                    pinned_bytes(path.parent, bad)

    def test_wrong_source_tree_and_head_reject_before_runtime(self):
        pin = {"head_sha": "a" * 40, "tree_sha": "b" * 40}
        with patch("smoke_incremental.subprocess.check_output", side_effect=["commit", "c" * 40]):
            with self.assertRaisesRegex(RuntimeError, "tree pin"):
                source_pin(ROOT, pin)
        with patch("smoke_incremental.subprocess.check_output", side_effect=["commit", "b" * 40, "c" * 40]):
            with self.assertRaisesRegex(RuntimeError, "executing checkout"):
                source_pin(ROOT, pin, current=True)
        with self.assertRaises(RuntimeError):
            source_pin(ROOT, {**pin, "head_sha": "main"})
        for kind in ("tree", "tag"):
            with patch("smoke_incremental.subprocess.check_output", return_value=kind), self.assertRaisesRegex(RuntimeError, "not a commit"):
                source_pin(ROOT, pin)

    def test_input_shape_is_closed_and_no_docker_is_started(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "inputs.json"
            path.write_text('{"schema_version":1,"kind":"disposable-incremental-inputs"}')
            with self.assertRaisesRegex(RuntimeError, "shape"):
                load_incremental_inputs(ROOT, Path(folder), path)
            path.write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaises(ValueError):
                load_incremental_inputs(ROOT, Path(folder), path)

    def test_changed_set_only_none_of_the_old_nine_is_forced(self):
        rehearsal = small_rehearsal()
        self.assertEqual(rehearsal.order, ["Create", "Owner", "Consumer"])
        result = coverage(rehearsal.baseline, rehearsal.desired, rehearsal.order)
        self.assertEqual(result["counts"], {"create": 1, "update": 2, "preserved": 1})
        self.assertEqual((result["operations"], result["prefixes"]), (3, 4))
        self.assertEqual(incremental_order(rehearsal.baseline, rehearsal.baseline), [])
        for bad in (rehearsal.order[:-1], rehearsal.order + ["Owner"], list(reversed(rehearsal.order))):
            with self.assertRaisesRegex(RuntimeError, "omitted, resent or reordered"):
                coverage(rehearsal.baseline, rehearsal.desired, bad)

    def test_missing_view_cycle_deletion_and_dynamic_edges_fail(self):
        baseline = {"Owner": selective_view("Old", "stock"), "Consumer": "{{:Owner|view=stock}}"}
        for desired in (
            {**baseline, "Owner": "No view"},
            {**baseline, "Consumer": "{{:Missing|view=stock}}"},
            {**baseline, "Consumer": "{{:Owner|view=missing}}"},
            {"Owner": baseline["Owner"]},
            {**baseline, "Consumer": "{{:Owner|view={{{dynamic}}}}}"},
            {"Owner": selective_view("New", "stock") + "{{:Consumer|view=stock}}",
             "Consumer": selective_view("New", "stock") + "{{:Owner|view=stock}}"},
        ):
            with self.subTest(desired=desired), self.assertRaises((RuntimeError, ValueError)):
                incremental_order(baseline, desired)

    def test_storage_noop_and_source_unchanged_preserve_exact_B_without_pst(self):
        previous = {"Unchanged": "Authored\n", "Noop": "Old\n"}
        baseline = {"Unchanged": "Observed stored body", "Noop": "New"}
        authored = {"Unchanged": "Authored\n", "Noop": "New\n"}
        called = []
        def api(query, **kwargs):
            called.append(query["title"])
            return {"parse": {"text": {"*": query["text"].rstrip("\r\n")}}}
        desired, receipt = materialize_desired(api, previous, baseline, authored, "a" * 40, {}, {"name": "Synthetic"},
                                             previous_source_head="b" * 40, evidence_kind="synthetic-unit-fixture")
        self.assertEqual(called, ["Noop"])
        self.assertEqual(desired, baseline)
        self.assertEqual(incremental_order(baseline, desired), [])
        self.assertEqual([row["classification"] for row in receipt["pages"]], ["storage-noop", "unchanged"])


class IncrementalDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, *cls.inputs)

    def test_all_45_current_defaults_and_exact_decimals(self):
        registry = default_registry(self.pages, self.pages, self.inputs, self.inputs)
        self.assertEqual(len(registry["prices"]), 42)
        self.assertEqual(len(registry["coins"]), 3)
        self.assertTrue(any(isinstance(row["value"], Decimal) for row in registry["prices"].values()))
        prices = {row["entity"]: row["value"] for row in self.inputs[1]["unit_prices"]["prices"]}
        for identity, value in (("item-32", "0.6"), ("item-84", "0.3"), ("item-138", "1.5"),
                                ("item-139", "1"), ("item-140", "0.25"), ("item-248", "1")):
            self.assertEqual(prices[identity], Decimal(value))

    def test_omitted_or_changed_former_six_defaults_reject(self):
        for identity in ("item-32", "item-84", "item-138", "item-139", "item-140", "item-248"):
            for remove in (True, False):
                current = copy.deepcopy(self.inputs)
                prices = current[1]["unit_prices"]["prices"]
                row = next(row for row in prices if row["entity"] == identity)
                if remove:
                    prices.remove(row)
                else:
                    row["value"] = Decimal("999")
                with self.subTest(identity=identity, remove=remove), self.assertRaisesRegex(RuntimeError, "registry"):
                    default_registry(self.pages, self.pages, self.inputs, current)

    def test_unregistered_or_unresolved_default_reject(self):
        for changes in ({"Consumer": "{{:Unknown}}", "Unknown": "<onlyinclude>0</onlyinclude>"},
                        {"Copper Coin": "No default"}):
            with self.assertRaises(RuntimeError):
                default_registry(self.pages, {**self.pages, **changes}, self.inputs, self.inputs)

    def test_all_default_endpoints_include_owners_without_consumers(self):
        rehearsal = IncrementalRehearsal.__new__(IncrementalRehearsal)
        rehearsal.registry = default_registry(self.pages, self.pages, self.inputs, self.inputs)
        rehearsal.default_endpoints = {}
        calls = []
        rehearsal.probe = lambda consumer, owner, arguments, fresh=False: calls.append((consumer, owner, fresh)) or {"id": len(calls)}
        rehearsal.capture_defaults("baseline")
        rehearsal.capture_defaults("desired")
        self.assertEqual(len(calls), 90)
        self.assertTrue(all(row[0] == "Prefix projection" and row[2] for row in calls))

    def test_current_prices_cannot_revert_to_not_established(self):
        rehearsal = IncrementalRehearsal(None, checks, self.pages, self.pages, *self.inputs[:2],
                                        self.inputs[1], {}, "a" * 40,
                                        previous_inputs=self.inputs, binding={"input_sha256": "a" * 64})
        for identity in ("item-32", "item-84", "item-138", "item-139", "item-140", "item-248"):
            owner = rehearsal.locations[identity]
            with self.assertRaises(RuntimeError):
                rehearsal.validate_projection(owner, {}, {"text": {"*": "<p>Not established</p>"},
                                                          "templates": [{"*": owner}]})

    def default_html(self, rehearsal, owner):
        identity = rehearsal.entities[owner]
        if identity in rehearsal.coins:
            coin = rehearsal.coins[identity]
            cells = [f'<span id="coin-{identity}"></span><a href="?title={owner}">{owner}</a>',
                     checks.scalar(coin["value_in_silver"]), checks.scalar(coin["weight_grams"]) + " g", str(coin["stack_limit"])]
            headers = ["Coin", "Value in silver", "Weight", "Maximum stack"]
            return "<table><tr>" + " ".join("<th>" + value + "</th>" for value in headers) + "</tr> <tr>" + " ".join(
                "<td>" + value + "</td>" for value in cells) + "</tr></table>"
        remainder = int(rehearsal.prices[identity] * 100)
        pieces = []
        for unit, value, image in (("gold", 1000, 74), ("silver", 100, 73), ("copper", 1, 72)):
            count, remainder = divmod(remainder, value)
            if count:
                pieces.append(f'<img src="/images/20px-Item-{image}.png" alt="{unit.capitalize()} coin" width="20" height="20"> {count} {unit}')
        return "<p>" + (" ".join(pieces) or "0 copper") + "</p>"

    def test_all_45_defaults_match_measured_B_expansion_and_dom_despite_new_owner_revisions(self):
        registry = default_registry(self.pages, self.pages, self.inputs, self.inputs)
        default_owners = registry["prices"].keys() | registry["coins"].keys()
        baseline = {title: text + ("\nBaseline body" if title in default_owners else "") for title, text in self.pages.items()}
        rehearsal = IncrementalRehearsal(None, checks, baseline, self.pages, *self.inputs[:2],
                                        self.inputs[1], {}, "a" * 40,
                                        previous_inputs=self.inputs, binding={"input_sha256": "a" * 64})
        rehearsal.metadata = metadata(baseline)
        rehearsal.baseline_contracts = {}
        payloads = {}
        owners = sorted(rehearsal.registry["prices"].keys() | rehearsal.registry["coins"].keys())
        for owner in owners:
            html = self.default_html(rehearsal, owner)
            payloads[owner] = {"expanded": "Synthetic measured B " + owner, "html": html}
            rehearsal.baseline_contracts[(owner, (), "Prefix projection")] = {
                "owner": dict(rehearsal.metadata[owner]), "expanded_wikitext": payloads[owner]["expanded"], "html": html}
            rehearsal.current[owner] = rehearsal.desired[owner]
            rehearsal.metadata[owner] = {**rehearsal.metadata[owner], "revid": rehearsal.metadata[owner]["revid"] + 1000,
                                         "raw_sha256": hashlib.sha256(rehearsal.current[owner].encode()).hexdigest()}
        def api(query, **kwargs):
            owner = query["text"].removeprefix("{{:").removesuffix("}}")
            if query["action"] == "expandtemplates":
                return {"expandtemplates": {"wikitext": payloads[owner]["expanded"]}}
            return {"parse": {"text": {"*": payloads[owner]["html"]}, "templates": [{"*": owner}]}}
        rehearsal.api = api
        rehearsal.capture_defaults("desired")
        self.assertEqual(len(rehearsal.default_endpoints["desired"]), 45)
        owner = "Antidote"
        original = dict(payloads[owner])
        for field, value in (
            ("expanded", original["expanded"] + " changed"),
            ("html", original["html"] + '<img src="/images/leaked-article.png">'),
            ("html", original["html"] + '<a href="?title=File:Leaked.png"><img src="/images/leaked-article.png"></a>'),
            ("html", original["html"] + '<a href="?title=File:Leaked.png"></a>'),
            ("html", original["html"] + '<a href="https://example.invalid/"></a>'),
        ):
            payloads[owner] = {**original, field: value}
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                rehearsal.probe("Prefix projection", owner, (), fresh=True)
        coin = rehearsal.locations[next(iter(rehearsal.coins))]
        payloads[coin]["html"] += '<img src="/images/leaked-article.png">'
        with self.assertRaisesRegex(RuntimeError, "coin leaked"):
            rehearsal.probe("Prefix projection", coin, (), fresh=True)


class IncrementalProjectionTests(unittest.TestCase):
    def test_mixed_prefix_run_observes_unchanged_B_consumer_and_no_compatibility_trace(self):
        rehearsal, _ = self.fixture()
        rehearsal.order = ["Owner"]
        rehearsal.base_meta = copy.deepcopy(rehearsal.metadata)
        rehearsal.provenance = {}
        rehearsal.prefixes, rehearsal.default_prefixes, rehearsal.settling = [], [], []
        rehearsal.default_endpoints = {}
        rehearsal.binding = {"input_sha256": "a" * 64}
        saved = []
        def save(title, records, text, probes):
            saved.append(title)
            rehearsal.metadata[title] = {**records[title], "revid": 99, "parentid": records[title]["revid"],
                                         "raw_sha256": hashlib.sha256(text.encode()).hexdigest()}
            return 99
        rehearsal.run(save, lambda api: None, lambda **kwargs: None, lambda **kwargs: None,
                      lambda *args: self.fail("Final acceptance must wait for endpoint/reader guards."))
        self.assertEqual(saved, ["Owner"])
        self.assertEqual(len(rehearsal.prefixes), 2)
        consumer = next(row for row in rehearsal.prefixes[1]["observations"] if row["consumer"]["title"] == "Consumer")
        self.assertEqual(consumer["consumer"], rehearsal.base_meta["Consumer"])
        self.assertEqual(rehearsal.probes[consumer["probe_ids"][0]]["kind"], "desired-leaf-projection")
        artifacts = rehearsal.artifacts()
        self.assertNotIn("price-compatibility-receipt.json", artifacts)
        self.assertNotIn("price_prefix", rehearsal.pending_final_guard)
        self.assertTrue(artifacts["consumer-html.json"])
        rehearsal.baseline = dict(rehearsal.current)
        rehearsal.base_meta = copy.deepcopy(rehearsal.metadata)
        rehearsal.order, rehearsal.prefixes, rehearsal.probes, rehearsal.default_prefixes = [], [], [], []
        rehearsal.cache = {}
        rehearsal.run(lambda *args: self.fail("No-op saved a revision."), lambda api: None,
                      lambda **kwargs: None, lambda **kwargs: None, lambda *args: self.fail("No-op accepted an operation."))
        proof = rehearsal.artifacts()["full-prefix-proof.json"]
        self.assertEqual(proof["incremental"]["outcome"], "no-publication")
        self.assertEqual(proof["order"], [])
        self.assertEqual(len(proof["prefixes"]), 1)
        self.assertIsNone(proof["prefixes"][0]["saved"])
        self.assertEqual(proof["baseline_revisions"], proof["desired_revisions"])

    def test_actual_owner_state_selects_legacy_B_or_compact_D_pool_checker(self):
        rehearsal = IncrementalRehearsal.__new__(IncrementalRehearsal)
        pool = {"id": "test", "title": "Test pool", "eligible_item_ids": ["item-1"], "item_conditions": {}}
        rehearsal.current, rehearsal.baseline, rehearsal.desired = {"Owner": "B"}, {"Owner": "B"}, {"Owner": "D"}
        rehearsal.checks, rehearsal.entities = checks, {}
        rehearsal.pools, rehearsal.locations, rehearsal.catalog = {"test": pool}, {"item-1": "Item"}, {}
        rehearsal.baseline_checker = copy.copy(rehearsal)
        old = ('<table><tr><th>Item</th><th>Quantity</th><th>Per-item probability</th><th>Eligibility</th></tr>'
               '<tr><td><span id="pool-item-test-item-1"></span><a href="?title=Item">Item</a></td>'
               '<td>Budget-dependent</td><td>Not established</td><td>Eligible, not guaranteed.</td></tr></table>')
        new = '<span id="pool-item-test-item-1"></span><a href="?title=Owner#pool-test">Test pool</a> (eligible)'
        result = lambda html: {"text": {"*": html}, "templates": [{"*": "Owner"}]}
        parameters = {"view": "pool", "pool": "test", "item": "item-1"}
        rehearsal.validate_projection("Owner", parameters, result(old), "Consumer")
        with self.assertRaises(RuntimeError):
            rehearsal.validate_projection("Owner", parameters, result(new), "Consumer")
        rehearsal.current["Owner"] = "D"
        rehearsal.validate_projection("Owner", parameters, result(new), "Consumer")
        with self.assertRaises(RuntimeError):
            rehearsal.validate_projection("Owner", parameters, result(old), "Consumer")

    def fixture(self, old="Old", new="New"):
        rehearsal = IncrementalRehearsal.__new__(IncrementalRehearsal)
        rehearsal.incremental = True
        rehearsal.baseline = {"Owner": selective_view(old, "stock"), "Consumer": "{{:Owner|view=stock}}"}
        rehearsal.current = dict(rehearsal.baseline)
        rehearsal.desired = {**rehearsal.current, "Owner": selective_view(new, "stock")}
        rehearsal.metadata = metadata(rehearsal.current)
        rehearsal.cache, rehearsal.probes, rehearsal.link_candidates = {}, [], {}
        rehearsal.registry = {"prices": {}, "coins": {}}
        rehearsal.catalog, rehearsal.locations = {"currency": {}}, {}
        rehearsal.default_sources, rehearsal.used_baseline_defaults = {}, []
        rehearsal.context_previews, rehearsal.context_cache, rehearsal.context_checks = [], {}, {}
        rehearsal.checks = checks
        rehearsal.validate_projection = lambda *args: None
        rehearsal.refresh_metadata = lambda: None
        rehearsal.consumer_html = {}
        rehearsal.check_merchant_rows = lambda *args: None
        calls = []
        def api(query, **kwargs):
            calls.append(query)
            if query["action"] == "query":
                return {"query": {"userinfo": {"id": 1, "name": "Synthetic"}}}
            value = old if rehearsal.current["Owner"] == rehearsal.baseline["Owner"] else new
            if query["action"] == "expandtemplates":
                return {"expandtemplates": {"wikitext": value}}
            text = query.get("text")
            if text is None:
                text = rehearsal.current[query["page"]]
            includes = "{{:Owner" in text
            result = {"text": {"*": "<p>" + (value if includes else text) + "</p>"},
                      "templates": [{"*": "Owner"}] if includes else [], "links": []}
            if "page" in query:
                result["revid"] = rehearsal.metadata[query["page"]]["revid"]
            return {"parse": result}
        rehearsal.api = api
        return rehearsal, calls

    def test_baseline_named_views_require_measured_context_contracts(self):
        rehearsal, calls = self.fixture()
        arguments = (("view", "stock"),)
        rehearsal.baseline_contracts = {}
        with self.assertRaisesRegex(RuntimeError, "Missing measured"):
            rehearsal.probe("Consumer", "Owner", arguments)
        rehearsal.capture_link_endpoint("baseline")
        probe = rehearsal.probe("Consumer", "Owner", arguments)
        self.assertEqual(probe["kind"], "baseline-leaf-projection")
        self.assertEqual(probe["parse_title"], "Consumer")
        self.assertEqual(probe["owner"], rehearsal.metadata["Owner"])
        before = len(calls)
        self.assertEqual(rehearsal.probe("Consumer", "Owner", arguments), probe)
        self.assertEqual(len(calls), before)
        with self.assertRaisesRegex(RuntimeError, "Missing measured"):
            rehearsal.probe("Unknown context", "Owner", arguments)

    def test_revision_raw_context_cache_is_not_reused_after_owner_change(self):
        rehearsal, calls = self.fixture()
        rehearsal.capture_link_endpoint("baseline")
        arguments = (("view", "stock"),)
        baseline = rehearsal.probe("Consumer", "Owner", arguments)
        rehearsal.current["Owner"] = rehearsal.desired["Owner"]
        rehearsal.metadata["Owner"] = {**rehearsal.metadata["Owner"], "revid": 99,
                                       "raw_sha256": hashlib.sha256(rehearsal.current["Owner"].encode()).hexdigest()}
        desired = rehearsal.probe("Consumer", "Owner", arguments)
        self.assertNotEqual(baseline["id"], desired["id"])
        self.assertEqual(desired["kind"], "desired-leaf-projection")
        self.assertEqual(desired["expanded_wikitext"], "New")
        self.assertEqual(rehearsal.current["Consumer"], rehearsal.baseline["Consumer"])
        self.assertEqual(rehearsal.inspect_consumer("Consumer")["probe_ids"], [desired["id"]])

    def test_baseline_contract_html_and_revision_drift_reject(self):
        for field in ("html", "owner"):
            rehearsal, _ = self.fixture()
            rehearsal.capture_link_endpoint("baseline")
            contract = rehearsal.baseline_contracts[("Owner", (("view", "stock"),), "Consumer")]
            if field == "html":
                contract["html"] = "<p>Invented</p>"
            else:
                contract["owner"] = {**contract["owner"], "revid": 999}
            with self.assertRaisesRegex(RuntimeError, "drifted"):
                rehearsal.probe("Consumer", "Owner", (("view", "stock"),))

    def test_endpoint_context_discrepancies_fail_closed(self):
        rehearsal, _ = self.fixture()
        api = rehearsal.api
        def changed(query, **kwargs):
            result = api(query, **kwargs)
            if query["action"] == "expandtemplates" and query["title"] == "Consumer":
                result["expandtemplates"]["wikitext"] = "Wrong context"
            return result
        rehearsal.api = changed
        with self.assertRaisesRegex(RuntimeError, "context discrepancies"):
            rehearsal.capture_link_endpoint("baseline")

    def test_missing_or_stale_full_consumer_context_rejects(self):
        rehearsal, _ = self.fixture()
        rehearsal.capture_link_endpoint("baseline")
        api = rehearsal.api
        def stale(query, **kwargs):
            result = api(query, **kwargs)
            if query.get("page") == "Consumer":
                result["parse"]["text"]["*"] = "<p>Missing source context</p>"
            return result
        rehearsal.api = stale
        with self.assertRaisesRegex(RuntimeError, "omitted"):
            rehearsal.inspect_consumer("Consumer")

    def test_shorter_stock_rule_settles_B_consumer_or_fails_bounded_with_diagnostics(self):
        previous_catalog = json.loads(subprocess.check_output(
            ["git", "show", "899a3f20a00aea7ca35a80aa49c0b6247e8c7a57:content/facts/catalog.json"], cwd=ROOT))
        old = next(row["text"] for row in previous_catalog["currency"]["rules"]
                   if row["id"] == "trade-stock-and-funds")
        new = "Listed wares do not run out, and merchants have unlimited buying funds."
        for stale_reads in (2, 100):
            rehearsal, _ = self.fixture(old=old, new=new)
            rehearsal.capture_link_endpoint("baseline")
            rehearsal.current["Owner"] = rehearsal.desired["Owner"]
            rehearsal.metadata["Owner"] = {**rehearsal.metadata["Owner"], "revid": 99,
                                           "raw_sha256": hashlib.sha256(rehearsal.current["Owner"].encode()).hexdigest()}
            rehearsal.prefixes, rehearsal.settling = [], []
            rehearsal.checks = SimpleNamespace(check_parser_errors=checks.check_parser_errors,
                                                wait_for_server_tick=lambda *args, **kwargs: None)
            api, reads, drains, diagnostics = rehearsal.api, [], [], []
            def cached(query, **kwargs):
                if query.get("curtimestamp"):
                    return {"curtimestamp": "2000-01-01T00:00:00Z", "query": {"pages": {}}}
                result = api(query, **kwargs)
                if query.get("page") == "Consumer":
                    reads.append(True)
                    if len(reads) <= stale_reads:
                        result["parse"]["text"]["*"] = "<p>" + old + "</p>"
                return result
            rehearsal.api = cached
            with patch("smoke_prefix.time.sleep"):
                if stale_reads == 2:
                    records = rehearsal.observe_consumers({"Consumer"}, lambda **kwargs: drains.append(True))
                    self.assertEqual(records[0]["consumer"], rehearsal.metadata["Consumer"])
                    self.assertEqual(len(drains), 2)
                    self.assertEqual(rehearsal.settling[-1]["status"], "settled")
                else:
                    with self.assertRaises(PendingConsumerUpdate):
                        rehearsal.observe_consumers({"Consumer"}, lambda **kwargs: drains.append(True),
                                                    lambda **kwargs: diagnostics.append(kwargs) or "0")
                    self.assertEqual(len(drains), 9)
                    self.assertEqual(len(diagnostics), 1)
                    self.assertEqual(rehearsal.settling[-1]["status"], "failed")
            pending = rehearsal.settling[0]
            self.assertEqual(pending["details"]["expected_text"], new)
            self.assertEqual(pending["html"], "<p>" + old + "</p>")


class ClosedDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, *cls.inputs)
        cls.baseline = {**cls.pages, "Antidote": cls.pages["Antidote"] + "\nOld item article",
                        "Gurb-Gurb": cls.pages["Gurb-Gurb"] + "\nOld merchant article"}
        cls.registry = default_registry(cls.baseline, cls.pages, cls.inputs, cls.inputs)
        cls.sources = default_source_contracts(cls.pages, cls.baseline, cls.pages, cls.registry)
        cls.binding = {"input_sha256": "a" * 64, "default_readiness": {
            "schema_version": 1, "policy": DEFAULT_POLICY, "source_contracts_sha256": digest(cls.sources)}}

    def rehearsal(self, binding=None, desired=None):
        return IncrementalRehearsal(None, checks, self.baseline, desired or self.pages, *self.inputs[:2],
                                    self.inputs[1], {}, "a" * 40, previous_inputs=self.inputs,
                                    binding=binding or self.binding, previous_authored=self.pages)

    def test_real_merchant_price_cycle_requires_exact_explicit_closed_approval(self):
        with self.assertRaisesRegex(RuntimeError, "cycle"):
            self.rehearsal({"input_sha256": "a" * 64})
        rehearsal = self.rehearsal()
        self.assertEqual(rehearsal.order, ["Gurb-Gurb", "Antidote"])
        rehearsal.metadata = metadata(rehearsal.baseline)
        operations, preserved = plan(rehearsal)
        validate_native_plan(rehearsal, operations, preserved)
        price = next(row for row in operations[0]["prerequisites"] if row["title"] == "Antidote")
        self.assertEqual(price["raw_sha256"], hashlib.sha256(self.baseline["Antidote"].encode()).hexdigest())
        self.assertNotEqual(price["raw_sha256"], hashlib.sha256(self.pages["Antidote"].encode()).hexdigest())
        bad_operations = copy.deepcopy(operations)
        next(row for row in bad_operations[0]["prerequisites"] if row["title"] == "Antidote")["raw_sha256"] = hashlib.sha256(
            self.pages["Antidote"].encode()).hexdigest()
        bad_operations[0]["prerequisites_sha256"] = digest(bad_operations[0]["prerequisites"])
        with self.assertRaisesRegex(RuntimeError, "CAS/prerequisite"):
            validate_native_plan(rehearsal, bad_operations, preserved)
        seller = next(row for row in operations[1]["prerequisites"] if row["title"] == "Gurb-Gurb")
        self.assertEqual(seller["raw_sha256"], hashlib.sha256(self.pages["Gurb-Gurb"].encode()).hexdigest())
        bad = copy.deepcopy(self.binding)
        bad["default_readiness"]["source_contracts_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "approval digest"):
            self.rehearsal(bad)

    def test_named_or_parameterized_default_edges_never_use_B_readiness(self):
        for arguments in ("view=price", "view=", "extra=ignored"):
            desired = {**self.pages, "Gurb-Gurb": self.pages["Gurb-Gurb"].replace(
                "{{:Antidote}}", "{{:Antidote|" + arguments + "}}")}
            self.assertNotEqual(desired["Gurb-Gurb"], self.pages["Gurb-Gurb"])
            with self.subTest(arguments=arguments), self.assertRaisesRegex(RuntimeError, "cycle"):
                self.rehearsal(desired=desired)

    def test_closed_shape_rejects_mutable_magic_hidden_tags_and_dependencies(self):
        block = next(block for block in default_blocks(self.pages["Antidote"], "prices") if "" in available_views(block))
        for insertion in ("{{REVISIONID}}", "{{CURRENTTIMESTAMP}}", "{{:Other}}", "{{Other}}",
                          "{{{{{item|Other}}}}}", "{{{unreviewed|Other}}}"):
            changed = block.replace("|#default=}}", insertion + "|#default=}}", 1)
            with self.subTest(insertion=insertion), self.assertRaises(RuntimeError):
                default_blocks(changed, "prices")
            bad = {**self.pages, "Antidote": self.pages["Antidote"].replace(block, changed)}
            with self.assertRaises(RuntimeError):
                default_source_contracts(bad, bad, bad, self.registry)
        for invalid in ("<nowiki>" + block + "</nowiki>", "<noinclude>" + block + "</noinclude>",
                        "<NOINCLUDE>" + block + "</NOINCLUDE>", "<noinclude class='x'>" + block + "</noinclude>",
                        "<!--" + block + "-->", block + block, block.replace("</onlyinclude>", "")):
            with self.assertRaises(RuntimeError):
                default_blocks(invalid, "prices")
        changed = {**self.pages, "Antidote": self.pages["Antidote"].replace(block, block.replace("silver", "SILVER"))}
        with self.assertRaisesRegex(RuntimeError, "sources differ"):
            default_source_contracts(self.pages, changed, changed, self.registry)
        with self.assertRaisesRegex(RuntimeError, "reproduced"):
            default_source_contracts(None, self.baseline, self.pages, self.registry)

    def test_source_approval_never_replaces_fresh_measured_B_context(self):
        rehearsal = self.rehearsal()
        rehearsal.metadata = metadata(rehearsal.baseline)
        html = '<p><img src="/images/20px-Item-73.png" alt="Silver coin" width="20" height="20"> 1 silver</p>'
        def api(query, **kwargs):
            if query["action"] == "expandtemplates":
                return {"expandtemplates": {"wikitext": "Synthetic B expansion"}}
            return {"parse": {"text": {"*": html}, "templates": [{"*": "Antidote"}]}}
        rehearsal.api = api
        original_html = html
        with self.assertRaisesRegex(RuntimeError, "Missing measured"):
            rehearsal.probe("Gurb-Gurb", "Antidote", (), fresh=True)
        rehearsal.baseline_contracts[("Antidote", (), "Gurb-Gurb")] = {
            "owner": dict(rehearsal.metadata["Antidote"]), "expanded_wikitext": "Synthetic B expansion", "html": html}
        probe = rehearsal.probe("Gurb-Gurb", "Antidote", (), fresh=True)
        from smoke_incremental import baseline_default_edges
        edge = baseline_default_edges(rehearsal, 1, "Gurb-Gurb", [probe])[0]
        self.assertEqual(edge["owner_revision"], rehearsal.metadata["Antidote"])
        self.assertEqual(edge["probe_id"], probe["id"])
        self.assertEqual(edge["parameters"], {})
        self.assertEqual(edge["transcludable_source_sha256"], self.sources["Antidote"]["transcludable_source_sha256"])
        html += '<a href="?title=Wrong"></a>'
        with self.assertRaises(RuntimeError):
            rehearsal.probe("Gurb-Gurb", "Antidote", (), fresh=True)
        html = original_html
        with self.assertRaisesRegex(RuntimeError, "Missing measured"):
            rehearsal.probe("Wrong context", "Antidote", (), fresh=True)

    def test_default_approval_schema_is_closed(self):
        self.assertIsNone(default_approval({}))
        self.assertEqual(default_approval(self.binding), self.binding["default_readiness"])
        for field, value in (("policy", "all-views"), ("schema_version", True),
                             ("source_contracts_sha256", "x"), ("extra", True)):
            bad = copy.deepcopy(self.binding)
            bad["default_readiness"][field] = value
            with self.assertRaises(RuntimeError):
                default_approval(bad)

    def test_missing_or_tampered_actual_B_edge_and_context_guards_reject(self):
        from smoke_incremental import baseline_default_edges, context_guards, context_key
        from smoke_prefix import linked_titles
        rehearsal = self.rehearsal()
        rehearsal.metadata = metadata(rehearsal.current)
        title = rehearsal.order[0]
        prerequisites = [{"id": index, "owner": dict(rehearsal.metadata[owner]), "parameters": dict(arguments),
                          "parse_title": title} for index, (owner, arguments) in enumerate(transclusions(self.pages[title]))]
        edges = baseline_default_edges(rehearsal, 1, title, prerequisites)
        self.assertEqual([row["owner"] for row in edges], ["Antidote"])
        rehearsal.current[title] = rehearsal.desired[title]
        rehearsal.metadata[title]["revid"] += 1000
        rehearsal.metadata[title]["raw_sha256"] = hashlib.sha256(rehearsal.current[title].encode()).hexdigest()
        rehearsal.probes = prerequisites[:]
        defaults = []
        for owner in sorted(self.registry["prices"].keys() | self.registry["coins"].keys()):
            defaults.append(len(rehearsal.probes))
            rehearsal.probes.append({"id": defaults[-1], "owner": rehearsal.metadata[owner],
                                     "parameters": {}, "parse_title": "Prefix projection"})
        rehearsal.default_prefixes = [[], defaults]
        affected = {title} | {consumer for consumer, text in rehearsal.current.items()
                              if title in {owner for owner, _ in transclusions(text)} or title in linked_titles(text)}
        observations = [{"consumer": dict(rehearsal.metadata[consumer]), "html_sha256": "e" * 64, "probe_ids": []}
                        for consumer in sorted(affected)]
        rehearsal.context_checks = {context_key(row): {**row, "direct_context_id": index}
                                    for index, row in enumerate(observations)}
        rehearsal.prefixes = [{"index": 0}, {"index": 1, "saved": rehearsal.metadata[title],
                              "prerequisites": [row["id"] for row in prerequisites], "observations": observations}]
        guard = {"prefix": rehearsal.prefixes[-1], "prerequisite_checks": prerequisites, "default_probe_ids": defaults,
                 "incremental_input_sha256": rehearsal.binding["input_sha256"], "baseline_default_edges": edges,
                 "offer_context_checks": context_guards(rehearsal, observations)}
        validate_prefix_guard(rehearsal, 1, guard)
        self.assertTrue(guard["offer_context_checks"])
        for key in ("baseline_default_edges", "offer_context_checks"):
            bad = copy.deepcopy(guard)
            del bad[key]
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "omitted"):
                validate_prefix_guard(rehearsal, 1, bad)
        bad = copy.deepcopy(guard)
        bad["baseline_default_edges"][0]["owner_revision"]["revid"] += 1
        with self.assertRaisesRegex(RuntimeError, "B-default"):
            validate_prefix_guard(rehearsal, 1, bad)


class OfferContextTests(unittest.TestCase):
    legacy_target = "Currency and trading#currency-trade-stock-and-funds"
    legacy_label = "Shared stock and merchant-funds rules"

    def test_selected_offer_context_uses_actual_B_or_D_owner_semantics(self):
        rehearsal = IncrementalRehearsal.__new__(IncrementalRehearsal)
        legacy = "<includeonly>[[" + self.legacy_target + "|" + self.legacy_label + "]]</includeonly>"
        modern = "<noinclude>[[:Category:Merchants#Trading_rules|Shared trading rules]]</noinclude>"
        rehearsal.baseline, rehearsal.desired = {"Owner": legacy}, {"Owner": modern}
        rehearsal.current = dict(rehearsal.baseline)
        rehearsal.checks, rehearsal.locations = checks, {"npc": "Owner"}
        rehearsal.catalog = {"currency": {"standard_merchants": ["npc"], "rules": [
            {"id": "trade-stock-and-funds", "text": "New stock rule."}]},
            "classifications": [{"entity": "npc", "location": {}}]}
        rehearsal.baseline_checker = SimpleNamespace(
            locations=rehearsal.locations, catalog={"currency": rehearsal.catalog["currency"], "classifications": []})
        old = f'<p><a href="?title={self.legacy_target}">{self.legacy_label}</a> Location: Not established.</p>'
        new = '<p>Location: <a href="?title=Owner#Location_and_access">Location and access</a>.</p>'
        rehearsal.validate_offer_context("Owner", old, "Consumer")
        with self.assertRaises(RuntimeError):
            rehearsal.validate_offer_context("Owner", new, "Consumer")
        rehearsal.current["Owner"] = modern
        rehearsal.validate_offer_context("Owner", new, "Consumer")
        for invalid in (old, new + old, new + " New stock rule.", new.replace("#Location_and_access", "#Wrong")):
            with self.assertRaises(RuntimeError):
                rehearsal.validate_offer_context("Owner", invalid, "Consumer")

    def fixture(self):
        rehearsal = IncrementalRehearsal.__new__(IncrementalRehearsal)
        rehearsal.current = {"Consumer": "Introduction. {{:Old seller|view=offers|item=item-1}} {{:New seller|view=offers|item=item-1}}",
                             "Old seller": "B", "New seller": "D"}
        rehearsal.metadata = metadata(rehearsal.current)
        rehearsal.context_previews, rehearsal.context_cache, rehearsal.context_checks = [], {}, {}
        rehearsal.checks = SimpleNamespace(check_parser_errors=checks.check_parser_errors,
                                            wait_for_server_tick=lambda *args, **kwargs: None)
        link = f'<a href="?title={self.legacy_target}">{self.legacy_label}</a>'
        direct = "<p>Introduction. " + link + "</p>"
        table = '<table><tr><td><span id="unchanged-row"></span>Unchanged row</td></tr></table>'
        old = "<p>" + link + " Location: Not established.</p>" + table
        new = '<p>Location: <a href="?title=New_seller#Location_and_access">Location and access</a>.</p>' + table
        rehearsal.probes = [
            {"id": index, "parameters": {"view": "offers", "item": "item-1"},
             "owner": rehearsal.metadata[owner], "html": html,
             "kind": "baseline-leaf-projection" if index == 0 else "desired-leaf-projection"}
            for index, (owner, html) in enumerate((("Old seller", old), ("New seller", new)))
        ]
        calls = []
        def api(query, **kwargs):
            if query.get("curtimestamp"):
                return {"curtimestamp": "2000-01-01T00:00:00Z", "query": {"pages": {}}}
            calls.append(query)
            return {"parse": {"text": {"*": direct}, "templates": []}}
        rehearsal.api = api
        correct = direct + "\n" + old + "\n" + new
        stale = direct + "\n" + old + "\n" + old
        def inspect(html):
            rehearsal.last_consumer_html = html
            record = {"consumer": dict(rehearsal.metadata["Consumer"]),
                      "html_sha256": hashlib.sha256(html.encode()).hexdigest(), "probe_ids": [0, 1]}
            from smoke_prefix import dom
            rehearsal.inspect_offer_context("Consumer", record, dom(html, "Consumer"))
            return record
        return rehearsal, inspect, correct, stale, calls

    def test_mixed_offer_context_composes_direct_and_B_D_fragments_not_global_bans(self):
        rehearsal, inspect, correct, stale, calls = self.fixture()
        record = inspect(correct)
        from smoke_incremental import context_guards, context_key
        original_key = context_key(record)
        self.assertIn(original_key, rehearsal.context_checks)
        self.assertEqual(context_guards(rehearsal, [record]), {original_key: rehearsal.context_checks[original_key]})
        self.assertEqual(len(calls), 1)
        for invalid in (stale, correct + "<p>Obsolete stock note.</p>",
                        correct.replace("#Location_and_access", "#Wrong")):
            with self.assertRaises(PendingConsumerUpdate):
                inspect(invalid)
        self.assertEqual(len(calls), 1)
        rehearsal.metadata["Consumer"]["revid"] += 1
        updated = inspect(correct)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(context_key(updated), original_key)
        self.assertEqual(len(rehearsal.context_checks), 2)
        self.assertEqual(rehearsal.context_checks[original_key]["consumer"], record["consumer"])
        del rehearsal.context_checks[context_key(updated)]
        with self.assertRaisesRegex(RuntimeError, "revision-bound"):
            context_guards(rehearsal, [updated])

    def test_stale_outside_row_notes_settle_without_changing_identical_rows(self):
        rehearsal, inspect, correct, stale, _ = self.fixture()
        rehearsal.prefixes, rehearsal.settling = [], []
        reads, drains = [], []
        def consumer(title):
            reads.append(title)
            return inspect(stale if len(reads) < 3 else correct)
        rehearsal.inspect_consumer = consumer
        with patch("smoke_prefix.time.sleep"):
            result = rehearsal.observe_consumers({"Consumer"}, lambda **kwargs: drains.append(True))
        self.assertEqual(len(result), 1)
        self.assertEqual(len(drains), 2)
        self.assertEqual(rehearsal.settling[-1]["status"], "settled")
        self.assertTrue(rehearsal.settling[0]["details"]["extra_links"])
        self.assertEqual(rehearsal.settling[0]["html"], stale)
        drains.clear()
        rehearsal.inspect_consumer = lambda title: inspect(stale)
        with patch("smoke_prefix.time.sleep"), self.assertRaises(PendingConsumerUpdate):
            rehearsal.observe_consumers({"Consumer"}, lambda **kwargs: drains.append(True))
        self.assertEqual(len(drains), 9)
        self.assertEqual(rehearsal.settling[-1]["status"], "failed")


class IncrementalNativeTests(unittest.TestCase):
    def test_multiple_operations_cold_replay_exact_prerequisites_and_preservation(self):
        from test_publication_journal import fixtures
        rehearsal = small_rehearsal()
        operations, preserved = plan(rehearsal)
        manifest, _, template = fixtures()
        manifest.update(operations=operations, preserved=preserved,
                        prerequisites_sha256=digest([row["prerequisites"] for row in operations]))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "journal"
            with Journal(path, manifest) as journal:
                states = journal.expected_states([])
                completion = journal.put_artifact({"kind": "synthetic-completion"})
                for index, title in enumerate(rehearsal.order, 1):
                    prerequisites = [{key: states[(0, owner["title"])][key] for key in
                                      ("namespace", "title", "page_id", "revision_id", "raw_sha256")}
                                     for owner in operations[index - 1]["prerequisites"]]
                    request = NativeSmoke.request(manifest, journal, index, rehearsal.desired[title], prerequisites)
                    journal.intent(request)
                    before = states[(0, title)]
                    revision = {"namespace": 0, "title": title, "page_id": before["page_id"] or 100 + index,
                                "revision_id": 200 + index, "parent_id": before["revision_id"],
                                "raw_sha256": operations[index - 1]["desired_sha256"], "actor_id": manifest["operator"]["actor_id"],
                                "comment": "native-publication/v1:" + digest(request)}
                    states[(0, title)] = revision
                    evidence = {**template, "request_sha256": digest(request), "worker": request["worker"],
                                "states": list(states.values()), "guard_sha256": journal.put_artifact({"synthetic_prefix": index}),
                                "quiescence": {**template["quiescence"], "authority_sha256": completion}}
                    self.assertEqual(journal.observe(request, evidence), "accept")
                    journal.accept(request)
                expected = copy.deepcopy(journal.accepted)
                journal.verify_resume(list(states.values()))
            with Journal(path) as replay:
                self.assertEqual(replay.accepted, expected)
                self.assertEqual(len(replay.accepted), 3)
                replay.verify_resume(list(states.values()))
                changed = copy.deepcopy(list(states.values()))
                next(row for row in changed if row["title"] == "Keep")["revision_id"] += 1
                with self.assertRaisesRegex(JournalError, "Fresh state"):
                    replay.verify_resume(changed)

    def test_historical_planning_acceptance_and_replay_share_one_count_gate(self):
        require_historical_coverage(HISTORICAL_OPERATIONS, preserved=HISTORICAL_PRESERVED)
        require_historical_coverage(HISTORICAL_OPERATIONS, prefixes=HISTORICAL_OPERATIONS + 1)
        require_historical_coverage(HISTORICAL_OPERATIONS)
        for operations, kwargs in ((453, {}), (HISTORICAL_OPERATIONS, {"preserved": 11}),
                                   (HISTORICAL_OPERATIONS, {"prefixes": 454})):
            with self.assertRaisesRegex(RuntimeError, "coverage"):
                require_historical_coverage(operations, **kwargs)
        source = (ROOT / "tools" / "smoke_deploy.py").read_text()
        self.assertIn("require_historical_coverage(len(native.release_journal.accepted), prefixes=len(rehearsal.prefixes))", source)
        self.assertIn("require_historical_coverage(len(replayed.accepted))", source)

    def test_independent_counts_and_exact_prerequisite_plan(self):
        rehearsal = small_rehearsal()
        operations, preserved = plan(rehearsal)
        result = validate_native_plan(rehearsal, operations, preserved)
        self.assertEqual(result["operations"], 3)
        self.assertEqual(result["titles"]["preserved"], ["Keep"])
        for field in ("expected", "prerequisites"):
            bad = copy.deepcopy(operations)
            bad[-1][field] = {} if field == "expected" else []
            with self.assertRaisesRegex(RuntimeError, "CAS/prerequisite"):
                validate_native_plan(rehearsal, bad, preserved)
        with self.assertRaisesRegex(RuntimeError, "preserved coverage"):
            validate_native_plan(rehearsal, operations, [])
        with self.assertRaisesRegex(RuntimeError, "operation coverage"):
            validate_native_plan(rehearsal, operations[:-1], preserved)

    def test_native_full_run_accepts_nonhistorical_count_and_zero_op_no_dispatch(self):
        rehearsal = small_rehearsal()
        rehearsal.refresh_metadata = lambda: None
        with tempfile.TemporaryDirectory() as folder:
            native = NativeSmoke(ROOT, Path(folder), None, None, {}, "a" * 40)
            with (patch.object(native, "manifest", return_value={}), patch.object(native, "effects", return_value={}),
                  patch("smoke_native.Journal") as journal):
                native.full_run(rehearsal, {})
                self.assertEqual(native.proof["incremental"]["coverage"]["operations"], 3)
                journal.assert_called_once()
            rehearsal.desired = dict(rehearsal.baseline)
            rehearsal.order = []
            with patch("smoke_native.Journal") as journal:
                save, accept = native.full_run(rehearsal, {})
                journal.assert_not_called()
                self.assertIsNone(native.release_journal)
                with self.assertRaisesRegex(RuntimeError, "zero-operation"):
                    save("Keep")
                with self.assertRaises(RuntimeError):
                    accept(1)
                native.close()

    def test_n_n_plus_one_and_accepted_order_are_required(self):
        rehearsal = small_rehearsal()
        rehearsal.prefixes = [{"index": index} for index in range(4)]
        accepted, operations = [], []
        for index, title in enumerate(rehearsal.order, 1):
            record = {"revision": {"title": title}}
            accepted.append(record)
            operations.append({"index": index, "accepted_sha256": digest(record), "result": record,
                               "prefix_guards": {"prefix": rehearsal.prefixes[index]}})
        proof = {"operations": operations}
        verify_native_completion(rehearsal, proof, accepted)
        for bad in (accepted[:-1], accepted + accepted[-1:], list(reversed(accepted))):
            with self.assertRaisesRegex(RuntimeError, "coverage"):
                verify_native_completion(rehearsal, proof, bad)
        proof["operations"][0]["prefix_guards"] = {}
        with self.assertRaises((RuntimeError, KeyError)):
            verify_native_completion(rehearsal, proof, accepted)

    def test_missing_prefix_guard_and_prerequisite_state_reject(self):
        rehearsal = small_rehearsal()
        rehearsal.current = dict(rehearsal.desired)
        rehearsal.metadata = metadata(rehearsal.current)
        rehearsal.registry = {"prices": {}, "coins": {}}
        rehearsal.default_prefixes = [[], [], [], []]
        owner = rehearsal.metadata["Owner"]
        probe = {"id": 0, "owner": owner, "parameters": {"view": "stock"}, "parse_title": "Consumer"}
        rehearsal.probes = [probe]
        rehearsal.prefixes = [{"index": index} for index in range(3)]
        rehearsal.prefixes.append({"index": 3, "saved": rehearsal.metadata["Consumer"], "prerequisites": [0],
                                   "observations": [{"consumer": rehearsal.metadata["Consumer"]}]})
        guard = {"prefix": rehearsal.prefixes[-1], "prerequisite_checks": [probe], "default_probe_ids": [],
                 "incremental_input_sha256": rehearsal.binding["input_sha256"]}
        validate_prefix_guard(rehearsal, 3, guard)
        with self.assertRaisesRegex(RuntimeError, "guard"):
            validate_prefix_guard(rehearsal, 3, {})
        for key, value in (("prerequisite_checks", []), ("default_probe_ids", [1])):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "guard"):
                validate_prefix_guard(rehearsal, 3, {**guard, key: value})
        rehearsal.prefixes[-1]["observations"] = []
        with self.assertRaisesRegex(RuntimeError, "affected consumer"):
            validate_prefix_guard(rehearsal, 3, guard)


if __name__ == "__main__":
    unittest.main()
