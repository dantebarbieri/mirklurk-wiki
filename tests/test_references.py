import copy
import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_catalog import parse_catalog
from wiki_data import DataError, load_data
from wiki_references import ACQUISITION_REFERENCES, CATALOG_REFERENCES, resolve_acquisition_references


SOURCE_ID = re.compile(r"\b(?:being|item|nature|skill(?:-group)?|damage-class)-\d")
# Paths where a record's own subject key or an extracted source entry/row identifier legitimately holds a source ID.
SUBJECT_KEYS = {
    "catalog": {
        ("pages", "*", "entity"), ("classifications", "*", "entity"), ("currency", "coins", "*", "entity"),
        ("damage_sources", "*", "entity"), ("item_effects", "*", "entity"), ("merchant_profiles", "*", "entity"),
        ("stations", "*", "entity"), ("taxonomy", "skill_groups", "*", "entity"),
        ("unit_prices", "prices", "*", "entity"), ("unit_prices", "covered_offers", "*"), ("entry_display", "*", "entry"),
    },
    "acquisition": {("item_notes", "*", "item"), ("pools", "*", "eligible_item_ids", "*"), ("sources", "*", "rows", "*", "id")},
}


def strings(node, path=()):
    """Yield (path, value) for every string in a document, with "*" for list positions."""
    if isinstance(node, dict):
        for key, child in node.items():
            yield from strings(child, path + (key,))
    elif isinstance(node, list):
        for child in node:
            yield from strings(child, path + ("*",))
    elif isinstance(node, str):
        yield path, node


def walk(node, path):
    """Yield every value reached by a reference path ("*" walks list elements)."""
    if not path:
        yield node
    elif path[0] == "*":
        for child in node if isinstance(node, list) else []:
            yield from walk(child, path[1:])
    elif isinstance(node, dict) and path[0] in node:
        yield from walk(node[path[0]], path[1:])


def guide_cells(catalog):
    for guide in catalog["guides"]:
        for table in guide.get("tables", []):
            for row in table["rows"]:
                for cell in row:
                    for ref in cell if isinstance(cell, list) else [cell]:
                        if isinstance(ref, dict) and "entity" in ref:
                            yield guide, ref


class AuthoredReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_data(ROOT / "content/facts/game.json")
        cls.catalog = json.loads((ROOT / "content/facts/catalog.json").read_text(encoding="utf-8"))
        cls.acquisition = json.loads((ROOT / "content/facts/acquisition.json").read_text(encoding="utf-8"))
        cls.titles = {row["title"]: row["entity"] for row in cls.catalog["pages"]}

    def test_authored_references_are_canonical_titles(self):
        values = [value for path in CATALOG_REFERENCES for value in walk(self.catalog, path)]
        values += [ref["entity"] for _, ref in guide_cells(self.catalog)]
        values += [value for path in ACQUISITION_REFERENCES for value in walk(self.acquisition, path)]
        self.assertGreater(len(values), 1000)
        self.assertEqual([value for value in values if value not in self.titles], [])
        self.assertEqual([value for value in values if SOURCE_ID.fullmatch(value)], [])

    def test_source_ids_appear_only_in_subject_keys(self):
        game = json.loads((ROOT / "content/facts/game.json").read_text(encoding="utf-8"))
        self.assertEqual([row["id"] for row in game["entities"] if not SOURCE_ID.match(row["id"])], [])
        for name, document in (("catalog", self.catalog), ("acquisition", self.acquisition)):
            leaks = sorted({(path, value) for path, value in strings(document)
                            if SOURCE_ID.search(value) and path not in SUBJECT_KEYS[name]})
            with self.subTest(document=name):
                self.assertEqual(leaks, [], "name entities by canonical page title (see wiki_references.py)")
        planted = copy.deepcopy(self.catalog)
        planted["guides"][0]["future_field"] = ["being-7"]
        self.assertTrue(any(SOURCE_ID.search(v) and p not in SUBJECT_KEYS["catalog"] for p, v in strings(planted)))

    def test_titles_resolve_to_entities_at_load(self):
        guide, ref = next(guide_cells(self.catalog))
        parsed = parse_catalog(json.dumps(self.catalog).encode(), self.data)
        parsed_guide = next(row for row in parsed["guides"] if row["title"] == guide["title"])
        identities = {r["entity"] for _, r in guide_cells({"guides": [parsed_guide]})}
        self.assertIn(self.titles[ref["entity"]], identities)
        acquisition = resolve_acquisition_references(copy.deepcopy(self.acquisition), self.catalog)
        items = [value for value in walk(acquisition, ("sources", "*", "rows", "*", "item"))]
        self.assertTrue(items)
        self.assertTrue(all(value in self.titles.values() for value in items))

    def test_ids_aliases_and_unknown_titles_are_rejected(self):
        guide = next(row for row in self.catalog["guides"] if row.get("related_entities"))
        cell_guide, _ = next(guide_cells(self.catalog))
        identity = self.titles[guide["related_entities"][0]]
        alias = next((a for row in self.catalog["pages"] for a in row.get("aliases", [])), None)

        def related(catalog, bad):
            next(row for row in catalog["guides"] if row["title"] == guide["title"])["related_entities"][0] = bad

        def cell(catalog, bad):
            next(ref for row, ref in guide_cells(catalog) if row["title"] == cell_guide["title"])["entity"] = bad

        for bad in [identity, "No such page title"] + ([alias] if alias else []):
            for change in (related, cell):
                catalog = copy.deepcopy(self.catalog)
                change(catalog, bad)
                with self.subTest(bad=bad, field=change.__name__), self.assertRaisesRegex(DataError, "canonical page title"):
                    parse_catalog(json.dumps(catalog).encode(), self.data)
            acquisition = copy.deepcopy(self.acquisition)
            next(walk(acquisition, ("sources", "*", "rows", "*")))["item"] = bad
            with self.subTest(bad=bad, field="acquisition"), self.assertRaisesRegex(DataError, "canonical page title"):
                resolve_acquisition_references(acquisition, self.catalog)


if __name__ == "__main__":
    unittest.main()
