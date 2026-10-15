import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_details import load_publication_inputs
from wiki_portal import TOPIC_GROUPS, browse_order
from wiki_render import build_pages


class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = build_pages(ROOT, *load_publication_inputs(ROOT))
        cls.main = cls.pages["Main Page"]

    def section(self, title, heading):
        return self.pages[title].split(f"\n== {heading} ==\n", 1)[1].split("\n== ", 1)[0]

    def test_main_page_sections_are_cards_and_steps_not_loose_links(self):
        for heading in ("New to the Mirk?", "Explore", "Guides by topic", "About this wiki"):
            self.assertIn(f"\n== {heading} ==\n", self.main)
        self.assertNotIn("\n[[", self.main.split("\n== About this wiki ==\n", 1)[1])
        steps = re.findall(r"^# .*?'''\[\[([^]|]+)\]\]'''", self.section("Main Page", "New to the Mirk?"), re.M)
        self.assertEqual(steps[:4], ["Difficulty", "Controls", "Starting equipment", "Action points"])
        explore = self.section("Main Page", "Explore")
        self.assertTrue(explore.startswith('<div class="mirklurk-cards"'))
        self.assertNotIn("\n* [[", explore)
        self.assertIn("'''[[Items]]'''<br />\nequipment, materials, recipes and supplies", explore)

    def test_every_top_level_guide_is_grouped_once_on_both_hubs(self):
        topics = self.section("Main Page", "Guides by topic")
        self.assertEqual(re.findall(r"'''([^'\[]+)'''<br />", topics),
                         [heading for heading, _, _ in TOPIC_GROUPS])
        for title in ("Satiation", "Survivors' camp", "Currency and trading", "Dead camp", "World generation"):
            self.assertEqual(topics.count(f"[[{title}]]"), 1, title)
            self.assertIn(f"[[{title}]]", self.pages["Game mechanics"])
        linked = set(re.findall(r"\[\[(?!File:)([^]|#]+)", topics))
        self.assertTrue(all(title in self.pages and not self.pages[title].startswith("#REDIRECT") for title in linked))
        self.assertNotIn("[[Game mechanics]]", self.section("Game mechanics", "Guides by topic"))

    def test_item_families_read_basic_to_best(self):
        clothes = self.pages["Items"].split("\n=== Socks ===\n", 1)[1].split("\n===", 1)[0]
        self.assertEqual(re.findall(r"\{\{Item\|([^}|]+)", clothes), ["Worn Socks", "Decent Socks", "Fine Wool Socks"])
        weapons = self.section("Items", "Weapons")
        found = re.findall(r"\{\{Item\|([^}|]+)", weapons)
        self.assertLess(found.index("Shoddy Dagger"), found.index("Iron Dagger"))
        self.assertLess(found.index("Iron Dagger"), found.index("Steel Dagger"))
        self.assertEqual(found.index("Iron Dagger") - found.index("Shoddy Dagger"), 1)
        self.assertLess(found.index("Orb of Fire"), found.index("Orb of Greater Fire"))
        self.assertEqual(browse_order("Orb of Fire", "item", {"initial-price": 10})[0], "Orb")
        self.assertEqual(browse_order("Log (Willow)", "item", {})[:2], ("Log", float("inf")))

    def test_creatures_read_weakest_to_strongest(self):
        mirkfangs = self.pages["Bestiary"].split("\n== Mirkfang faction ==\n", 1)[1].split("\n== ", 1)[0]
        self.assertEqual(re.findall(r"\{\{Creature\|([^}]+)\}\}", mirkfangs),
                         ["Mirkfang", "Giant Mirkfang", "Mirkfang Matriarch", "The Terror"])

    def test_family_pages_and_navboxes_list_tiers_in_order(self):
        self.assertEqual(re.findall(r"^\| \d+ \|\| \{\{Item\|([^}]+)\}\}", self.pages["Socks"], re.M),
                         ["Worn Socks", "Decent Socks", "Fine Wool Socks"])
        socks = self.pages["Decent Socks"]
        navbox = socks.split('<div class="mirklurk-navbox"', 1)[1].split("</div>", 1)[0]
        self.assertIn("'''[[Socks]]''' (lowest to highest value)", navbox)
        self.assertIn("{{DEFAULTSORT:Socks 02 Decent Socks}}", socks)
        self.assertLess(socks.index("mirklurk-navbox"), socks.index("[[Category:"))
        mirkfang = self.pages["Giant Mirkfang"]
        self.assertIn("'''[[:Category:Mirkfangs|Mirkfangs]]''' (weakest to strongest)", mirkfang)
        self.assertIn("{{DEFAULTSORT:Mirkfangs 02 Giant Mirkfang}}", mirkfang)

    def test_guides_open_with_a_lead_and_section_links(self):
        stamina = self.pages["Stamina"].split("\n== How it works ==\n", 1)[0]
        self.assertIn("'''Stamina''' is one of the [[Game mechanics|survival topics]].", stamina)
        self.assertIn("'''Sharp''' is one of the [[Damage types|damage types]].", self.pages["Sharp"])
        self.assertNotIn("'''<nowiki>Sharp</nowiki>'''", self.pages["Sharp"])
        self.assertIn("On this page: [[#Mouse|Mouse]] &middot; [[#Keyboard|Keyboard]]", self.pages["Controls"])
        for title in ("Controls", "Difficulty", "Death", "Combat basics"):
            self.assertIn(f"[[{title}]]", self.section("Main Page", "New to the Mirk?"))


if __name__ == "__main__":
    unittest.main()
