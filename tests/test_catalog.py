import copy
import hashlib
import html
import json
import re
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_wiki import build_pages, build_xml, literal, profile_value
from wiki_catalog import (
    category_definitions, default_catalog, entry_owners, entry_relations, fact_owners, page_locations,
    parse_catalog, validate_catalog,
)
from wiki_data import DataError, load_data
from wiki_details import (
    MAX_DETAILS_BYTES, empty_details, load_publication_inputs, parse_details,
    parse_illustrations, validate_details,
)
from wiki_render import PAIRED_PROPERTIES, display_entry, fact_value, known, price_text, recipe_groups, recipe_profile_values
from test_wiki import illustration_data, research_data, synthetic_data
from smoke_deploy import refreshed_transclusion
from wiki_views import available_views, selective_view, transclusions


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)

    def test_ordinary_titles_qualify_only_collisions(self):
        locations = page_locations(self.data, self.catalog)
        self.assertEqual(locations["item-0"], "Wood Buckler")
        self.assertEqual(locations["being-12"], "Ranger Bhato")
        self.assertEqual(locations["skill-0-0"], "Strider")
        self.assertEqual(locations["item-221"], "Turnip (item)")
        self.assertEqual(locations["nature-18"], "Turnip (nature)")
        self.assertEqual(len(self.catalog["pages"]), 331)
        self.assertEqual(sum(not title.startswith("Category:") for title in self.pages), 385)
        self.assertEqual(sum(title.startswith("Category:") for title in self.pages), 80)
        self.assertTrue(all(row["title"] in self.pages for row in self.catalog["pages"]))
        self.assertEqual(len({row["entity"] for row in self.catalog["pages"]}), 331)

    def test_all_primary_records_and_typed_relationships_are_retained(self):
        locations = page_locations(self.data, self.catalog)
        facts = fact_owners(self.data, locations)
        relations = entry_relations(self.data, self.catalog)
        entries = entry_owners(self.data, locations, relations, self.catalog)
        for fact in self.data["facts"]:
            with self.subTest(fact=fact["id"]):
                page = self.pages[facts[fact["id"]]]
                self.assertIn(f'id="fact-{fact["id"]}"', page)
                if not fact["id"].endswith("-base-armor"):
                    value = profile_value("initial-weight", fact["value"], {}, {}) if fact["id"].endswith("-base-weight") else fact_value(fact)
                    self.assertIn(value, page)
        for entry in self.data["entries"]:
            with self.subTest(entry=entry["id"]):
                page = self.pages[entries[entry["id"]]]
                self.assertIn(f'id="entry-{entry["id"]}"', page)
                shown = display_entry(entry, self.catalog)
                if entry["kind"] in {"quest", "algorithm"}:
                    self.assertIn(literal(shown["summary"]), page)
                for identity in relations[entry["id"]]:
                    if entry["kind"] in {"quest", "algorithm", "recipe", "merchant"} and locations[identity] != entries[entry["id"]]:
                        self.assertIn(f'[[{locations[identity]}', page)
                    if locations[identity] != entries[entry["id"]] and "#" not in locations[identity] and entry["kind"] != "loot":
                        if entry["kind"] == "merchant" and identity == entry["details"]["item"]:
                            self.assertIn(
                                (entries[entry["id"]], (("item", identity), ("view", "offers"))),
                                transclusions(self.pages[locations[identity]]),
                            )
                            continue
                        fragment = "Recipes" if entry["kind"] == "recipe" else "entry-" + entry["id"]
                        self.assertIn(f'[[{entries[entry["id"]]}#{fragment}|', self.pages[locations[identity]])
        for entity in self.data["entities"]:
            target = locations[entity["id"]].split("#", 1)[0]
            self.assertIn(f'id="entity-{entity["id"]}"', self.pages[target])
        self.assertEqual(set(facts), {fact["id"] for fact in self.data["facts"]})
        self.assertEqual(set(entries), {entry["id"] for entry in self.data["entries"]})

    def test_complete_reviewed_profiles_keep_every_value_and_its_scope(self):
        self.assertEqual(
            hashlib.sha256((json.dumps({
                "schema_version": 1,
                "properties": [r for r in self.details["properties"] if r["id"] != "equip-ap-cost"],
                "profiles": [r for r in self.details["profiles"] if not r["id"].endswith("-equip-cost")],
            }, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(),
            "1afe8a32c2e129d483555878c938a2fbb08aa2bc6565433ecbaa9d5366568001",
        )
        self.assertEqual(len(self.details["properties"]), 49)
        self.assertEqual(len(self.details["profiles"]), 475)
        self.assertEqual(len({row["entity"] for row in self.details["profiles"]}), 297)
        self.assertEqual(sum(len(row["values"]) for row in self.details["profiles"]), 2559)
        locations = page_locations(self.data, self.catalog)
        entities = {row["id"]: row for row in self.data["entities"]}
        prices = {row["entity"]: row for row in self.catalog["unit_prices"]["prices"]}
        coins = {row["entity"]: row for row in self.catalog["currency"]["coins"]}
        recipes = [row for row in self.data["entries"] if row["kind"] == "recipe"]
        for profile in self.details["profiles"]:
            with self.subTest(profile=profile["id"]):
                page = self.pages[locations[profile["entity"]]]
                self.assertEqual(page.count(f'id="profile-{profile["id"]}"'), 1)
                self.assertIn(literal(profile["context"]), self.pages["Source provenance"])
                self.assertNotIn(literal(profile["context"]), page)
                folded = recipe_profile_values(profile, recipes, self.catalog.get("construction_recipes", []))
                for key, value in profile["values"].items():
                    grids = [grid for grid in self.details["grids"] if grid["entity"] == profile["entity"]]
                    if key == "being-armor" and any(g["kind"] == "health" for g in grids):
                        self.assertNotIn("<nowiki>Armor</nowiki> ||", page)
                    elif key in {"hp-grid-width", "hp-grid-height"} and any(g["kind"] == "health" for g in grids):
                        health = next(g for g in grids if g["kind"] == "health")
                        self.assertIn(f'{len(health["rows"])} rows x {len(health["rows"][0])} columns', page)
                    elif "-pattern-" in key and any(g["kind"] == key.split("-")[0] for g in grids):
                        self.assertIn(f'{profile["values"][key.split("-")[0] + "-pattern-min"]} to {profile["values"][key.split("-")[0] + "-pattern-max"]}', page)
                    elif key in folded:
                        self.assertIn(known(folded[key]), page.split("== Recipes ==", 1)[1])
                    elif profile["entity"] in coins and key in {"initial-price", "initial-weight", "stack-limit"}:
                        field = {"initial-price": "value_in_silver", "initial-weight": "weight_grams", "stack-limit": "stack_limit"}[key]
                        self.assertIn(known(coins[profile["entity"]][field]), page)
                    elif key == "initial-price" and profile["entity"] in prices:
                        self.assertIn(selective_view(price_text(prices[profile["entity"]]), "price", True), page)
                    else:
                        self.assertIn(profile_value(key, value, entities, locations), page)
        for name in ("Flax", "Linen"):
            self.assertIn("Numerical stats are not established", self.pages[name])
            self.assertNotIn("== Stats ==", self.pages[name])

    def test_final_image_metadata_has_exact_coverage_without_guessed_frames(self):
        images = self.data["illustrations"]
        replaced_trees = {"nature-4", "nature-7", "nature-17", "nature-20"}
        original_batch = {"schema_version": 1, "illustrations": [
            row for row in images if "health_armor" not in row and row.get("entity") not in replaced_trees]}
        self.assertEqual(
            hashlib.sha256((json.dumps(original_batch, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(),
            "d3df203720abfff6fe543008b9a6cdfe02906c3e5079cadaca6268ede9a576c7",
        )
        self.assertEqual(len(images), 326)
        original = {"schema_version": 1, "illustrations": [
            row for row in images if "entity" in row and row["entity"] not in replaced_trees]}
        self.assertEqual(hashlib.sha256((json.dumps(original, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(),
                         "16e17eb58db7b29c276393755aa73df2a6315607c9e621d1f260f21f84d0b799")
        missing = {row["entity"] for row in self.catalog["pages"] if not row["entity"].startswith("damage-class-")} - {row["entity"] for row in images if "entity" in row}
        self.assertEqual(missing, {"item-31", "item-48", "item-49", "item-171"})
        locations = page_locations(self.data, self.catalog)
        stations = {row["id"]: row for row in self.catalog["stations"]}
        for image in original_batch["illustrations"]:
            title = locations[image["entity"]] if "entity" in image else stations[image["station"]]["title"]
            page = self.pages[title]
            self.assertEqual(page.count(f'[[{image["file_title"]}|thumb|'), 1)
            self.assertIn(literal(image["sha256"]), self.pages["Source provenance"])
            self.assertNotIn(image["sha256"], page)
            self.assertIn(literal(image["caption"]), page)
        for identity in ("nature-6",):
            self.assertIn("not a complete mature specimen", self.pages[locations[identity]])

    def test_skill_specific_facts_and_algorithms_have_individual_owners(self):
        locations = page_locations(self.data, self.catalog)
        owners = fact_owners(self.data, locations)
        mechanics = self.pages["Game mechanics"]
        for entity in self.data["entities"]:
            if entity["category"] != "skill":
                continue
            page = self.pages[locations[entity["id"]]]
            entry_id = entity["id"] + "-mechanics"
            self.assertIn(f'id="entry-{entry_id}"', page)
            for fact in self.data["facts"]:
                if fact["entity"] == entity["name"]:
                    self.assertEqual(owners[fact["id"]], locations[entity["id"]])
                    self.assertNotIn(literal(fact["description"]), mechanics)
        self.assertIn("[[Focused Mind|", self.pages["Level progression"])
        self.assertIn("[[Brewer|", self.pages["Alchemy workstation"])
        self.assertNotIn("{|", mechanics)
        self.assertNotIn("[[Getting started", self.pages["Main Page"])
        self.assertEqual(self.pages["Getting started"], "#REDIRECT [[Research policy]]\n")
        self.assertIn("Record a useful observation", self.pages["Research policy"])

    def test_all_internal_links_and_explicit_anchors_resolve(self):
        for title, text in self.pages.items():
            for target in re.findall(r"\[\[([^\]|]+)", text):
                target = target.removeprefix(":")
                if target.startswith("File:"):
                    continue
                page, _, anchor = target.partition("#")
                page = page or title
                with self.subTest(source=title, target=target):
                    self.assertTrue(page in self.pages, f"{title}: missing target {page}")
                    if anchor:
                        headings = {html.unescape(re.sub(r"<[^>]+>", "", heading)).replace(" ", "_")
                                    for heading in re.findall(r"^=+\s*(.*?)\s*=+$", self.pages[page], re.MULTILINE)}
                        self.assertTrue(f'id="{anchor}"' in self.pages[page] or anchor in headings, target)

    def test_title_collisions_missing_entities_and_bad_classification_fail(self):
        changes = [
            lambda c: c["pages"].pop(),
            lambda c: c["pages"][0].update(title=c["pages"][1]["title"]),
            lambda c: c["pages"][0].update(title="File:Injected.png"),
            lambda c: c["pages"][0].update(title="Main Page"),
            lambda c: c["pages"][0].update(title="Some_title"),
            lambda c: c["pages"][0].update(title="Injected#Section"),
            lambda c: c["pages"][0].update(aliases=["Items"]),
            lambda c: c["pages"][0].update(aliases=[c["pages"][1]["title"]]),
            lambda c: c["entry_links"].append({"entry": "not-present", "entities": ["item-0"]}),
            lambda c: c.update(classifications=[{
                "entity": "item-0", "kind": "npc", "confidence": "inferred",
                "evidence": self.data["entities"][0]["evidence"], "note": "Synthetic test.",
            }]),
        ]
        for change in changes:
            catalog = copy.deepcopy(self.catalog)
            change(catalog)
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)
        with self.assertRaises(DataError):
            parse_catalog(b'{"schema_version":1,"schema_version":1}', self.data)

    def test_alias_is_redirect_and_never_replaces_an_index(self):
        data = synthetic_data()
        catalog = default_catalog(data)
        catalog["pages"][0]["aliases"] = ["Previous synthetic title"]
        pages = build_pages(ROOT, data, catalog)
        self.assertEqual(pages["Previous synthetic title"], "#REDIRECT [[Entity synthetic-item]]\n")

    def test_explicit_classification_is_cited_without_implying_hostility(self):
        data = research_data()
        catalog = default_catalog(data)
        catalog["classifications"] = [{
            "entity": "synthetic-being", "kind": "npc", "confidence": "inferred",
            "evidence": data["entities"][1]["evidence"], "note": "Synthetic classification only.",
        }]
        pages = build_pages(ROOT, data, catalog)
        self.assertIn("[[Synthetic merchant|", pages["NPCs"])
        self.assertIn("Synthetic classification only.", pages["Source provenance"])
        self.assertNotIn("Synthetic classification only.", pages["Synthetic merchant"])
        self.assertIn("Characters now listed under NPCs", pages["Bestiary"])
        self.assertNotIn("Synthetic merchant", pages["Bestiary"].split("Characters now listed")[0])

    def test_reviewed_npc_mapping_separates_characters_from_creatures(self):
        npcs = {row["entity"] for row in self.catalog["classifications"] if row["kind"] == "npc"}
        self.assertEqual(npcs, {f"being-{number}" for number in (5, 6, 8, 9, 12, 19, 20, 26, 33, 34, 35)})
        self.assertEqual(len(self.catalog["classifications"]), 36)
        self.assertIn("Dead Unwanted is Viend before his revival", self.pages["Dead Unwanted"])
        for name in ("Ranger Bhato", "Magus Clay", "Captain Eir", "Wilda"):
            self.assertIn(f"[[{name}|", self.pages["NPCs"])
            self.assertNotIn(name, self.pages["Bestiary"].split("Characters now listed")[0])

    def test_ambiguous_fact_identity_cannot_silently_select_a_page(self):
        data = synthetic_data()
        data["entities"][0]["name"] = "Same"
        second = copy.deepcopy(data["entities"][0])
        second["id"] = "second-item"
        data["entities"].append(second)
        data["facts"][0].update(entity="Same", page="Items")
        with self.assertRaises(DataError):
            fact_owners(data, {entity["id"]: entity["id"] for entity in data["entities"]})

    def test_catalog_and_profiles_order_do_not_change_output(self):
        catalog, details = copy.deepcopy(self.catalog), copy.deepcopy(self.details)
        for key in ("pages", "classifications", "entry_links", "guides", "damage_sources"):
            catalog[key].reverse()
        for key in ("profiles", "properties", "grids"):
            details[key].reverse()
        catalog["taxonomy"]["groups"].reverse()
        catalog["taxonomy"]["tags"].reverse()
        catalog["taxonomy"]["skill_groups"].reverse()
        for row in [*catalog["taxonomy"]["groups"], *catalog["taxonomy"]["tags"]]:
            row["members"].reverse()
            if "parents" in row:
                row["parents"].reverse()
        self.assertEqual(build_xml(self.pages), build_xml(build_pages(ROOT, self.data, catalog, details)))

    def test_player_pages_hide_identifiers_and_evidence_plumbing(self):
        for title, page in self.pages.items():
            if title in {"Source provenance", "Research policy", "Evidence and spoilers"}:
                continue
            visible = re.sub(r"\[\[File:.*?\]\]", "", page)
            visible = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", visible)
            visible = html.unescape(re.sub(r"<[^>]+>", "", visible))
            with self.subTest(title=title):
                self.assertNotRegex(visible, r"gml_\w+|\b\w*DB\[|quest_active_check|chopMod|daysAlive|Ygrid")
                self.assertNotRegex(visible, r"(?i)\b(?:Table|Stage|internal ID|station IDs?)\s*\d+|Evidence status|Source / section / key|Record ID|confidence")
                self.assertNotRegex(page, r"(?m)^.+\{\|")

    def test_bhato_has_compact_wares_and_journal_links_without_copied_prose(self):
        bhato = self.pages["Ranger Bhato"]
        self.assertEqual(bhato.count('{| class="wikitable"') + bhato.count('<table class="wikitable">'), 2)
        self.assertEqual(bhato.count('id="entry-merchant-12-'), 12)
        self.assertEqual(bhato.count("{{:"), 12)
        self.assertIn("[[Ranger Bhato|", self.pages["Merchants"])
        self.assertIn("[[Ranger Bhato|", self.pages["NPCs"])
        for identity in ("journal-7", "journal-7-location", "journal-8", "journal-9"):
            entry = next(row for row in self.data["entries"] if row["id"] == identity)
            self.assertIn(f"[[Quests and journal#entry-{identity}|", bhato)
            self.assertNotIn(literal(entry["summary"]), bhato)
            self.assertIn(literal(entry["summary"]), self.pages["Quests and journal"])
        self.assertIn("[[Armor workstation]]", bhato)
        armor = next(row for row in self.catalog["stations"] if row["id"] == "armor-workstation")
        self.assertIn(literal(armor["acquisition"]), self.pages["Armor workstation"])
        self.assertNotIn(literal(armor["acquisition"]), bhato)

    def test_workstations_are_output_catalogs_and_recipe_facts_have_one_owner(self):
        locations = page_locations(self.data, self.catalog)
        owners = entry_owners(self.data, locations, entry_relations(self.data, self.catalog), self.catalog)
        recipes = [display_entry(row, self.catalog) for row in self.data["entries"] if row["kind"] == "recipe"]
        self.assertEqual(len(recipes), 96)
        self.assertEqual(len(recipe_groups(recipes)), 77)
        self.assertEqual(self.pages["Alchemy workstation"].count('<table class="wikitable">'), 1)
        self.assertEqual(len(transclusions(self.pages["Alchemy workstation"])), 15)
        self.assertIn("Ingredients", self.pages["Alchemy workstation"])
        self.assertIn("Base cost", self.pages["Alchemy workstation"])
        self.assertNotIn("Maybe unused", self.pages["Armor workstation"])
        self.assertNotIn("{|", self.pages["Crafting"])
        self.assertIn("[[Inventory crafting]]", self.pages["Crafting"])
        for station in self.catalog["stations"]:
            self.assertIn(f'[[{station["title"]}]]', self.pages["Crafting"])
            self.assertIn("== What you can craft ==", self.pages[station["title"]])
        for entry in recipes:
            owner = owners[entry["id"]]
            self.assertIn(f'id="entry-{entry["id"]}"', self.pages[owner])
            for station in self.catalog["stations"]:
                if entry["details"]["station"] in station["methods"]:
                    self.assertIn(f'[[{station["title"]}]]', self.pages[owner])
        self.assertNotIn("item-53", locations)
        self.assertNotIn("item-131", locations)
        self.assertNotIn("item-125", locations)
        self.assertNotIn("Obtaining or finding", self.pages["Inventory crafting"])
        self.assertNotIn("Not established", self.pages["Inventory crafting"])

    def test_matching_recipe_profile_cost_and_yield_share_recipe_cells(self):
        campfire = self.pages["Campfire"]
        self.assertNotIn("Base crafting cost", campfire)
        self.assertNotIn("Base recipe yield", campfire)
        self.assertIn('id="profile-item-38-initializer"', campfire)
        self.assertIn('id="entry-recipe-personal-crafting-menu-38"', campfire)
        self.assertIn("<nowiki>4</nowiki> base [[Action points|AP]]", campfire)
        self.assertIn("[[Campfire|<nowiki>Campfire</nowiki>]] x <nowiki>1</nowiki>", campfire)
        for key, value, label in (
            ("craft-ap-cost", 5, "Base crafting cost"),
            ("craft-yield", 2, "Base recipe yield (items)"),
        ):
            details = copy.deepcopy(self.details)
            profile = next(row for row in details["profiles"] if row["id"] == "item-38-initializer")
            profile["values"][key] = value
            changed = build_pages(ROOT, self.data, self.catalog, details)["Campfire"]
            self.assertIn(literal(label) + " || " + known(value), changed)
            self.assertIn("<nowiki>4</nowiki> base [[Action points|AP]]", changed)
            self.assertIn("[[Campfire|<nowiki>Campfire</nowiki>]] x <nowiki>1</nowiki>", changed)
        profile = next(row for row in self.details["profiles"] if row["id"] == "item-38-initializer")
        recipes = [row for row in self.data["entries"] if row["kind"] == "recipe"]
        for change in (
            lambda p: p.update(context="Different effective runtime values."),
            lambda p: p.update(confidence="observed"),
            lambda p: p["evidence"][0].update(section="Different_source_scope"),
        ):
            modified = copy.deepcopy(profile)
            change(modified)
            self.assertEqual(recipe_profile_values(modified, recipes), {})
        original = next(row for row in recipes if row["id"] == "recipe-personal-crafting-menu-38")
        for change, retained in (
            (lambda e: e["details"]["cost"].update(amount=5), "craft-ap-cost"),
            (lambda e: e["details"]["cost"].update(unit="different unit"), "craft-ap-cost"),
            (lambda e: e["details"].update(cost=None), "craft-ap-cost"),
            (lambda e: e["details"]["outputs"][0].update(quantity=2), "craft-yield"),
        ):
            variant = copy.deepcopy(original)
            change(variant)
            self.assertNotIn(retained, recipe_profile_values(profile, [original, variant]))

    def test_ingredient_links_are_unique_outputs_with_all_legacy_recipe_anchors(self):
        used_in = self.pages["Beeswax"].split("== Used in ==\n", 1)[1].split("\n== ", 1)[0]
        links = re.findall(r"\[\[([^|]+)\|", used_in)
        self.assertEqual(set(links), {"Lesser Wound Salve#Recipes", "Minor Wound Salve#Recipes", "Wound Salve#Recipes"})
        self.assertEqual(len(links), 3)
        locations = page_locations(self.data, self.catalog)
        owners = entry_owners(self.data, locations, entry_relations(self.data, self.catalog), self.catalog)
        recipes = [row for row in self.data["entries"] if row["kind"] == "recipe"]
        self.assertEqual(len(recipes), 96)
        for recipe in recipes:
            self.assertEqual(self.pages[owners[recipe["id"]]].count(f'id="entry-{recipe["id"]}"'), 1)

    def test_initializer_weight_and_value_are_explicitly_not_final_stats(self):
        for title in ("Campfire", "Wood Buckler"):
            self.assertIn("literal initializer values before recipe postprocessing", self.pages[title])
            self.assertIn("not finalized in-game weights or prices", self.pages[title])

    def test_global_prices_are_item_owned_selective_transclusions(self):
        prices = self.catalog["unit_prices"]
        raw_prices = json.loads((ROOT / "content" / "facts" / "catalog.json").read_text())["unit_prices"]
        resolved = {"item-32", "item-84", "item-138", "item-139", "item-140", "item-248"}
        original_prices = [row for row in raw_prices["prices"] if row["entity"] not in resolved]
        self.assertEqual(hashlib.sha256((json.dumps(original_prices, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(),
                         "cacc81734f11f214e0bf28c0115050d129fe497112d0e415ba70e8aff4e1dc4e")
        self.assertEqual(len(prices["prices"]), 42)
        self.assertEqual(len(prices["covered_offers"]), 63)
        self.assertEqual(prices["unresolved_offers"], [])
        self.assertEqual({row["entity"]: row["value"] for row in prices["prices"] if row["entity"] in resolved},
                         {identity: Decimal(value) for identity, value in {
                             "item-32": "0.6", "item-84": "0.3", "item-138": "1.5",
                             "item-139": "1", "item-140": "0.25", "item-248": "1",
                         }.items()})
        locations = page_locations(self.data, self.catalog)
        known_prices = {row["entity"]: row for row in prices["prices"]}
        items = {row["details"]["item"] for row in self.data["entries"] if row["kind"] == "merchant"}
        self.assertEqual(len(items), 42)
        expected_default_owners = {locations[identity] for identity in items} | {
            locations[row["entity"]] for row in self.catalog["currency"]["coins"]}
        self.assertEqual({title for title, page in self.pages.items() if "" in available_views(page)}, expected_default_owners)
        for identity in items:
            page = self.pages[locations[identity]]
            self.assertIn(selective_view(price_text(known_prices.get(identity)), "price", True), page)
            if identity in known_prices:
                self.assertNotIn("Base value (not a shop price)", page)
        for entry in self.data["entries"]:
            if entry["kind"] != "merchant":
                continue
            page = self.pages[locations[entry["details"]["merchant"]]]
            self.assertIn("{{:" + locations[entry["details"]["item"]] + "}}", page)
            self.assertEqual(available_views(page), {"offers"})

    def test_unit_price_validation_rejects_wrong_currency_or_coverage(self):
        for change in (
            lambda c: c["unit_prices"].update(unit="unverified currency"),
            lambda c: c["unit_prices"]["prices"][0].update(value=True),
            lambda c: c["unit_prices"]["prices"][0].update(value=-1),
            lambda c: c["unit_prices"]["prices"][0].update(evidence=[]),
            lambda c: c["unit_prices"]["covered_offers"].pop(),
            lambda c: c["unit_prices"]["prices"].append(copy.deepcopy(c["unit_prices"]["prices"][0])),
        ):
            catalog = copy.deepcopy(self.catalog)
            change(catalog)
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)

    def test_no_vendor_price_is_repeated_on_the_item_or_technical_page(self):
        data = research_data()
        offer = next(row for row in data["entries"] if row["kind"] == "merchant")
        offer["details"].update(price=19.25, quantity=7, currency="test currency")
        pages = build_pages(ROOT, data)
        self.assertIn(literal(19.25), pages["Synthetic merchant"])
        self.assertNotIn(literal(19.25), pages["Entity synthetic-item"])
        self.assertNotIn(literal(19.25), pages["Source provenance"])

    def test_station_images_and_operator_reports_have_valid_explicit_targets(self):
        stations = {row["id"]: row for row in self.catalog["stations"]}
        self.assertEqual(len(stations), 8)
        station_images = [row for row in self.data["illustrations"] if "station" in row]
        self.assertEqual(len(station_images), 3)
        self.assertNotIn("Maybe unused", self.pages["Armor workstation"])
        for image in station_images:
            page = self.pages[stations[image["station"]]["title"]]
            self.assertIn(f'[[{image["file_title"]}|thumb|', page)
        raw = {"schema_version": 1, "illustrations": [copy.deepcopy(station_images[0])]}
        base = load_data(ROOT / "content" / "facts" / "game.json")
        raw["illustrations"][0]["variant"] = "unreviewed"
        with self.assertRaises(DataError):
            parse_illustrations(json.dumps(raw).encode(), base, self.catalog)
        self.assertIn("User-reported gameplay", self.pages["Source provenance"])

    def test_currency_guide_transcludes_coin_owned_values_and_keeps_pricing_exceptions(self):
        guide = self.pages["Currency and trading"]
        self.assertEqual(guide.count("{{:"), 3)
        for coin in self.catalog["currency"]["coins"]:
            title = next(row["title"] for row in self.catalog["pages"] if row["entity"] == coin["entity"])
            page = self.pages[title]
            self.assertIn("{{:" + title + "}}", guide)
            self.assertEqual(page.count("<onlyinclude>"), 1)
            self.assertIn(known(coin["weight_grams"]) + " g", page)
            self.assertNotIn("Base weight", page)
            self.assertNotIn("Base value (not a shop price)", page)
            self.assertNotIn("initial-weight", guide)
            self.assertNotIn("Acquisition is not established", page)
            self.assertIn("[[Currency and trading#currency-coin-consolidation|", page)
        self.assertIn("replaces the durability factor", guide)
        self.assertIn("does not multiply the durability and fuel reductions together", guide)
        self.assertIn("25 percent", guide)
        self.assertIn("10 percent", guide)
        self.assertIn("fewest possible coins are not guaranteed", guide)
        self.assertIn("Currency and trading", self.pages["Merchants"])
        self.assertEqual(self.data["game"]["build"], "0.8.1.5")
        self.assertIn("user report", self.pages["Source provenance"])

    def test_currency_editorial_qualifications_stay_on_technical_page(self):
        guide = self.pages["Currency and trading"]
        self.assertNotRegex(guide, r"Describe descending|so do not promise|Use the coin pages as")
        self.assertIn("Change uses the highest denominations first", guide)
        self.assertIn("Copper change is rounded to a whole coin", guide)
        self.assertIn("affect fractions smaller than one copper coin", guide)
        for rule in self.catalog["currency"]["rules"]:
            if rule["id"] in {"coin-consolidation", "coin-weight-units", "trade-standard-value"}:
                self.assertIn(literal(rule["qualification"]), self.pages["Source provenance"])
                self.assertNotIn(literal(rule["qualification"]), guide)

    def test_coin_profile_and_unit_mismatch_are_rejected(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["currency"]["coins"][0]["weight_grams"] = 26
        with self.assertRaises(DataError):
            build_pages(ROOT, self.data, catalog, self.details)
        catalog = copy.deepcopy(self.catalog)
        catalog["currency"]["coins"][0]["value_in_silver"] = 0.02
        with self.assertRaises(DataError):
            build_pages(ROOT, self.data, catalog, self.details)

    def test_taxonomy_is_complete_and_preserves_primary_and_cross_navigation(self):
        locations = page_locations(self.data, self.catalog)
        kinds = {row["entity"]: row["kind"] for row in self.catalog["classifications"]}
        seen = set()
        for group in self.catalog["taxonomy"]["groups"]:
            for identity in group["members"]:
                self.assertNotIn(identity, seen)
                seen.add(identity)
                self.assertIn(f'[[Category:{group["title"]}]]', self.pages[locations[identity]])
                section = self.pages[group["index"]].split(f'== {group["title"]} ==\n', 1)[1].split("\n== ", 1)[0]
                self.assertIn(f'[[{locations[identity]}|', section)
                self.assertNotEqual(kinds.get(identity), "npc")
        for title in ("Sceetler", "Scaal"):
            self.assertIn("[[Category:Scaalmyr]]", self.pages[title])
        for title in ("Mirk Runner", "Mirk Mauler"):
            self.assertIn("[[Category:Rodents]]", self.pages[title])
        for title in ("Mudfin", "Razorfin"):
            self.assertIn("[[Category:Aquatic creatures]]", self.pages[title])
        self.assertIn("[[Category:Bugs]]", self.pages["Nightmare"])
        self.assertIn("[[Category:Cutting and chopping tools]]", self.pages["Steel Hand Axe"])
        self.assertIn("[[Category:Weapons]]", self.pages["Steel Hand Axe"])
        for change in (
            lambda c: c["taxonomy"]["groups"][0]["members"].pop(),
            lambda c: c["taxonomy"]["groups"][0]["members"].append("being-12"),
            lambda c: c["taxonomy"]["groups"][0]["members"].append("item-0"),
            lambda c: c["taxonomy"]["groups"][0].update(title="Category:Injected"),
        ):
            catalog = copy.deepcopy(self.catalog)
            change(catalog)
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)

    def test_player_facing_skill_rewrites_keep_their_evidence_off_the_page(self):
        locations = page_locations(self.data, self.catalog)
        skills = [row for row in self.data["entities"] if row["category"] == "skill"]
        self.assertEqual(len(skills), 25)
        for skill in skills:
            page = self.pages[locations[skill["id"]]]
            self.assertIn("== <nowiki>Effects</nowiki> ==", page)
            self.assertNotRegex(page, r"Paraphrase of|not independently verified|localized design|described effects|runtime implementation")
            self.assertIn("[[Category:Skills]]", page)
        self.assertIn("Skill description methodology", self.pages["Source provenance"])

    def test_category_graph_links_and_transitive_membership_resolve(self):
        categories = category_definitions(self.data, self.catalog)
        locations = page_locations(self.data, self.catalog)
        expected = {identity: set() for identity in locations}

        def ancestors(title):
            return {title}.union(*(ancestors(parent) for parent in categories[title]["parents"]))

        for title, row in categories.items():
            page = self.pages["Category:" + title]
            children = {name for name, child in categories.items() if title in child["parents"]}
            self.assertTrue(row["members"] or children)
            self.assertIn(row["index"], ancestors(title))
            for parent in row["parents"]:
                self.assertIn(f"[[Category:{parent}]]", page)
                self.assertIn(f"[[:Category:{parent}|", page)
                self.assertIn(f"[[:Category:{title}|", self.pages["Category:" + parent])
            for identity in row["members"]:
                expected[identity].update(ancestors(title))
                self.assertIn(f"[[{locations[identity]}|", page)
        for row in self.catalog["pages"]:
            actual = set(re.findall(r"\[\[Category:([^\]|]+)", self.pages[row["title"]]))
            self.assertEqual(actual, expected[row["entity"]], row["title"])
        for title, page in self.pages.items():
            for target in re.findall(r"\[\[:?(Category:[^\]|]+)", page):
                self.assertIn(target, self.pages, (title, target))
        self.assertIn("[[:Category:Equipment by slot|", self.pages["Items"])
        self.assertIn("[[:Category:Skills|", self.pages["Skills"])
        document = build_xml(self.pages)
        from xml.etree import ElementTree
        root = ElementTree.fromstring(document)
        ns = {"w": "http://www.mediawiki.org/xml/export-0.11/"}
        for page in root.findall("w:page", ns):
            title = page.findtext("w:title", namespaces=ns)
            self.assertEqual(page.findtext("w:ns", namespaces=ns), "14" if title.startswith("Category:") else "0")

    def test_category_graph_rejects_cycles_orphans_empty_leaves_and_collisions(self):
        def change_row(catalog, target, **values):
            next(row for row in catalog["taxonomy"]["tags"] if row["title"] == target).update(values)

        changes = (
            lambda c: change_row(c, "Equipment by slot", parents=["Main-hand equipment"]),
            lambda c: change_row(c, "Equipment by slot", parents=[]),
            lambda c: change_row(c, "Equipment by slot", parents=["Missing parent"]),
            lambda c: change_row(c, "Equipment by slot", parents=["Nature"]),
            lambda c: change_row(c, "Equipment by slot", parents=["Items", "Items"]),
            lambda c: change_row(c, "Equipment by slot", parents=["Category:Items"]),
            lambda c: change_row(c, "Equipment by slot", parents="Items"),
            lambda c: change_row(c, "Equipment by slot", title="Wanderer"),
            lambda c: change_row(c, "Equipment by slot", title="Skills"),
            lambda c: change_row(c, "Equipment by slot", summary=""),
            lambda c: change_row(c, "Helmet-slot equipment", members=[]),
            lambda c: change_row(c, "Helmet-slot equipment", confidence="unknown"),
            lambda c: change_row(c, "Helmet-slot equipment", index=[]),
            lambda c: change_row(c, "Helmet-slot equipment", evidence=[]),
            lambda c: c["taxonomy"]["skill_groups"].pop(),
            lambda c: c["taxonomy"]["skill_groups"][0].update(entity="item-0"),
            lambda c: c["taxonomy"]["skill_groups"][0].update(members=["skill-0-0"]),
            lambda c: c["taxonomy"]["tags"].append({
                "title": "Empty filler", "index": "Items", "members": [],
                "summary": "No articles.", "parents": ["Items"],
            }),
        )
        for change in changes:
            catalog = copy.deepcopy(self.catalog)
            change(catalog)
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)
        catalog = copy.deepcopy(self.catalog)
        catalog["taxonomy"]["tags"].extend(
            {"title": f"Filler {number}", "index": "Items", "members": ["item-0"]}
            for number in range(129)
        )
        with self.assertRaisesRegex(DataError, "at most 128"):
            validate_catalog(catalog, self.data)

    def test_equipment_categories_match_native_slot_acceptance_not_dimensions(self):
        slots = {
            "Main-hand equipment": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 27, 28, 29, 30, 41, 44, 90, 93, 96, 105, 106, 157, 158, 159, 160, 161, 169, 179, 184, 185, 186, 187, 188, 189, 190, 191, 206, 212],
            "Off-hand equipment": [0, 1, 41, 45, 46, 50, 58, 76, 96, 110, 111, 118, 174, 212, 219, 220],
            "Helmet-slot equipment": [54, 116, 117, 119],
            "Hood-slot equipment": [42, 146, 204, 205],
            "Shirt-slot equipment": [22, 23, 24],
            "Outer torso equipment": [43, 55, 147, 194, 196, 197, 198],
            "Belt-slot equipment": [13, 166, 167, 168],
            "Cloak-slot equipment": [137, 145, 207, 208, 209],
            "Backpack-slot equipment": [12, 14, 26, 148],
            "Glove-slot equipment": [59, 164, 165, 199, 200],
            "Pants-slot equipment": [20, 21, 33],
            "Leg-armor-slot equipment": [56, 192, 193, 195],
            "Sock-slot equipment": [16, 17, 18],
            "Footwear-slot equipment": [15, 57, 201, 202, 203],
        }
        categories = category_definitions(self.data, self.catalog)
        actual = {title: row for title, row in categories.items() if "Equipment by slot" in row["parents"]}
        self.assertEqual(set(actual), set(slots))
        for title, numbers in slots.items():
            self.assertEqual(set(actual[title]["members"]), {f"item-{number}" for number in numbers})
            self.assertTrue(actual[title]["evidence"])
        self.assertEqual(sum(len(row["members"]) for row in actual.values()), 105)
        self.assertEqual(len(set().union(*(set(row["members"]) for row in actual.values()))), 102)
        for title in ("Torch", "Improvised Torch", "Improvised Enduring Torch"):
            self.assertIn("[[Category:Main-hand equipment]]", self.pages[title])
            self.assertIn("[[Category:Off-hand equipment]]", self.pages[title])
            self.assertNotIn("[[Category:Weapons]]", self.pages[title])
        for identity in categories["Ammunition"]["members"]:
            page = self.pages[page_locations(self.data, self.catalog)[identity]]
            self.assertIn("[[Category:Off-hand equipment]]", page)
            self.assertNotIn("[[Category:Weapons]]", page)
            self.assertNotIn("[[Category:Main-hand equipment]]", page)
        self.assertNotIn("[[Category:Equipment by slot]]", self.pages["Unarmed"])
        self.assertIn("[[Category:Weapons]]", self.pages["Unarmed"])
        self.assertNotIn("[[Category:Off-hand equipment]]", self.pages["Steel Greatsword"])
        self.assertIn("[[Category:Two-handed weapons]]", self.pages["Steel Greatsword"])
        self.assertIn("[[Category:Outer torso equipment]]", self.pages["Forager's Vest"])
        self.assertIn("[[Category:Clothes]]", self.pages["Forager's Vest"])
        self.assertIn("[[Category:Glove-slot equipment]]", self.pages["Iron Reinforced Gloves"])
        self.assertIn("[[Category:Armor]]", self.pages["Iron Reinforced Gloves"])
        self.assertNotIn("[[Category:Equipment by slot]]", self.pages["Jar of Fireflies"])

    def test_skill_categories_derive_the_five_localized_groups(self):
        categories = category_definitions(self.data, self.catalog)
        names = ("Wanderer", "Survivor", "Hunter", "Warrior", "Forager")
        for number, name in enumerate(names):
            self.assertEqual(set(categories[name]["members"]), {f"skill-{number}-{skill}" for skill in range(5)})
            self.assertEqual(categories[name]["parents"], ["Skills"])
            self.assertIn(f"[[:Category:{name}|", self.pages["Skills"])
            self.assertIn(f'id="entity-skill-group-{number}"', self.pages["Skills"])
        for entity in self.data["entities"]:
            if entity["category"] == "skill":
                page = self.pages[page_locations(self.data, self.catalog)[entity["id"]]]
                name = names[int(entity["group"].rsplit("-", 1)[1])]
                self.assertIn(f"[[Category:{name}]]", page)
                self.assertIn(f"[[:Category:{name}|", page)
        catalog = copy.deepcopy(self.catalog)
        catalog["taxonomy"]["skill_groups"][0]["summary"] = "</nowiki>[[Category:Injected]]"
        rendered = build_pages(ROOT, self.data, catalog, self.details)["Category:Wanderer"]
        self.assertIn("&lt;/nowiki&gt;", rendered)
        self.assertNotIn("</nowiki>[[Category:Injected]]", rendered)

    def test_consumables_materials_and_weapons_keep_evidenced_overlapping_roles(self):
        categories = category_definitions(self.data, self.catalog)
        expected = {
            "Steel Hand Axe": {"Weapons", "Axes", "Cutting and chopping tools", "Tools"},
            "Heavy Branch (Cypress)": {"Weapons", "Wood and bark", "Crafting materials", "Fire-making supplies"},
            "Honey": {"Food and drink", "Food ingredients", "Consumables", "Crafting materials"},
            "Riftvine Berries": {"Plant foods", "Food ingredients", "Consumables", "Crafting materials"},
            "Lamp Oil": {"Consumables", "Repair and refuelling supplies"},
            "Map Drawing Kit": {"Tools", "Consumables", "Mapping supplies"},
            "Summoning Stone": {"Consumables", "Summoning supplies"},
            "Large Scaalmyr Husk": {"Animal materials", "Crafting materials", "Armor", "Off-hand equipment"},
            "Glow Goo": {"Animal materials", "Crafting materials"},
            "Flask of Fire": {"Weapons", "Consumables", "Thrown flasks"},
        }
        for title, required in expected.items():
            actual = set(re.findall(r"\[\[Category:([^\]|]+)", self.pages[title]))
            self.assertTrue(required <= actual, (title, required - actual))
        for title in ("Lamp Oil", "Wayfarer's Vigor", "Glow Goo", "Mold", "Water Lily"):
            self.assertNotIn("[[Category:Food and drink]]", self.pages[title])
        for title in ("Rock", "Summoning Stone", "Map Drawing Kit", "Iron Arrow"):
            self.assertNotIn("[[Category:Weapons]]", self.pages[title])
        recipes = [entry for entry in self.data["entries"] if entry["kind"] == "recipe"]
        inputs = {row["item"] for entry in recipes for row in entry["details"]["inputs"]}
        food = set(categories["Food and drink"]["members"])
        self.assertEqual(set(categories["Food ingredients"]["members"]), food & inputs)
        for parent in ("Consumables", "Crafting materials"):
            children = [row for row in categories.values() if parent in row["parents"]]
            self.assertTrue(set(categories[parent]["members"]) <= set().union(*(set(row["members"]) for row in children)))
        self.assertIn("localized names only", self.pages["Category:Fibers and fabrics"])
        self.assertEqual(len(recipes), 96)
        self.assertEqual(sum(entry["kind"] == "merchant" for entry in self.data["entries"]), 63)
        self.assertEqual(len(self.catalog["unit_prices"]["prices"]), 42)

    def test_prices_use_exact_minimum_coin_count_and_approved_icons(self):
        cases = ((20, "2 gold"), (Decimal("3.57"), "3 silver 57 copper"),
                 (Decimal("12.34"), "1 gold 2 silver 34 copper"),
                 (Decimal("0.01"), "1 copper"), (0, "0 copper"))
        for value, expected in cases:
            self.assertEqual(price_text({"value": value}, []), expected)
        rendered = price_text({"value": Decimal("12.34")}, self.data["illustrations"])
        for number, name in ((74, "Gold"), (73, "Silver"), (72, "Copper")):
            self.assertIn(f"[[File:Item-{number}.png|20px|link=|alt={name} coin]]", rendered)
        for value in (Decimal("0.001"), Decimal("1.23000000000000000000000000000000001")):
            with self.assertRaises(DataError):
                price_text({"value": value}, [])
        raw = (ROOT / "content" / "facts" / "catalog.json").read_bytes().replace(
            b'"value": 0.25,', b'"value": 0.25000000000000000000000000000000001,', 1)
        exact = parse_catalog(raw, self.data)
        self.assertTrue(any(row["value"] == Decimal("0.25000000000000000000000000000000001")
                            for row in exact["unit_prices"]["prices"]))
        field_kit = self.pages["Survivor's Field Kit"]
        self.assertIn(selective_view(price_text({"value": 20}, self.data["illustrations"]), "price", True), field_kit)
        self.assertIn("{{:Survivor's Field Kit}}", self.pages["Gurb-Gurb"])
        self.assertIn("[[Alchemy workstation|Alternative crafting method]]", field_kit)
        self.assertIn("only while the fire remains active", field_kit)
        self.assertIn("[[Survivor's Field Kit|Alternative crafting method]]", self.pages["Alchemy workstation"])

    def test_health_and_attack_grids_preserve_shape_orientation_and_cell_meaning(self):
        grids = self.details["grids"]
        self.assertEqual(len(grids), 118)
        self.assertEqual(sum(g["kind"] == "health" for g in grids), 36)
        nightmare = next(g for g in grids if g["id"] == "being-28-health")
        self.assertEqual((len(nightmare["rows"]), len(nightmare["rows"][0])), (7, 3))
        self.assertEqual({(y, x) for y, row in enumerate(nightmare["rows"]) for x, cell in enumerate(row) if cell is None},
                         {(y, 2 if y % 2 == 0 else 0) for y in range(7)})
        self.assertEqual(sum(c["health"] for r in nightmare["rows"] for c in r if c), 14)
        page = self.pages["Nightmare"]
        self.assertIn("14 occupied health cells", page)
        self.assertIn('aria-label="Row 1, column 3: empty"', page)
        thorns = next(g for g in grids if g["id"] == "item-206-melee")
        self.assertEqual(thorns["rows"], [[{"min": 1, "max": 4}, {"min": 1, "max": 4}]] * 4)
        attack = self.pages["Thorns of Wackah"]
        self.assertEqual(attack.count(">1-4</td>"), 8)
        self.assertIn("4 rows x 2 columns", attack)
        self.assertIn("not maximum actual damage", attack)
        self.assertNotIn("Potential melee damage", attack)
        self.assertNotIn("== Melee", self.pages["Shortbow (Willow)"])
        self.assertIn("0-1</td>", self.pages["Unarmed"])
        self.assertIn("[[File:Health-armor-3.png|32px|alt=1 HP, 3 armor layers (gold shield)", self.pages["Sceetler"])
        self.assertNotIn("<nowiki>Armor</nowiki> ||", self.pages["Sceetler"])
        for title in ("Giant Slug", "Swamp Troll", "Mirk Mauler", "Scaal", "Wilda", "Unwanted Guard"):
            self.assertNotIn("<nowiki>Armor</nowiki> ||", self.pages[title])
        self.assertIn('id="fact-being-0-base-armor"', self.pages["Giant Slug"])
        for g in grids:
            self.assertIn(f'id="grid-{g["id"]}"', self.pages[page_locations(self.data, self.catalog)[g["entity"]]])
            if g["kind"] == "health":
                self.assertTrue(all(c is None or c["health"] == 1 for r in g["rows"] for c in r))

    def test_grid_schema_rejects_invented_health_holes_ranges_and_totals(self):
        for change in (
            lambda g: g["rows"].append([]),
            lambda g: g["rows"][0][0].update(health=2),
            lambda g: g["rows"][0][0].update(armor=4),
            lambda g: g["rows"][0][0].update(health=0),
            lambda g: g.update(rows=[]),
            lambda g: g.update(rows=[[None]]),
            lambda g: g.update(evidence=[]),
        ):
            details = copy.deepcopy(self.details)
            change(details["grids"][0])
            with self.assertRaises(DataError):
                validate_details(details, self.data)
        for cell in ({"min": 4, "max": 1}, {"min": 0, "max": 0}, {"min": False, "max": 1}, {"min": 1, "max": 999}):
            details = copy.deepcopy(self.details)
            next(g for g in details["grids"] if g["id"] == "item-206-melee")["rows"][0][0] = cell
            with self.assertRaises(DataError):
                validate_details(details, self.data)

    def test_semantic_units_are_explicit_without_changing_raw_values(self):
        for key, value, expected in (
            ("insulation", 0.5, "<nowiki>50</nowiki>%"),
            ("waterproof", 0.95, "<nowiki>95</nowiki>%"),
            ("tinder-bonus", -0.2, "<nowiki>-20</nowiki>%"),
            ("satiation-gain", 0.03, "<nowiki>3</nowiki>%"),
            ("initial-weight", 0.025, "<nowiki>25</nowiki> g"),
            ("initial-weight", 1.5, "<nowiki>1.5</nowiki> kg"),
            ("melee-ap-cost", 6, "<nowiki>6</nowiki> [[Action points|AP]]"),
            ("durability-max", 50, "<nowiki>50</nowiki>"),
            ("item-armor", 3.5, "<nowiki>3.5</nowiki>"),
        ):
            self.assertEqual(profile_value(key, value, {}, {}), expected)
        for title, page in self.pages.items():
            if title.startswith("Category:") or title in {"Source provenance", "Research policy", "Evidence and spoilers"}:
                continue
            self.assertNotRegex(page, r"\((?:internal [^)]*|0-1 fraction|fraction|unitless|durability units)\)")
        self.assertIn("not finalized in-game weights or prices", self.pages["Twine"])

    def test_character_state_and_damage_reverse_links_have_canonical_owners(self):
        self.assertIn("[[Dead Unwanted#State_history|", self.pages["Viend"])
        for title in ("Dead Unwanted", "Viend", "Magus Clay", "Clay's Strange Potion"):
            self.assertIn("[[Quests and journal#entry-journal-11|", self.pages[title])
            self.assertNotIn("Return to the abandoned campsite with the potion", self.pages[title])
        self.assertIn("Return to the abandoned campsite with Clay's Strange Potion", self.pages["Quests and journal"])
        for title in ("Thorns of Wackah", "Serpent Fang", "Nightmare", "Viper"):
            self.assertIn(f"[[{title}|", self.pages["Poison"])
        self.assertIn("[[Poison|", self.pages["Thorns of Wackah"])
        self.assertIn('id="entity-damage-class-2"', self.pages["Damage types"])

    def test_combat_guides_distinguish_initial_hits_spread_and_remedies(self):
        poison = self.pages["Poison"]
        self.assertIn("Poison that spreads can get beneath armor", poison)
        self.assertIn("loses one armor layer instead of receiving poison", poison)
        self.assertIn("do not restore already lost hit points", poison)
        sharp = self.pages["Sharp"]
        self.assertIn("cannot also make that cell bleed", sharp)
        self.assertIn("Rank 10 Blade Master", sharp)
        fire = self.pages["Fire"]
        self.assertIn("cannot be restored by ordinary wound salves", fire)
        self.assertIn("turn the burned cell into an ordinary wound", fire)
        self.assertIn("does not immediately restore the hit point", fire)
        self.assertIn("multi-point hit can make more than one check", self.pages["Piercing"])
        self.assertIn("Each positive-damage pattern cell", self.pages["Force"])
        for title, guide in (("Bandage", "Sharp"), ("Minor Antidote", "Poison"), ("Simple Burn Remedy", "Fire")):
            self.assertIn(f"[[{guide}|{guide}: effects and related rules]]", self.pages[title])
        self.assertIn("normally has 8 AP per turn", self.pages["Action points"])
        self.assertIn("minus any action cost carried over", self.pages["Action points"])
        self.assertIn("0.4 AP per square", self.pages["Action points"])
        self.assertIn("<nowiki>Equip cost</nowiki> || <nowiki>3.2</nowiki> [[Action points|AP]]", self.pages["Thorns of Wackah"])
        self.assertIn("<nowiki>7.2</nowiki> [[Action points|AP]]", self.pages["Thorns of Wackah"])
        locations = page_locations(self.data, self.catalog)
        self.assertEqual(len(self.catalog["damage_sources"]), 5)
        for source in self.catalog["damage_sources"]:
            item, damage = locations[source["entity"]], locations[source["damage_type"]]
            self.assertIn(f"[[{item}|", self.pages[damage])
            self.assertIn(f"[[{damage}|", self.pages[item])
            self.assertIn(literal(source["summary"]), self.pages[item])
            self.assertNotIn(literal(source["summary"]), self.pages[damage])
            self.assertIn(source["delivery"].capitalize(), self.pages[damage])
        for title in ("Gurb's Flask of Vileness", "Flask of Fire"):
            self.assertIn("bypasses armor", self.pages[title])
        for value, expected in ((0, "0"), (0.1, "0-1"), (1.2, "1-2"), (2.3, "2-3")):
            text = profile_value("extra-damage", value, {}, {})
            self.assertEqual(re.sub(r"</?nowiki>", "", text), expected)
        self.assertIn("rolled independently for each occupied attack cell", self.pages["Health and armor"])
        for change in (
            lambda c: c["guides"][0].update(title="Unreviewed guide"),
            lambda c: c["guides"][0].update(paragraphs=[]),
            lambda c: c["guides"][0].update(evidence=[]),
            lambda c: c["guides"][0].update(related_entities=["missing"]),
            lambda c: c["damage_sources"][0].update(damage_type="item-45"),
            lambda c: c["damage_sources"][0].update(delivery="melee"),
            lambda c: c["damage_sources"][0].update(evidence=[]),
        ):
            catalog = copy.deepcopy(self.catalog)
            change(catalog)
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)


def synthetic_details():
    data = synthetic_data()
    return {
        "schema_version": 1,
        "properties": [{"id": "synthetic-value", "label": "Synthetic value", "unit": None,
                        "description": "Synthetic test quantity, not game data."}],
        "profiles": [{
            "id": "synthetic-profile", "entity": "synthetic-item", "context": "Synthetic literal initializer.",
            "confidence": "inferred", "evidence": data["entities"][0]["evidence"],
            "values": {"synthetic-value": 0},
        }],
    }


class ProfileTests(unittest.TestCase):
    def test_transclusion_smoke_waits_for_jobs_but_never_masks_leaks_or_timeout(self):
        outputs = iter(("old price", "new price"))
        calls = []
        def run(*args, **kwargs):
            calls.append((args, kwargs))
            return b"0"
        api = lambda args: {"parse": {"text": {"*": next(outputs)}}}
        with patch("smoke_deploy.time.sleep"):
            self.assertEqual(refreshed_transclusion(run, api, "Merchant", "new price", "owner-anchor"), "new price")
        self.assertEqual(len(calls), 4)
        self.assertEqual(sum("runJobs" in args for args, _ in calls), 2)
        self.assertTrue(all(0 < kwargs["timeout"] <= 90 for _, kwargs in calls))
        for response in ("old price", "new price owner-anchor"):
            calls.clear()
            api = lambda args: {"parse": {"text": {"*": response}}}
            with patch("smoke_deploy.time.sleep"), self.assertRaises(RuntimeError):
                refreshed_transclusion(run, api, "Merchant", "new price", "owner-anchor")
            self.assertEqual(sum("runJobs" in args for args, _ in calls), 1 if "owner-anchor" in response else 10)

    def test_damage_class_ids_link_to_the_canonical_damage_page(self):
        data = synthetic_data()
        entity = copy.deepcopy(data["entities"][0])
        entity.update(id="damage-class-14", name="Synthetic damage class", category="damage_class")
        data["entities"].append(entity)
        details = synthetic_details()
        details["properties"][0]["id"] = "damage-class-id"
        details["profiles"][0]["values"] = {"damage-class-id": 14}
        page = build_pages(ROOT, data, details=details)["Entity synthetic-item"]
        self.assertIn("[[Synthetic damage class|", page)

    def test_numeric_boolean_and_unknown_values_are_distinct(self):
        for value in (0, -1, 2.5, True, False, None):
            details = synthetic_details()
            details["profiles"][0]["values"]["synthetic-value"] = value
            pages = build_pages(ROOT, synthetic_data(), details=details)
            self.assertIn("== Stats ==", pages["Entity synthetic-item"])
            self.assertIn(known(value), pages["Entity synthetic-item"])
            self.assertNotIn("Numerical stats are not established", pages["Entity synthetic-item"])

    def test_profile_schema_rejects_unbounded_strings_missing_sources_and_duplicates(self):
        changes = [
            lambda d: d["profiles"][0]["values"].update(**{"synthetic-value": "copied source text"}),
            lambda d: d["profiles"][0]["values"].update(**{"synthetic-value": float("inf")}),
            lambda d: d["profiles"][0]["values"].update(**{"synthetic-value": float("nan")}),
            lambda d: d["profiles"][0]["values"].update(**{"synthetic-value": 10**16}),
            lambda d: d["profiles"][0]["values"].update(unknown=4),
            lambda d: d["profiles"][0].update(evidence=[]),
            lambda d: d["profiles"][0].update(entity="not-present"),
            lambda d: d["profiles"].append(copy.deepcopy(d["profiles"][0])),
            lambda d: d["properties"].append(copy.deepcopy(d["properties"][0])),
        ]
        for change in changes:
            details = synthetic_details()
            change(details)
            with self.assertRaises(DataError):
                validate_details(details, synthetic_data())
        raw = json.dumps(empty_details()).encode()
        self.assertEqual(parse_details(raw + b" " * (MAX_DETAILS_BYTES - len(raw)), synthetic_data()), empty_details())
        with self.assertRaises(DataError):
            parse_details(raw + b" " * (MAX_DETAILS_BYTES + 1 - len(raw)), synthetic_data())

    def test_profile_text_is_literal(self):
        details = synthetic_details()
        details["profiles"][0]["context"] = "</nowiki>[[Injected]]<script>"
        pages = build_pages(ROOT, synthetic_data(), details=details)
        self.assertIn("&lt;/nowiki&gt;", pages["Source provenance"])
        self.assertNotIn("<script>", pages["Source provenance"])

    def test_external_image_metadata_supports_nature_and_skills_without_bytes(self):
        for category in ("item", "being", "nature", "skill"):
            data = illustration_data(approved=True)
            image = data.pop("illustrations")[0]
            data["entities"][0]["category"] = category
            if category == "skill":
                group = copy.deepcopy(data["entities"][0])
                group.update(id="synthetic-group", category="skill_group")
                data["entities"][0]["group"] = group["id"]
                data["entities"].append(group)
            images = parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [image]}).encode(), data)
            data["illustrations"] = images
            page = build_pages(ROOT, data)["Entity synthetic-item"]
            self.assertEqual(page.count("[[File:Synthetic.png|"), 1)
            self.assertIn("Synthetic test creator", build_pages(ROOT, data)["Source provenance"])
        self.assertEqual(
            hashlib.sha256((ROOT / "content" / "facts" / "game.json").read_bytes().replace(
                b'"build": "0.8.1.5"', b'"build": null', 1,
            )).hexdigest(),
            "0ab88dfd0d509370d93f87b79390f550358230c784e735d147f66c58bb70c0d8",
        )


if __name__ == "__main__":
    unittest.main()
