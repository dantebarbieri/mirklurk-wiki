import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_data import DataError, load_data
from wiki_details import load_publication_inputs
from wiki_render import build_pages
from wiki_tester import load_tester
from smoke_deploy import require_image_coverage, synthetic_image_specs


class TesterDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = load_publication_inputs(ROOT)
        cls.stable = cls.inputs[0]
        cls.tester = load_tester(ROOT, cls.stable)
        cls.pages = build_pages(ROOT, *cls.inputs)

    def test_promoted_pages_use_release_defaults_without_inventing_merchant_stock(self):
        before = copy.deepcopy(self.stable)
        pages = build_pages(ROOT, *self.inputs)
        self.assertEqual(self.stable, before)
        self.assertEqual(self.stable["game"]["build"], "1.0.1.5")
        self.assertLessEqual({row["id"] for row in self.tester["data"]["entities"]},
                             {row["id"] for row in self.stable["entities"]})
        self.assertIn("'''Current version:''' 1.0.1.5", pages["Main Page"])
        self.assertNotIn("== 0.9.9.7 tester ==", pages["Finish Raft"])
        for entity in self.tester["data"]["entities"]:
            text = pages[entity["name"]]
            self.assertNotIn("tester only (next_version_tester)", text)
            self.assertIn("does not establish merchant stock", text)
            self.assertNotIn("can be bought", text)
            self.assertNotIn("crafted, bought", text)
            self.assertNotIn("Merchants sell", text)
            self.assertNotIn("New in [[Version 0.9.9.7", text)
            self.assertNotIn("0.9.9.7", text)
        self.assertIn("[[Inventory crafting]]", pages["Sturdy Shortbow"])
        self.assertIn("{{Item|Twine|quantity=2}}", pages["Sturdy Shortbow"])
        self.assertIn("{{Item|Branch (Trollgnarl)|quantity=2}}", pages["Sturdy Shortbow"])
        self.assertIn("{{Item|Spider Silk|quantity=10}}", pages["Sturdy Shortbow"])
        self.assertIn("[[Piercing|", pages["Sturdy Shortbow"])
        self.assertNotIn("2.4000000000000004", pages["Sturdy Shortbow"])

    def test_release_access_and_exposure_have_one_current_stable_reference(self):
        meat = self.pages["Grilled Spider Meat"]
        self.assertNotIn("== 0.9.9.7 tester ==", meat)
        self.assertIn("burning Campfire", meat)
        self.assertNotIn("access to this crafting option is unconfirmed", meat)
        self.assertIn("Previously saved areas do not receive", self.pages["World generation"])
        self.assertIn("not 12.5% or 10%", self.pages["Deathlob"])
        self.assertIn("normalized 0.35", self.pages["Temperature"])
        self.assertIn("ordinary population updater still exits", self.pages["World generation"])
        self.assertEqual(self.pages["Version 0.9.9.7"], "#REDIRECT [[Version 1.0.0.0]]\n")
        for note in self.tester["page_notes"]:
            self.assertNotIn("== 0.9.9.7 tester ==", self.pages[note["page"]])
        for title in ("Main Page", "Versions", "Game mechanics", "World generation",
                      "Crafting", "Version 1.0.0.0", "Version 1.0.1.0", "Version 1.0.1.5"):
            self.assertNotIn("0.9.9.7", self.pages[title], title)
            self.assertNotIn("tester", self.pages[title].lower(), title)
        self.assertEqual(hashlib.sha256((ROOT / "content" / "facts" / "tester.json").read_bytes()).hexdigest(),
                         "d8c468049e2a2b483ff7cb775aaf09dd3a40645f6a7fec5ff346329d01eeb481")

    def test_promoted_art_reuses_the_approved_tester_records_and_smoke_pixels(self):
        images = self.tester["data"]["illustrations"]
        specs = synthetic_image_specs(self.stable, images)
        require_image_coverage(specs, {row["name"]: self.pages[row["name"]]
                                       for row in self.tester["data"]["entities"]})
        for image in images:
            self.assertIn(image, self.stable["illustrations"])
            self.assertIn(image["file_title"].removeprefix("File:"), specs)
            title = next(row["name"] for row in self.tester["data"]["entities"] if row["id"] == image["entity"])
            self.assertIn(image["caption"].replace(" (0.9.9.7 tester)", ""), self.pages[title])

    def test_base_only_release_render_preserves_the_legacy_redirect_without_overlays(self):
        pages = build_pages(ROOT, load_data(ROOT / "content" / "facts" / "game.json"))
        self.assertIn("Version 0.9.9.7", pages)
        self.assertEqual(pages["Version 0.9.9.7"], "#REDIRECT [[Version 1.0.0.0]]\n")
        self.assertNotIn("tester only (next_version_tester)", pages["Sturdy Shortbow"])
        self.assertNotIn("== 0.9.9.7 tester ==", pages["Finish Raft"])

    def test_promoted_bow_recipe_folds_matching_initializer_stats(self):
        page = self.pages["Sturdy Shortbow"]
        summary = page.split("== How to acquire ==", 1)[0]
        self.assertNotIn("Base crafting cost", summary)
        self.assertNotIn("Base recipe yield", summary)
        self.assertIn("|ap=<nowiki>8</nowiki>", page)
        self.assertIn("|output={{Item|Sturdy Shortbow|quantity=1}}", page)

    def test_release_raft_instructions_are_not_repeated(self):
        page = self.pages["Finish Raft"]
        for step in ("The base item action cost is 6 AP",
                     "Push targets a free tile 16 pixels away",
                     "Direct boarding requires being within 8 pixels"):
            self.assertEqual(page.count(step), 1, step)

    def test_shield_fix_distinguishes_recognition_from_unchanged_initializer_values(self):
        profiles = {row["entity"]: row for row in self.inputs[2]["profiles"]
                    if row["id"].endswith("-tester-profile")}
        for identity, title, chance in (
            ("item-280", "Iron Shield", 0.12),
            ("item-282", "Steel Buckler", 0.08),
            ("item-283", "Wooden Shield", 0.12),
        ):
            page = self.pages[title]
            self.assertIn("active off hand", page)
            self.assertIn("1.0.1.0 fixes", page)
            self.assertIn("already defined in 1.0.0.0", page)
            self.assertIn("does not increase its stats", page)
            self.assertEqual(profiles[identity]["values"]["block-chance"], chance)
            self.assertTrue(any(row["source"] == "game-data-1000"
                                for row in profiles[identity]["evidence"]))
        self.assertNotIn("fixes this shield", self.pages["Iron Chestplate"])
        self.assertIn("recognized from 1.0.1.0", self.pages["Shield Savant"])
        self.assertIn("Version 1.0.1.0 fixes recognition", self.pages["Combat basics"])

    def test_spider_revisit_documents_the_distinct_caller_and_failed_placement(self):
        entry = next(row for row in self.stable["entries"] if row["id"] == "spider-cave-revisit-1015")
        self.assertEqual(entry["confidence"], "inferred")
        self.assertTrue(any(row["source"] == "game-data-1010" for row in entry["evidence"]))
        page = self.pages["World generation"]
        for caveat in ("relative weights 15:1", "does not require a cleared cave",
                       "up to 256 candidate positions", "candidate is destroyed",
                       "Existing saved non-spider inhabitants are not purged",
                       "unchanged ordinary turn-by-turn population updater"):
            self.assertIn(caveat, page)
        self.assertIn("Ordinary caves", self.pages["Interior floors"])
        self.assertIn("Placement can fail", self.pages["Areas"])
        self.assertIn("nature 16, tile 148", self.pages["Version 1.0.1.5"])

    def test_patch_audio_and_raft_fix_do_not_promise_silence_or_changed_costs(self):
        self.assertIn("UI thud", self.pages["Foods"])
        self.assertIn("does not make consumption silent", self.pages["Foods"])
        self.assertIn("defaults to enabled", self.pages["Foods"])
        page = self.pages["Finish Raft"]
        self.assertIn("as soon as Finish Raft crafting succeeds", page)
        self.assertIn("without reloading", page)
        self.assertEqual(page.count("Push targets a free tile 16 pixels away"), 1)
        self.assertIn("AP costs, movement and direct-boarding rules are unchanged", page)
        version = self.pages["Version 1.0.1.5"]
        self.assertIn("27 November 2026", version)
        self.assertIn("seventh language", version)
        self.assertIn("base text remains", version)
        self.assertIn("font already gained Polish characters in 1.0.1.0", version)

    def test_shadowed_stable_entities_and_unapproved_beta_art_fail_before_rendering(self):
        def shadow(document):
            identity = document["data"]["entities"][0]["id"]
            document["data"]["entities"][0]["id"] = "item-0"
            for row in (document["data"]["illustrations"] + document["details"]["profiles"] +
                        document["item_notes"]):
                if row.get("entity") == identity:
                    row["entity"] = "item-0"

        for mutation, error in (
            (shadow, "shadow"),
            (lambda doc: doc["data"]["illustrations"][0].update(rights_status="pending"), "approved"),
            (lambda doc: doc["data"]["entities"][0].update(name="File:Invalid"), "canonical"),
        ):
            document = copy.deepcopy(self.tester)
            mutation(document)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "content" / "facts" / "tester.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(DataError, error):
                    load_tester(root, self.stable)

    def test_historical_tester_requires_complete_matching_promotion_and_approved_art(self):
        stable = copy.deepcopy(self.stable)
        stable["game"]["build"] = "1.0.0.0"
        identities = {row["id"] for row in self.tester["data"]["entities"]}
        stable["entities"] = [row for row in stable["entities"] if row["id"] not in identities]
        stable["illustrations"] = [row for row in stable["illustrations"] if row.get("entity") not in identities]
        stable["entities"].extend(copy.deepcopy(self.tester["data"]["entities"]))
        stable["illustrations"].extend(copy.deepcopy(self.tester["data"]["illustrations"]))
        self.assertEqual(load_tester(ROOT, stable), self.tester)
        for field, mutation, error in (
            ("entities", lambda rows: rows.pop(), "shadow"),
            ("entities", lambda rows: rows[-1].update(name="Different item"), "shadow"),
            ("illustrations", lambda rows: rows[-1].update(caption="Changed art"), "illustrations"),
        ):
            changed = copy.deepcopy(stable)
            mutation(changed[field])
            with self.assertRaisesRegex(DataError, error):
                load_tester(ROOT, changed)
