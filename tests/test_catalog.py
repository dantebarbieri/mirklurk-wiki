import copy
import hashlib
import html
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_wiki import build_pages, build_xml, literal, profile_value
from wiki_catalog import (
    default_catalog, entry_owners, entry_relations, fact_owners, page_locations,
    parse_catalog, validate_catalog,
)
from wiki_data import DataError, load_data
from wiki_details import (
    MAX_DETAILS_BYTES, empty_details, load_publication_inputs, parse_details,
    parse_illustrations, validate_details,
)
from wiki_render import PAIRED_PROPERTIES, display_entry, known, price_text, recipe_groups
from test_wiki import illustration_data, research_data, synthetic_data


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
        self.assertEqual(len(self.catalog["pages"]), 324)
        self.assertEqual(len(self.pages), 348)
        self.assertTrue(all(row["title"] in self.pages for row in self.catalog["pages"]))
        self.assertEqual(len({row["entity"] for row in self.catalog["pages"]}), 324)

    def test_all_primary_records_and_typed_relationships_are_retained(self):
        locations = page_locations(self.data, self.catalog)
        facts = fact_owners(self.data, locations)
        relations = entry_relations(self.data, self.catalog)
        entries = entry_owners(self.data, locations, relations, self.catalog)
        for fact in self.data["facts"]:
            with self.subTest(fact=fact["id"]):
                page = self.pages[facts[fact["id"]]]
                self.assertIn(f'id="fact-{fact["id"]}"', page)
                self.assertIn(known(fact["value"]), page)
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
                        self.assertIn(f'[[{entries[entry["id"]]}#entry-{entry["id"]}|', self.pages[locations[identity]])
        for entity in self.data["entities"]:
            target = locations[entity["id"]].split("#", 1)[0]
            self.assertIn(f'id="entity-{entity["id"]}"', self.pages[target])
        self.assertEqual(set(facts), {fact["id"] for fact in self.data["facts"]})
        self.assertEqual(set(entries), {entry["id"] for entry in self.data["entries"]})

    def test_complete_reviewed_profiles_keep_every_value_and_its_scope(self):
        self.assertEqual(
            hashlib.sha256((ROOT / "content" / "facts" / "entity_details.json").read_bytes()).hexdigest(),
            "1afe8a32c2e129d483555878c938a2fbb08aa2bc6565433ecbaa9d5366568001",
        )
        self.assertEqual(len(self.details["properties"]), 48)
        self.assertEqual(len(self.details["profiles"]), 372)
        self.assertEqual(len({row["entity"] for row in self.details["profiles"]}), 297)
        self.assertEqual(sum(len(row["values"]) for row in self.details["profiles"]), 2456)
        locations = page_locations(self.data, self.catalog)
        entities = {row["id"]: row for row in self.data["entities"]}
        prices = {row["entity"]: row for row in self.catalog["unit_prices"]["prices"]}
        coins = {row["entity"]: row for row in self.catalog["currency"]["coins"]}
        for profile in self.details["profiles"]:
            with self.subTest(profile=profile["id"]):
                page = self.pages[locations[profile["entity"]]]
                self.assertEqual(page.count(f'id="profile-{profile["id"]}"'), 1)
                self.assertIn(literal(profile["context"]), self.pages["Source provenance"])
                self.assertNotIn(literal(profile["context"]), page)
                for key, value in profile["values"].items():
                    if profile["entity"] in coins and key in {"initial-price", "initial-weight", "stack-limit"}:
                        field = {"initial-price": "value_in_silver", "initial-weight": "weight_grams", "stack-limit": "stack_limit"}[key]
                        self.assertIn(known(coins[profile["entity"]][field]), page)
                    elif key == "initial-price" and profile["entity"] in prices:
                        self.assertIn("<onlyinclude>" + price_text(prices[profile["entity"]]) + "</onlyinclude>", page)
                    else:
                        self.assertIn(profile_value(key, value, entities, locations), page)
        for name in ("Flax", "Linen"):
            self.assertIn("Numerical stats are not established", self.pages[name])
            self.assertNotIn("== Stats ==", self.pages[name])

    def test_final_image_metadata_has_exact_coverage_without_guessed_frames(self):
        self.assertEqual(
            hashlib.sha256((ROOT / "content" / "facts" / "illustrations.json").read_bytes()).hexdigest(),
            "c39da5b3edcc0a8ca077b7265fdf7ebc92b44613c23c79f01bbc1d2de51f6459",
        )
        images = self.data["illustrations"]
        self.assertEqual(len(images), 323)
        original = {"schema_version": 1, "illustrations": [row for row in images if "entity" in row]}
        self.assertEqual(hashlib.sha256((json.dumps(original, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(),
                         "d2127f41f5f41dcbe3fb7f04354b97289708c25c60a411487a3ae53cc886399e")
        missing = {row["entity"] for row in self.catalog["pages"]} - {row["entity"] for row in images if "entity" in row}
        self.assertEqual(missing, {"item-31", "item-48", "item-49", "item-171"})
        locations = page_locations(self.data, self.catalog)
        stations = {row["id"]: row for row in self.catalog["stations"]}
        for image in images:
            title = locations[image["entity"]] if "entity" in image else stations[image["station"]]["title"]
            page = self.pages[title]
            self.assertEqual(page.count(f'[[{image["file_title"]}|thumb|'), 1)
            self.assertIn(literal(image["sha256"]), self.pages["Source provenance"])
            self.assertNotIn(image["sha256"], page)
            self.assertIn(literal(image["caption"]), page)
        for identity in ("nature-4", "nature-6", "nature-7", "nature-17", "nature-20"):
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
                if target.startswith("File:"):
                    continue
                page, _, anchor = target.partition("#")
                page = page or title
                with self.subTest(source=title, target=target):
                    self.assertIn(page, self.pages)
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
        self.assertIn("deceased character record", self.pages["Dead Unwanted"])
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
        for key in ("pages", "classifications", "entry_links"):
            catalog[key].reverse()
        for key in ("profiles", "properties"):
            details[key].reverse()
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
        self.assertEqual(bhato.count('{| class="wikitable"'), 2)
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
        self.assertEqual(self.pages["Alchemy workstation"].count('{| class="wikitable"'), 1)
        self.assertEqual(self.pages["Alchemy workstation"].count("|-\n"), 15)
        self.assertNotIn("Ingredients", self.pages["Alchemy workstation"])
        self.assertNotIn("Base cost", self.pages["Alchemy workstation"])
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

    def test_global_prices_are_item_owned_selective_transclusions(self):
        prices = self.catalog["unit_prices"]
        self.assertEqual(hashlib.sha256((json.dumps(prices, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(),
                         "cc87a1884a50596233aad3708fd145d636bbe88e8c8bea9fa1867aaff4e198ea")
        self.assertEqual(len(prices["prices"]), 36)
        self.assertEqual(len(prices["covered_offers"]), 52)
        self.assertEqual(len(prices["unresolved_offers"]), 11)
        locations = page_locations(self.data, self.catalog)
        known_prices = {row["entity"]: row for row in prices["prices"]}
        items = {row["details"]["item"] for row in self.data["entries"] if row["kind"] == "merchant"}
        self.assertEqual(len(items), 42)
        self.assertEqual(sum(page.count("<onlyinclude>") for page in self.pages.values()), 45)
        for identity in items:
            page = self.pages[locations[identity]]
            self.assertEqual(page.count("<onlyinclude>"), 1)
            self.assertIn("<onlyinclude>" + price_text(known_prices.get(identity)) + "</onlyinclude>", page)
            if identity in known_prices:
                self.assertNotIn("Base value (not a shop price)", page)
        for entry in self.data["entries"]:
            if entry["kind"] != "merchant":
                continue
            page = self.pages[locations[entry["details"]["merchant"]]]
            self.assertIn("{{:" + locations[entry["details"]["item"]] + "}}", page)
            self.assertNotIn("<onlyinclude>", page)

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
        self.assertEqual(len(stations), 7)
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
        self.assertIn("replaces the durability factor", guide)
        self.assertIn("does not multiply the durability and fuel reductions together", guide)
        self.assertIn("25 percent", guide)
        self.assertIn("10 percent", guide)
        self.assertIn("not an absolute guarantee", guide)
        self.assertIn("Currency and trading", self.pages["Merchants"])
        self.assertEqual(self.data["game"]["build"], "0.8.1.5")
        self.assertIn("user report", self.pages["Source provenance"])

    def test_coin_profile_and_unit_mismatch_are_rejected(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["currency"]["coins"][0]["weight_grams"] = 26
        with self.assertRaises(DataError):
            build_pages(ROOT, self.data, catalog, self.details)
        catalog = copy.deepcopy(self.catalog)
        catalog["currency"]["coins"][0]["value_in_silver"] = 0.02
        with self.assertRaises(DataError):
            build_pages(ROOT, self.data, catalog, self.details)


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
    def test_damage_class_ids_link_to_the_single_damage_index(self):
        data = synthetic_data()
        entity = copy.deepcopy(data["entities"][0])
        entity.update(id="damage-class-14", name="Synthetic damage class", category="damage_class")
        data["entities"].append(entity)
        details = synthetic_details()
        details["properties"][0]["id"] = "damage-class-id"
        details["profiles"][0]["values"] = {"damage-class-id": 14}
        page = build_pages(ROOT, data, details=details)["Entity synthetic-item"]
        self.assertIn("[[Damage types#entity-damage-class-14|", page)

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
