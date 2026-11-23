import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_data import DataError
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

    def test_beta_pages_preserve_stable_defaults_and_do_not_claim_merchant_stock(self):
        before = copy.deepcopy(self.stable)
        pages = build_pages(ROOT, *self.inputs)
        self.assertEqual(self.stable, before)
        self.assertEqual(self.stable["game"]["build"], "0.9.6.5")
        self.assertFalse({row["id"] for row in self.tester["data"]["entities"]} &
                         {row["id"] for row in self.stable["entities"]})
        self.assertIn("'''Current version:''' 0.9.6.5", pages["Main Page"])
        self.assertIn("== 0.9.9.7 tester ==", pages["Finish Raft"])
        for entity in self.tester["data"]["entities"]:
            text = pages[entity["name"]]
            self.assertIn("tester only (next_version_tester)", text)
            self.assertIn("does not establish merchant stock", text)
            self.assertNotIn("Merchants sell", text)
            self.assertNotIn("New in [[Version 0.9.9.7", text)
        self.assertIn("2 [[Twine]], 2 [[Branch (Trollgnarl)]] and 10 [[Spider Silk]]", pages["Sturdy Shortbow"])
        self.assertIn("[[Piercing]]", pages["Sturdy Shortbow"])
        self.assertNotIn("2.4000000000000004", pages["Sturdy Shortbow"])

    def test_cooking_and_cave_access_are_labeled_without_rewriting_stable_records(self):
        meat = self.pages["Grilled Spider Meat"]
        self.assertIn("== 0.9.9.7 tester ==", meat)
        self.assertIn("burning [[Campfire]]", meat)
        self.assertIn("menu access", meat)
        self.assertIn("Previously saved areas do not receive", self.pages["World generation"])
        self.assertIn("not 12.5% and 10%", self.pages["Deathlob"])
        self.assertIn("weather/day clock", self.pages["Weather"].split("== 0.9.9.7 tester ==", 1)[1])
        self.assertIn("weather temperature, not the fixed underground 0.35",
                      self.pages["Temperature"].split("== 0.9.9.7 tester ==", 1)[1])
        for note in self.tester["page_notes"]:
            beta_section = self.pages[note["page"]].split("== 0.9.9.7 tester ==", 1)[1]
            self.assertNotIn("\nChanged in [[Version ", beta_section)
            self.assertNotIn("\nNew in [[Version ", beta_section)
        self.assertIn("no timestamp or link", self.pages["Version 0.9.9.7"])
        self.assertIn("not a released 1.0", self.pages["Version 0.9.9.7"])

    def test_tester_art_is_included_in_smoke_fixtures_without_changing_stable_registry(self):
        images = self.tester["data"]["illustrations"]
        specs = synthetic_image_specs(self.stable, images)
        require_image_coverage(specs, {row["name"]: self.pages[row["name"]]
                                       for row in self.tester["data"]["entities"]})
        for image in images:
            self.assertNotIn(image, self.stable["illustrations"])
            self.assertIn(image["file_title"].removeprefix("File:"), specs)

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
