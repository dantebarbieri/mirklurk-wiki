"""Reviewed NPC overworld sprite metadata and presentation regressions."""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_catalog import page_locations, validate_catalog
from wiki_data import DataError, uncropped
from wiki_details import load_publication_inputs, parse_illustrations
from wiki_render import audit_report, build_pages, image_for

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
        self.assertEqual(set(self.sprites), set(OVERWORLD_SPRITES) | {"being-36", "being-41"})
        npcs = {row["entity"] for row in self.catalog["classifications"] if row["kind"] == "npc"}
        images = {identity: image_for(identity, self.data["illustrations"]) for identity in npcs}
        for identity in ("being-36", "being-41"):  # Sprite titles predate these portraits.
            title = "File:" + identity.capitalize()
            self.assertEqual((image_for(identity, self.data["illustrations"])["file_title"], uncropped(self.sprites[identity])["file_title"]),
                             (title + "-portrait.png", title + ".png"))
            lead = self.pages[self.locations[identity]].split("\n==", 1)[0]
            self.assertLess(lead.index(title + "-portrait.png|"), lead.index(title + "-cropped.png|"))
        self.assertEqual({identity for identity, image in images.items() if image is None}, set())
        portraits = {identity for identity, image in images.items() if image and "portrait" in image["caption"]}
        # Dead Unwanted's beingDB entry uses spr_blank, so it has no overworld sprite to show.
        self.assertEqual(portraits - set(self.sprites), {"being-9"})
        for identity, (sprite, (width, height, scale)) in OVERWORLD_SPRITES.items():
            image = self.sprites[identity]
            self.assertEqual(image["id"], identity + "-sprite-illustration")
            # The full padded-canvas export is preserved; pages show its transparent-margin crop.
            self.assertEqual(uncropped(image)["file_title"], f"File:{identity.capitalize()}-overworld.png")
            self.assertEqual(uncropped(image)["pixel_art"], {"width": width, "height": height, "source_scale": scale})
            self.assertEqual(image["file_title"], f"File:{identity.capitalize()}-overworld-cropped.png")
            width = image["pixel_art"]["width"]
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

class HealingAbilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)
        cls.ability = next(row["ability"] for row in cls.catalog["classifications"] if row["entity"] == "being-19")
        cls.image = next(row for row in cls.data["illustrations"] if row.get("role") == "ability")

    def test_healing_guidance_is_owned_by_viend_without_reader_provenance(self):
        page = self.pages["Viend"]
        self.assertEqual(page.count("== <nowiki>Healing</nowiki> =="), 1)
        for phrase in (
            "within 16 tiles", "two randomly chosen wounded health cells", "10 action points",
            "no separate cooldown", "player always takes priority", "heals himself if wounded",
            "nearest eligible friendly character", "Walls and other obstacles do not block",
            "does not remove poison, bleeding or sickness", "Burns cannot be healed directly",
            "before moving or attacking", "works outside combat", "10% chance", "1.5%",
            "at least two conditions", "During his escort or an active summon",
        ):
            self.assertIn(phrase, page)
        self.assertIn("[[Simple Burn Remedy|", page)
        self.assertIn("[[Resting|", page)
        for phrase in ("real-world", "standing still", "Source trace", "being_heal", "APmax", "game-data", "gml_"):
            self.assertNotIn(phrase, page)
        audit = audit_report(self.data, self.catalog, self.details)
        self.assertIn("== Being ability evidence ==", audit)
        self.assertIn("[[Viend#Healing|", audit)
        for reference in self.ability["evidence"]:
            self.assertIn(reference["key"].replace(">", "&gt;"), audit)

    def test_healing_icon_is_supplementary_and_pixel_exact_metadata(self):
        image = self.image
        self.assertEqual(image["entity"], "being-19")
        self.assertEqual(image["file_title"], "File:Healing-popup.png")
        self.assertEqual(image["sha256"], "26b01e30c749985620208d1e2db64e9b11df2046711c46b4de545d84700169ff")
        self.assertEqual(image["pixel_art"], {"width": 64, "height": 64, "source_scale": 4})
        self.assertEqual(image["creator"], "Edym Pixels")
        self.assertEqual(image["rights_status"], "approved")
        self.assertIn("spr_ui_16x16_fullycenter.frame10", image["evidence"][1]["key"])
        page = self.pages["Viend"]
        section = page.split("== <nowiki>Healing</nowiki> ==", 1)[1].split("\n== ", 1)[0]
        self.assertEqual(page.count("[[File:Healing-popup.png|"), 1)
        self.assertIn("[[File:Healing-popup.png|64px|", section)
        self.assertIn("|class=notpageimage|", section)
        self.assertIn("zoom:calc(4 / 4)", section)
        self.assertNotIn("|thumb", section)
        self.assertNotIn("|frameless", section)
        portrait = image_for("being-19", self.data["illustrations"])
        self.assertIs(portrait, image_for("being-19", [image, portrait]))
        self.assertNotIn("Healing-popup.png", page.split("== <nowiki>Healing", 1)[0])
        from smoke_deploy import require_image_coverage, synthetic_image_specs
        specs = synthetic_image_specs(self.data)
        self.assertEqual(specs["Healing-popup.png"][:2], (64, 64))
        require_image_coverage(specs, self.pages)

    def test_no_other_page_or_existing_image_changes(self):
        catalog, data = copy.deepcopy(self.catalog), copy.deepcopy(self.data)
        del next(row for row in catalog["classifications"] if row["entity"] == "being-19")["ability"]
        data["illustrations"] = [row for row in data["illustrations"] if row["id"] != self.image["id"]]
        baseline = build_pages(ROOT, data, catalog, self.details)
        self.assertEqual({title for title in baseline if baseline[title] != self.pages[title]}, {"Viend"})
        self.assertEqual(baseline.keys(), self.pages.keys())
        for image in data["illustrations"]:
            if image.get("entity") == "being-19":
                self.assertIn(image["file_title"], self.pages["Viend"])

    def test_ability_prose_and_links_require_bounded_reviewed_metadata(self):
        changes = (
            {"title": "[[Healing]]"}, {"paragraphs": []}, {"paragraphs": ["x"] * 7},
            {"paragraphs": ["x" * 801]}, {"related_entities": ["item-missing"]},
            {"related_entities": ["being-19"]}, {"related_entities": ["item-141", "item-141"]},
            {"related_pages": ["Unknown guide"]}, {"related_pages": ["Resting", "Resting"]},
            {"related_pages": ["Main Page"]}, {"related_pages": ["Research policy"]},
            {"related_pages": ["Evidence and spoilers"]}, {"related_pages": ["Items"]},
            {"confidence": "certain"}, {"evidence": []},
        )
        for change in changes:
            with self.subTest(change=change):
                catalog = copy.deepcopy(self.catalog)
                next(row for row in catalog["classifications"] if row["entity"] == "being-19")["ability"].update(change)
                with self.assertRaises(DataError):
                    validate_catalog(catalog, self.data)

    def test_ability_image_requires_its_owner_and_never_replaces_a_portrait(self):
        base = {key: value for key, value in self.data.items() if key != "illustrations"}
        duplicate = dict(self.image, id="duplicate-healing", file_title="File:Duplicate-healing.png")
        with self.assertRaisesRegex(DataError, "one ability illustration"):
            parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [self.image, duplicate]}).encode(),
                                base, self.catalog)
        with self.assertRaises(DataError):
            parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [dict(self.image, entity="item-8")]}).encode(),
                                base, self.catalog)
        catalog = copy.deepcopy(self.catalog)
        del next(row for row in catalog["classifications"] if row["entity"] == "being-19")["ability"]
        with self.assertRaisesRegex(DataError, "reviewed being ability owner"):
            parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [self.image]}).encode(), base, catalog)
        with self.assertRaisesRegex(DataError, "reviewed being ability owner"):
            build_pages(ROOT, self.data, catalog, self.details)
        data = copy.deepcopy(self.data)
        next(row for row in data["illustrations"] if row["id"] == self.image["id"])["rights_status"] = "pending"
        page = build_pages(ROOT, data, self.catalog, self.details)["Viend"]
        self.assertNotIn("File:Healing-popup.png", page)
        self.assertIn("== <nowiki>Healing</nowiki> ==", page)
        self.assertIn(image_for("being-19", data["illustrations"])["file_title"], page)


class JumperMechanicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)

    def test_jump_costs_and_strips_follow_effects(self):
        page = self.pages["Jumper"]
        section = page.split("== <nowiki>Effects</nowiki> ==", 1)[1]
        self.assertIn("4.0, 3.6, 3.2, 2.6, 2.4, 2.2, 2.2, 2.0, 1.8, 1.8 and 1.6 AP", section)
        self.assertIn("8.0, 7.2, 6.4, 5.4, 5.0, 4.6, 4.2, 4.0, 3.8, 3.6 and 3.4 AP", section)
        self.assertLess(section.index("# <nowiki>Find your maximum range."), section.index("# <nowiki>For example,"))
        adjacent = section.index("[[File:Jumper-adjacent-jump-costs.png|1200px|")
        self.assertLess(section.index("# <nowiki>For example,"), adjacent)
        self.assertLess(adjacent, section.index("[[File:Jumper-two-tile-jump-costs.png|930px|"))
        self.assertEqual(section.count("|class=notpageimage|"), 2)
        self.assertEqual(page.count("[[File:Skill-0-2.png|"), 1)
        self.assertEqual(image_for("skill-0-2", self.data["illustrations"])["file_title"], "File:Skill-0-2.png")

    def test_mechanics_role_requires_a_skill_with_effects(self):
        image = next(row for row in self.data["illustrations"] if row.get("role") == "mechanics")
        base = {key: value for key, value in self.data.items() if key != "illustrations"}
        moved = dict(image, entity="being-19", id="moved", file_title="File:Moved.png")
        with self.assertRaisesRegex(DataError, "mechanics illustrations belong to a skill"):
            parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [moved]}).encode(), base, self.catalog)
        data = copy.deepcopy(self.data)
        data["illustrations"].append(dict(image, entity="skill-0-3", id="climber", file_title="File:Climber.png"))
        data["entries"] = [row for row in data["entries"] if row["id"] != "skill-0-3-mechanics"]
        catalog = copy.deepcopy(self.catalog)
        catalog["entry_display"] = [row for row in catalog["entry_display"] if row["entry"] != "skill-0-3-mechanics"]
        with self.assertRaisesRegex(DataError, "skill's own Effects section"):
            build_pages(ROOT, data, catalog, self.details)


if __name__ == "__main__":
    unittest.main()
