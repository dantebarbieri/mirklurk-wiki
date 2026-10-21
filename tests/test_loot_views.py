"""Item acquisition sections: transcluded views must merge into tables with rows, never header-only stubs."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_catalog import entry_owners, entry_relations, page_locations
from wiki_details import load_publication_inputs
from wiki_render import LOOT_HEADERS, LOOT_ITEM_HEADERS, LOOT_QUANTITY_NOTE, build_pages
from test_views import expand_selective_view

TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.S)


def headers(table):
    return re.findall(r'<th scope="col">(.*?)</th>', table)


def data_rows(table):
    rows = [row for row in re.findall(r"<tr>(.*?)</tr>", table, re.S) if "<th" not in row]
    return rows + re.findall(r"\{\{(?:Ware|Recipe) row\n", table)


class LootViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)
        cls.locations = page_locations(cls.data, cls.catalog)
        cls.owners = entry_owners(cls.data, cls.locations, entry_relations(cls.data, cls.catalog), cls.catalog)
        cls.sources = cls.catalog["acquisition"]["sources"]

    def acquisition(self, title):
        """The item's How to acquire section with every selective transclusion evaluated."""
        section = self.pages[title].split("== How to acquire ==\n", 1)[1].split("\n== ", 1)[0]

        def include(match):
            owner, *arguments = match[1].split("|")
            return expand_selective_view(self.pages[owner], dict(argument.split("=", 1) for argument in arguments))

        return re.sub(r"\{\{:([^{}\n]+)\}\}", include, section)

    def expected_rows(self, identity):
        loot = sum(entry["kind"] == "loot" and entry["details"]["outcome"] == identity for entry in self.data["entries"])
        return loot + sum(row["item"] == identity for source in self.sources for row in source["rows"])

    def test_item_pages_merge_loot_and_acquisition_rows_into_one_consistent_table(self):
        items = [row for row in self.data["entities"] if row["category"] == "item"]
        checked = 0
        for item in items:
            title = self.locations[item["id"]]
            with self.subTest(item=title):
                expanded = self.acquisition(title)
                for table in TABLE.findall(expanded):
                    self.assertTrue(data_rows(table), "header-only table: " + "/".join(headers(table)))
                if "=== Loot sources ===" not in expanded:
                    self.assertEqual(self.expected_rows(item["id"]), 0)
                    continue
                checked += 1
                section = expanded.split("=== Loot sources ===\n", 1)[1].split("\n===", 1)[0]
                tables = TABLE.findall(section)
                self.assertEqual(len(tables), 1)
                self.assertEqual(headers(tables[0]), LOOT_ITEM_HEADERS)
                rows = data_rows(tables[0])
                self.assertEqual(len(rows), self.expected_rows(item["id"]))
                for row in rows:
                    self.assertEqual(row.count("<td>"), len(LOOT_ITEM_HEADERS))
                self.assertLessEqual(section.count(LOOT_QUANTITY_NOTE), 1)
                for source in self.sources:
                    if source.get("loot_context"):
                        self.assertLessEqual(section.count(source["loot_context"]), 1)
        self.assertGreaterEqual(checked, 85)

    def test_flint_items_list_every_source_once_with_the_boulder_qualifier(self):
        boulders = next(source["loot_context"] for source in self.sources if source["title"] == "Searching boulders")
        for title, count in (("Dragon Flint", 15), ("Flint", 6), ("Flint (Large)", 5), ("Bat Hide", 4)):
            with self.subTest(item=title):
                section = self.acquisition(title).split("=== Loot sources ===\n", 1)[1].split("\n===", 1)[0]
                self.assertEqual(len(TABLE.findall(section)), 1)
                self.assertEqual(len(data_rows(section)), count)
                self.assertEqual(section.count(boulders), 0 if title == "Bat Hide" else 1)
                self.assertNotIn("{{Item|", section)

    def test_owner_pages_keep_full_rows_and_expose_only_rows_to_readers(self):
        owners = {self.owners[entry["id"]] for entry in self.data["entries"] if entry["kind"] == "loot"}
        owners |= {source["title"] for source in self.sources if source["rows"]}
        for owner in sorted(owners):
            with self.subTest(owner=owner):
                page = self.pages[owner]
                tables = [table for table in TABLE.findall(page) if headers(table)[:1] == ["Source"]]
                self.assertTrue(tables)
                for table in tables:
                    self.assertEqual(headers(table), LOOT_HEADERS)
                    for row in data_rows(table):
                        self.assertEqual(row.count("<td>"), len(LOOT_HEADERS))
                view = expand_selective_view(page, {"view": "loot"})
                self.assertNotIn("<th", view)
                self.assertNotIn(LOOT_QUANTITY_NOTE, view)
                self.assertNotIn("<table", view)
