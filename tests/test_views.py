import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from plan_migration import plan_migration
from wiki_catalog import entry_owners, entry_relations, page_locations, validate_catalog
from wiki_data import DataError, MECHANIC_GUIDE_TITLES
from wiki_details import load_publication_inputs
from wiki_render import build_pages, display_entry, linked_prose, merchant_table, recipe_groups
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
            expected.update(locations[recipe["owner_item"]] for recipe in self.catalog.get("construction_recipes", [])
                            if recipe["station_id"] == station["id"])
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

    def test_shared_stock_rule_has_one_owner_and_reaches_filtered_sellers(self):
        locations = page_locations(self.data, self.catalog)
        rule = next(row for row in self.catalog["currency"]["rules"] if row["id"] == "trade-stock-and-funds")
        self.assertIn(selective_view("<nowiki>" + rule["text"] + "</nowiki>", "stock"),
                      self.pages["Currency and trading"])
        self.assertEqual(available_views(self.pages["Currency and trading"]), {"stock"})
        merchants = set(self.catalog["currency"]["standard_merchants"])
        self.assertEqual(merchants, {"being-8", "being-12", "being-19", "being-20", "being-26", "being-33"})
        for identity in merchants:
            page = self.pages[locations[identity]]
            self.assertNotIn(rule["text"], page)
            self.assertNotIn("Quantity is not established", page)
            self.assertIn(("Currency and trading", (("view", "stock"),)), transclusions(page))
            self.assertIn("<noinclude>{{:Currency and trading|view=stock}}</noinclude><includeonly>", page)
            self.assertIn("[[Currency and trading#currency-trade-stock-and-funds|Shared stock and merchant-funds rules]]", page)
            self.assertIn("<onlyinclude>{{#switch:", page)
            self.assertEqual(available_views(page), {"offers"})
        self.assertIn("Quest items cannot be sold", self.pages["Currency and trading"])
        self.assertIn("Rift Weave is also blocked", self.pages["Currency and trading"])
        self.assertIn("no merchant-specific, player or difficulty markup", self.pages["Currency and trading"])
        self.assertNotIn("Wares", self.pages["Wilda"])

    def test_merchant_story_availability_is_owned_inside_offer_views(self):
        locations = page_locations(self.data, self.catalog)
        profiles = {row["entity"]: row for row in self.catalog["merchant_profiles"]}
        self.assertEqual(set(profiles), set(self.catalog["currency"]["standard_merchants"]))
        for identity, profile in profiles.items():
            page = self.pages[locations[identity]]
            self.assertEqual(page.count(profile["conditions"]), 1)
            offers_view = page.split("<onlyinclude>", 1)[1].split("</onlyinclude>", 1)[0]
            self.assertIn(profile["conditions"], offers_view)
            if profile["spoiler"]:
                self.assertIn('class="mw-collapsible mw-collapsed"', offers_view)
                self.assertIn("Story availability (spoilers)", offers_view)
            for original in self.data["entries"]:
                if original["kind"] == "merchant" and original["details"]["merchant"] == identity:
                    self.assertEqual(display_entry(original, self.catalog)["conditions"], profile["conditions"])
                    self.assertNotIn(profile["conditions"], self.pages[locations[original["details"]["item"]]])
        self.assertIn("already with Clay before the explosion", profiles["being-19"]["conditions"])
        self.assertIn("only after Clay has departed", profiles["being-19"]["conditions"])
        self.assertIn("Eir announces", profiles["being-19"]["conditions"])
        self.assertTrue(any("MAINQUESTSTAGE>=27" in row["key"] for row in profiles["being-19"]["evidence"]))
        self.assertIn("Clay survives outside", profiles["being-8"]["conditions"])
        self.assertIn("Tain dies in the explosion", profiles["being-20"]["conditions"])
        self.assertIn("Summoned characters cannot be interacted with", self.pages["Currency and trading"])
        self.assertIn("Crafting access and Viend", self.pages["Alchemy workstation"])
        self.assertFalse(any("Other story restrictions are not established" in page for page in self.pages.values()))

    def test_viend_clay_stock_comparison_links_exact_original_offers(self):
        offers = {merchant: {row["details"]["item"]: row["id"] for row in self.data["entries"]
                            if row["kind"] == "merchant" and row["details"]["merchant"] == merchant}
                  for merchant in ("being-8", "being-19", "being-20")}
        clay, viend = offers["being-8"], offers["being-19"]
        self.assertEqual((len(clay), len(viend), len(clay.keys() & viend.keys())), (16, 15, 12))
        self.assertEqual(viend.keys() - clay.keys(), {"item-138", "item-139", "item-252"})
        self.assertEqual(clay.keys() - viend.keys(), {"item-14", "item-27", "item-44", "item-57"})
        self.assertEqual(set(offers["being-20"]), {"item-252"})
        comparison = self.pages["Viend"].split("== Comparing stock ==", 1)[1].split("\n== ", 1)[0]
        for merchant, rows, other in (("Magus Clay", clay, viend), ("Viend", viend, clay)):
            for item in rows.keys() - other.keys():
                self.assertIn("[[" + merchant + "#entry-" + rows[item] + "|", comparison)
        self.assertNotIn("<table", comparison)
        self.assertNotIn("{{:", comparison)

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

    def test_survival_guides_keep_exact_thresholds_and_distinct_meter_indices(self):
        guides = {row["title"]: row for row in self.catalog["guides"]}
        for index, title in enumerate(("Satiation", "Stamina", "Focus", "Temperature")):
            self.assertIn(title, self.pages)
            self.assertEqual(guides[title]["confidence"], "observed")
            self.assertTrue(any(f"player_get_stat_changes[{index}]" in ref["key"] for ref in guides[title]["evidence"]))
            self.assertIn("[[Wellbeing", self.pages[title])
            self.assertIn("Contribution to wellbeing", self.pages[title])
        for title, text in (
            ("Satiation", "0.715 percentage points"), ("Satiation", "above 90%"),
            ("Stamina", "4 percentage points"), ("Focus", "0.56 percentage points"),
            ("Temperature", "40-60%"), ("Temperature", "not Celsius or Fahrenheit"),
            ("Temperature", "-3 percentage points"), ("Wellbeing", "0.1 percentage point"),
            ("Wellbeing", "by 0.67"), ("Wellbeing", "by 1.2"),
            ("Resting", "At 50% wellbeing or more"), ("Resting", "5% per resting turn"),
            ("Resting", "not routinely doubled"), ("Resting", "Below 45% wellbeing"),
            ("Resting", "focus exceeds 95%"), ("Resting", "35 turns"),
            ("Weather", "Easy and Medium"), ("Weather", "fewer than two days"),
        ):
            self.assertIn(text, self.pages[title])
        for title in ("Stamina", "Focus"):
            self.assertIn("not an accident chance on every turn" if title == "Stamina" else "must still make an accident check", self.pages[title])
        self.assertIn("distinct from your personal temperature meter", self.pages["Weather"])
        self.assertIn("[[:Category:Food and drink", self.pages["Foods"])
        self.assertIn('id="Combat_and_action_guide_evidence"', self.pages["Source provenance"])

    def test_food_effect_amounts_have_one_item_owner_not_copied_guide_values(self):
        locations = page_locations(self.data, self.catalog)
        for effect in self.catalog["item_effects"]:
            text = "\n\n".join(effect["paragraphs"])
            self.assertIn("== Consumption effects ==", self.pages[locations[effect["entity"]]])
            self.assertIn(text, self.pages[locations[effect["entity"]]])
            for guide in self.catalog["guides"]:
                self.assertNotIn(text, self.pages[guide["title"]])
        bursthopper = next(row for row in self.catalog["item_effects"] if row["entity"] == "item-243")
        self.assertIn("15 percentage points of stamina", bursthopper["paragraphs"][0])
        self.assertNotIn("focus", bursthopper["paragraphs"][0].lower())
        self.assertNotIn("4% per rank", self.pages["Satiation"])
        self.assertNotIn("3% per rank", self.pages["Focus"])
        self.assertNotIn("8% per rank", self.pages["Foods"])
        for change in (
            lambda c: c["item_effects"][0].update(entity="being-0"),
            lambda c: c["item_effects"][0].update(evidence=[]),
            lambda c: c["item_effects"][0].update(paragraphs=[]),
            lambda c: c["item_effects"].append(copy.deepcopy(c["item_effects"][0])),
            lambda c: c["guides"][-1].update(section_titles=["Mismatch"]),
        ):
            catalog = copy.deepcopy(self.catalog)
            change(catalog)
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)

    def test_guide_inline_links_are_explicit_and_literal_safe(self):
        text = linked_prose("See Focus, not Focused. {{untrusted|markup}}", {"Focus": "Focus"})
        self.assertIn("[[Focus|<nowiki>Focus</nowiki>]]", text)
        self.assertIn("<nowiki>, not Focused. {{untrusted|markup}}</nowiki>", text)
        self.assertNotIn("[[Focused", text)

    def test_all_original_titles_survive_the_additive_guides(self):
        new_guides = MECHANIC_GUIDE_TITLES - {"Action points", "Health and armor", "Weather"}
        source_titles = {source["title"] for source in self.catalog.get("acquisition", {}).get("sources", [])}
        historical_categories = {
            "Ammunition", "Aquatic creatures", "Armor", "Bestiary", "Bugs",
            "Camping and construction", "Carrying equipment", "Clothes", "Coins and valuables",
            "Consumables", "Crabs", "Crafting materials", "Cutting and chopping tools",
            "Damage types", "Fire-making supplies", "Food and drink", "Forager",
            "Gatherable food plants", "Ground cover and water plants", "Hunter", "Items",
            "Light sources", "Miscellaneous items", "Mollusks", "NPCs", "Nature",
            "Non-growing nature", "Quest items", "Remedies", "Rift growth", "Rodents",
            "Scaalmyr", "Seeds", "Skills", "Snakes", "Survivor", "Toadkin", "Tools",
            "Trees", "Trolls", "Unwanted creatures", "Wanderer", "Warrior", "Weapons",
        }
        self.assertTrue({"Category:" + title for title in historical_categories} <= set(self.pages))
        old_titles = sorted(title for title in set(self.pages) - new_guides - source_titles
                            if not title.startswith("Category:") or title.removeprefix("Category:") in historical_categories)
        self.assertEqual(len(old_titles), 401)
        self.assertEqual(hashlib.sha256(("\n".join(old_titles) + "\n").encode()).hexdigest(),
                         "b32b5d0645406b2b6e8073d4c355ebca0eacf1fbd554ba1b6dfdc1bbffc78b75")

    def test_four_tree_references_use_distinct_reviewed_mature_compositions(self):
        locations = page_locations(self.data, self.catalog)
        hashes = {
            "nature-4": "f73b3ed66aacdf320cdd9e892ce251e767024639c7a0114c0d169554564b17ad",
            "nature-7": "088b42c512242db358a0c34cb9da78208d7522470161e8db3283a5519d866176",
            "nature-17": "f8b178269b50ff3da8bb828a4cee6f5805880036a11c656f451f5eba3557939e",
            "nature-20": "5404f6444c81488e1535dc57bdd5b17c7cf992d52939dd0a8d8c486172ce65e0",
        }
        self.assertEqual(len(self.data["illustrations"]), 326)
        for identity, digest in hashes.items():
            images = [image for image in self.data["illustrations"] if image.get("entity") == identity]
            self.assertEqual(len(images), 1)
            image = images[0]
            self.assertEqual(image["sha256"], digest)
            self.assertEqual(image["file_title"], "File:" + identity.capitalize() + "-mature.png")
            page = self.pages[locations[identity]]
            self.assertIn("[[" + image["file_title"] + "|thumb|", page)
            self.assertNotIn("[[File:" + identity.capitalize() + ".png", page)
            self.assertIn("representative shape assembled", page)
            self.assertIn(locations[identity], image["caption"])
            self.assertEqual({row["section"] for row in image["evidence"]}, {
                "gml_Object_databank_Alarm_2", "gml_GlobalScript_scr_nature",
                "gml_Object_obj_tree_Step_0", "gml_Object_obj_tree_Draw_0",
            })


if __name__ == "__main__":
    unittest.main()
