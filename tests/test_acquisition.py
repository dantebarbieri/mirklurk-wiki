import copy
import hashlib
import json
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from wiki_anchors import acquisition_fragments, entry_fragments, titled
from wiki_catalog import category_definitions, entry_owners, entry_relations, ingredient_acquisition, page_locations, validate_catalog
from wiki_data import DataError
from wiki_details import load_publication_inputs
from wiki_render import audit_report, image_caption, acquisition_probability, build_pages, clothing_subgroups, display_entry, literal
from wiki_views import available_views, transclusions


class AcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)
        cls.audit = audit_report(cls.data, cls.catalog, cls.details)
        cls.locations = page_locations(cls.data, cls.catalog)
        owners = entry_owners(cls.data, cls.locations, entry_relations(cls.data, cls.catalog), cls.catalog)
        cls.shown = entry_fragments(cls.data["entries"], owners, cls.locations)

    def test_every_item_has_a_verified_method_or_an_explicit_scoped_note(self):
        document = self.catalog["acquisition"]
        self.assertEqual(len(document["sources"]), 22)
        self.assertEqual(sum(len(source["rows"]) for source in document["sources"]), 130)
        normal = {row["item"] for source in document["sources"] for row in source["rows"]}
        normal.update(item for pool in document["pools"] for item in pool["eligible_item_ids"])
        for original in self.data["entries"]:
            entry = display_entry(original, self.catalog)
            if entry["kind"] == "recipe":
                normal.update(row["item"] for row in entry["details"]["outputs"])
            elif entry["kind"] == "merchant":
                normal.add(entry["details"]["item"])
            elif entry["kind"] == "loot" and entry["details"]["outcome"] is not None:
                normal.add(entry["details"]["outcome"])
        notes = {note["item"]: note for note in document["item_notes"]}
        unverified = {identity for identity, note in notes.items() if note["kind"] in {"unverified", "unreleased"}}
        self.assertEqual(unverified, {"item-40", "item-48", "item-49"})
        self.assertFalse(normal & unverified)
        self.assertIn("item-254", normal)
        self.assertEqual(len(normal | (notes.keys() - unverified)), 263)
        self.assertEqual(normal | notes.keys(), {entity["id"] for entity in self.data["entities"] if entity["category"] == "item"})
        self.assertFalse(any("No documented acquisition source is available yet." in text for text in self.pages.values()))
        self.assertIn("built-in", self.pages["Unarmed"])
        self.assertIn("not a collectible item", self.pages["Finish Raft"])
        locations = self.locations
        for identity in ("item-170",):
            self.assertIn("[[" + locations[identity] + "#Recipes|", self.pages["Finish Raft"])
        for identity in unverified:
            self.assertIn("Unknown" if identity == "item-40" else "unreleased content", self.pages[locations[identity]])
            self.assertNotIn("unobtainable", self.pages[locations[identity]])

    def test_clothing_is_browsable_in_items_and_category_by_reviewed_slots(self):
        clothes = next(row for row in self.catalog["taxonomy"]["groups"] if row["title"] == "Clothes")
        expected = {"Headwear": 5, "Shirts": 3, "Outerwear": 3, "Cloaks": 5, "Gloves": 4,
                    "Pants": 3, "Socks": 3, "Footwear": 5}
        groups = clothing_subgroups(self.catalog, clothes["members"])
        self.assertEqual({label: len(members) for label, members, _ in groups}, expected)
        self.assertEqual(set().union(*(members for _, members, _ in groups)), set(clothes["members"]))
        locations = self.locations
        for page in ("Items", "Category:Clothes"):
            for label, members, slots in groups:
                section = self.pages[page].split("=== " + label + " ===\n", 1)[1].split("\n==", 1)[0]
                for identity in members:
                    self.assertIn("{{Item|" + locations[identity] + "}}", section)
                for slot in slots:
                    self.assertIn("[[:Category:" + slot + "|", section)
        anchors = re.findall(r'id="item-([^"]+)"', self.pages["Items"])
        self.assertEqual(len(anchors), 265)
        self.assertEqual(set(anchors), {locations[row["id"]].replace(" ", "_") for row in self.data["entities"] if row["category"] == "item" and row["id"] != "item-31"})

    def test_overlapping_clothing_tags_never_duplicate_primary_index_anchors(self):
        catalog = copy.deepcopy(self.catalog)
        gloves = next(row for row in catalog["taxonomy"]["tags"] if row["title"] == "Glove-slot equipment")
        gloves["members"].append("item-42")
        pages = build_pages(ROOT, self.data, catalog, self.details)
        self.assertEqual(pages["Items"].count('id="item-Simple_Hood"'), 1)
        self.assertIn("[[Category:Glove-slot equipment]]", pages["Simple Hood"])
        self.assertIn("[[Category:Hood-slot equipment]]", pages["Simple Hood"])
        clothes = next(row for row in catalog["taxonomy"]["groups"] if row["title"] == "Clothes")
        gloves["members"].remove("item-42")
        hood = next(row for row in catalog["taxonomy"]["tags"] if row["title"] == "Hood-slot equipment")
        hood["members"].remove("item-42")
        self.assertEqual(dict((label, members) for label, members, _ in clothing_subgroups(catalog, clothes["members"]))["Other clothing"],
                         {"item-42"})

    def test_ingredient_groups_are_exact_input_source_joins_not_material_or_ware_lists(self):
        inputs = {row["item"] for entry in self.data["entries"] if entry["kind"] == "recipe"
                  for row in entry["details"]["inputs"]}
        inputs.update(row["item"] for recipe in self.catalog["construction_recipes"] for row in recipe["inputs"])
        routes = ingredient_acquisition(self.data, self.catalog)
        self.assertEqual(set(routes), inputs)
        self.assertEqual(len(inputs), 55)
        expected = {"Creature drops": 13, "Gatherables": 37, "Purchased ingredients": 1,
                    "Crafted ingredients": 4, "Other ingredient sources": 1}
        categories = category_definitions(self.data, self.catalog)
        self.assertEqual(set(categories["Recipe ingredients"]["members"]), inputs)
        locations = self.locations
        for method, count in expected.items():
            members = {identity for identity, methods in routes.items() if method in methods}
            self.assertEqual(len(members), count, method)
            self.assertEqual(set(categories[method]["members"]), members)
            section = self.pages["Items"].split("=== " + method + " ===\n", 1)[1].split("\n==", 1)[0]
            for item in members:
                self.assertIn("{{Item|" + locations[item] + "}}", section)
                self.assertIn("[[Category:" + method + "]]", self.pages[locations[item]])
                for target, _ in routes[item][method]:
                    self.assertIn("[[" + target + "|", section)
                    self.assertIn("[[" + target + "|", self.pages["Category:" + method])
        offers = {entry["details"]["item"] for entry in self.data["entries"] if entry["kind"] == "merchant"}
        self.assertEqual(set(categories["Purchased ingredients"]["members"]), inputs & offers)
        self.assertEqual(inputs & offers, {"item-45"})
        self.assertNotIn("Creature drops", routes["item-142"])
        self.assertIn(("Plant harvesting#acquisition-Calmia_Root", "Plant harvesting"), routes["item-142"]["Gatherables"])
        self.assertIn(("Starting equipment#" + titled("acquisition", locations["item-39"]), "Starting equipment"),
                      routes["item-39"]["Other ingredient sources"])
        self.assertIn("[[:Category:Crafting materials|Material families]]", self.pages["Items"])
        material_section = self.pages["Items"].split("== Crafting materials ==\n", 1)[1].split("\n== ", 1)[0]
        self.assertIn("[[#Recipe_ingredients_by_acquisition|", material_section)
        self.assertIn("[[Items#Recipe_ingredients_by_acquisition|", self.pages["Category:Crafting materials"])
        self.assertIn("[[Category:Food ingredients]]", self.pages["Honey"])

    def test_ingredient_methods_overlap_and_ignore_random_only_eligibility(self):
        data, catalog = copy.deepcopy(self.data), copy.deepcopy(self.catalog)
        item = "item-103"
        offer = next(row for row in data["entries"] if row["kind"] == "merchant")
        offer["details"]["item"] = item
        source = next(row for row in catalog["acquisition"]["sources"] if row["id"] == "plant-harvesting")
        source["rows"][0]["item"] = item
        routes = ingredient_acquisition(data, catalog)
        self.assertTrue({"Creature drops", "Gatherables", "Purchased ingredients"} <= routes[item].keys())
        source["rows"][0]["coverage"] = "eligible-pool"
        self.assertNotIn("Gatherables", ingredient_acquisition(data, catalog)[item])
        self.assertNotIn("Creature drops", ingredient_acquisition(self.data, self.catalog)["item-142"])

    def test_ingredient_fallbacks_keep_story_random_only_and_unknown_records_reachable(self):
        data, catalog = copy.deepcopy(self.data), copy.deepcopy(self.catalog)
        recipe = next(row for row in data["entries"] if row["kind"] == "recipe")
        recipe["details"]["inputs"].extend({"item": item, "quantity": 1} for item in ("item-48", "item-100"))
        catalog["construction_recipes"][0]["inputs"].append({"item": "item-107", "quantity": 1})
        routes = ingredient_acquisition(data, catalog)
        self.assertEqual(set(routes["item-48"]), {"Unverified ingredient sources"})
        self.assertEqual(set(routes["item-100"]), {"Other ingredient sources"})
        self.assertTrue(all(label.endswith("(eligibility only)") for _, label in routes["item-100"]["Other ingredient sources"]))
        self.assertTrue(any(target.startswith("Story rewards and finds#acquisition-")
                            for target, _ in routes["item-107"]["Other ingredient sources"]))
        pages = build_pages(ROOT, data, catalog, self.details)
        self.assertIn("{{Item|Flax}}", pages["Category:Unverified ingredient sources"])
        self.assertIn("{{Item|Sapphire}}", pages["Category:Other ingredient sources"])
        self.assertNotIn("[[Category:Gatherables]]", pages["Sapphire"])
        self.assertNotIn("[[Category:Creature drops]]", pages["Sapphire"])
        self.assertIn("{{Item|Flax}}", pages["Category:Fibers and fabrics"])

    def test_acquisition_snapshot_includes_conditions_and_probability_qualifications(self):
        document = self.catalog["acquisition"]
        # Prose carries prerequisites too: retain condition, odds_note and probability.scope.
        snapshot = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        self.assertEqual(hashlib.sha256(snapshot.encode()).hexdigest(),
                         "5fe4b5f770b768b0a568441ac26ec95883dfab52a0a00ff49aafbae94d8eef33")

    def test_gathering_quantities_and_insect_distributions_remain_exact(self):
        sources = {source["id"]: source for source in self.catalog["acquisition"]["sources"]}
        identities = {"plant-harvesting", "tree-shrub-harvesting", "beehives", "harvested-insects",
                      "night-fireflies", "story-acquisition", "mapmaking"}
        rows = [row for source in self.catalog["acquisition"]["sources"] if source["id"] in identities for row in source["rows"]]
        from test_editorial import gameplay_record
        self.assertEqual(hashlib.sha256((json.dumps([gameplay_record(row) for row in rows], sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest(),
                         "ca3989c85242bae95b6f3fee84550bfb95762cb455f4533e2e193ab4bd66475d")
        for path in ("ground", "berries"):
            insects = [row for row in sources["harvested-insects"]["rows"] if row["id"].startswith("extra-bug-" + path + "-")]
            self.assertEqual(len(insects), 7)
            self.assertEqual(sum(Fraction(row["probability"]["numerator"], row["probability"]["denominator"]) for row in insects), 1)
            self.assertTrue(all("check succeeding" in row["probability"]["scope"] for row in insects))
        by_id = {row["id"]: row for row in rows}
        for identity, minimum, maximum in (("harvest-fern-fiber", 1, 10), ("harvest-cranberries", 2, 8),
                                           ("harvest-watercress", 1, 8), ("harvest-turnip", 1, 2),
                                           ("harvest-calmia-root", 1, 3), ("harvest-water-lily", 1, 2),
                                           ("beehive-honey", 1, 4), ("beehive-beeswax", 1, 4)):
            self.assertEqual(by_id[identity]["quantity"], {"min": minimum, "max": maximum})
        self.assertIsNone(by_id["harvest-ash-coal"]["quantity"])
        self.assertIn("Map of area for the current area", " ".join(sources["mapmaking"]["conditions"]))
        self.assertIn("no fixed item count for a whole tree", sources["tree-shrub-harvesting"]["loot_context"])
        self.assertIn("not the chance per harvested plant", sources["harvested-insects"]["loot_context"])
        self.assertIn("[[Harvested insects]]", self.pages["Creepy-Crawlies"])
        self.assertIn("one extra-insect check instead of the repeated", self.pages["Creepy-Crawlies"])
        self.assertIn("[[Green Fingers", self.pages["Plant harvesting"])
        self.assertIn("[[Creepy-Crawlies", self.pages["Harvested insects"])

    def test_calmia_world_harvest_keeps_yield_separate_from_plant_placement(self):
        source = next(row for row in self.catalog["acquisition"]["sources"] if row["id"] == "plant-harvesting")
        row = next(row for row in source["rows"] if row["id"] == "harvest-calmia-root")
        self.assertEqual(row["quantity"], {"min": 1, "max": 3})
        self.assertIn("overworld", row["condition"])
        self.assertIn("purple-flowered", row["condition"])
        self.assertIn("not plants in a clump", row["condition"])
        self.assertIn("Green Fingers can add one extra root", row["condition"])
        self.assertIn("insects are separate", row["condition"])
        self.assertEqual({reference["section"] for reference in row["evidence"]},
                         {"gml_GlobalScript_scr_items", "gml_Object_manager_area_Alarm_2", "spr_ts_hinderance"})
        self.assertIn(literal(row["condition"]), self.pages["Plant harvesting"])
        self.assertIn(("Plant harvesting", (("item", "Calmia Root"), ("view", "loot"))),
                      transclusions(self.pages["Calmia Root"]))
        self.assertNotIn("clumps of", self.pages["Calmia Root"])
        self.assertNotIn("clumps of", self.pages["Plant harvesting"])

    def test_calmia_sale_guidance_does_not_create_a_purchase_price_contract(self):
        note = next(row for row in self.catalog["acquisition"]["item_notes"] if row["item"] == "item-142")
        self.assertEqual(note["kind"], "gathering")
        self.assertIn("intact Calmia Root sells for 25 copper per root", note["text"])
        self.assertIn("sells for 25 copper per root", note["text"])
        self.assertIn(literal(note["text"]), self.pages["Calmia Root"])
        self.assertNotIn(literal(note["text"]), self.pages["Plant harvesting"])
        self.assertNotIn("item-142", {row["entity"] for row in self.catalog["unit_prices"]["prices"]})
        self.assertNotIn("", available_views(self.pages["Calmia Root"]))
        self.assertNotIn("price", available_views(self.pages["Calmia Root"]))
        self.assertNotIn("=== Buying ===", self.pages["Calmia Root"])

    def test_recorder_scripted_pickup_and_eir_hand_in_have_distinct_owners(self):
        source = next(row for row in self.catalog["acquisition"]["sources"] if row["id"] == "story-acquisition")
        row = next(row for row in source["rows"] if row["id"] == "story-wooden-recorder")
        self.assertEqual(row["item"], "item-75")
        self.assertEqual(row["quantity"], {"min": 1, "max": 1})
        self.assertIn("Dead Unwanted", row["condition"])
        self.assertIn("scripted quest pickup, not ordinary corpse loot", row["condition"])
        self.assertIn(literal(row["condition"]), self.pages["Story rewards and finds"])
        self.assertIn(("Story rewards and finds", (("item", "Wooden Recorder"), ("view", "loot"))),
                      transclusions(self.pages["Wooden Recorder"]))
        self.assertIn("[[Story rewards and finds]]", self.pages["Dead camp"])
        self.assertIn("automatically hands over one recorder", self.pages["Quests and journal"])
        self.assertIn("next midnight", self.pages["Quests and journal"])
        self.assertNotIn("recovered flute", self.pages["Quests and journal"])
        for title in ("Wooden Recorder", "Dead Unwanted", "Captain Eir"):
            self.assertIn("[[Quests and journal#quest-The_ruined_camp|", self.pages[title])
            self.assertNotIn("automatically hands over one recorder", self.pages[title])
        self.assertIn("Editorial entry evidence", self.audit)
        self.assertIn("menu_psynch[being6/item75]", self.audit)

    def test_fixed_sources_are_conditional_and_have_single_editable_rows(self):
        sources = {row["id"]: row for row in self.catalog["acquisition"]["sources"]}
        self.assertEqual(len(sources["starting-equipment"]["rows"]), 12)
        self.assertEqual(len(sources["dead-camp"]["rows"]), 5)
        locations = self.locations
        for source in (sources["starting-equipment"], sources["dead-camp"]):
            self.assertEqual(available_views(self.pages[source["title"]]), {"loot"})
            for row in source["rows"]:
                owner, anchor = self.pages[source["title"]], 'id="' + acquisition_fragments(source, locations)[row["id"]] + '"'
                self.assertEqual(owner.count(anchor), 1)
                self.assertEqual(row["probability"]["numerator"], row["probability"]["denominator"])
                self.assertIn((source["title"], (("item", locations[row["item"]]), ("view", "loot"))),
                              transclusions(self.pages[locations[row["item"]]]))
                self.assertNotIn(anchor, self.pages[locations[row["item"]]])
                self.assertNotIn("No documented acquisition source", self.pages[locations[row["item"]]])
        starting = {row["item"]: row for row in sources["starting-equipment"]["rows"]}
        self.assertEqual(starting["item-36"]["quantity"], {"min": 3, "max": 3})
        self.assertIn("Easy only", starting["item-3"]["condition"])
        self.assertIn("Medium and Hard", starting["item-2"]["condition"])
        for identity in ("item-12", "item-25", "item-68", "item-89"):
            self.assertIn("All difficulties", starting[identity]["condition"])
        camp = {row["item"]: row for row in sources["dead-camp"]["rows"]}
        self.assertEqual(set(camp), {"item-13", "item-32", "item-95", "item-41", "item-25"})
        for identity in ("item-13", "item-32", "item-95"):
            self.assertIn("dead-body pile", camp[identity]["condition"])
        for identity in ("item-41", "item-25"):
            self.assertIn("second, wooden container", camp[identity]["condition"])
        self.assertIn("torn central tent", self.pages["Dead camp"])
        self.assertIn("not random corpse loot or replenishing supplies", self.pages["Dead camp"])

    def test_raft_completion_is_an_owned_in_place_recipe_not_a_field_kit(self):
        recipes = self.catalog["construction_recipes"]
        self.assertEqual(len(recipes), 1)
        recipe = recipes[0]
        self.assertEqual((recipe["owner_item"], recipe["station_item"], recipe["station_id"]),
                         ("item-171", "item-170", "raft-base"))
        self.assertEqual({row["item"]: row["quantity"] for row in recipe["inputs"]},
                         {"item-92": 8, "item-35": 6, "item-169": 1})
        self.assertEqual(recipe["base_ap_cost"], 8)
        self.assertEqual(recipe["result"]["kind"], "in-place")
        owner = self.pages["Finish Raft"]
        self.assertIn("no inventory item is created", owner)
        self.assertNotIn("Survivor's Field Kit", owner)
        self.assertNotIn("Crafting AP cost", owner)
        self.assertNotIn("Crafting yield", owner)
        self.assertEqual(owner.count('id="recipe-Finish_Raft"'), 1)
        self.assertIn(("Finish Raft", (("station", "raft-base"), ("view", "recipes"))),
                      transclusions(self.pages["Raft Base"]))
        locations = self.locations
        for ingredient in recipe["inputs"]:
            self.assertIn("[[Finish Raft#Recipes|", self.pages[locations[ingredient["item"]]])
        for change in (
            lambda c: c["construction_recipes"][0]["result"].update(item="item-172"),
            lambda c: c["construction_recipes"][0]["result"].update(kind="inventory"),
            lambda c: c["construction_recipes"][0].update(owner_item="item-172"),
            lambda c: c["construction_recipes"][0].update(station_item="item-172"),
            lambda c: c["construction_recipes"][0].update(evidence=[]),
        ):
            catalog = copy.deepcopy(self.catalog)
            change(catalog)
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)

    def test_invalid_acquisition_data_fails_closed(self):
        changes = (
            lambda d: d.update(raw_dump="forbidden field"),
            lambda d: d.update(build="unreviewed"),
            lambda d: d["sources"].append(copy.deepcopy(d["sources"][0])),
            lambda d: d["sources"][0].update(title="Items"),
            lambda d: d["sources"][0].update(title="Template:Acquisition"),
            lambda d: d["sources"][0].update(related_pages=["Missing"]),
            lambda d: d["sources"][0].update(image_entity="skill-0-0"),
            lambda d: d["sources"][0].update(evidence=[]),
            lambda d: d["sources"][0].update(kind=[]),
            lambda d: d["sources"][0]["rows"][0].update(item="unreviewed"),
            lambda d: d["sources"][0]["rows"][0].update(quantity={"min": 3, "max": 1}),
            lambda d: d["sources"][0]["rows"][0]["probability"].update(numerator=2),
            lambda d: d["sources"][0]["rows"][0]["probability"].update(denominator=0),
            lambda d: d["sources"][0]["rows"][0]["probability"].update(numerator=True),
            lambda d: d["sources"][0]["rows"][0].update(probability=None),
            lambda d: d["sources"][0]["rows"][0].update(coverage="guessed"),
            lambda d: d["sources"][0]["rows"][0].update(coverage={}),
            lambda d: d["sources"][0]["rows"].append(copy.deepcopy(d["sources"][0]["rows"][0])),
        )
        for change in changes:
            catalog = copy.deepcopy(self.catalog)
            change(catalog["acquisition"])
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)

    def test_all_reviewed_pools_have_exact_members_and_static_item_readers(self):
        document = self.catalog["acquisition"]
        sources = {source["id"]: source for source in document["sources"]}
        pools = {pool["id"]: pool for pool in document["pools"]}
        from test_editorial import gameplay_record
        unchanged = [gameplay_record(pool) for pool in document["pools"]]
        self.assertEqual(hashlib.sha256((json.dumps(unchanged, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest(),
                         "dda22507ce2ad209ff7504ed1bf9b40b0aa675706c010722e9dbd4b4a0f0d479")
        self.assertEqual({identity: len(pool["eligible_item_ids"]) for identity, pool in pools.items()}, {
            "skeleton-outdoors": 92, "skeleton-indoors": 70, "chest-common": 96, "chest-middle": 95,
            "chest-rich": 78, "ruins-large": 20, "ruins-small": 9, "nest-tiny": 7,
            "cracks-tiny": 6, "unwanted-remains": 73, "survivor-remains": 67,
        })
        self.assertEqual(pools["chest-common"]["item_conditions"], {})
        self.assertIn("item-258", set(pools["unwanted-remains"]["eligible_item_ids"]) & set(pools["survivor-remains"]["eligible_item_ids"]))
        self.assertIn("item-254", pools["survivor-remains"]["eligible_item_ids"])
        self.assertNotIn("item-254", pools["unwanted-remains"]["eligible_item_ids"])
        self.assertFalse(set(pools["skeleton-outdoors"]["eligible_item_ids"]) <= set(pools["skeleton-indoors"]["eligible_item_ids"]))
        locations = self.locations
        for source in sources.values():
            for reference in source.get("pool_refs", []):
                pool = pools[reference["pool"]]
                owner = sources[pool["owner_source"]]["title"]
                self.assertIn("pool-source", available_views(self.pages[source["title"]]))
                self.assertIn("pool", available_views(self.pages[owner]))
                source_text = self.pages[source["title"]]
                self.assertEqual(source_text.count("{{:"), len(transclusions(source_text)))
                for item in pool["eligible_item_ids"]:
                    with self.subTest(source=source["id"], pool=pool["id"], item=item):
                        readers = transclusions(self.pages[locations[item]])
                        self.assertIn((source["title"], (("pool", pool["id"]), ("view", "pool-source"))), readers)
                        self.assertIn((owner, (("item", locations[item]), ("pool", pool["id"]), ("view", "pool"))), readers)
                        self.assertNotIn("No documented acquisition source", self.pages[locations[item]])
                        self.assertEqual(self.pages[owner].count('id="' + titled("pool-item-" + pool["id"], locations[item]) + '"'), 1)
        for title in ("Raving Unwanted", "Mutated Unwanted"):
            self.assertIn("[[Raving and Mutated Unwanted loot", self.pages[title])
        self.assertIn("[[Survivor loot", self.pages["Survivor"])

    def test_shared_story_gate_and_boulder_context_have_one_owner(self):
        pools = self.catalog["acquisition"]["pools"]
        gate = next(pool["item_conditions"]["item-127"] for pool in pools if "item-127" in pool["item_conditions"])
        self.assertEqual(self.pages["Random treasure"].count(literal(gate)), 1)
        self.assertIn("|chest-middle|chest-rich=", self.pages["Random treasure"])
        self.assertNotIn("|chest-common|chest-middle|chest-rich=", self.pages["Random treasure"])
        source = next(source for source in self.catalog["acquisition"]["sources"] if source["id"] == "boulders")
        self.assertEqual(self.pages[source["title"]].count(literal(source["loot_context"])), 1)
        self.assertIn("10% chance", source["loot_context"])
        self.assertIn("Viper", source["loot_context"])
        self.assertEqual({row["id"] for row in source["rows"] if row["quantity"] == {"min": 1, "max": 5}},
                         {"boulders-base-maggot", "boulders-base-beetle"})
        for row in source["rows"]:
            self.assertNotIn("10%", row["probability"]["scope"])
        for identity in source["existing_entry_ids"]:
            self.assertEqual(self.pages[source["title"]].count('id="' + self.shown[identity] + '"'), 1)

    def test_world_rehoming_moves_records_to_one_readable_anchor_on_their_new_owner(self):
        sources = self.catalog["acquisition"]["sources"]
        inherited = {identity: source["title"] for source in sources for identity in source.get("existing_entry_ids", [])}
        self.assertEqual(len(inherited), 32)
        text = "\n".join(self.pages.values())
        for identity, target in inherited.items():
            self.assertEqual(self.pages[target].count('id="' + self.shown[identity] + '"'), 1)
            self.assertNotIn("entry-" + identity, text)
        rows = {row["id"]: row for source in sources for row in source["rows"]}
        for identity, numerator, denominator in (("boulders-base-maggot", 71, 120),
                                                ("boulders-base-beetle", 71, 120),
                                                ("cracks-cave-creeper", 65, 96),
                                                ("cracks-drake-jasper", 173, 360)):
            self.assertEqual((rows[identity]["probability"]["numerator"], rows[identity]["probability"]["denominator"]),
                             (numerator, denominator))

    def test_invalid_pools_fail_closed(self):
        changes = (
            lambda d: d["pools"][0].update(probability={"numerator": 1, "denominator": 1, "scope": "guessed"}),
            lambda d: d["pools"][0].update(quantity={"min": 1, "max": 1}),
            lambda d: d["pools"][0].update(owner_source="missing"),
            lambda d: d["pools"][0].update(eligible_item_ids=["item-48", "item-48"]),
            lambda d: d["pools"][0].update(eligible_item_ids=["being-31"]),
            lambda d: d["pools"][0].update(item_conditions={"missing": "Not a member"}),
            lambda d: d["pools"].append(copy.deepcopy(d["pools"][0])),
            lambda d: next(s for s in d["sources"] if s["id"] == "random-treasure").update(pool_ids=[]),
            lambda d: next(s for s in d["sources"] if s["id"] == "treasure-chests")["pool_refs"][0].update(pool="missing"),
            lambda d: next(p for p in d["pools"] if p["id"] == "chest-middle")["item_conditions"].update({"item-127": "Conflicting condition"}),
            lambda d: next(p for p in d["pools"] if p["id"] == "chest-common")["item_conditions"].update({"item-127": "Not a member"}),
        )
        for change in changes:
            catalog = copy.deepcopy(self.catalog)
            change(catalog["acquisition"])
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)

    def test_source_titles_cannot_overwrite_aliases(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["pages"][0]["aliases"].append("Starting equipment")
        with self.assertRaises(DataError):
            validate_catalog(catalog, self.data)

    def test_unknown_odds_require_explicit_context_and_never_become_zero(self):
        catalog = copy.deepcopy(self.catalog)
        row = catalog["acquisition"]["sources"][0]["rows"][0]
        row.update(coverage="conditional", probability=None, quantity=None,
                   odds_note="Synthetic budget-dependent outcome; per-container odds are not established.")
        validate_catalog(catalog, self.data)
        text = acquisition_probability(row)
        self.assertIn("Unknown", text)
        self.assertNotIn("0%", text)
        self.assertIn("budget-dependent", text)
        row["probability"] = {"numerator": 1, "denominator": 8, "scope": "one documented selection"}
        self.assertIn("<nowiki>12.5</nowiki>%", acquisition_probability(row))
        row["probability"] = {"numerator": 1, "denominator": 3, "scope": "one documented selection"}
        self.assertIn("<nowiki>1</nowiki>/<nowiki>3</nowiki>", acquisition_probability(row))

    def test_historical_source_mapping_changes_ownership_not_immutable_records(self):
        catalog = copy.deepcopy(self.catalog)
        inherited = {identity for source in catalog["acquisition"]["sources"] for identity in source.get("existing_entry_ids", [])}
        entry = next(row for row in self.data["entries"] if row["kind"] == "loot" and row["id"] not in inherited)
        source = catalog["acquisition"]["sources"][0]
        source["existing_entry_ids"] = [entry["id"]]
        locations = page_locations(self.data, catalog)
        owners = entry_owners(self.data, locations, entry_relations(self.data, catalog), catalog)
        previous = entry_owners(self.data, locations, entry_relations(self.data, catalog),
                                {key: value for key, value in catalog.items() if key != "acquisition"})[entry["id"]]
        self.assertEqual(owners[entry["id"]], source["title"])
        pages = build_pages(ROOT, self.data, catalog, self.details)
        anchor = 'id="' + entry_fragments(self.data["entries"], owners, locations)[entry["id"]] + '"'
        self.assertEqual(pages[source["title"]].count(anchor), 1)
        self.assertNotIn(anchor, pages[previous])
        catalog["acquisition"]["sources"][1]["existing_entry_ids"] = [entry["id"]]
        with self.assertRaises(DataError):
            validate_catalog(catalog, self.data)


if __name__ == "__main__":
    unittest.main()
