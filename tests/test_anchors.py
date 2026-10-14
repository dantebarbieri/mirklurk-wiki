import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_anchors import (
    acquisition_fragments, anchor_ids, canonical, entity_fragment, entry_fragments, fragment,
    illustration_fragment, titled, validate_anchors,
)
from wiki_data import DataError


class AnchorTests(unittest.TestCase):
    def test_titles_become_kind_prefixed_fragments(self):
        self.assertEqual(titled("offer", "Iron Hand Axe"), "offer-Iron_Hand_Axe")
        self.assertEqual(titled("recipe", "Longbow (Cypress)", 2), "recipe-Longbow_(Cypress)-2")
        self.assertEqual(entity_fragment({"category": "being"}, "Sceetler"), "creature-Sceetler")
        self.assertEqual(entity_fragment({"category": "being"}, "Captain Eir", npc=True), "npc-Captain_Eir")

    def test_own_page_anchors_drop_the_entity(self):
        self.assertEqual(fragment("fact", "being-0-base-armor"), "base-armor")
        self.assertEqual(fragment("fact", "area-seed-ceiling"), "area-seed-ceiling")
        self.assertEqual(fragment("profile", "item-27-initializer"), "stats-base")
        self.assertEqual(fragment("profile", "item-27-equip-cost"), "stats-equip-cost")
        self.assertEqual(fragment("grid", "being-13-health"), "health-grid")
        self.assertEqual(fragment("grid", "being-13-melee"), "attack-grid-melee")
        self.assertEqual(fragment("pool", "chest-rich"), "pool-chest-rich")
        self.assertEqual(illustration_fragment({"id": "item-27-illustration", "entity": "item-27"}), "image")
        self.assertEqual(illustration_fragment({"id": "item-27-sprite", "entity": "item-27"}), "image-sprite")
        with self.assertRaises(DataError):
            fragment("entity", "item-27")

    def test_entries_number_per_owner_and_recipes_globally(self):
        locations = {"item-1": "Axe", "item-2": "Rope"}
        entries = [
            {"id": "m1", "kind": "merchant", "details": {"item": "item-1"}},
            {"id": "m2", "kind": "merchant", "details": {"item": "item-1"}},
            {"id": "m3", "kind": "merchant", "details": {"item": "item-1"}},
            {"id": "r1", "kind": "recipe", "details": {"outputs": [{"item": "item-2"}]}},
            {"id": "r2", "kind": "recipe", "details": {"outputs": [{"item": "item-2"}]}},
            {"id": "l1", "kind": "loot", "details": {"outcome": None}},
            {"id": "q1", "kind": "quest", "title": "Find Bhato", "details": {}},
        ]
        owners = {"m1": "Clay", "m2": "Clay", "m3": "Viend", "r1": "Rope", "r2": "Workbench", "l1": "Crab", "q1": "Quests"}
        shown = entry_fragments(entries, owners, locations)
        self.assertEqual(shown, {"m1": "offer-Axe", "m2": "offer-Axe-2", "m3": "offer-Axe", "r1": "recipe-Rope",
                                 "r2": "recipe-Rope-2", "l1": "loot-nothing", "q1": "quest-Find_Bhato"})
        source = {"rows": [{"id": "a", "item": "item-1"}, {"id": "b", "item": "item-1"}]}
        self.assertEqual(acquisition_fragments(source, locations), {"a": "acquisition-Axe", "b": "acquisition-Axe-2"})

    def test_headings_are_numbered_like_mediawiki(self):
        text = '<span id="price"></span>\n== Uses ==\n=== [[Fire|Fire]] ===\n== Uses ==\n'
        self.assertEqual(anchor_ids(text), ["price", "Uses", "Fire", "Uses_2"])

    def test_validator_rejects_duplicates_and_dangling_links(self):
        good = {"Axe": '<span id="price"></span>', "Shop": "[[Axe#price|cost]] [[axe#Obtaining|x]]"}
        validate_anchors(good)
        for pages in ({"Axe": '<span id="price"></span><span id="price"></span>'},
                      {"Axe": "", "Shop": "[[Axe#price|cost]]"},
                      {"Shop": "[[Gone#price|cost]]"}):
            with self.subTest(pages=pages), self.assertRaises(DataError):
                validate_anchors(pages)
        validate_anchors({"Axe": "", "Notes": "[[Axe#price|cost]] [[Gone#x|y]]"}, lenient={"Notes"})

    def test_links_follow_redirects(self):
        pages = {"Axe": '<span id="price"></span>', "Hatchet": "#REDIRECT [[Axe]]", "Shop": "[[Hatchet#price|c]]"}
        self.assertEqual(canonical("hatchet", pages), "Axe")
        validate_anchors(pages)


if __name__ == "__main__":
    unittest.main()
