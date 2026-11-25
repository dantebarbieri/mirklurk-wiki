import copy
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
        self.assertEqual(self.stable["game"]["build"], "1.0.0.0")
        self.assertLessEqual({row["id"] for row in self.tester["data"]["entities"]},
                             {row["id"] for row in self.stable["entities"]})
        self.assertIn("'''Current version:''' 1.0.0.0", pages["Main Page"])
        self.assertNotIn("== 0.9.9.7 tester ==", pages["Finish Raft"])
        for entity in self.tester["data"]["entities"]:
            text = pages[entity["name"]]
            self.assertNotIn("tester only (next_version_tester)", text)
            self.assertIn("does not establish merchant stock", text)
            self.assertNotIn("can be bought", text)
            self.assertNotIn("crafted, bought", text)
            self.assertNotIn("Merchants sell", text)
            self.assertNotIn("New in [[Version 0.9.9.7", text)
        self.assertIn("[[Inventory crafting]]", pages["Sturdy Shortbow"])
        self.assertIn("{{Item|Twine|quantity=2}}", pages["Sturdy Shortbow"])
        self.assertIn("{{Item|Branch (Trollgnarl)|quantity=2}}", pages["Sturdy Shortbow"])
        self.assertIn("{{Item|Spider Silk|quantity=10}}", pages["Sturdy Shortbow"])
        self.assertIn("[[Piercing|", pages["Sturdy Shortbow"])
        self.assertNotIn("2.4000000000000004", pages["Sturdy Shortbow"])

    def test_release_access_and_exposure_preserve_the_historical_tester_boundary(self):
        meat = self.pages["Grilled Spider Meat"]
        self.assertNotIn("== 0.9.9.7 tester ==", meat)
        self.assertIn("burning Campfire", meat)
        self.assertNotIn("access to this crafting option is unconfirmed", meat)
        self.assertIn("Previously saved areas do not receive", self.pages["World generation"])
        self.assertIn("not 12.5% or 10%", self.pages["Deathlob"])
        self.assertIn("normalized 0.35", self.pages["Temperature"])
        self.assertIn("ordinary population updater still exits", self.pages["World generation"])
        self.assertIn("weather/day clock", self.pages["Version 0.9.9.7"])
        self.assertIn("Version boundary:", self.pages["Version 0.9.9.7"])
        for note in self.tester["page_notes"]:
            self.assertNotIn("== 0.9.9.7 tester ==", self.pages[note["page"]])
        self.assertIn("no timestamp or link", self.pages["Version 0.9.9.7"])
        self.assertIn("not a released 1.0", self.pages["Version 0.9.9.7"])

    def test_promoted_art_reuses_the_approved_tester_records_and_smoke_pixels(self):
        images = self.tester["data"]["illustrations"]
        specs = synthetic_image_specs(self.stable, images)
        require_image_coverage(specs, {row["name"]: self.pages[row["name"]]
                                       for row in self.tester["data"]["entities"]})
        for image in images:
            self.assertIn(image, self.stable["illustrations"])
            self.assertIn(image["file_title"].removeprefix("File:"), specs)

    def test_base_only_release_render_retains_linked_tester_history_without_overlays(self):
        pages = build_pages(ROOT, load_data(ROOT / "content" / "facts" / "game.json"))
        self.assertIn("Version 0.9.9.7", pages)
        self.assertIn("weather/day clock", pages["Version 0.9.9.7"])
        self.assertNotIn("tester only (next_version_tester)", pages["Sturdy Shortbow"])
        self.assertNotIn("== 0.9.9.7 tester ==", pages["Finish Raft"])

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
