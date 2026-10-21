"""The edited Survivors' camp scene and the NPC location links to its guide."""

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_catalog import page_locations, validate_catalog
from wiki_data import DataError
from wiki_details import load_publication_inputs
from wiki_render import build_pages

GUIDE = "Survivors' camp"
FILE = "File:Survivors' camp area.png"


class CampSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)
        cls.locations = page_locations(cls.data, cls.catalog)

    def test_guide_shows_the_edited_native_scene_once(self):
        scene = next(row for row in self.data["illustrations"] if row.get("guide") == GUIDE)
        self.assertEqual(scene["file_title"], FILE)
        self.assertEqual(scene["sha256"], "77e751494be3e000e27b6f79e670ad72aae0eb2ed18296f17c39d59ac35f1af5")
        self.assertEqual(scene["pixel_art"], {"width": 256, "height": 280, "source_scale": 1})
        self.assertNotIn("role", scene)
        for phrase in ("Trees and everything beyond the palisade ring are left out", "they wander in play"):
            self.assertIn(phrase, scene["caption"])
        self.assertEqual(self.pages[GUIDE].count("[[" + FILE + "|"), 1)

    def test_camp_npc_locations_link_to_the_guide_without_embedding_it(self):
        for identity in ("being-34", "being-35", "being-36"):
            with self.subTest(npc=identity):
                self.assertFalse(any(row.get("entity") == identity and row.get("role") == "location"
                                     for row in self.data["illustrations"]))
                page = self.pages[self.locations[identity]]
                location = page.split("== Location and access ==", 1)[1].split("\n== ", 1)[0]
                self.assertIn("[[" + GUIDE + "|", location)
                self.assertNotIn("[[" + FILE, page)

    def test_camp_seller_locations_link_the_guide_on_npc_and_item_views(self):
        sellers = {self.locations[row["details"]["merchant"]] for row in self.data["entries"]
                   if row["kind"] == "merchant" and row["details"]["merchant"] in {"being-34", "being-36"}}
        self.assertEqual(sellers, {"Wilda", "Grand Mother"})
        for title in sellers:
            with self.subTest(seller=title):
                note = self.pages[title].split("Location: ", 1)[1].split("\n", 1)[0]
                self.assertIn("[[" + GUIDE + "|<nowiki>" + GUIDE + "</nowiki>]]", note)
                self.assertNotIn(title + "#Location_and_access", note)
        for title in ("Ranger Bhato",):
            self.assertIn("[[" + title + "#Location_and_access|", self.pages[title])

    def test_related_guides_must_be_unique_registered_and_named(self):
        for change, message in (
            ([GUIDE, GUIDE], "at most four unique"),
            (["Not a guide"], "at most four unique"),
            (GUIDE, "at most four unique"),
            ([GUIDE, "Terrain"], "named in its paragraphs"),
        ):
            with self.subTest(related_pages=change):
                catalog = copy.deepcopy(self.catalog)
                next(row for row in catalog["classifications"] if row["entity"] == "being-34")["location"][
                    "related_pages"] = change
                with self.assertRaisesRegex(DataError, message):
                    validate_catalog(catalog, self.data)


if __name__ == "__main__":
    unittest.main()
