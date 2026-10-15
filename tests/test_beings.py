import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_anchors import fragment
from wiki_beings import being_article
from wiki_catalog import page_locations
from wiki_data import DataError
from wiki_details import load_publication_inputs
from wiki_display import grid_argument
from wiki_render import build_pages, profile_value


class BeingArticleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)
        cls.entities = {row["id"]: row for row in cls.data["entities"]}
        cls.locations = page_locations(cls.data, cls.catalog)
        cls.properties = {row["id"]: row for row in cls.details["properties"]}
        cls.beings = sorted(identity for identity, row in cls.entities.items() if row["category"] == "being")

    def test_being_pages_replace_the_raw_stat_table_with_a_combat_section(self):
        self.assertEqual(len(self.beings), 42)
        for identity in self.beings:
            page = self.pages[self.locations[identity]]
            with self.subTest(being=identity):
                self.assertNotIn("== Stats ==", page)
                self.assertNotIn("Applies to / notes", page)
                combat = page.split("== Combat ==", 1)[1]
                self.assertNotRegex(combat, r"\|\| Base\n|(?:speed|reach|movement) parameter|threshold|Base XP award")
                self.assertIn('! scope="row" | [[Level progression|XP]] award', combat)
                self.assertIn('! scope="row" | [[Action points]]', combat)
                self.assertIn("'''Targeting:'''", combat)
                self.assertIn("[[Bestiary#Aggression_rules|Faction and targeting rules]]", combat)

    def test_every_attack_grid_states_its_damage_type_cost_and_reach(self):
        grids = [grid for grid in self.details["grids"] if self.entities[grid["entity"]]["category"] == "being"]
        profiles = {}
        for row in self.details["profiles"]:
            profiles.setdefault(row["entity"], {}).update(row["values"])
        for grid in grids:
            if grid["kind"] == "health":
                continue
            values = profiles[grid["entity"]]
            prefix = "ranged-" if grid["kind"] == "ranged" else ""
            label = "Ranged attack" if grid["kind"] == "ranged" else "Melee attack"
            parts = []
            if prefix + "damage-class-id" in values:
                damage = profile_value(prefix + "damage-class-id", values[prefix + "damage-class-id"], self.entities, self.locations)
                parts.append(f"deals {damage} damage")
            parts.append("costs " + profile_value(grid["kind"] + "-ap-cost", values[grid["kind"] + "-ap-cost"], {}, {}))
            parts.append("reach " + profile_value(grid["kind"] + "-distance", values[grid["kind"] + "-distance"], {}, {}))
            sentence = ", ".join(parts)
            expected = (f'<span id="{fragment('grid', grid['id'])}"></span>\n=== {label} ===\n{sentence[:1].upper()}{sentence[1:]}.\n'
                        "{{Attack grid|" + grid_argument(grid) + "|label=" + label + "}}")
            with self.subTest(grid=grid["id"]):
                self.assertIn(expected, self.pages[self.locations[grid["entity"]]])

    def test_examples_keep_health_unused_values_and_merged_fact_anchors(self):
        sceetler = self.pages["Sceetler"]
        self.assertIn("| [[#Health|5 HP]]", sceetler)
        self.assertIn("'''Opportunity attacks:''' <nowiki>15</nowiki>%", sceetler)
        self.assertIn("Deals [[Poison|<nowiki>Poison</nowiki>]] damage, costs <nowiki>6</nowiki> [[Action points|AP]], reach <nowiki>7</nowiki>.", sceetler)
        self.assertLess(sceetler.index("== Combat =="), sceetler.index("=== Health ==="))
        self.assertLess(sceetler.index("=== Ranged attack ==="), sceetler.index("== Loot =="))
        self.assertIn("<onlyinclude>{{#switch:{{{view|<noinclude>page</noinclude>}}}|page|loot=", sceetler)
        grand_mother = self.pages["Grand Mother"]
        self.assertIn("Has no melee attack pattern, although the game lists [[Blunt|<nowiki>Blunt</nowiki>]] damage, "
                      "a <nowiki>6</nowiki> [[Action points|AP]] cost and reach <nowiki>2.25</nowiki>.", grand_mother)
        self.assertIn("'''Ranged attack:''' none (ranged reach <nowiki>0</nowiki>).", grand_mother)
        slug = self.pages["Giant Slug"]
        for field in ("apmax", "armor", "attackcost"):
            self.assertEqual(slug.count(f'id="base-{field}"'), 1)
        boss = self.pages["Magus Clay (boss)"]
        self.assertLess(boss.index("== <nowiki>Blink and rewards</nowiki> =="), boss.index("== Combat =="))
        self.assertIn("[[Clay's Magus Hood|", boss)

    def test_unmatched_values_and_conflicts_are_never_dropped(self):
        profile = {"id": "x-profile", "entity": "being-13", "values": {"base-xp": 5, "melee-pattern-min": 1,
                                                                       "melee-pattern-max": 3, "storage-grid-width": 2}}
        fact = {"id": "being-13-base-armor", "property": "Base armor", "value": 2.0, "confidence": "inferred",
                "description": "Example."}
        text = being_article([fact], [profile], self.properties, self.entities, self.locations)
        self.assertIn("=== Melee attack ===\nHas no melee attack pattern.", text)
        self.assertIn("Potential damage: <nowiki>1</nowiki> to <nowiki>3</nowiki>", text)
        self.assertIn('<span id="base-armor"></span>', text)
        self.assertIn("<nowiki>2</nowiki>", text)
        conflicting = {"id": "y-profile", "entity": "being-13", "values": {"base-xp": 6}}
        with self.assertRaises(DataError):
            being_article([], [profile, conflicting], self.properties, self.entities, self.locations)


if __name__ == "__main__":
    unittest.main()
