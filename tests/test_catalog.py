import copy
import hashlib
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
        self.assertEqual(len(self.pages), 343)
        self.assertTrue(all(row["title"] in self.pages for row in self.catalog["pages"]))
        self.assertEqual(len({row["entity"] for row in self.catalog["pages"]}), 324)

    def test_all_primary_records_and_typed_relationships_are_retained(self):
        locations = page_locations(self.data, self.catalog)
        facts = fact_owners(self.data, locations)
        relations = entry_relations(self.data, self.catalog)
        entries = entry_owners(self.data, locations, relations)
        for fact in self.data["facts"]:
            with self.subTest(fact=fact["id"]):
                page = self.pages[facts[fact["id"]]]
                self.assertIn(f'id="fact-{fact["id"]}"', page)
                self.assertIn(literal(fact["description"]), page)
                if fact["page"] != facts[fact["id"]]:
                    self.assertNotIn(literal(fact["description"]), self.pages[fact["page"]])
        for entry in self.data["entries"]:
            with self.subTest(entry=entry["id"]):
                page = self.pages[entries[entry["id"]]]
                self.assertIn(f'id="entry-{entry["id"]}"', page)
                self.assertIn(literal(entry["summary"]), page)
                for identity in relations[entry["id"]]:
                    self.assertIn(f'[[{locations[identity]}', page)
                    if locations[identity] != entries[entry["id"]] and "#" not in locations[identity]:
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
        properties = {row["id"]: row for row in self.details["properties"]}
        for profile in self.details["profiles"]:
            with self.subTest(profile=profile["id"]):
                page = self.pages[locations[profile["entity"]]]
                self.assertEqual(page.count(f'id="profile-{profile["id"]}"'), 1)
                self.assertIn(literal(profile["context"]), page)
                for key, value in profile["values"].items():
                    self.assertIn(literal(properties[key]["label"]), page)
                    self.assertIn(profile_value(key, value, entities, locations), page)
        for name in ("Flax", "Linen"):
            self.assertIn("No numerical mechanics", self.pages[name])
            self.assertNotIn("Documented profile", self.pages[name])

    def test_final_image_metadata_has_exact_coverage_without_guessed_frames(self):
        self.assertEqual(
            hashlib.sha256((ROOT / "content" / "facts" / "illustrations.json").read_bytes()).hexdigest(),
            "d2127f41f5f41dcbe3fb7f04354b97289708c25c60a411487a3ae53cc886399e",
        )
        images = self.data["illustrations"]
        self.assertEqual(len(images), 320)
        missing = {row["entity"] for row in self.catalog["pages"]} - {row["entity"] for row in images}
        self.assertEqual(missing, {"item-31", "item-48", "item-49", "item-171"})
        locations = page_locations(self.data, self.catalog)
        for image in images:
            page = self.pages[locations[image["entity"]]]
            self.assertEqual(page.count(f'[[{image["file_title"]}|'), 1)
            self.assertIn(literal(image["sha256"]), page)
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
        self.assertIn("[[Focused Mind|", self.pages["Skills"])
        self.assertIn("[[Brewer|", self.pages["Crafting"])
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
                with self.subTest(source=title, target=target):
                    self.assertIn(page, self.pages)
                    if anchor:
                        self.assertIn(f'id="{anchor}"', self.pages[page])

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
        self.assertIn("Synthetic classification only.", pages["Synthetic merchant"])
        self.assertIn("Characters moved to [[NPCs]]", pages["Bestiary"])
        self.assertNotIn("Synthetic merchant", pages["Bestiary"].split("Characters moved")[0])

    def test_reviewed_npc_mapping_separates_characters_from_creatures(self):
        npcs = {row["entity"] for row in self.catalog["classifications"] if row["kind"] == "npc"}
        self.assertEqual(npcs, {f"being-{number}" for number in (5, 6, 8, 9, 12, 19, 20, 26, 33, 34, 35)})
        self.assertEqual(len(self.catalog["classifications"]), 36)
        self.assertIn("deceased character record", self.pages["Dead Unwanted"])
        for name in ("Ranger Bhato", "Magus Clay", "Captain Eir", "Wilda"):
            self.assertIn(f"[[{name}|", self.pages["NPCs"])
            self.assertNotIn(name, self.pages["Bestiary"].split("Characters moved")[0])

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
            self.assertIn("Documented profile", pages["Entity synthetic-item"])
            self.assertIn(literal(value) if value is not None else "Not established", pages["Entity synthetic-item"])
            self.assertNotIn("No numerical mechanics", pages["Entity synthetic-item"])

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
        self.assertIn("&lt;/nowiki&gt;", pages["Entity synthetic-item"])
        self.assertNotIn("<script>", pages["Entity synthetic-item"])

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
            self.assertIn("Synthetic test creator", page)
        self.assertEqual(
            hashlib.sha256((ROOT / "content" / "facts" / "game.json").read_bytes()).hexdigest(),
            "0ab88dfd0d509370d93f87b79390f550358230c784e735d147f66c58bb70c0d8",
        )


if __name__ == "__main__":
    unittest.main()
