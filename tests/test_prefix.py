"""Synthetic unit cases only; real prefix evidence requires the disposable runtime."""

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from smoke_deploy import (
    RenderedRows, bounded_maintenance, check_parser_errors, drain_jobs_bounded, item_links,
    plain, require_image_coverage, smoke, synthetic_image_specs, wait_for_server_tick, write_smoke_evidence,
)
from smoke_prefix import (
    COHORT, STORED_BASELINE_BINDING, PendingConsumerUpdate, Rehearsal, baseline_metadata, canonical_bytes,
    capture_installer_welcome, dom, endpoint_targets, linked_titles, materialize_desired, planned_order, reconstruct_stored_baseline,
    settings_hash, strip_colon_invocations, verify_materialization,
)
from build_wiki import build_pages, build_xml
from plan_migration import plan_migration, read_snapshot
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

    def test_stock_projection_is_an_exact_registered_leaf_not_a_general_waiver(self):
        text = "Purchases do not deplete the listed stock."
        rehearsal = SimpleNamespace(
            checks=SimpleNamespace(check_parser_errors=check_parser_errors, plain=plain),
            entities={}, catalog={"currency": {"rules": [{"id": "trade-stock-and-funds", "text": text}]}},
        )
        result = {"templates": [{"*": "Currency and trading"}], "text": {"*": "<p>" + text + "</p>"}}
        Rehearsal.validate_projection(rehearsal, "Currency and trading", {"view": "stock"}, result)
        for html in ("Changed rule.", text + "<table></table>", text + '<span id="extra"></span>',
                     '<a href="/index.php?title=Item">' + text + "</a>",
                     '<a href="https://example.test/">' + text + "</a>", text + '<img src="extra.png">'):
            changed = {**result, "text": {"*": html}}
            with self.assertRaises(RuntimeError):
                Rehearsal.validate_projection(rehearsal, "Currency and trading", {"view": "stock"}, changed)
        for templates in ([], [{"*": "Currency and trading"}, {"*": "Copper Coin"}]):
            with self.assertRaises(RuntimeError):
                Rehearsal.validate_projection(rehearsal, "Currency and trading", {"view": "stock"},
                                             {**result, "templates": templates})
        with self.assertRaises(RuntimeError):
            Rehearsal.validate_projection(rehearsal, "Currency and trading", {"view": "stock", "item": "item-0"}, result)
        with self.assertRaises(RuntimeError):
            Rehearsal.validate_projection(rehearsal, "Other owner", {"view": "stock"},
                                         {**result, "templates": [{"*": "Other owner"}]})

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
        self.assertEqual(parsed.wiki_links[0], {"target": "New item", "redlink": True,
                                              "href": "/index.php?title=New_item&redlink=1", "classes": ["new"]})
        self.assertEqual(parsed.rows[0]["cells"][1]["text"], "2 gold")

    def test_nonwiki_urls_are_retained_not_invented_as_selflinks(self):
        parsed = dom('<p><a href="https://example.invalid/?title=Other">External</a>'
                     '<a href="/images/example.png">Binary</a><a href="#Details">Section</a></p>', "Owner")
        self.assertEqual(parsed.links, [{"target": "Owner#Details", "text": "Section"}])
        self.assertEqual(parsed.non_wiki_links, [
            {"href": "https://example.invalid/?title=Other", "text": "External"},
            {"href": "/images/example.png", "text": "Binary"},
        ])

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
        self.assertEqual(len(specs), 334)
        self.assertEqual(len({row[2] for row in specs.values()}), 334)
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
        rehearsal.api = lambda query, **kwargs: {"curtimestamp": "2000-01-01T00:00:00Z", "query": {"pages": {}}}
        ticks = []
        rehearsal.checks = SimpleNamespace(wait_for_server_tick=lambda api, minimum=None: ticks.append(True))
        calls, drains = [], []
        def inspect(title):
            calls.append(title)
            if len(calls) < 3:
                raise PendingConsumerUpdate("Pending", title, "Owner", "<p>cached</p>")
            return {"title": title}
        rehearsal.inspect_consumer = inspect
        with patch("smoke_prefix.time.sleep"):
            self.assertEqual(rehearsal.observe_consumers({"Consumer"}, lambda **kwargs: drains.append(True)),
                             [{"title": "Consumer"}])
        self.assertEqual(len(drains), 2)
        self.assertEqual(len(ticks), 2)
        self.assertEqual([event["status"] for event in rehearsal.settling], ["pending", "pending", "settled"])
        rehearsal.inspect_consumer = lambda title: (_ for _ in ()).throw(RuntimeError("Invalid selector"))
        with self.assertRaisesRegex(RuntimeError, "Invalid selector"):
            rehearsal.observe_consumers({"Consumer"}, lambda **kwargs: self.fail("Must not retry arbitrary failures"))

    def test_deferred_consumer_retry_exhaustion_fails_with_diagnostics(self):
        rehearsal = Rehearsal.__new__(Rehearsal)
        rehearsal.prefixes, rehearsal.settling = [], []
        rehearsal.metadata = {"Consumer": {"title": "Consumer"}, "Owner": {"title": "Owner"}}
        diagnostics, drains = [], []
        rehearsal.api = lambda query, **kwargs: {"curtimestamp": "2000-01-01T00:00:00Z", "query": {"pages": {}}}
        rehearsal.checks = SimpleNamespace(wait_for_server_tick=lambda api, minimum=None: None)
        rehearsal.inspect_consumer = lambda title: (_ for _ in ()).throw(PendingConsumerUpdate("Still pending", title, "Owner", "HTML"))
        with patch("smoke_prefix.time.sleep"), self.assertRaises(PendingConsumerUpdate):
            rehearsal.observe_consumers({"Consumer"}, lambda **kwargs: drains.append(True),
                                        lambda **kwargs: diagnostics.append(kwargs) or "0")
        self.assertEqual(len(drains), 9)
        self.assertEqual(len(diagnostics), 1)

    def test_elapsed_settling_budget_stops_further_attempts(self):
        rehearsal = Rehearsal.__new__(Rehearsal)
        rehearsal.prefixes, rehearsal.settling = [], []
        rehearsal.metadata = {"Consumer": {"title": "Consumer"}, "Owner": {"title": "Owner"}}
        rehearsal.api = lambda query, **kwargs: {"curtimestamp": "2000-01-01T00:00:00Z", "query": {"pages": {}}}
        rehearsal.checks = SimpleNamespace(wait_for_server_tick=lambda api, minimum=None: None)
        rehearsal.inspect_consumer = lambda title: (_ for _ in ()).throw(PendingConsumerUpdate("Pending", title, "Owner", "HTML"))
        with patch("smoke_prefix.time.monotonic", side_effect=[0, 91]), self.assertRaises(TimeoutError):
            rehearsal.observe_consumers({"Consumer"}, lambda **kwargs: self.fail("Elapsed budget must stop job drains"))

    def test_server_clock_boundary_records_ticks_and_rejects_frozen_or_backward_time(self):
        before, after = "2000-01-01T00:00:00Z", "2000-01-01T00:00:01Z"
        values = iter([before, before, after])
        with patch("smoke_deploy.time.sleep"):
            self.assertEqual(wait_for_server_tick(lambda query: {"curtimestamp": next(values)}, minimum=before),
                             {"before": before, "after": after})
            with self.assertRaisesRegex(RuntimeError, "did not advance"):
                wait_for_server_tick(lambda query: {"curtimestamp": before})
            with self.assertRaisesRegex(RuntimeError, "backwards"):
                wait_for_server_tick(lambda query: {"curtimestamp": before}, minimum=after)
            values = iter([after, before])
            with self.assertRaisesRegex(RuntimeError, "backwards"):
                wait_for_server_tick(lambda query: {"curtimestamp": next(values)})

    def test_job_drain_has_remote_and_subprocess_deadlines_and_never_retries_timeout(self):
        calls = []
        def run(*args, **kwargs):
            calls.append((args, kwargs))
            return b"0"
        result = drain_jobs_bounded(run, timeout=10)
        self.assertEqual(result["remaining_jobs"], "0")
        self.assertEqual(len(calls), 2)
        for args, kwargs in calls:
            self.assertEqual(args[3:5], ("timeout", "--kill-after=1s"))
            self.assertTrue(0 < kwargs["timeout"] <= 10)
        def expired(*args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        with self.assertRaises(subprocess.TimeoutExpired):
            drain_jobs_bounded(expired, timeout=10)
        calls.clear()
        with patch("smoke_deploy.time.monotonic", side_effect=[0, 1, 11]), self.assertRaises(TimeoutError):
            drain_jobs_bounded(run, timeout=10)
        self.assertEqual(len(calls), 1)
        def remote_expired(*args, **kwargs):
            raise subprocess.CalledProcessError(124, args)
        with self.assertRaisesRegex(TimeoutError, "exhausted"):
            bounded_maintenance(remote_expired, ("runJobs",), 10)


class EndpointCandidateTests(unittest.TestCase):
    def mediawiki_fixture(self, fault=None):
        rehearsal, _ = self.fixture()
        rehearsal.current = {"Owner": "<onlyinclude>[[Consumer#row]]</onlyinclude>", "Consumer": "{{:Owner}}"}
        rehearsal.baseline = dict(rehearsal.current)
        rehearsal.desired = dict(rehearsal.current)
        rehearsal.validate_projection = lambda *args: None
        original_api = rehearsal.api
        def api(query, **kwargs):
            if query["action"] == "query":
                return original_api(query)
            if query["action"] == "expandtemplates":
                return {"expandtemplates": {"wikitext": "[[Consumer#row]]"}}
            title = query.get("title", query.get("page"))
            selected = "{{:Owner}}" in query.get("text", "")
            linked = selected or query.get("page") in rehearsal.current or query.get("text") == rehearsal.current["Owner"]
            html = (f'<div id="toc" class="toc"><a href="#Top">Top</a></div>'
                    f'<span class="mw-editsection"><a href="?title={title}&amp;action=edit&amp;section=1">edit</a></span>')
            links = []
            if linked:
                href = "#row" if title == "Consumer" else "?title=Consumer#row"
                css = ' class="mw-selflink-fragment"' if title == "Consumer" else ""
                html += f'<a{css} href="{href}">Consumer</a>'
                if title != "Consumer":
                    links = [{"ns": 0, "*": "Consumer"}]
            result = {"text": {"*": html}, "templates": [{"*": "Owner"}] if selected else [],
                      "links": links, "revid": rehearsal.metadata.get(title, {}).get("revid")}
            if fault:
                fault(query, result)
            return {"parse": result}
        rehearsal.api = api
        return rehearsal

    def test_mediawiki_self_fragments_and_navigation_are_not_parser_dependencies(self):
        rehearsal = self.mediawiki_fixture()
        rehearsal.capture_link_endpoint("baseline")
        result = rehearsal.link_candidates["baseline"]
        self.assertTrue(result["capture_complete"])
        self.assertFalse(result["candidate_promotion_blocked"])
        neutral, contextual = result["selected"]
        self.assertNotEqual(neutral["links"], contextual["links"])
        self.assertEqual(neutral["semantic_targets"], ["Consumer#row"])
        self.assertEqual(contextual["semantic_targets"], ["Consumer#row"])
        parsed = dom('<a class="mw-selflink selflink">Consumer</a>'
                     '<a class="mw-selflink-fragment" href="#row">row</a>'
                     '<a href="?title=Consumer"><img alt="linked image"></a>', "Consumer")
        self.assertEqual(endpoint_targets(parsed, rehearsal.current), ({"Consumer"}, {"Consumer", "Consumer#row"}))
        self.assertEqual(len(parsed.wiki_links), 3)
        ordinary = dom('<a href="#Top">Content fragment</a>'
                       '<a href="?title=Consumer&amp;action=edit&amp;section=1">Content edit link</a>', "Consumer")
        self.assertEqual(endpoint_targets(ordinary, rehearsal.current), ({"Consumer"}, {"Consumer", "Consumer#Top"}))

    def test_contextual_wrong_missing_self_links_fragments_and_redlinks_still_block(self):
        for replacement in ('<a href="#wrong">Consumer</a>', "", '<a href="?title=Owner">Owner</a>',
                            '<a class="new" href="#row">Consumer</a>'):
            def fault(query, result):
                if query.get("title") == "Consumer" and query.get("text") == "{{:Owner}}":
                    result["text"]["*"] = replacement
            with self.subTest(replacement=replacement):
                rehearsal = self.mediawiki_fixture(fault)
                rehearsal.capture_link_endpoint("baseline")
                self.assertTrue(rehearsal.link_candidates["baseline"]["candidate_promotion_blocked"])
        def wrong_union(query, result):
            if query.get("page") == "Consumer":
                result["text"]["*"] += '<a href="#wrong">Wrong original</a>'
        rehearsal = self.mediawiki_fixture(wrong_union)
        rehearsal.capture_link_endpoint("baseline")
        self.assertIn("direct-projected-union", {row["kind"] for row in rehearsal.link_candidates["baseline"]["discrepancies"]})

    def test_navigation_classes_do_not_hide_unexpected_cross_page_links(self):
        def fault(query, result):
            if query.get("title") == "Consumer" and query.get("text") == "{{:Owner}}":
                result["text"]["*"] += '<div id="toc" class="toc"><a href="?title=Owner">Wrong</a></div>'
        rehearsal = self.mediawiki_fixture(fault)
        rehearsal.capture_link_endpoint("baseline")
        self.assertIn("api-dom-targets", {row["kind"] for row in rehearsal.link_candidates["baseline"]["discrepancies"]})

    def test_projection_failure_retains_active_raw_parse_and_incomplete_capture(self):
        rehearsal = self.mediawiki_fixture()
        def invalid(*args):
            raise RuntimeError("Synthetic invalid projection")
        rehearsal.validate_projection = invalid
        with self.assertRaisesRegex(RuntimeError, "Synthetic invalid"):
            rehearsal.capture_link_endpoint("baseline")
        captures = rehearsal.link_candidates["baseline"]
        self.assertFalse(captures["capture_complete"])
        self.assertTrue(captures["candidate_promotion_blocked"])
        self.assertEqual(captures["active_capture"]["expanded_wikitext"], "[[Consumer#row]]")
        self.assertIn("mw-editsection", captures["active_capture"]["parse_result"]["text"]["*"])
        self.assertNotIn("revisions_after", captures)

    def test_span_removal_is_byte_exact_duplicate_preserving_and_leaves_other_markup(self):
        text = "\u00e9<noinclude>{{:Owner|view=loot|item=item-1}}</noinclude>\n{{#switch:x|x=y}}\n{{:Owner|view=loot|item=item-1}}\n"
        transformed, spans = strip_colon_invocations(text)
        self.assertEqual(transformed, "\u00e9<noinclude></noinclude>\n{{#switch:x|x=y}}\n\n")
        self.assertEqual(len(spans), 2)
        raw, parts, previous = text.encode("utf-8"), [], 0
        for span in spans:
            self.assertEqual(raw[span["start_byte"]:span["end_byte"]].decode(), span["invocation"])
            parts.append(raw[previous:span["start_byte"]])
            previous = span["end_byte"]
        parts.append(raw[previous:])
        self.assertEqual(b"".join(parts).decode(), transformed)
        for invalid in ("{{:Unclosed", "{{:Owner|view={{{view}}}}}", "{{:Owner|view=loot}}\n{{:bad"):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                strip_colon_invocations(invalid)
        with self.assertRaises(DataError):
            strip_colon_invocations("{{:Owner|positional}}")

    def fixture(self, context_difference=False, change_revision=False):
        rehearsal = Rehearsal.__new__(Rehearsal)
        rehearsal.current = {"Owner": "<onlyinclude>1 silver</onlyinclude>", "Consumer": "A{{:Owner}}B{{:Owner}}"}
        rehearsal.baseline = dict(rehearsal.current)
        rehearsal.desired = dict(rehearsal.current)
        rehearsal.metadata = {title: {"title": title, "pageid": i, "revid": i, "parentid": 0,
                                     "raw_sha256": hashlib.sha256(text.encode()).hexdigest()}
                              for i, (title, text) in enumerate(rehearsal.current.items(), 1)}
        rehearsal.checks = SimpleNamespace(check_parser_errors=check_parser_errors)
        rehearsal.validate_projection = lambda owner, parameters, result, title: self.assertEqual(result["templates"], [{"*": owner}])
        rehearsal.link_candidates = {}
        calls = []
        def api(query, **kwargs):
            calls.append(query)
            self.assertIn(query["action"], {"query", "parse", "expandtemplates"})
            if query["action"] == "query":
                return {"query": {"userinfo": {"id": 1, "name": "Synthetic operator"}}}
            if query["action"] == "expandtemplates":
                value = "context difference" if context_difference and query["title"] == "Consumer" else "1 silver"
                return {"expandtemplates": {"wikitext": value}}
            text = query.get("text", rehearsal.current.get(query.get("page")))
            templates = [{"*": "Owner"}] if "{{:Owner}}" in text else []
            visible = re.sub("</?onlyinclude>", "", text.replace("{{:Owner}}", "1 silver"))
            result = {"text": {"*": "<p>" + visible + "</p>"}, "templates": templates, "links": []}
            if "page" in query:
                result["revid"] = rehearsal.metadata[query["page"]]["revid"]
            return {"parse": result}
        rehearsal.api = api
        def refresh():
            if change_revision:
                rehearsal.metadata["Owner"] = {**rehearsal.metadata["Owner"], "revid": 99}
        rehearsal.refresh_metadata = refresh
        return rehearsal, calls

    def test_endpoint_capture_uses_original_context_and_retains_duplicate_spans(self):
        rehearsal, calls = self.fixture()
        rehearsal.capture_link_endpoint("desired")
        result = rehearsal.link_candidates["desired"]
        self.assertFalse(result["candidate_promotion_blocked"])
        self.assertEqual({row["parse_title"] for row in result["selected"]}, {"Prefix projection", "Consumer"})
        direct = next(row for row in result["direct"] if row["consumer"]["title"] == "Consumer")
        self.assertEqual(direct["transformed_text"], "AB")
        self.assertEqual(len(direct["removed_invocations"]), 2)
        self.assertEqual(result["revisions_before"], result["revisions_after"])
        self.assertTrue(all(row["templates"] == [] for row in result["direct"]))

    def test_context_variation_is_retained_and_blocks_candidate_promotion(self):
        rehearsal, _ = self.fixture(context_difference=True)
        rehearsal.capture_link_endpoint("desired")
        result = rehearsal.link_candidates["desired"]
        self.assertTrue(result["candidate_promotion_blocked"])
        self.assertTrue(any(row["kind"] == "projection-context" for row in result["discrepancies"]))

    def test_endpoint_revision_drift_fails_instead_of_binding_new_content(self):
        rehearsal, _ = self.fixture(change_revision=True)
        with self.assertRaisesRegex(RuntimeError, "changed during"):
            rehearsal.capture_link_endpoint("desired")
        result = rehearsal.link_candidates["desired"]
        self.assertFalse(result["capture_complete"])
        self.assertNotEqual(result["revisions_before"], result["revisions_after"])

    def test_baseline_named_views_are_explicitly_unsupported_not_old_defaults(self):
        rehearsal, calls = self.fixture()
        rehearsal.desired["Consumer"] = "{{:Owner|view=loot|item=item-1}}"
        rehearsal.capture_link_endpoint("baseline")
        unsupported = rehearsal.link_candidates["baseline"]["unsupported"]
        self.assertEqual(len(unsupported), 1)
        self.assertEqual(unsupported[0]["reason"], "view-not-declared")
        self.assertFalse(any("|view=loot" in query.get("text", "") for query in calls))


class FailureEvidenceTests(unittest.TestCase):
    def test_failure_preserves_partial_preimages_without_success_artifact_names(self):
        rehearsal = SimpleNamespace(link_candidates={"baseline": {"discrepancies": [{"kind": "api-dom-targets"}],
                                    "selected": [{"html": "<p>Actual captured preimage</p>"}]}}, prefixes=[])
        native = SimpleNamespace(proof={"operations": []},
                                 release_journal=SimpleNamespace(records={"manifest.json": {"synthetic": True}}))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "failed"
            write_smoke_evidence(path, "a" * 40, {"full-prefix-proof.json": {"not_final": True}},
                                 {"baseline-seed.xml": b"synthetic"}, RuntimeError("endpoint mismatch"), rehearsal, native)
            manifest = json.loads((path / "artifact-manifest.json").read_bytes())
            self.assertEqual(manifest["status"], "failed")
            self.assertFalse(manifest["complete"])
            self.assertFalse((path / "full-prefix-proof.json").exists())
            failure = json.loads((path / "failed-rehearsal.json").read_bytes())
            self.assertEqual(failure["rehearsal"]["link_candidates"], rehearsal.link_candidates)
            self.assertEqual(failure["native_partial"]["release_journal_records"], native.release_journal.records)
            self.assertEqual(failure["failure"], {"type": "RuntimeError", "message": "endpoint mismatch"})
            for name, pin in manifest["artifacts"].items():
                raw = (path / name).read_bytes()
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (pin["bytes"], pin["sha256"]))
            with self.assertRaises(FileExistsError):
                write_smoke_evidence(path, "a" * 40, {}, {})

    def test_success_writer_keeps_existing_artifacts_and_manifest_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "passed"
            write_smoke_evidence(path, "a" * 40, {"proof.json": {"synthetic": True}}, {"baseline-seed.xml": b"seed"})
            manifest = json.loads((path / "artifact-manifest.json").read_bytes())
            self.assertEqual(manifest["status"], "passed")
            self.assertTrue(manifest["complete"])
            self.assertEqual(set(manifest["artifacts"]), {"proof.json", "baseline-seed.xml"})
            self.assertFalse((path / "failed-rehearsal.json").exists())

    def test_interruption_before_release_journal_is_explicitly_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "interrupted"
            write_smoke_evidence(path, "a" * 40, {}, {}, KeyboardInterrupt(), native=SimpleNamespace(proof={"faults": []}))
            result = json.loads((path / "failed-rehearsal.json").read_bytes())
            self.assertEqual(result["failure"]["type"], "KeyboardInterrupt")
            self.assertIsNone(result["native_partial"]["release_journal_records"])
            self.assertFalse(result["complete"])

    def test_smoke_writes_before_cleanup_and_propagates_original_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "failure"
            calls = []
            failure = RuntimeError("Synthetic config failure before native initialization")
            def command(args, **kwargs):
                calls.append(args)
                if "config" in args:
                    raise failure
                if "down" in args:
                    self.assertTrue((output / "failed-rehearsal.json").exists())
                return SimpleNamespace(stdout=b"")
            with (patch("smoke_prefix.reconstruct_baseline", return_value=({}, b"A0", {}, b"B", {})),
                  patch("smoke_deploy.subprocess.check_output", return_value="a" * 40 + "\n"),
                  patch("smoke_deploy.subprocess.run", side_effect=command),
                  patch("smoke_deploy.socket.socket") as socket):
                socket.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 12345)
                with self.assertRaises(RuntimeError) as raised:
                    smoke(output)
            self.assertIs(raised.exception, failure)
            self.assertEqual(sum("down" in args for args in calls), 1)
            result = json.loads((output / "failed-rehearsal.json").read_bytes())
            self.assertIsNone(result["rehearsal"])
            self.assertIsNone(result["native_partial"])
            with patch("smoke_deploy.subprocess.run") as command, self.assertRaises(FileExistsError):
                smoke(output)
            command.assert_not_called()

    def test_evidence_io_failure_does_not_skip_disposable_cleanup(self):
        calls = []
        original = RuntimeError("Synthetic failed run")
        def command(args, **kwargs):
            calls.append(args)
            if "config" in args:
                raise original
            return SimpleNamespace(stdout=b"")
        with tempfile.TemporaryDirectory() as folder:
            with (patch("smoke_prefix.reconstruct_baseline", return_value=({}, b"A0", {}, b"B", {})),
                  patch("smoke_deploy.subprocess.check_output", return_value="a" * 40),
                  patch("smoke_deploy.subprocess.run", side_effect=command),
                  patch("smoke_deploy.write_smoke_evidence", side_effect=OSError("Synthetic disk failure")),
                  patch("smoke_deploy.socket.socket") as socket):
                socket.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 12345)
                with self.assertRaises(OSError) as raised:
                    smoke(Path(folder) / "unwritten")
        self.assertIs(raised.exception.__context__, original)
        self.assertEqual(sum("down" in args for args in calls), 1)


class StoredBaselineTests(unittest.TestCase):
    def setUp(self):
        self.previous = {"Evidence and spoilers": "Exact\n", "Action points": "Action\n\n", "Other": "Other\n"}
        self.stored = {"Evidence and spoilers": "Exact\n", "Action points": "Action", "Other": "Other"}
        self.payload = build_xml(self.previous)
        stored_payload = build_xml(self.stored)
        self.binding = {
            **STORED_BASELINE_BINDING,
            "previous_authored_seed_bytes": len(self.payload),
            "previous_authored_seed_sha256": hashlib.sha256(self.payload).hexdigest(),
            "baseline_seed_bytes": len(stored_payload),
            "baseline_seed_sha256": hashlib.sha256(stored_payload).hexdigest(),
            "baseline_corpus_sha256": hashlib.sha256(canonical_bytes(self.stored)).hexdigest(),
            "managed_title_count": 3, "removed_lf_counts": {"0": 1, "1": 1, "2": 1},
        }

    def test_synthetic_binding_preserves_observed_exact_title_and_roundtrips_stored_bytes(self):
        with patch("smoke_prefix.STORED_BASELINE_BINDING", self.binding):
            pages, payload = reconstruct_stored_baseline(self.previous, self.payload)
        self.assertEqual(pages, self.stored)
        self.assertNotEqual(payload, self.payload)
        self.assertTrue(pages["Evidence and spoilers"].endswith("\n"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stored.xml"
            path.write_bytes(payload)
            self.assertEqual(read_snapshot(path), self.stored)

    def test_reconstruction_requires_exact_source_bytes_and_complete_identities(self):
        for previous, payload in (
            (self.previous, self.payload + b"\n"),
            (self.stored, build_xml(self.stored)),
            ({**self.previous, "Other": "Changed\n"}, self.payload),
            ({title: text for title, text in self.previous.items() if title != "Other"}, self.payload),
            ({**self.previous, "Extra": "Unknown"}, self.payload),
        ):
            with patch("smoke_prefix.STORED_BASELINE_BINDING", self.binding), self.assertRaisesRegex(RuntimeError, "exact reviewed"):
                reconstruct_stored_baseline(previous, payload)

    def test_blanket_normalization_and_rebound_xml_do_not_waive_observed_corpus_pin(self):
        for field, value in (
            ("exact_titles", []), ("exact_titles", ["Other"]), ("baseline_seed_sha256", "0" * 64),
            ("baseline_corpus_sha256", "0" * 64), ("baseline_seed_bytes", 0),
            ("removed_lf_counts", {"0": 1, "1": 2}),
        ):
            binding = {**self.binding, field: value}
            with self.subTest(field=field), patch("smoke_prefix.STORED_BASELINE_BINDING", binding):
                with self.assertRaisesRegex(RuntimeError, "observed release"):
                    reconstruct_stored_baseline(self.previous, self.payload)
        trimmed = {title: text.rstrip("\n") for title, text in self.previous.items()}
        trimmed_xml = build_xml(trimmed)
        rebound = {**self.binding, "exact_titles": [], "removed_lf_counts": {"1": 2, "2": 1},
                   "baseline_seed_bytes": len(trimmed_xml),
                   "baseline_seed_sha256": hashlib.sha256(trimmed_xml).hexdigest()}
        with patch("smoke_prefix.STORED_BASELINE_BINDING", rebound), self.assertRaisesRegex(RuntimeError, "observed release"):
            reconstruct_stored_baseline(self.previous, self.payload)

    def test_unknown_duplicate_or_generic_transform_identities_fail(self):
        for field, value in (
            ("exact_titles", ["Unknown"]), ("exact_titles", ["Other", "Other"]),
            ("historical_transform", "normalize-all-whitespace"),
        ):
            with patch("smoke_prefix.STORED_BASELINE_BINDING", {**self.binding, field: value}):
                with self.assertRaisesRegex(RuntimeError, "transform"):
                    reconstruct_stored_baseline(self.previous, self.payload)


class MaterializationTests(unittest.TestCase):
    actor = {"id": 1, "name": "Synthetic writer"}
    head = "0" * 40
    kind = "synthetic-unit-fixture"
    provenance = {"previous_source_head": "1" * 40, "evidence_kind": kind}

    def inputs(self):
        return (
            {"Stable": "same\n", "Legacy": "stored\n\n", "Changed": "old\n", "Noop": "old\n"},
            {"Stable": "same\n", "Legacy": "stored", "Changed": "old", "Noop": "new"},
            {"Stable": "same\n", "Legacy": "stored\n\n", "Changed": "new\r\n\r\n", "Noop": "new\n", "New": "created\n"},
        )

    def api(self, query, post=False):
        self.assertTrue(post)
        self.assertEqual(query["onlypst"], 1)
        self.assertEqual(query["assertuser"], self.actor["name"])
        self.assertNotIn(query["title"], {"Stable", "Legacy"})
        return {"parse": {"text": {"*": query["text"].rstrip("\r\n")},
                          "wikitext": {"*": query["text"]}}}

    def test_actual_transformed_text_is_used_and_unchanged_pages_are_not_trimmed(self):
        previous, baseline, authored = self.inputs()
        desired, receipt = materialize_desired(self.api, previous, baseline, authored, self.head, {}, self.actor,
                                               **self.provenance)
        self.assertEqual(desired, {"Changed": "new", "New": "created", "Stable": "same\n", "Legacy": "stored", "Noop": "new"})
        stable = next(row for row in receipt["pages"] if row["title"] == "Stable")
        self.assertIsNone(stable["only_pst_output"])
        self.assertIsNone(stable["removed_suffix"])
        legacy = next(row for row in receipt["pages"] if row["title"] == "Legacy")
        self.assertEqual(legacy["classification"], "unchanged")
        self.assertIsNone(legacy["only_pst_output"])
        self.assertIsNone(legacy["removed_suffix"])
        self.assertNotEqual(legacy["authored_sha256"], legacy["desired_sha256"])
        noop = next(row for row in receipt["pages"] if row["title"] == "Noop")
        self.assertEqual(noop["classification"], "storage-noop")
        self.assertEqual(noop["only_pst_output"], "new")
        self.assertEqual(noop["removed_suffix"], "\n")
        self.assertEqual(receipt["pages"][0]["removed_suffix"], "\r\n\r\n")
        self.assertEqual(receipt["evidence_kind"], self.kind)
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["previous_authored_seed_sha256"], hashlib.sha256(build_xml(previous)).hexdigest())
        self.assertEqual({row["title"]: row["action"] for row in plan_migration(baseline, baseline, desired)["pages"]},
                         {"Changed": "review-update", "New": "create", "Stable": "unchanged",
                          "Legacy": "unchanged", "Noop": "unchanged"})

    def test_source_changed_already_matching_storage_still_requires_actual_pst(self):
        calls = []
        def api(query, post=False):
            calls.append(query["title"])
            return self.api(query, post=post)
        desired, receipt = materialize_desired(api, {"Noop": "old"}, {"Noop": "new"}, {"Noop": "new"},
                                               self.head, {}, self.actor, **self.provenance)
        self.assertEqual(calls, ["Noop"])
        self.assertEqual(receipt["pages"][0]["classification"], "storage-noop")
        self.assertEqual(desired, {"Noop": "new"})

    def test_planned_order_omits_preserved_storage_and_storage_noops(self):
        baseline, desired, locations = PrefixTests().fixture()
        baseline.update({"Legacy": "stored", "Noop": "new"})
        desired.update({"Legacy": "stored", "Noop": "new"})
        order = planned_order(baseline, desired, locations, set(), set())
        self.assertNotIn("Legacy", order)
        self.assertNotIn("Noop", order)

    def test_live_conflicts_use_stored_baseline_not_previous_authored_whitespace(self):
        previous, baseline, authored = self.inputs()
        desired, _ = materialize_desired(self.api, previous, baseline, authored, self.head, {}, self.actor,
                                         **self.provenance)
        current = {**baseline, "Legacy": "community change", "Changed": "community change",
                   "New": "community collision"}
        actions = {row["title"]: row["action"] for row in plan_migration(baseline, current, desired)["pages"]}
        self.assertEqual(actions["Legacy"], "preserve-live")
        self.assertEqual(actions["Changed"], "conflict")
        self.assertEqual(actions["New"], "conflict")

    def test_missing_unknown_or_noncanonical_baseline_identities_fail_before_pst(self):
        previous, baseline, authored = self.inputs()
        for old, stored, new in (
            (None, baseline, authored), ({}, baseline, authored),
            ({**previous, "Unknown": "extra"}, baseline, authored),
            (previous, {**baseline, "Unknown": "extra"}, authored),
            (previous, {title: text for title, text in baseline.items() if title != "Legacy"}, authored),
            (previous, baseline, {title: text for title, text in authored.items() if title != "Legacy"}),
            ({"Some_page": "one", "Some page": "two"}, {"Some page": "one"}, {"Some page": "one"}),
            ({"": "invalid"}, {"": "invalid"}, {"": "invalid"}),
            ({"Page": None}, {"Page": ""}, {"Page": ""}),
        ):
            with self.subTest(previous=old), self.assertRaisesRegex(RuntimeError, "explicit|identities"):
                materialize_desired(lambda *args, **kwargs: self.fail("Invalid inputs must fail before PST"),
                                    old, stored, new, self.head, {}, self.actor, **self.provenance)
        with self.assertRaisesRegex(RuntimeError, "source commits"):
            materialize_desired(self.api, previous, baseline, authored, self.head, {}, self.actor,
                                previous_source_head=None, evidence_kind=self.kind)

    def test_wrong_onlypst_return_field_cannot_substitute_for_transformed_text(self):
        def wrong_field(query, post=False):
            return {"parse": {"wikitext": {"*": query["text"].rstrip("\r\n")}}}
        with self.assertRaisesRegex(RuntimeError, "transformed text"):
            materialize_desired(wrong_field, {}, {}, {"New": "created\n"}, self.head, {}, self.actor, **self.provenance)

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
                    materialize_desired(changed, {}, {}, {"New": authored}, self.head, {}, self.actor, **self.provenance)

    def test_source_runtime_actor_hash_and_suffix_mismatches_fail(self):
        previous, baseline, authored = self.inputs()
        desired, receipt = materialize_desired(self.api, previous, baseline, authored, self.head, {}, self.actor,
                                               **self.provenance)
        for field, value in (
            ("source_head_sha", "1" * 40), ("authored_seed_sha256", "1" * 64),
            ("baseline_seed_sha256", "1" * 64), ("desired_seed_sha256", "1" * 64),
            ("previous_authored_seed_sha256", "1" * 64), ("previous_source_head_sha", "2" * 40),
            ("runtime", {"different": True}), ("actor", {"id": 2, "name": "Different"}),
            ("acceptance", "php-rtrim"), ("schema_version", True),
            ("actor", {"id": True, "name": "Synthetic writer"}),
        ):
            with self.subTest(field=field):
                changed = {**receipt, field: value}
                with self.assertRaisesRegex(RuntimeError, "pins differ"):
                    verify_materialization(previous, baseline, authored, desired, changed, self.head, {}, self.actor,
                                           **self.provenance)
        changed = copy.deepcopy(receipt)
        changed["pages"][0]["removed_suffix"] = ""
        with self.assertRaisesRegex(RuntimeError, "per-title hashes"):
            verify_materialization(previous, baseline, authored, desired, changed, self.head, {}, self.actor,
                                   **self.provenance)
        for title, field, value in (
            ("Legacy", "removed_suffix", "\n\n"), ("Legacy", "only_pst_output", "stored"),
            ("Noop", "classification", "update"), ("Noop", "only_pst_output", None),
            ("New", "previous_authored_sha256", "1" * 64),
        ):
            changed = copy.deepcopy(receipt)
            next(row for row in changed["pages"] if row["title"] == title)[field] = value
            with self.subTest(title=title, field=field), self.assertRaisesRegex(RuntimeError, "per-title hashes"):
                verify_materialization(previous, baseline, authored, desired, changed, self.head, {}, self.actor,
                                       **self.provenance)
        for records in (receipt["pages"][:-1], receipt["pages"] + [receipt["pages"][-1]],
                        [{**receipt["pages"][0], "title": "Unknown"}, *receipt["pages"][1:]]):
            with self.assertRaisesRegex(RuntimeError, "title records"):
                verify_materialization(previous, baseline, authored, desired, {**receipt, "pages": records},
                                       self.head, {}, self.actor, **self.provenance)

    def test_unchanged_page_trimming_is_forbidden_even_with_recomputed_seed_hash(self):
        previous, baseline, authored = self.inputs()
        desired, receipt = materialize_desired(self.api, previous, baseline, authored, self.head, {}, self.actor,
                                               **self.provenance)
        for title, text in (("Stable", "same"), ("Legacy", authored["Legacy"])):
            changed = {**desired, title: text}
            rebound = {**receipt, "desired_seed_sha256": hashlib.sha256(build_xml(changed)).hexdigest()}
            with self.assertRaisesRegex(RuntimeError, "unchanged page"):
                verify_materialization(previous, baseline, authored, changed, rebound, self.head, {}, self.actor,
                                       **self.provenance)

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
