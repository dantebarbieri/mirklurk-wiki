"""Synthetic unit cases only; real prefix evidence requires the disposable runtime."""

import copy
import hashlib
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from smoke_deploy import RenderedRows, check_parser_errors, item_links, require_image_coverage, synthetic_image_specs
from smoke_prefix import (
    COHORT, PendingConsumerUpdate, Rehearsal, baseline_metadata, canonical_bytes, capture_installer_welcome, dom,
    linked_titles, materialize_desired, planned_order, settings_hash, verify_materialization,
)
from build_wiki import build_pages, build_xml
from wiki_catalog import page_locations
from wiki_data import DataError
from wiki_details import load_publication_inputs


class PrefixTests(unittest.TestCase):
    def fixture(self):
        locations = {identity: identity for identity in COHORT}
        baseline = {title: "Baseline" for title in locations.values()}
        desired = {title: "Desired" for title in locations.values()}
        for title in COHORT[3:]:
            desired[title] += "{{:New source|view=loot|item=" + title + "}}"
        desired["New source"] = "[[Later source]]"
        desired["Later source"] = "[[New source]]"
        return baseline, desired, locations

    def test_complete_order_prioritizes_ready_creates_and_preserves_cohort(self):
        baseline, desired, locations = self.fixture()
        order = planned_order(baseline, desired, locations, set(), set())
        self.assertEqual(set(order), set(desired))
        self.assertEqual(order[:2], ["Later source", "New source"])
        self.assertEqual([title for title in order if title in COHORT], list(COHORT))

    def test_named_prerequisite_cycle_is_not_waived_as_a_link_cycle(self):
        baseline, desired, locations = self.fixture()
        desired["New source"] = "{{:Later source|view=loot|item=item-32}}"
        desired["Later source"] = "{{:New source|view=loot|item=item-32}}"
        with self.assertRaisesRegex(RuntimeError, "Unresolved"):
            planned_order(baseline, desired, locations, set(), set())

    def test_only_exact_eleven_default_price_edges_can_use_old_unknowns(self):
        baseline, desired, locations = self.fixture()
        desired["being-8"] += "{{:item-32}}"
        self.assertEqual([title for title in planned_order(baseline, desired, locations, set(), set()) if title in COHORT], list(COHORT))
        desired["being-8"] += "{{:item-248}}"
        with self.assertRaisesRegex(RuntimeError, "Unresolved"):
            planned_order(baseline, desired, locations, set(), set())
        desired["being-8"] = "{{:item-32|view=price}}"
        with self.assertRaisesRegex(RuntimeError, "Unresolved"):
            planned_order(baseline, desired, locations, set(), set())

    def test_baseline_price_preservation_is_not_a_named_view_waiver(self):
        baseline, desired, locations = self.fixture()
        desired["being-8"] = "{{:item-248}}"
        planned_order(baseline, desired, locations, {"item-248"}, set())
        desired["being-8"] = "{{:item-248|view=offers}}"
        with self.assertRaisesRegex(RuntimeError, "Unresolved"):
            planned_order(baseline, desired, locations, {"item-248"}, set())

    def test_deletions_and_incomplete_cohort_fail(self):
        baseline, desired, locations = self.fixture()
        desired.pop("item-248")
        with self.assertRaises(RuntimeError):
            planned_order(baseline, desired, locations, set(), set())
        baseline, desired, locations = self.fixture()
        desired["item-248"] = baseline["item-248"]
        with self.assertRaises(RuntimeError):
            planned_order(baseline, desired, locations, set(), set())

    def test_settings_hash_is_exact_nonsecret_typed_canonical_json(self):
        value = {"EnableUploads": False, "AllowCopyUploads": False, "AllowExternalImages": False,
                 "ReadOnly": "", "GroupPermissions": {"user": {"edit": True}}, "CaptchaTriggers": {"edit": False}}
        self.assertEqual(settings_hash(value), hashlib.sha256(canonical_bytes(value)).hexdigest())
        changed = copy.deepcopy(value)
        changed["ReadOnly"] = False
        self.assertNotEqual(settings_hash(changed), settings_hash(value))
        changed["ReadOnly"] = None
        self.assertNotEqual(settings_hash(changed), settings_hash(value))
        for key, invalid in (("Extra", False), ("EnableUploads", 0), ("GroupPermissions", [])):
            changed = {**value, key: invalid}
            with self.assertRaises(RuntimeError):
                settings_hash(changed)
        self.assertEqual(canonical_bytes({"b": "\u00e9", "a": True}), b'{"a":true,"b":"\xc3\xa9"}')
        with self.assertRaises(ValueError):
            canonical_bytes({"invalid": float("nan")})

    def test_ordered_price_dom_preserves_fragment_and_redlink_state(self):
        parsed = dom('<table><tr><th>Item</th><th>Unit price</th></tr>'
                     '<tr><td><span id="entry-merchant-x"></span>'
                     '<a class="new" href="/index.php?title=New_item&amp;redlink=1" title="New item (page does not exist)">New item</a>'
                     '<a href="#Some_anchor">Self</a></td><td>2 gold</td></tr></table>', "Example owner")
        self.assertEqual(parsed.rows[0]["headers"], ["Item", "Unit price"])
        self.assertEqual(parsed.rows[0]["ids"], ["entry-merchant-x"])
        self.assertEqual(parsed.links, [{"target": "New item", "text": "New item"},
                                        {"target": "Example owner#Some_anchor", "text": "Self"}])
        self.assertEqual(parsed.wiki_links[0], {"target": "New item", "redlink": True})
        self.assertEqual(parsed.rows[0]["cells"][1]["text"], "2 gold")

    def test_recipe_identity_uses_canonical_href_not_redlink_tooltip(self):
        parsed = RenderedRows()
        parsed.feed('<table><tr><td><span id="entry-recipe-example"></span>'
                    '<a class="new" href="/index.php?title=Twine&amp;redlink=1" title="Twine (page does not exist)">Twine</a> x 8'
                    '</td></tr></table>')
        self.assertEqual(item_links(parsed.rows[0]["cells"][0], {"item-92": "Twine"}), ["Twine"])

    def test_all_active_and_retired_media_have_unique_synthetic_pixels(self):
        root = Path(__file__).resolve().parents[1]
        data, catalog, details = load_publication_inputs(root)
        specs = synthetic_image_specs(data)
        self.assertEqual(len(specs), 331)
        self.assertEqual(len({row[2] for row in specs.values()}), 331)
        self.assertTrue({f"Nature-{index}.png" for index in (4, 7, 17, 20)} <= specs.keys())
        self.assertTrue({row["file_title"].removeprefix("File:") for row in data["illustrations"]} <= specs.keys())
        require_image_coverage(specs, build_pages(root, data, catalog, details))
        with self.assertRaisesRegex(RuntimeError, "lack synthetic"):
            require_image_coverage(specs, {"Unseeded": "[[File:Unseeded.png|32px]]"})
        for armor in (1, 2, 3):
            self.assertEqual(specs[f"Health-armor-{armor}.png"][2][-1], 128)

    def test_missing_file_placeholders_are_not_valid_row_evidence(self):
        with self.assertRaisesRegex(RuntimeError, "missing image"):
            check_parser_errors('<span typeof="mw:Error mw:File"><span class="mw-file-element mw-broken-media">Twine</span></span>')
        check_parser_errors('<span typeof="mw:File"><a href="/index.php?title=Twine"><img src="synthetic.png" /></a></span>')

    def test_ordinary_links_are_recorded_separately_from_selectors(self):
        self.assertEqual(linked_titles("[[New_source#Details|label]] {{:Owner|view=loot}} [[Existing]]"),
                         {"New source", "Existing"})

    def test_baseline_metadata_preserves_exact_decimals_and_rejects_duplicate_keys(self):
        value = baseline_metadata(b'{"price":0.20000000000000000001}')
        self.assertEqual(value["price"], Decimal("0.20000000000000000001"))
        with self.assertRaises(DataError):
            baseline_metadata(b'{"price":0.2,"price":0.3}')

    def test_expectation_candidate_has_exact_shared_provenance_shape(self):
        root = Path(__file__).resolve().parents[1]
        data, catalog, details = load_publication_inputs(root)
        desired = build_pages(root, data, catalog, details)
        locations = page_locations(data, catalog)
        baseline = dict(desired)
        for identity in COHORT:
            baseline[locations[identity]] = "Synthetic schema-test baseline"
        old_catalog = baseline_metadata((root / "content" / "facts" / "catalog.json").read_bytes())
        rehearsal = Rehearsal(None, None, baseline, desired, data, catalog, old_catalog, {}, "0" * 40)
        rehearsal.final_observations = []
        rehearsal.endpoint_projections = {
            state: {locations[identity]: {} for identity in COHORT[3:]} for state in ("baseline", "desired")
        }
        artifacts = rehearsal.artifacts()
        receipt = artifacts["price-compatibility-receipt.json"]
        candidate = artifacts["price-expectations-candidate.json"]
        shared = {"schema_version", "evidence_kind", "source_head_sha", "checkout_sha",
                  "baseline_seed_sha256", "desired_seed_sha256", "runtime", "order"}
        self.assertEqual(set(candidate), shared | {"versions", "projections", "prefixes"})
        self.assertEqual(set(receipt), shared | {"receipt_type", "coverage_scope", "prefixes"})
        self.assertEqual({key: candidate[key] for key in shared}, {key: receipt[key] for key in shared})
        self.assertEqual(candidate["evidence_kind"], "disposable-mediawiki")
        self.assertEqual(candidate["prefixes"], [])  # Deliberately incomplete synthetic data, never runtime evidence.

    def test_only_deferred_consumer_mismatches_receive_bounded_job_retries(self):
        rehearsal = Rehearsal.__new__(Rehearsal)
        rehearsal.prefixes, rehearsal.settling = [], []
        rehearsal.metadata = {"Consumer": {"title": "Consumer"}, "Owner": {"title": "Owner"}}
        rehearsal.api = lambda query: {"curtimestamp": "2000-01-01T00:00:00Z", "query": {"pages": {}}}
        calls, drains = [], []
        def inspect(title):
            calls.append(title)
            if len(calls) < 3:
                raise PendingConsumerUpdate("Pending", title, "Owner", "<p>cached</p>")
            return {"title": title}
        rehearsal.inspect_consumer = inspect
        with patch("smoke_prefix.time.sleep"):
            self.assertEqual(rehearsal.observe_consumers({"Consumer"}, lambda: drains.append(True)),
                             [{"title": "Consumer"}])
        self.assertEqual(len(drains), 2)
        self.assertEqual([event["status"] for event in rehearsal.settling], ["pending", "pending", "settled"])
        rehearsal.inspect_consumer = lambda title: (_ for _ in ()).throw(RuntimeError("Invalid selector"))
        with self.assertRaisesRegex(RuntimeError, "Invalid selector"):
            rehearsal.observe_consumers({"Consumer"}, lambda: self.fail("Must not retry arbitrary failures"))

    def test_deferred_consumer_retry_exhaustion_fails_with_diagnostics(self):
        rehearsal = Rehearsal.__new__(Rehearsal)
        rehearsal.prefixes, rehearsal.settling = [], []
        rehearsal.metadata = {"Consumer": {"title": "Consumer"}, "Owner": {"title": "Owner"}}
        diagnostics, drains = [], []
        rehearsal.api = lambda query: {"curtimestamp": "2000-01-01T00:00:00Z", "query": {"pages": {}}}
        rehearsal.checks = SimpleNamespace(cache_diagnostics=lambda *args: diagnostics.append(args))
        rehearsal.inspect_consumer = lambda title: (_ for _ in ()).throw(PendingConsumerUpdate("Still pending", title, "Owner", "HTML"))
        with patch("smoke_prefix.time.sleep"), self.assertRaises(PendingConsumerUpdate):
            rehearsal.observe_consumers({"Consumer"}, lambda: drains.append(True))
        self.assertEqual(len(drains), 9)
        self.assertEqual(len(diagnostics), 1)


class MaterializationTests(unittest.TestCase):
    actor = {"id": 1, "name": "Synthetic writer"}
    head = "0" * 40
    kind = "synthetic-unit-fixture"

    def inputs(self):
        return {"Stable": "same\n", "Changed": "old\n"}, {
            "Stable": "same\n", "Changed": "new\r\n\r\n", "New": "created\n",
        }

    def api(self, query, post=False):
        self.assertTrue(post)
        self.assertEqual(query["onlypst"], 1)
        self.assertEqual(query["assertuser"], self.actor["name"])
        self.assertNotEqual(query["title"], "Stable")
        return {"parse": {"text": {"*": query["text"].rstrip("\r\n")},
                          "wikitext": {"*": query["text"]}}}

    def test_actual_transformed_text_is_used_and_unchanged_pages_are_not_trimmed(self):
        baseline, authored = self.inputs()
        desired, receipt = materialize_desired(self.api, baseline, authored, self.head, {}, self.actor, self.kind)
        self.assertEqual(desired, {"Changed": "new", "New": "created", "Stable": "same\n"})
        stable = next(row for row in receipt["pages"] if row["title"] == "Stable")
        self.assertIsNone(stable["only_pst_output"])
        self.assertEqual(stable["removed_suffix"], "")
        self.assertEqual(receipt["pages"][0]["removed_suffix"], "\r\n\r\n")
        self.assertEqual(receipt["evidence_kind"], self.kind)

    def test_wrong_onlypst_return_field_cannot_substitute_for_transformed_text(self):
        def wrong_field(query, post=False):
            return {"parse": {"wikitext": {"*": query["text"].rstrip("\r\n")}}}
        with self.assertRaisesRegex(RuntimeError, "transformed text"):
            materialize_desired(wrong_field, {}, {"New": "created\n"}, self.head, {}, self.actor, self.kind)

    def test_broader_trims_internal_changes_substitution_and_signature_fail(self):
        for authored, forbidden in [
            ("word \n", "word"), ("word\t\n", "word"), ("word\0\n", "word"),
            ("word\v\n", "word"), ("word\u00a0\n", "word"),
            ("a\r\nb\n", "a\nb"), ("{{subst:Example}}\n", "expanded"), ("~~~~\n", "signature"),
        ]:
            with self.subTest(authored=repr(authored)):
                def changed(query, post=False):
                    return {"parse": {"text": {"*": forbidden}}}
                with self.assertRaisesRegex(RuntimeError, "more than terminal"):
                    materialize_desired(changed, {}, {"New": authored}, self.head, {}, self.actor, self.kind)

    def test_source_runtime_actor_hash_and_suffix_mismatches_fail(self):
        baseline, authored = self.inputs()
        desired, receipt = materialize_desired(self.api, baseline, authored, self.head, {}, self.actor, self.kind)
        for field, value in (
            ("source_head_sha", "1" * 40), ("authored_seed_sha256", "1" * 64),
            ("baseline_seed_sha256", "1" * 64), ("desired_seed_sha256", "1" * 64),
            ("runtime", {"different": True}), ("actor", {"id": 2, "name": "Different"}),
            ("acceptance", "php-rtrim"), ("schema_version", True),
            ("actor", {"id": True, "name": "Synthetic writer"}),
        ):
            with self.subTest(field=field):
                changed = {**receipt, field: value}
                with self.assertRaisesRegex(RuntimeError, "pins differ"):
                    verify_materialization(baseline, authored, desired, changed, self.head, {}, self.actor, self.kind)
        changed = copy.deepcopy(receipt)
        changed["pages"][0]["removed_suffix"] = ""
        with self.assertRaisesRegex(RuntimeError, "per-title hashes"):
            verify_materialization(baseline, authored, desired, changed, self.head, {}, self.actor, self.kind)

    def test_unchanged_page_trimming_is_forbidden_even_with_recomputed_seed_hash(self):
        baseline, authored = self.inputs()
        desired, receipt = materialize_desired(self.api, baseline, authored, self.head, {}, self.actor, self.kind)
        desired["Stable"] = "same"
        receipt["desired_seed_sha256"] = hashlib.sha256(build_xml(desired)).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "unchanged page"):
            verify_materialization(baseline, authored, desired, receipt, self.head, {}, self.actor, self.kind)

    def test_bootstrap_capture_refuses_changed_or_extra_pages(self):
        def fixture(raw="Welcome\n\nFooter", user="MediaWiki default", parentid=0, extra=False):
            def api(query, post=False):
                if query["action"] == "parse":
                    return {"parse": {"text": {"*": query["text"]}}}
                if query.get("list") == "allpages":
                    names = ["Main Page", *(["Unexpected"] if extra else [])] if query["apnamespace"] == 0 else []
                    return {"query": {"allpages": [{"title": title} for title in names]}}
                return {"query": {"pages": {"1": {"title": "Main Page", "pageid": 1, "revisions": [{
                    "revid": 1, "parentid": parentid, "user": user, "slots": {"main": {"*": raw}},
                }]}}}}
            return api
        self.assertEqual(capture_installer_welcome(fixture(), "Welcome\n\nFooter", self.actor)["revid"], 1)
        for change in ({"raw": "Changed"}, {"user": "Editor"}, {"parentid": 1}, {"extra": True}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                capture_installer_welcome(fixture(**change), "Welcome\n\nFooter", self.actor)


if __name__ == "__main__":
    unittest.main()
