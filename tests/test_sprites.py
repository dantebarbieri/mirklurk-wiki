"""Reviewed NPC overworld sprite metadata and presentation regressions."""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_catalog import page_locations
from wiki_data import DataError
from wiki_details import load_publication_inputs, parse_illustrations
from wiki_render import build_pages, image_for

OVERWORLD_SPRITES = {
    "being-6": ("spr_captain_eir", (240, 200, 5)),
    "being-8": ("spr_clay", (240, 240, 6)),
    "being-12": ("spr_ranger_t", (240, 200, 5)),
    "being-19": ("spr_viend", (240, 240, 6)),
    "being-20": ("spr_commander_tain", (240, 240, 6)),
    "being-26": ("spr_gurb", (224, 224, 7)),
    "being-33": ("spr_ihar", (240, 240, 6)),
    "being-34": ("spr_wilda", (240, 200, 5)),
}


class OverworldSpriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)
        cls.locations = page_locations(cls.data, cls.catalog)
        cls.sprites = {row["entity"]: row for row in cls.data["illustrations"] if row.get("role") == "sprite"}

    def test_every_portrait_npc_with_a_world_sprite_also_shows_it(self):
        self.assertEqual(set(self.sprites), set(OVERWORLD_SPRITES))
        npcs = {row["entity"] for row in self.catalog["classifications"] if row["kind"] == "npc"}
        portraits = {identity for identity in npcs
                     if "portrait" in image_for(identity, self.data["illustrations"])["caption"]}
        # Dead Unwanted's beingDB entry uses spr_blank, so it has no overworld sprite to show.
        self.assertEqual(portraits - set(self.sprites), {"being-9"})
        for identity, (sprite, (width, height, scale)) in OVERWORLD_SPRITES.items():
            image = self.sprites[identity]
            self.assertEqual(image["id"], identity + "-sprite-illustration")
            self.assertEqual(image["file_title"], f"File:{identity.capitalize()}-overworld.png")
            self.assertEqual(image["pixel_art"], {"width": width, "height": height, "source_scale": scale})
            self.assertEqual(image["rights_status"], "approved")
            self.assertEqual(image["creator"], "Edym Pixels")
            self.assertIn(f"beingDB[{identity.split('-')[1]}].sprite/{sprite}.frame0",
                          [row["key"] for row in image["evidence"]])
            page = self.pages[self.locations[identity]]
            portrait = image_for(identity, self.data["illustrations"])
            self.assertIs(portrait, image_for(identity, [image, portrait]))
            self.assertEqual(page.count("[[" + image["file_title"] + "|"), 1)
            lead = page.split("\n==", 1)[0]
            self.assertLess(lead.index(portrait["file_title"]), lead.index(image["file_title"]))
            self.assertIn(image["file_title"] + f"|{width}px|alt=", lead)
            self.assertIn("|class=notpageimage|", lead.split(image["file_title"], 1)[1].split("]]", 1)[0])

    def test_sprite_roles_are_bounded_to_one_being_with_a_portrait(self):
        base = {key: value for key, value in self.data.items() if key != "illustrations"}
        original = self.sprites["being-6"]
        for change in ({"entity": "item-8"}, {"role": "overworld"}, {"sha256": None}):
            with self.subTest(change=change):
                with self.assertRaises(DataError):
                    parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [dict(original, **change)]}).encode(),
                                        base, self.catalog)
        duplicate = dict(original, id="duplicate-sprite", file_title="File:Duplicate-sprite.png")
        with self.assertRaisesRegex(DataError, "one sprite illustration"):
            parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [original, duplicate]}).encode(),
                                base, self.catalog)
        data = copy.deepcopy(self.data)
        data["illustrations"] = [row for row in data["illustrations"] if row["id"] != "being-6-illustration"]
        with self.assertRaisesRegex(DataError, "approved primary portrait"):
            build_pages(ROOT, data, self.catalog, self.details)



if __name__ == "__main__":
    unittest.main()
