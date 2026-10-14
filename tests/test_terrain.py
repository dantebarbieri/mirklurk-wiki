import copy
import re
import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_catalog import validate_catalog
from wiki_data import DataError, validate_data
from wiki_details import load_publication_inputs
from wiki_display import ASSETS_TITLE
from wiki_render import build_pages


class TerrainGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)
        cls.guides = {row["title"]: row for row in cls.catalog["guides"]}
        cls.tiles = [title for title, row in cls.guides.items() if row.get("index_page") == "Terrain"]
        cls.areas = [title for title, row in cls.guides.items() if row.get("index_page") == "Areas"]

    def test_tile_template_and_registry_cover_every_ground_page(self):
        self.assertIn("{{#invoke:Display|tile|", self.pages["Template:Tile"])
        registry = self.pages[ASSETS_TITLE].split("    tiles = {\n", 1)[1].split("\n    },")[0]
        self.assertEqual(registry.count("        [ "), len(self.tiles))
        tile_files = {row["guide"]: row["file_title"] for row in self.data["illustrations"] if row.get("role") == "tile"}
        for title in self.tiles:
            page = self.pages[title]
            self.assertTrue(page.startswith("[[Terrain]] | [[Main Page]]\n"))
            self.assertIn(tile_files[title], page.split("== How it works ==")[0])
            self.assertIn(f"link={title}|", registry)
            for section in ("Where it appears", "Moving and building", "Creatures"):
                self.assertIn(f"=== <nowiki>{section}</nowiki> ===", page)
        used = set()
        for text in self.pages.values():
            used.update(re.findall(r"\{\{Tile\|([^{}|]+)\}\}", text))
        self.assertEqual(used, set(self.tiles))

    def test_area_pages_list_ground_spawns_and_complete_tree_mix(self):
        self.assertEqual(len(self.areas), 9)
        for title in self.areas:
            page = self.pages[title]
            self.assertTrue(page.startswith("[[Areas]] | [[Main Page]]\n"))
            self.assertIn("{{Tile|", page)
            self.assertIn("{{Creature|", page)
            if "<nowiki>Share of new trees</nowiki>" not in page:
                self.assertIn(title, ("Vast Waters", "Fort Solid Shorehold"))
                continue
            rows = page.split("<nowiki>Share of new trees</nowiki>", 1)[1].split("|}", 1)[0]
            shares = [Decimal(value) for value in re.findall(r"\|\| <nowiki>([0-9.]+)%</nowiki>", rows)]
            self.assertAlmostEqual(sum(shares), Decimal(100), delta=Decimal("0.05"), msg=title)
        for word in ("biome", "Biome"):
            self.assertNotIn(word, "".join(self.pages.values()))

    def test_depth_bands_use_one_set_of_names(self):
        bands = ("Deep water", "Medium water", "Open shallows", "Shore shallows", "Waterline", "Low ground")
        for title in ("Terrain", "Planting"):
            for band in bands[:4]:
                self.assertIn(band.lower(), self.pages[title].lower(), msg=(title, band))
        self.assertNotIn("past the shallow strip", "".join(self.pages.values()))
        planting = self.pages["Planting"]
        row = planting.split("| {{Item|Watercress Seeds}} ||", 1)[1].split("|-", 1)[0]
        self.assertIn("−0.45", row)
        self.assertIn("−0.26", row)
        self.assertNotIn("No flooding", planting)
        self.assertIn("No flooding", self.pages["Terrain"])

    def test_guide_blocks_refuse_malformed_tables_and_pictures(self):
        changes = [
            lambda g: g["tables"][0].update(after=99),
            lambda g: g["tables"][0].update(columns=[]),
            lambda g: g["tables"][0]["rows"][0].append("extra"),
            lambda g: g["tables"][0]["rows"][0].__setitem__(0, {"entity": "item-0-not-real"}),
            lambda g: g["tables"][0]["rows"][0].__setitem__(0, {"page": "Not a guide"}),
            lambda g: g["tables"][0]["rows"][0].__setitem__(0, {"entity": "item-1", "page": "Areas"}),
            lambda g: g["tables"].extend([g["tables"][0]] * 12),
            lambda g: g.update(images=[{"illustration": "x", "after": 99}]),
            lambda g: g.update(images=[{"illustration": "x", "after": 0}] * 2),
            lambda g: g["evidence"].extend([g["evidence"][0]] * 17),
        ]
        for index, change in enumerate(changes):
            catalog = copy.deepcopy(self.catalog)
            change(next(row for row in catalog["guides"] if row["title"] == "Soil"))
            with self.subTest(index=index), self.assertRaises(DataError):
                validate_catalog(catalog, self.data)

    def test_placed_pictures_and_tile_cells_stay_with_their_owner(self):
        catalog = copy.deepcopy(self.catalog)
        mud = next(row for row in self.data["illustrations"] if row.get("guide") == "Mud" and row.get("role") == "tile")
        catalog_soil = next(row for row in catalog["guides"] if row["title"] == "Soil")
        catalog_soil["images"] = [{"illustration": mud["id"], "after": 0}]
        with self.assertRaisesRegex(DataError, "placed picture"):
            build_pages(ROOT, self.data, catalog, self.details)
        catalog = copy.deepcopy(self.catalog)
        next(row for row in catalog["guides"] if row["title"] == "Soil")["tables"][0]["rows"][0][0] = {"tile": "Areas"}
        validate_catalog(catalog, self.data)
        with self.assertRaisesRegex(DataError, "not a terrain page"):
            build_pages(ROOT, self.data, catalog, self.details)
        for change in ({"guide": "Not a guide"}, {"guide": "Soil", "role": "tile"}, {"guide": "Soil", "role": "sprite"}):
            data = copy.deepcopy(self.data)
            row = next(row for row in data["illustrations"] if row.get("guide") == "Soil" and "role" not in row)
            row.update(change)
            with self.subTest(change=change), self.assertRaises(DataError):
                validate_data(data)


if __name__ == "__main__":
    unittest.main()
