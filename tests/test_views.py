import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from plan_migration import plan_migration
from wiki_catalog import entry_owners, entry_relations, page_locations, validate_catalog
from wiki_data import DataError, MECHANIC_GUIDE_TITLES
from wiki_details import load_publication_inputs
from wiki_render import build_pages, display_entry, merchant_table, recipe_groups
from wiki_views import available_views, selective_view, transclusions, validate_transclusions


class SelectiveViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)

    def test_default_contracts_and_named_views_are_distinct(self):
        price = selective_view("2 silver", "price", default=True)
        recipe = selective_view("<tr><td>3 ingredients</td></tr>", "recipes")
        self.assertEqual(available_views(price + recipe), {"", "price", "recipes"})
        self.assertEqual(available_views("<onlyinclude>coin table</onlyinclude>"), {""})
        self.assertEqual(available_views(price + "<onlyinclude>unconditional leak</onlyinclude>"), set())
        self.assertEqual(available_views(price + "<onlyinclude>"), set())
        self.assertEqual(available_views("full article"), set())
        self.assertEqual(transclusions("{{:Item}} {{:Item|view=recipes|station=campfire}}"), [
            ("Item", ()), ("Item", (("station", "campfire"), ("view", "recipes"))),
        ])
        for markup in ("{{:Item|recipes}}", "{{:Item|view=recipes|view=price}}"):
            with self.assertRaises(DataError):
                transclusions(markup)
        for pages in ({"Reader": "{{:Missing}}"}, {"Reader": "{{:Owner|view=loot}}", "Owner": price}):
            with self.assertRaises(DataError):
                validate_transclusions(pages)

    def test_every_station_selects_all_and_only_its_recipe_owners(self):
        locations = page_locations(self.data, self.catalog)
        owners = entry_owners(self.data, locations, entry_relations(self.data, self.catalog), self.catalog)
        recipes = [display_entry(entry, self.catalog) for entry in self.data["entries"] if entry["kind"] == "recipe"]
        for station in self.catalog["stations"]:
            refs = {
                owner for owner, arguments in transclusions(self.pages[station["title"]])
                if dict(arguments) == {"view": "recipes", "station": station["id"]}
            }
            expected = {owners[entry["id"]] for entry in recipes if entry["details"]["station"] in station["methods"]}
            self.assertEqual(refs, expected)
            for owner in expected:
                self.assertIn("recipes", available_views(self.pages[owner]))
        for group in recipe_groups(recipes):
            owner = owners[group[0]["id"]]
            for entry in group:
                self.assertEqual(self.pages[owner].count(f'id="entry-{entry["id"]}"'), 1)
        self.assertIn('class="wikitable"', self.pages["Alchemy workstation"])
        self.assertIn("Ingredients", self.pages["Alchemy workstation"])
        self.assertIn("Base cost", self.pages["Alchemy workstation"])

    def test_offer_views_never_nest_item_price_inclusions(self):
        locations = page_locations(self.data, self.catalog)
        for entry in self.data["entries"]:
            if entry["kind"] != "merchant":
                continue
            item = entry["details"]["item"]
            merchant = locations[entry["details"]["merchant"]]
            self.assertIn(
                (merchant, (("item", item), ("view", "offers"))),
                transclusions(self.pages[locations[item]]),
            )
            self.assertIn("offers", available_views(self.pages[merchant]))
            self.assertIn("<noinclude><td>{{:" + locations[item] + "}}</td></noinclude>", self.pages[merchant])
            page = self.pages[locations[item]]
            self.assertEqual(page.count('id="price-' + item + '"'), 1)
            self.assertIn("== How to acquire ==", page)
            self.assertNotIn("Standard unit price", page.split("== How to acquire ==", 1)[0])

    def test_verified_loot_sources_are_selected_by_exact_outcome(self):
        locations = page_locations(self.data, self.catalog)
        owners = entry_owners(self.data, locations, entry_relations(self.data, self.catalog), self.catalog)
        for entry in self.data["entries"]:
            if entry["kind"] != "loot" or entry["details"]["outcome"] is None:
                continue
            item = entry["details"]["outcome"]
            owner = owners[entry["id"]]
            self.assertIn("loot", available_views(self.pages[owner]))
            if owner != locations[item]:
                self.assertIn((owner, (("item", item), ("view", "loot"))), transclusions(self.pages[locations[item]]))
            self.assertEqual(self.pages[owner].count('id="entry-' + entry["id"] + '"'), 1)

    def test_explicit_vendor_prices_stay_visible_without_price_recursion(self):
        offers = copy.deepcopy([entry for entry in self.data["entries"] if entry["kind"] == "merchant"][:2])
        offers[0]["details"].update(price=19, currency="silver")
        entities = {row["id"]: row for row in self.data["entities"]}
        locations = page_locations(self.data, self.catalog)
        rendered = merchant_table(offers, [], entities, locations, True)
        self.assertIn("<td><nowiki>19</nowiki> <nowiki>silver</nowiki></td>", rendered)
        self.assertNotIn("<noinclude><td><nowiki>19", rendered)
        self.assertIn("<includeonly>[[", rendered)
        self.assertIn("|Standard item price]]</includeonly>", rendered)

    def test_planner_tracks_every_parameterized_edge_and_unknown_contract(self):
        base = {"Item": "<onlyinclude>old price</onlyinclude>"}
        desired = {
            "Item": selective_view("new price", "price", True) + selective_view("recipe", "recipes"),
            "Merchant": "{{:Item}}", "Station": "{{:Item|view=recipes|station=campfire}}",
            "Unknown": "{{:Missing|view=offers|item=item-0}}",
        }
        report = plan_migration(base, base, desired)
        self.assertEqual(report["schema_version"], 2)
        edges = {row["page"]: row for row in report["transclusion_dependencies"]}
        self.assertEqual(set(edges), {"Merchant", "Station", "Unknown"})
        self.assertTrue(edges["Merchant"]["current_view_declared"])
        self.assertFalse(edges["Station"]["current_view_declared"])
        self.assertFalse(edges["Unknown"]["current_view_declared"])
        self.assertEqual(edges["Station"]["parameters"], {"station": "campfire", "view": "recipes"})
        ready = plan_migration(base, desired, desired)["transclusion_dependencies"]
        self.assertTrue(all(row["current_owner_matches_desired"] for row in ready if row["owner"] == "Item"))

    def test_new_guides_require_evidence_and_finite_existing_targets(self):
        catalog = copy.deepcopy(self.catalog)
        evidence = catalog["guides"][0]["evidence"]
        new = sorted(MECHANIC_GUIDE_TITLES - {row["title"] for row in catalog["guides"]})
        for title in new:
            catalog["guides"].append({
                "title": title, "paragraphs": ["Synthetic reviewed guide."],
                "related_entities": [], "confidence": "observed", "evidence": evidence,
                "related_pages": ["Action points"],
            })
        pages = build_pages(ROOT, self.data, catalog, self.details)
        for title in new:
            self.assertIn("Synthetic reviewed guide.", pages[title])
            self.assertIn("[[Action points]]", pages[title])
            self.assertIn("[[" + title + "]]", pages["Game mechanics"])
        for change in (
            lambda c: c["guides"][-1].update(title="Unreviewed guide"),
            lambda c: c["guides"][-1].update(evidence=[]),
            lambda c: c["guides"][-1].update(related_pages=["Unknown"]),
            lambda c: c["guides"][-1].update(related_pages=["Action points", "Action points"]),
        ):
            modified = copy.deepcopy(catalog)
            change(modified)
            with self.assertRaises(DataError):
                validate_catalog(modified, self.data)

    def test_guide_images_reuse_approved_records_with_context(self):
        catalog = copy.deepcopy(self.catalog)
        guide = next(row for row in catalog["guides"] if row["title"] == "Action points")
        guide.update(image_entity="item-68", image_caption="A bedroll used as a contextual illustration.")
        pages = build_pages(ROOT, self.data, catalog, self.details)
        self.assertIn("[[File:Item-68.png|thumb|<nowiki>A bedroll used as a contextual illustration.", pages["Action points"])
        for change in (
            lambda g: g.update(image_entity="unknown"),
            lambda g: g.update(image_entity="item-31"),
            lambda g: g.pop("image_caption"),
            lambda g: g.pop("image_entity"),
        ):
            modified = copy.deepcopy(catalog)
            change(next(row for row in modified["guides"] if row["title"] == "Action points"))
            with self.assertRaises(DataError):
                build_pages(ROOT, self.data, modified, self.details)


if __name__ == "__main__":
    unittest.main()
