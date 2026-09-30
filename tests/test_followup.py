"""Reviewed classifications, equipment capacity, image sizing and human edits."""

import copy
import hashlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_catalog import armor_groups, category_definitions, page_locations, primary_groups, validate_catalog
from wiki_data import DataError, validate_data
from wiki_details import load_publication_inputs, validate_capacity_profiles, validate_details
from wiki_render import audit_report, image_caption, build_pages, icon, illustration_markup, pixel_geometry, pixel_image
from wiki_views import scroll_open
from smoke_deploy import smoke_pixel_art


FACTIONS = {
    0: [5, 6, 8, 9, 12, 19, 20, 26, 33, 34, 35],
    3: [1, 2, 4, 7, 11, 17, 24, 25, 27, 29, 30],
    4: [0], 5: [13, 14, 15, 16, 22, 32], 6: [21], 7: [10, 23], 8: [28, 31], 9: [3, 18],
}
CAPACITY = {
    12: (35, 7, 5), 14: (49, 7, 7), 148: (56, 8, 7), 26: (72, 8, 9),
    13: (8, 4, 2), 166: (10, 5, 2), 167: (12, 6, 2), 168: (16, 8, 2),
    196: (9, 3, 3), 197: (12, 3, 4), 198: (16, 4, 4), 24: (6, 3, 2), 21: (6, 3, 2),
}


class FollowupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)
        cls.audit = audit_report(cls.data, cls.catalog, cls.details)
        cls.locations = page_locations(cls.data, cls.catalog)
        cls.categories = category_definitions(cls.data, cls.catalog)

    def test_recorder_quest_classification_retires_only_the_empty_misc_group(self):
        self.assertEqual(set(self.categories["Quest items"]["members"]),
                         {"item-75", "item-123", "item-126", "item-130", "item-132"})
        self.assertNotIn("Miscellaneous items", self.categories)
        self.assertNotIn("== Miscellaneous items ==", self.pages["Items"])
        self.assertNotIn("[[:Category:Miscellaneous items|", self.pages["Category:Items"])
        self.assertEqual(self.pages["Category:Miscellaneous items"], "#REDIRECT [[Items]]\n")
        self.assertIn("{{Item|Wooden Recorder}}", self.pages["Category:Quest items"])
        self.assertIn("[[Category:Quest items]]", self.pages["Wooden Recorder"])
        self.assertNotIn("[[Category:Miscellaneous items]]", self.pages["Wooden Recorder"])
        self.assertEqual(self.pages["Items"].count('<span id="entity-item-75"></span>'), 1)

        # A populated group must remain visible; retirement cannot hide its members.
        catalog = copy.deepcopy(self.catalog)
        next(row for row in catalog["taxonomy"]["groups"]
             if row["title"] == "Quest items")["members"].remove("item-75")
        misc = {"title": "Miscellaneous items", "index": "Items", "members": ["item-75"]}
        catalog["taxonomy"]["groups"].append(misc)
        pages = build_pages(ROOT, self.data, catalog, self.details)
        section = pages["Items"].split("== Miscellaneous items ==\n", 1)[1].split("\n== ", 1)[0]
        self.assertIn("{{Item|Wooden Recorder}}", section)
        self.assertIn("{{Item|Wooden Recorder}}", pages["Category:Miscellaneous items"])
        self.assertIn("[[Category:Miscellaneous items]]", pages["Wooden Recorder"])
        misc["members"] = []
        with self.assertRaisesRegex(DataError, "primary groups cannot be empty"):
            validate_catalog(catalog, self.data)

    def test_reconciled_pages_preserve_reviewed_human_text_and_add_mobile_wrappers(self):
        # Live Items r2996 (minus its empty Misc section) and Wooden Recorder r2995.
        # Strip only the known mobile wrappers for this comparison, never for sync.
        digests = {
            "Items": "aaf1f220179afa287c55b4e32badc5993863442a30baf574ac21ed5a96a4f8f5",
            "Wooden Recorder": "eadd66853c40f7f856eae6529e53fb8b628eea0cad2609b3afca8664efd51090",
        }
        for title, digest in digests.items():
            with self.subTest(title=title):
                text = self.pages[title]
                table_count = 7 if title == "Items" else 1
                self.assertEqual(text.count(scroll_open()), table_count)
                text, count = re.subn(re.escape(scroll_open()) + r"(.*?)\n</div>\n",
                                     r"\1\n", text, flags=re.DOTALL)
                self.assertEqual(count, table_count)
                if title == "Wooden Recorder":
                    figure = scroll_open("Wooden Recorder inventory icon.", "pixel-art-figure")
                    self.assertEqual(text.count(figure), 1)
                    text = text.replace(figure, '<div class="pixel-art-figure" style="max-width:100%;overflow-x:auto;">')
                self.assertEqual(hashlib.sha256(text.rstrip().encode()).hexdigest(), digest)

    def test_exact_factions_cover_all_beings_and_replace_primary_taxonomy(self):
        factions = self.catalog["aggression"]["factions"]
        self.assertEqual({row["id"]: {int(identity.split("-")[1]) for identity in row["members"]}
                          for row in factions}, {team: set(members) for team, members in FACTIONS.items()})
        groups = [row for row in primary_groups(self.catalog) if row["index"] == "Bestiary"]
        self.assertEqual(len(groups), 7)
        self.assertEqual(sum(len(row["members"]) for row in groups), 25)
        for faction in factions:
            title = faction["title"]
            index = "NPCs" if faction["id"] == 0 else "Bestiary"
            self.assertEqual(self.categories[title]["index"], index)
            for identity in faction["members"]:
                page = self.pages[self.locations[identity]]
                self.assertIn(f"[[Category:{title}]]", page)
                self.assertIn(f"[[:Category:{title}|{title}]]", page)
                self.assertIn("[[Bestiary#Aggression_rules|", page)
        for old in ("Bugs", "Snakes", "Scaalmyr", "Unwanted creatures", "Aquatic creatures"):
            self.assertIn("Category:" + old, self.pages)
            self.assertNotIn("\n== " + old + " ==\n", self.pages["Bestiary"])
            self.assertIn("aggression factions may differ", self.pages["Category:" + old])
        self.assertIn("== Aggression faction evidence ==", self.audit)

    def test_target_rules_include_both_exceptions_and_retaliation_not_universal_friendliness(self):
        rules = self.pages["Bestiary"].split("== Aggression rules ==", 1)[1].split("\n== ", 1)[0]
        for phrase in ("Nightmare", "Raving Unwanted", "retaliate", "without the usual faction check",
                       "never themselves", "separate faction", "distance", "line-of-sight"):
            self.assertIn(phrase, rules)
        for title in ("Nightmare", "Raving Unwanted"):
            self.assertIn("Both Nightmare and Raving Unwanted can select other members", self.pages[title])
        self.assertIn("[[Category:Scaalmyr faction]]", self.pages["Mutated Unwanted"])
        self.assertIn("[[Category:Wildlife faction]]", self.pages["Mire Serpent"])
        self.assertNotIn("[[Category:Viper faction]]", self.pages["Mire Serpent"])

    def test_faction_schema_rejects_missing_duplicate_wrong_kind_and_unsupported_values(self):
        for mutate in (
            lambda a: a["factions"][0]["members"].pop(),
            lambda a: a["factions"][1]["members"].append("being-5"),
            lambda a: a["factions"][0]["members"].append("item-5"),
            lambda a: a["factions"][0].update(id=True),
            lambda a: a["factions"][1].update(id=0),
            lambda a: a["factions"][0].update(evidence=[]),
            lambda a: a.update(paragraphs=[]),
        ):
            catalog = copy.deepcopy(self.catalog)
            mutate(catalog["aggression"])
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)

    def test_all_thirteen_exact_positive_bonuses_and_grid_shapes_reach_browse_tables(self):
        profiles = {row["entity"]: row for row in self.details["profiles"] if "inventory-slots-added" in row["values"]}
        self.assertEqual(set(profiles), {f"item-{identity}" for identity in CAPACITY})
        self.assertEqual(set(self.categories["Capacity-granting equipment"]["members"]), set(profiles))
        self.assertNotIn("item-108", profiles)
        for number, (slots, width, height) in CAPACITY.items():
            identity = f"item-{number}"
            values = profiles[identity]["values"]
            self.assertEqual(values, {"inventory-slots-added": slots, "storage-grid-width": width, "storage-grid-height": height})
            for title in (self.locations[identity], "Items", "Category:Capacity-granting equipment"):
                self.assertIn(f"+<nowiki>{slots}</nowiki> inventory slots", self.pages[title])
                self.assertIn(f"<nowiki>{width}</nowiki> x <nowiki>{height}</nowiki>", self.pages[title])
            for category, row in self.categories.items():
                if identity in row["members"]:
                    self.assertIn(f"+<nowiki>{slots}</nowiki> inventory slots", self.pages["Category:" + category])
        self.assertIn("+<nowiki>9</nowiki> inventory slots", self.pages["Forager's Vest"])
        self.assertIn("Replacing an item replaces its capacity bonus", self.pages["Forager's Vest"])
        carrying = self.pages["Items"].split("== Carrying equipment ==", 1)[1].split("\n== ", 1)[0]
        for identity in self.categories["Carrying equipment"]["members"]:
            self.assertIn(f'id="entity-{identity}"', carrying)
            self.assertIn("{{Item|" + self.locations[identity] + "}}", self.pages["Category:Carrying equipment"])

    def test_capacity_validation_rejects_ambiguous_or_incomplete_bonus_data(self):
        for mutate in (
            lambda v: v.update({"inventory-slots-added": 0}),
            lambda v: v.update({"inventory-slots-added": -1}),
            lambda v: v.update({"inventory-slots-added": 1.5}),
            lambda v: v.update({"inventory-slots-added": True}),
            lambda v: v.update({"inventory-slots-added": 36}),
            lambda v: v.pop("storage-grid-width"),
        ):
            details = copy.deepcopy(self.details)
            mutate(next(row for row in details["profiles"] if row["entity"] == "item-12" and "inventory-slots-added" in row["values"])["values"])
            with self.assertRaises(DataError):
                validate_details(details, self.data)
        catalog = copy.deepcopy(self.catalog)
        next(row for row in catalog["taxonomy"]["tags"] if row["title"] == "Capacity-granting equipment")["members"].pop()
        with self.assertRaises(DataError):
            validate_capacity_profiles(catalog, self.details)

    def test_armor_groups_cover_each_item_once_using_reviewed_slots(self):
        expected = {
            "Head armor": {54, 116, 117, 119}, "Torso armor": {43, 55, 147, 194},
            "Armored gloves": {165}, "Leg armor": {56, 192, 193, 195}, "Shields": {0, 1, 50, 58, 118},
        }
        groups = armor_groups(self.catalog)
        self.assertEqual({row["title"]: {int(identity.split("-")[1]) for identity in row["members"]} for row in groups}, expected)
        self.assertEqual(sum(len(row["members"]) for row in groups), 18)
        for group in groups:
            for title in ("Items", "Category:Armor"):
                self.assertIn("=== " + group["title"] + " ===", self.pages[title])
            for identity in group["members"]:
                self.assertIn("[[Category:" + group["title"] + "]]", self.pages[self.locations[identity]])
                self.assertIn("{{Item|" + self.locations[identity] + "}}", self.pages["Category:" + group["title"]])

    def test_every_image_uses_original_pixels_and_integer_native_geometry(self):
        entities = {row["id"]: row for row in self.data["entities"]}
        for image in self.data["illustrations"]:
            pixels = image["pixel_art"]
            native_width, native_height = (pixels[key] // pixels["source_scale"] for key in ("width", "height"))
            for width, height in ((224, 288), (32, 32), (20, 20)):
                shown_width, shown_height, scale = pixel_geometry(image, width, height)
                self.assertEqual((shown_width, shown_height), (native_width * scale, native_height * scale))
                self.assertGreaterEqual(scale, 1)
                self.assertLessEqual(shown_width, max(width, native_width))
                self.assertLessEqual(shown_height, max(height, native_height))
                markup = pixel_image(image, width, height)
                self.assertIn(f'|{pixels["width"]}px|', markup)
                self.assertIn(f'zoom:calc({scale} / {pixels["source_scale"]})', markup)
                self.assertIn("image-rendering:pixelated", markup)
                self.assertNotRegex(markup, r"thumb|frameless|upright")
            figure = illustration_markup(image)
            self.assertIn("max-width:100%;overflow-x:auto", figure)
            if image.get("entity") in entities and "role" not in image:
                self.assertIn("|link=" + self.locations[image["entity"]], icon(image["entity"], [image], entities, self.locations))
        self.assertFalse(any(re.search(r"\[\[File:[^\n]*\|(?:thumb|frameless)(?:\||\]\])", page) for page in self.pages.values()))
        hut = next(image for image in self.data["illustrations"] if image["id"] == "being-12-location-illustration")
        self.assertEqual(pixel_geometry(hut), (192, 192, 4))
        shield = next(image for image in self.data["illustrations"] if image.get("health_armor") == 1)
        self.assertEqual(pixel_geometry(shield, 32, 32), (32, 32, 2))

    def test_pixel_metadata_requires_positive_divisible_integer_dimensions(self):
        for mutation in ({"width": 0}, {"height": True}, {"source_scale": 1.5}, {"width": 255}, {"source_scale": 0}):
            data = copy.deepcopy(self.data)
            data["illustrations"][0]["pixel_art"].update(mutation)
            with self.assertRaises(DataError):
                validate_data(data, stations={row["id"]: row for row in self.catalog["stations"]})

    def test_smoke_rejects_resampled_sources_and_stripped_scaling(self):
        image = next(row for row in self.data["illustrations"] if row.get("health_armor") == 1)
        def rendered_case(image_source="", image_attrs="", style_override=None):
            def api(query, post=False):
                self.assertEqual(query["action"], "parse")
                self.assertTrue(post, "Bulk read-only parsing must not exceed HTTP request-URI limits")
                html = ""
                for width, height in ((224, 288), (32, 32)):
                    scale = pixel_geometry(image, width, height)[2]
                    style = f"image-rendering:pixelated;zoom:calc({scale} / 4);" if style_override is None else style_override
                    html += (f'<span class="pixel-art" style="{style}">'
                             f'<img src="/images/{image_source}Health-armor-1.png" width="64" height="64" {image_attrs}/></span>')
                return {"parse": {"text": {"*": html}}}
            return api
        smoke_pixel_art(rendered_case(), {"illustrations": [image]})
        for api in (rendered_case("thumb/"), rendered_case(image_attrs='srcset="blurred.png 2x"'),
                    rendered_case(style_override=""), rendered_case(style_override="image-rendering:pixelated;zoom:0.7;")):
            with self.assertRaises(RuntimeError):
                smoke_pixel_art(api, {"illustrations": [image]})


if __name__ == "__main__":
    unittest.main()
