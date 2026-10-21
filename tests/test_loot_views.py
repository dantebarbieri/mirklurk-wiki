"""Item tables: transcluded views merge into tables with rows, never header-only stubs, and values show once."""

import re
import sys
import unittest
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_catalog import entry_owners, entry_relations, page_locations
from wiki_details import load_publication_inputs
from wiki_render import LOOT_HEADERS, LOOT_ITEM_HEADERS, LOOT_QUANTITY_NOTE, build_pages, price_text
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

    def test_buying_lists_every_seller_as_one_row_of_one_table(self):
        sellers = defaultdict(set)
        for entry in self.data["entries"]:
            if entry["kind"] == "merchant":
                sellers[entry["details"]["item"]].add(self.locations[entry["details"]["merchant"]])
        self.assertEqual(len(sellers), 58)
        for identity, merchants in sellers.items():
            title = self.locations[identity]
            with self.subTest(item=title):
                section = self.acquisition(title).split("=== Buying ===\n", 1)[1].split("\n===", 1)[0]
                tables = TABLE.findall(section)
                self.assertEqual(len(tables), 1)
                columns = headers(tables[0])
                self.assertEqual([columns[0], *columns[-2:]], ["Seller", "Location", "Availability"])
                rows = data_rows(tables[0])
                self.assertEqual(sorted(re.match(r"<td><a [^>]*>([^<]+)</a></td>", row)[1] for row in rows), sorted(merchants))
                self.assertTrue(all(row.count("<td>") == len(columns) for row in rows))
                outside = TABLE.sub("", section)
                for text in ("Location:", "Story availability", "Value]]: ", "{{Coins"):
                    self.assertNotIn(text, outside)

    def test_every_item_summary_shows_one_value_matching_its_merchant_price(self):
        prices = {row["entity"]: row for row in self.catalog["unit_prices"]["prices"]}
        profiles = defaultdict(set)
        for profile in self.details["profiles"]:
            for key in ("initial-price", "value"):
                if key in profile["values"]:
                    profiles[profile["entity"]].add(Decimal(str(profile["values"][key])))
        summaries = 0
        for item in (row for row in self.data["entities"] if row["category"] == "item"):
            title = self.locations[item["id"]]
            page = self.pages[title]
            with self.subTest(item=title):
                if 'class="mirklurk-summary"' not in page:
                    self.assertIn(title, {"Copper Coin", "Silver Coin", "Gold Coin", "Flax", "Linen"})
                    continue
                summaries += 1
                summary = page.split('class="mirklurk-summary"', 1)[1].split("\n|}", 1)[0]
                values = re.findall(r"\|Value\]\]\n\| (.*)", summary)
                self.assertEqual(len(values), 1 if profiles[item["id"]] or item["id"] in prices else 0)
                self.assertNotIn(" per ", "".join(values))
                if item["id"] in prices:
                    self.assertEqual(profiles[item["id"]], {Decimal(str(prices[item["id"]]["value"]))})
                    self.assertEqual(values[0], '<span id="price"></span><onlyinclude>{{#switch:{{{view|<noinclude>page'
                                     "</noinclude>}}}|page|price|=" + price_text(prices[item["id"]]) + "|#default=}}</onlyinclude>")
                    self.assertEqual(page.count('<span id="price">'), 1)
        self.assertEqual(summaries, 261)

    def test_currency_denominations_are_one_table_of_coin_rows(self):
        section = self.pages["Currency and trading"].split("== Denominations ==\n", 1)[1].split("\n==", 1)[0]
        expanded = re.sub(r"\{\{:([^{}|\n]+)\}\}", lambda match: "".join(re.findall(r"<onlyinclude>(.*?)</onlyinclude>", self.pages[match[1]], re.S)),
                          section)
        tables = TABLE.findall(expanded)
        self.assertEqual(len(tables), 1)
        self.assertEqual(headers(tables[0]), ["Coin", "Value", "Weight", "Maximum stack"])
        self.assertEqual([re.search(r"\[\[([^|\]]+)", row)[1] for row in data_rows(tables[0])],
                         ["Copper Coin", "Silver Coin", "Gold Coin"])
