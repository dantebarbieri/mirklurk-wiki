import copy
from collections import Counter
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_wiki import EXPORT_NS, build_pages, build_xml, existing_titles, literal, title_key
from wiki_data import DataError, MAX_FACTS_BYTES, PAGE_FILES, RESEARCH_PAGE_FILES, load_data, parse_data, validate_data
from check_publication import blob_errors
from wiki_catalog import entry_owners, entry_relations, default_catalog, page_locations
from wiki_render import recipe_groups
from smoke_deploy import smoke_category_memberships, smoke_reader_release, wait_for_server_tick


def synthetic_data():
    reference = {"source": "synthetic", "section": "SyntheticTitles", "key": "1"}
    return {
        "schema_version": 1,
        "game": {"name": "MirkLurk", "developer": None, "build": None, "steam_app_id": 3972980},
        "sources": [{
            "id": "synthetic", "path": "Synthetic.ini",
            "sha256": hashlib.sha256(b"synthetic test evidence, not a game file").hexdigest(),
            "build": None,
        }],
        "entities": [{
            "id": "synthetic-item", "category": "item", "name": "Synthetic & <name>",
            "confidence": "observed", "evidence": [reference.copy()],
        }],
        "facts": [{
            "id": "synthetic-fact", "page": "Game mechanics", "entity": "Synthetic",
            "property": "Synthetic toggle", "value": True, "description": "Synthetic test statement.",
            "confidence": "inferred", "evidence": [reference.copy()],
        }],
    }


def research_data():
    data = synthetic_data()
    being = copy.deepcopy(data["entities"][0])
    being.update(id="synthetic-being", category="being", name="Synthetic merchant")
    data["entities"].append(being)
    details = {
        "quest": {"quest_id": "synthetic-journal-1", "stage": None},
        "merchant": {
            "merchant": "synthetic-being", "item": "synthetic-item", "quantity": None,
            "price": 2, "currency": "synthetic units", "location": None,
        },
        "recipe": {
            "station": "Synthetic station",
            "inputs": [{"item": "synthetic-item", "quantity": 2}],
            "outputs": [{"item": "synthetic-item", "quantity": 1}], "cost": None,
        },
        "loot": {
            "table": "synthetic-pool", "outcome": "synthetic-item",
            "quantity": {"min": 1, "max": 2}, "weight": 2, "probability": None,
            "rolls": None,
        },
        "algorithm": {
            "page": "Weather", "steps": ["An original synthetic step."],
            "fact_ids": ["synthetic-fact"],
        },
    }
    data["entries"] = [
        {
            "id": f"synthetic-{kind}", "kind": kind, "title": f"Synthetic {kind}",
            "summary": "Original synthetic summary; not a game claim.", "conditions": None,
            "confidence": "inferred", "evidence": copy.deepcopy(data["facts"][0]["evidence"]),
            "details": value,
        }
        for kind, value in details.items()
    ]
    return data


def illustration_data(approved=False):
    data = synthetic_data()
    data["illustrations"] = [{
        "id": "synthetic-picture", "entity": "synthetic-item", "file_title": "File:Synthetic.png",
        "caption": "Original synthetic caption.", "creator": None, "sha256": None,
        "rights_status": "pending", "rights_basis": None, "rights_note": None,
        "confidence": "inferred", "evidence": copy.deepcopy(data["entities"][0]["evidence"]),
    }]
    if approved:
        data["illustrations"][0].update(
            creator="Synthetic test creator", sha256=hashlib.sha256(b"no image bytes; schema test").hexdigest(),
            rights_status="approved", rights_basis="Synthetic schema fixture only",
            rights_note="This test does not provide or clear any actual artwork.",
        )
    return data


class SmokeClockTests(unittest.TestCase):
    def test_owner_edit_waits_for_a_distinct_server_second(self):
        api = Mock(side_effect=[
            {"curtimestamp": "2026-09-25T22:58:51Z"},
            {"curtimestamp": "2026-09-25T22:58:51Z"},
            {"curtimestamp": "2026-09-25T22:58:52Z"},
        ])
        with patch("smoke_deploy.time.sleep") as sleep:
            wait_for_server_tick(api)
        self.assertEqual(api.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        for call in api.call_args_list:
            self.assertEqual(call.args, ({"action": "query", "curtimestamp": 1},))

    def test_stopped_or_backward_server_clock_fails_within_the_bound(self):
        for later in ("2026-09-25T22:58:51Z", "2026-09-25T22:58:50Z"):
            with self.subTest(later=later):
                api = Mock(side_effect=[{"curtimestamp": "2026-09-25T22:58:51Z"}]
                           + [{"curtimestamp": later}] * 20)
                with patch("smoke_deploy.time.sleep") as sleep, self.assertRaisesRegex(RuntimeError, "clock"):
                    wait_for_server_tick(api)
                self.assertEqual(api.call_count, 2 if later.endswith("50Z") else 21)
                self.assertEqual(sleep.call_count, 1 if later.endswith("50Z") else 20)


class SmokeCategoryTests(unittest.TestCase):
    def setUp(self):
        groups = ["Category:" + name for name in ("Wanderer", "Survivor", "Hunter", "Warrior", "Forager")]
        self.memberships = {
            "Skills": [], "Sample skill": ["Category:Skills", "Category:Wanderer"],
            "Browse only": [], "Category:Skills": [],
            **{group: ["Category:Skills"] for group in groups},
            **{f"Uncategorized {number}": [] for number in range(55)},
        }
        self.browse = {
            "Skills": ["Category:Skills", *groups],
            "Category:Skills": groups,
            **{group: ["Category:Skills"] for group in groups},
        }
        self.pages = {
            title: " ".join(f"[[{category}]]" for category in categories)
                   + " ".join(f"[[:{category}|Browse]]" for category in self.browse.get(title, []))
            for title, categories in self.memberships.items()
        }
        self.pages["Browse only"] = "[[:Category:Wanderer|Not a membership]]"
        self.pages["Category:Skills"] += "[[:Category:Skills|Self-link]]"
        self.calls = []

    def api(self, parameters):
        self.calls.append(parameters)
        if parameters["action"] == "parse":
            return {"parse": {"links": [
                {"ns": 14, "*": title, "exists": ""} for title in self.browse.get(parameters["page"], [])
            ]}}
        titles = parameters["titles"].split("|")
        category_slice = slice(1, None) if parameters.get("clcontinue") else slice(0, 1)
        result = {"query": {"pages": {
            str(number): {
                "title": title, "ns": 14 if title.startswith("Category:") else 0,
                "categories": [{"ns": 14, "title": category} for category in self.memberships[title][category_slice]],
            }
            for number, title in enumerate(titles, 1)
        }}}
        if not parameters.get("clcontinue"):
            result["continue"] = {"continue": "||", "clcontinue": "second-page"}
        return result

    def test_actual_memberships_are_batched_continued_and_not_browse_links(self):
        smoke_category_memberships(self.api, self.pages)
        queries = [call for call in self.calls if call["action"] == "query"]
        self.assertEqual(len(queries), 4)
        self.assertTrue(all(len(call["titles"].split("|")) <= 50 for call in queries))
        self.assertTrue(all(call["prop"] == "categories" and call["cllimit"] == "max" for call in queries))
        self.assertEqual(sum(call.get("clcontinue") == "second-page" for call in queries), 2)
        for call in queries:
            if "clcontinue" in call:
                self.assertEqual(call["continue"], "||")
        self.assertEqual({call["page"] for call in self.calls if call["action"] == "parse"}, set(self.browse))

    def test_continuation_can_omit_already_completed_pages(self):
        def api(parameters):
            result = self.api(parameters)
            if parameters.get("clcontinue"):
                result["query"]["pages"] = {
                    key: row for key, row in result["query"]["pages"].items() if row["categories"]
                }
            return result
        smoke_category_memberships(api, self.pages)

    def test_missing_extra_and_wrong_namespace_results_fail_explicitly(self):
        for mutation in ("omit", "missing", "namespace", "category-namespace", "missing-category", "extra-category"):
            with self.subTest(mutation=mutation):
                def api(parameters):
                    result = self.api(parameters)
                    if parameters["action"] == "query":
                        rows = result["query"]["pages"]
                        key = next((key for key, row in rows.items() if row["title"] == "Sample skill"), None)
                        if key is not None:
                            if mutation == "omit":
                                del rows[key]
                            elif mutation == "missing":
                                rows[key]["missing"] = ""
                            elif mutation == "namespace":
                                rows[key]["ns"] = 14
                            elif mutation == "category-namespace":
                                rows[key]["categories"] = [{"ns": 0, "title": "Category:Skills"}]
                            elif mutation == "missing-category":
                                rows[key]["categories"] = []
                            else:
                                rows[key]["categories"].append({"ns": 14, "title": "Category:Unexpected"})
                    return result
                with self.assertRaisesRegex(RuntimeError, "Category"):
                    smoke_category_memberships(api, self.pages)
        self.memberships["Category:Wanderer"] = []
        with self.assertRaisesRegex(RuntimeError, "membership mismatch for Category:Wanderer"):
            smoke_category_memberships(self.api, self.pages)

    def test_skills_and_category_parent_child_browse_links_must_exist(self):
        for title in ("Skills", "Category:Skills", "Category:Wanderer"):
            for mutation in ("omit", "missing"):
                with self.subTest(title=title, mutation=mutation):
                    def api(parameters):
                        result = self.api(parameters)
                        if parameters["action"] == "parse" and parameters["page"] == title:
                            if mutation == "omit":
                                result["parse"]["links"] = []
                            else:
                                for link in result["parse"]["links"]:
                                    link.pop("exists")
                        return result
                    with self.assertRaisesRegex(RuntimeError, "browse links did not resolve"):
                        smoke_category_memberships(api, self.pages)

    def test_continuation_cannot_repeat_override_queries_or_run_forever(self):
        for mutation in ("repeat", "override", "unbounded"):
            with self.subTest(mutation=mutation):
                calls = 0
                def api(parameters):
                    nonlocal calls
                    calls += 1
                    result = self.api(parameters)
                    result["continue"] = {"continue": "||", "clcontinue": str(calls) if mutation == "unbounded" else "repeat"}
                    if mutation == "override":
                        result["continue"]["titles"] = "Unrelated"
                    return result
                with self.assertRaisesRegex(RuntimeError, "continuation"):
                    smoke_category_memberships(api, self.pages)
                self.assertLessEqual(calls, 100)

    def test_reader_release_invokes_actual_category_verification(self):
        with patch("smoke_deploy.smoke_category_memberships", side_effect=RuntimeError("category probe")) as probe:
            with self.assertRaisesRegex(RuntimeError, "category probe"):
                smoke_reader_release(self.api, self.pages, {}, {}, {}, {})
        probe.assert_called_once_with(self.api, self.pages)


class DataTests(unittest.TestCase):
    def test_curated_json_exact_size_boundary(self):
        raw = json.dumps(synthetic_data()).encode()
        at_limit = raw + b" " * (MAX_FACTS_BYTES - len(raw))
        self.assertEqual(MAX_FACTS_BYTES, 655360)
        self.assertEqual(parse_data(at_limit)["schema_version"], 1)
        self.assertEqual(blob_errors("content/facts/game.json", at_limit), [])
        with self.assertRaises(DataError):
            parse_data(at_limit + b" ")
        self.assertIn("limit", blob_errors("content/facts/game.json", at_limit + b" ")[0])

    def test_expanded_snapshot_preserves_the_complete_vetted_handoff(self):
        data = load_data(ROOT / "content" / "facts" / "game.json")
        self.assertEqual(
            {key: len(data[key]) for key in ("sources", "entities", "facts", "entries")},
            {"sources": 5, "entities": 336, "facts": 107, "entries": 293},
        )
        self.assertEqual(
            Counter(entry["kind"] for entry in data["entries"]),
            {"quest": 31, "merchant": 63, "recipe": 96, "loot": 70, "algorithm": 33},
        )
        extension = {"sources": [], "entities": [], "facts": data["facts"][79:], "entries": data["entries"][:249]}
        raw = json.dumps(extension, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "a850094c2624cf2db5262bea5bc6647954de639cefc90a7f3d2adcc3a62ec270")
        supplement = {"sources": [], "entities": [], "facts": [], "entries": data["entries"][249:]}
        raw = json.dumps(supplement, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "2c5261500e871c46dfaa0ee7d62c69592c2349726293be3ee9772d13da00e3c2")
        self.assertEqual(data.get("illustrations", []), [])
        pages = build_pages(ROOT, data)
        self.assertEqual(len(pages), 368)
        self.assertTrue(RESEARCH_PAGE_FILES.keys() <= pages.keys())
        for title in RESEARCH_PAGE_FILES:
            self.assertIn(f"[[{title}]]", pages["Main Page"])
        self.assertIn("[[Loot mechanics", pages["Loot tables"])
        self.assertIn("Budgeted creature treasure", pages["Loot mechanics"])
        self.assertIn("reproducibility has not been demonstrated", pages["World seed logic"])
        self.assertIn("0.8.1.5", pages["Game mechanics"])
        self.assertIn("versionString", pages["Source provenance"])
        self.assertNotIn("versionString", pages["Game mechanics"])

    def test_curated_payload_and_expected_shape(self):
        data = load_data(ROOT / "content" / "facts" / "game.json")
        baseline = {
            "sources": (5, "8dae164eff56d6bbd220051cded80d2fa6f4dd130b8adff3f471f8c82ed75508"),
            "entities": (336, "947b17faa67b5e8fc50a37d2a0a13ee73157c6c32ea9f2ce80a895a452b8a92e"),
            "facts": (79, "cc0c1c66f198029fffe8fa1de023fcbd1d5c5d59722d328b4d6d320aa358dc7e"),
        }
        for key, (count, digest) in baseline.items():
            records = sorted(data[key][:count], key=lambda record: record["id"])
            raw = json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest, f"Original {key} changed")
        self.assertEqual(data["game"]["build"], "0.8.1.5")
        self.assertEqual(
            {confidence: sum(f["confidence"] == confidence for f in data["facts"][:79])
             for confidence in ("localization-described", "inferred")},
            {"localization-described": 28, "inferred": 51},
        )
        pages = build_pages(ROOT, data)
        self.assertTrue(set(PAGE_FILES) <= pages.keys())
        self.assertIn("not a guarantee", pages["Source provenance"])
        self.assertIn("non-hostile", pages["Bestiary"])

    def test_valid_boolean_and_numeric_values(self):
        for value in (True, False, 0, -4, 2.5):
            data = synthetic_data()
            data["facts"][0]["value"] = value
            self.assertIs(validate_data(data), data)

    def test_invalid_or_unvetted_shapes_are_rejected(self):
        changes = [
            lambda d: d.update(raw_dump="not allowed"),
            lambda d: d.update(schema_version=True),
            lambda d: d["game"].update(steam_app_id=True),
            lambda d: d["sources"][0].update(path="../Synthetic.ini"),
            lambda d: d["sources"][0].update(path="/Synthetic.ini"),
            lambda d: d["sources"][0].update(path="Z:\\Synthetic.ini"),
            lambda d: d["sources"][0].update(path="export.json"),
            lambda d: d["sources"][0].update(sha256="invalid"),
            lambda d: d["sources"].append(copy.deepcopy(d["sources"][0])),
            lambda d: d["entities"][0].update(name="Copied paragraph.\nMore prose."),
            lambda d: d["entities"][0].update(category="enemy"),
            lambda d: d["entities"][0].update(category=[]),
            lambda d: d["entities"][0].update(confidence=[]),
            lambda d: d["entities"][0].update(group="missing"),
            lambda d: d["entities"][0].update(category="skill", group="missing"),
            lambda d: d["entities"].append(copy.deepcopy(d["entities"][0])),
            lambda d: d["facts"][0].update(value="copied text"),
            lambda d: d["facts"][0].update(value=float("nan")),
            lambda d: d["facts"][0].update(value=float("inf")),
            lambda d: d["facts"][0].update(value=10**16),
            lambda d: d["facts"][0].update(page="Template:Injected"),
            lambda d: d["facts"][0].update(confidence="verified"),
            lambda d: d["facts"][0].update(description="x" * 501),
            lambda d: d["facts"][0].update(evidence=[]),
            lambda d: d["facts"][0]["evidence"][0].update(source="missing"),
            lambda d: d["facts"][0]["evidence"].append(copy.deepcopy(d["facts"][0]["evidence"][0])),
        ]
        for number, change in enumerate(changes):
            with self.subTest(case=number):
                data = synthetic_data()
                change(data)
                with self.assertRaises(DataError):
                    validate_data(data)

    def test_duplicate_json_keys_and_nonfinite_constants_fail(self):
        for raw in (b'{"x":1,"x":2}', b'{"value":NaN}', b"\xff"):
            with self.assertRaises(DataError):
                parse_data(raw)

    def test_skill_relationship_requires_a_real_group(self):
        data = synthetic_data()
        group = copy.deepcopy(data["entities"][0])
        group.update(id="synthetic-group", category="skill_group")
        data["entities"][0].update(category="skill", group=group["id"])
        data["entities"].append(group)
        validate_data(data)
        self.assertIn("Synthetic &amp; &lt;name&gt;", build_pages(ROOT, data)["Skills"])


class ResearchTests(unittest.TestCase):
    def test_quests_render_prologue_then_numeric_stages_and_related_location(self):
        data = research_data()
        quest = data["entries"][0]
        expected = [
            ("journal-first", "First"), ("journal-1", "1"), ("journal-2", "2"),
            ("journal-7", "7"), ("journal-7-location", "7"),
            ("journal-10", "10"), ("journal-30", "30"),
            ("fallback-z", "Appendix"), ("fallback-a", "Epilogue"),
        ]
        data["entries"] = []
        for identity, quest_id in reversed(expected):
            entry = copy.deepcopy(quest)
            entry["id"] = identity
            entry["details"]["quest_id"] = quest_id
            data["entries"].append(entry)
        original = copy.deepcopy(data)
        page = build_pages(ROOT, data)["Quests and journal"]
        self.assertEqual(
            re.findall(r'<span id="entry-([^"]+)"></span>', page),
            [identity for identity, _ in expected],
        )
        self.assertEqual(data, original)
        data["entries"].reverse()
        self.assertEqual(build_pages(ROOT, data)["Quests and journal"], page)

    def test_entry_groups_retain_deterministic_record_order(self):
        data = load_data(ROOT / "content" / "facts" / "game.json")
        catalog = default_catalog(data)
        owners = entry_owners(data, page_locations(data, catalog), entry_relations(data, catalog))
        pages = build_pages(ROOT, data)
        kinds = {entry["id"]: entry["kind"] for entry in data["entries"]}
        for title, page in pages.items():
            if title == "Quests and journal":
                continue
            with self.subTest(page=title):
                identities = [identity for identity in re.findall(r'<span id="entry-([^"]+)"></span>', page) if owners[identity] == title]
                for kind in ("merchant", "loot", "algorithm"):
                    matching = [identity for identity in identities if kinds[identity] == kind]
                    self.assertEqual(matching, sorted(matching))
                recipes = [entry for entry in data["entries"] if entry["kind"] == "recipe" and owners[entry["id"]] == title]
                grouped = recipe_groups(sorted(recipes, key=lambda entry: entry["id"]))
                self.assertEqual([identity for identity in identities if kinds[identity] == "recipe"],
                                 [entry["id"] for group in grouped for entry in group])

    def test_original_version_one_needs_no_extension_fields(self):
        data = synthetic_data()
        validate_data(data)
        pages = build_pages(ROOT, data)
        self.assertEqual(set(pages), {*PAGE_FILES, "Source provenance", "NPCs", "Entity synthetic-item", "Category:Items"})
        self.assertNotIn("More researched topics", pages["Main Page"])
        self.assertNotIn("Illustration references", pages["Items"])

    def test_typed_entries_render_with_evidence_and_unknowns(self):
        data = research_data()
        pages = build_pages(ROOT, data)
        self.assertIn("Quests and journal", pages)
        self.assertIn("[[Merchants]]", pages["Main Page"])
        self.assertNotIn("World seed logic", pages)
        self.assertNotIn("[[World seed logic]]", pages["Main Page"])
        self.assertIn("Not established", pages["Synthetic merchant"])
        self.assertIn("not converted to probabilities", pages["Synthetic merchant"])
        self.assertNotIn("50%", pages["Synthetic merchant"])
        self.assertIn("[[Entity synthetic-item|", pages["Entity synthetic-item"])
        self.assertIn("[[Game mechanics]]", pages["Weather"])
        self.assertIn("[[Source provenance#synthetic|synthetic]]", pages["Source provenance"])
        for title in ("Quests and journal", "Synthetic merchant", "Entity synthetic-item", "Weather"):
            self.assertNotIn("Source / section / key", pages[title])
            self.assertNotIn("Evidence status", pages[title])

    def test_topic_fact_without_entry_activates_only_its_page(self):
        data = synthetic_data()
        data["facts"][0]["page"] = "World seed logic"
        pages = build_pages(ROOT, data)
        self.assertIn("World seed logic", pages)
        self.assertEqual(set(pages) & RESEARCH_PAGE_FILES.keys(), {"World seed logic"})
        self.assertIn("[[World seed logic]]", pages["Main Page"])

    def test_all_algorithm_destinations_are_supported(self):
        for title in ("Weather", "Level progression", "World seed logic", "Skills", "Crafting", "Loot tables"):
            data = research_data()
            data["entries"][-1]["details"]["page"] = title
            owner = {"Loot tables": "Loot mechanics", "Skills": "Level progression"}.get(title, title)
            self.assertIn("An original synthetic step.", build_pages(ROOT, data)[owner])

    def test_explicit_empty_result_is_not_an_unknown_item(self):
        for quantity in (None, {"min": 0, "max": 0}):
            data = research_data()
            details = data["entries"][3]["details"]
            details.update(outcome=None, quantity=quantity, probability=0.25, rolls={"min": 0, "max": 1})
            page = build_pages(ROOT, data)["Synthetic merchant"]
            self.assertIn("No items", page)
            self.assertIn("<nowiki>25</nowiki>%", page)

    def test_invalid_structured_claims_fail(self):
        changes = [
            lambda d: d["entries"][0].update(summary="x" * 1201),
            lambda d: d["entries"][0].update(summary="not\none line"),
            lambda d: d["entries"][0].update(evidence=[]),
            lambda d: d["entries"][0].update(conditions=True),
            lambda d: d["entries"][0].update(kind="unknown"),
            lambda d: d["entries"][0]["details"].update(raw_journal="copied"),
            lambda d: d["entries"].append(copy.deepcopy(d["entries"][0])),
            lambda d: d["entries"][1]["details"].update(merchant="synthetic-item"),
            lambda d: d["entries"][1]["details"].update(item="missing"),
            lambda d: d["entries"][1]["details"].update(quantity=True),
            lambda d: d["entries"][1]["details"].update(quantity=0),
            lambda d: d["entries"][1]["details"].update(price=-1),
            lambda d: d["entries"][1]["details"].update(currency=None),
            lambda d: d["entries"][2]["details"].update(outputs=[]),
            lambda d: d["entries"][2]["details"]["inputs"][0].update(quantity=0.5),
            lambda d: d["entries"][2]["details"]["inputs"].append({"item": "synthetic-item", "quantity": 1}),
            lambda d: d["entries"][2]["details"].update(cost={"amount": -1, "unit": "synthetic"}),
            lambda d: d["entries"][3]["details"].update(probability=1.01),
            lambda d: d["entries"][3]["details"].update(weight=float("nan")),
            lambda d: d["entries"][3]["details"].update(weight=float("inf")),
            lambda d: d["entries"][3]["details"].update(outcome=None),
            lambda d: d["entries"][3]["details"].update(quantity={"min": 2, "max": 1}),
            lambda d: d["entries"][3]["details"].update(rolls={"min": False, "max": 1}),
            lambda d: d["entries"][4]["details"].update(page="Template:Injected"),
            lambda d: d["entries"][4]["details"].update(steps=[]),
            lambda d: d["entries"][4]["details"].update(fact_ids=["missing"]),
            lambda d: d["entries"][4]["details"].update(fact_ids=["synthetic-fact", "synthetic-fact"]),
        ]
        for number, change in enumerate(changes):
            with self.subTest(case=number):
                data = research_data()
                change(data)
                with self.assertRaises(DataError):
                    validate_data(data)

    def test_research_text_is_literal_and_output_is_deterministic(self):
        data = research_data()
        data["entries"][0]["summary"] = '</nowiki>{{No template}}|[[No link]]<script>'
        original = build_xml(build_pages(ROOT, data))
        data["entries"].reverse()
        for key in ("facts", "entities", "sources"):
            data[key].reverse()
        self.assertEqual(original, build_xml(build_pages(ROOT, data)))
        self.assertIn("&amp;lt;/nowiki", original.decode())
        self.assertNotIn("<script>", original.decode())

    def test_pending_images_never_embed_or_link_artwork(self):
        pages = build_pages(ROOT, illustration_data())
        self.assertIn("No reviewed picture", pages["Entity synthetic-item"])
        self.assertNotIn("[[File:", pages["Entity synthetic-item"])
        self.assertNotIn("[[:File:", pages["Entity synthetic-item"])

    def test_approved_references_have_domain_independent_attribution(self):
        pages = build_pages(ROOT, illustration_data(approved=True))
        self.assertIn("[[File:Synthetic.png|thumb|", pages["Entity synthetic-item"])
        self.assertIn("Synthetic test creator", pages["Source provenance"])
        self.assertNotIn("https://", pages["Entity synthetic-item"])

    def test_invalid_illustration_metadata_is_rejected(self):
        changes = [
            lambda i: i.update(entity="missing"),
            lambda i: i.update(file_title="https://example.invalid/image.png"),
            lambda i: i.update(file_title="File:../../Image.png"),
            lambda i: i.update(file_title="File:Image.svg"),
            lambda i: i.update(file_title="File:Image.png|link=Injected"),
            lambda i: i.update(file_title="File:Image]].png"),
            lambda i: i.update(rights_status="assumed"),
            lambda i: i.update(rights_status="approved"),
            lambda i: i.update(sha256="invalid"),
            lambda i: i.update(evidence=[]),
        ]
        for number, change in enumerate(changes):
            with self.subTest(case=number):
                data = illustration_data()
                change(data["illustrations"][0])
                with self.assertRaises(DataError):
                    validate_data(data)
        data = illustration_data(approved=True)
        duplicate = copy.deepcopy(data["illustrations"][0])
        duplicate["id"] = "another-picture"
        data["illustrations"].append(duplicate)
        with self.assertRaises(DataError):
            validate_data(data)


class HealthArmorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from wiki_details import load_publication_inputs
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)

    def test_shields_replace_only_occupied_armored_cells_at_exact_levels(self):
        from smoke_deploy import RenderedGrids
        from wiki_render import cell_grid
        self.assertEqual(hashlib.sha256(json.dumps(self.details["grids"], sort_keys=True).encode()).hexdigest(),
                         "d693bb51f80cbd3ad1502cd260c6eca44351c9bd3f1d4f8fda87eb75d3bb693b")
        totals = {0: 0, 1: 0, 2: 0, 3: 0}
        for grid in self.details["grids"]:
            rendered = cell_grid(grid, "being", self.data["illustrations"])
            parsed = RenderedGrids()
            parsed.feed(rendered)
            self.assertEqual([len(row) for row in parsed.grids[0]], [len(row) for row in grid["rows"]])
            for y, (expected_row, row) in enumerate(zip(grid["rows"], parsed.grids[0]), 1):
                for x, (expected, cell) in enumerate(zip(expected_row, row), 1):
                    with self.subTest(grid=grid["id"], row=y, column=x):
                        position = f"Row {y}, column {x}: "
                        if expected is None:
                            self.assertEqual(cell["attrs"]["aria-label"], position + "empty")
                            self.assertEqual(cell["text"], "")
                            self.assertEqual(cell["attrs"]["class"], "grid-hole")
                        elif grid["kind"] == "health":
                            armor = expected["armor"]
                            totals[armor] += 1
                            description = position + f"1 HP, {armor} armor layers"
                            self.assertEqual(cell["attrs"]["aria-label"], description)
                            if armor:
                                name = {1: "bronze", 2: "silver", 3: "gold"}[armor]
                                label = f'1 HP, {armor} armor {"layer" if armor == 1 else "layers"} ({name} shield)'
                                self.assertEqual(cell["text"], f'[[File:Health-armor-{armor}.png|32px|alt={label}|{label}]]')
                                self.assertEqual(cell["attrs"]["title"], description)
                                self.assertEqual(cell["icon_styles"], ["image-rendering:pixelated;"])
                            else:
                                self.assertEqual(cell["text"], "1 HP")
                            self.assertIn("background:#852c36;", cell["attrs"]["style"])
                            self.assertIn("min-width:3em;height:3em;padding:0.25em;", cell["attrs"]["style"])
                        else:
                            visible = str(expected["min"]) if expected["min"] == expected["max"] else f'{expected["min"]}-{expected["max"]}'
                            self.assertEqual(cell["text"], visible)
                            self.assertEqual(cell["attrs"]["aria-label"], position + visible + " damage")
                        if expected is None or grid["kind"] != "health" or not expected["armor"]:
                            self.assertNotIn("Health-armor-", cell["text"])
                            self.assertEqual(cell["icon_styles"], [])
            self.assertNotIn("#663d24", rendered)
        self.assertEqual(totals, {0: 259, 1: 189, 2: 22, 3: 10})
        self.assertEqual(sum(page.count('class="health-armor-icon"') for page in self.pages.values()), 224)
        guide = self.pages["Health and armor"]
        for armor, name in ((1, "Bronze"), (2, "Silver"), (3, "Gold")):
            self.assertEqual(guide.count(f"[[File:Health-armor-{armor}.png|32px|"), 1)
            self.assertIn(f"{name} shield: {armor} armor", guide)

    def test_shared_shields_require_finite_targets_and_approved_metadata(self):
        from wiki_details import parse_illustrations
        base = load_data(ROOT / "content" / "facts" / "game.json")
        shields = [copy.deepcopy(row) for row in self.data["illustrations"] if "health_armor" in row]
        self.assertEqual([row["health_armor"] for row in shields], [1, 2, 3])
        for change in (
            lambda i: i.update(health_armor=0), lambda i: i.update(health_armor=4),
            lambda i: i.update(health_armor=True), lambda i: i.update(health_armor="1"),
            lambda i: i.update(entity="item-0"), lambda i: i.update(station="armor-workstation"),
            lambda i: i.update(variant="early-game"),
            lambda i: i.update(file_title="File:Health-armor-2.png"),
            lambda i: i.update(file_title="File:Invented-shield.png"),
            lambda i: i.update(sha256=None), lambda i: i.update(creator=None),
            lambda i: i.update(rights_basis=None), lambda i: i.update(rights_note=None),
            lambda i: i.update(evidence=[]),
        ):
            image = copy.deepcopy(shields[0])
            change(image)
            with self.assertRaises(DataError):
                parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [image]}).encode(), base, self.catalog)
        duplicate = dict(shields[0], id="duplicate-shield")
        with self.assertRaisesRegex(DataError, "duplicate armor level"):
            parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [*shields, duplicate]}).encode(), base)
        for armor in (1, 2, 3):
            for state in ("missing", "pending"):
                data = copy.deepcopy(self.data)
                if state == "missing":
                    data["illustrations"] = [row for row in data["illustrations"] if row.get("health_armor") != armor]
                else:
                    next(row for row in data["illustrations"] if row.get("health_armor") == armor).update(
                        rights_status="pending", creator=None, sha256=None, rights_basis=None, rights_note=None)
                with self.subTest(armor=armor, state=state), self.assertRaisesRegex(
                    DataError, f"health armor {armor}: an approved shield illustration is required"
                ):
                    build_pages(ROOT, data, self.catalog, self.details)
        data = dict(self.data, illustrations=[row for row in self.data["illustrations"] if "health_armor" not in row])
        with self.assertRaisesRegex(DataError, "approved shield illustration is required"):
            build_pages(ROOT, data, self.catalog, self.details)


class ExportTests(unittest.TestCase):
    def test_deterministic_independent_of_input_order(self):
        data = load_data(ROOT / "content" / "facts" / "game.json")
        original = build_xml(build_pages(ROOT, data))
        reversed_data = copy.deepcopy(data)
        for key in ("sources", "entities", "facts", "entries", "illustrations"):
            if key not in reversed_data:
                continue
            reversed_data[key].reverse()
        for record in reversed_data["entities"] + reversed_data["facts"] + reversed_data.get("entries", []) + reversed_data.get("illustrations", []):
            record["evidence"].reverse()
        self.assertEqual(original, build_xml(build_pages(ROOT, reversed_data)))

    def test_xml_roundtrip_and_byte_counts(self):
        pages = {"A & <title>": "Original <text> & {{literal wiki markup}}\n"}
        root = ET.fromstring(build_xml(pages))
        ns = {"m": EXPORT_NS}
        self.assertEqual(root.findtext("m:page/m:title", namespaces=ns), next(iter(pages)))
        text = root.find("m:page/m:revision/m:text", ns)
        self.assertEqual(text.text, next(iter(pages.values())))
        self.assertEqual(int(text.attrib["bytes"]), len(text.text.encode("utf-8")))

    def test_untrusted_fact_strings_cannot_escape_nowiki(self):
        value = '</nowiki>{{INJECTED}}|[[Injected]]<script>&"'
        escaped = literal(value)
        self.assertEqual(escaped.count("</nowiki>"), 1)
        self.assertNotIn("<script>", escaped)
        self.assertIn("&lt;/nowiki&gt;", escaped)
        data = synthetic_data()
        data["entities"][0]["name"] = value
        payload = build_xml(build_pages(ROOT, data))
        ET.fromstring(payload)
        self.assertIn("&amp;lt;/nowiki", payload.decode())

    def test_existing_title_filter_never_includes_an_existing_page(self):
        with tempfile.TemporaryDirectory() as folder:
            export = Path(folder) / "current.xml"
            export.write_bytes(build_xml({"main_Page": "Live edit, not repository text.\n"}))
            excluded = existing_titles(export)
            pages = build_pages(ROOT, synthetic_data())
            new_pages = {title: text for title, text in pages.items() if title_key(title) not in excluded}
            self.assertNotIn("Main Page", new_pages)
            self.assertEqual(len(new_pages), len(pages) - 1)
            self.assertNotIn("Live edit", build_xml(new_pages).decode())

    def test_incomplete_or_wrong_export_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            export = Path(folder) / "invalid.xml"
            for raw in (
                b"<unexpected/>", b"<mediawiki",
                f'<mediawiki xmlns="{EXPORT_NS}"/>'.encode(),
                f'<mediawiki xmlns="{EXPORT_NS}"><siteinfo/><page><title>x</title></page></mediawiki>'.encode(),
            ):
                export.write_bytes(raw)
                with self.assertRaises(DataError):
                    existing_titles(export)

    def test_cli_requires_mode_and_refuses_output_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "seed.xml"
            command = [sys.executable, str(ROOT / "tools" / "build_wiki.py"), "--output", str(output)]
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            success = subprocess.run(command + ["--fresh"], capture_output=True)
            self.assertEqual(success.returncode, 0, success.stderr.decode())
            original = output.read_bytes()
            self.assertNotEqual(subprocess.run(command + ["--fresh"], capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), original)
            filtered = Path(folder) / "missing.xml"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "build_wiki.py"), "--existing-export",
                 str(output), "--output", str(filtered)],
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(ET.parse(filtered).getroot().findall(f"{{{EXPORT_NS}}}page"), [])


if __name__ == "__main__":
    unittest.main()
