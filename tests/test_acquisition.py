import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_catalog import entry_owners, entry_relations, page_locations, validate_catalog
from wiki_data import DataError
from wiki_details import load_publication_inputs
from wiki_render import acquisition_probability, build_pages
from wiki_views import available_views, transclusions


class AcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)

    def test_fixed_sources_are_conditional_and_have_single_editable_rows(self):
        sources = {row["id"]: row for row in self.catalog["acquisition"]["sources"]}
        self.assertEqual(len(sources["starting-equipment"]["rows"]), 12)
        self.assertEqual(len(sources["dead-camp"]["rows"]), 5)
        locations = page_locations(self.data, self.catalog)
        for source in sources.values():
            self.assertEqual(available_views(self.pages[source["title"]]), {"loot"})
            for row in source["rows"]:
                owner = self.pages[source["title"]]
                self.assertEqual(owner.count('id="acquisition-' + row["id"] + '"'), 1)
                self.assertEqual(row["probability"]["numerator"], row["probability"]["denominator"])
                self.assertIn((source["title"], (("item", row["item"]), ("view", "loot"))),
                              transclusions(self.pages[locations[row["item"]]]))
                self.assertNotIn('id="acquisition-' + row["id"] + '"', self.pages[locations[row["item"]]])
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
        self.assertIn("do not promise replenishment", self.pages["Dead camp"])

    def test_invalid_acquisition_data_fails_closed(self):
        changes = (
            lambda d: d.update(raw_dump="forbidden field"),
            lambda d: d.update(build="unreviewed"),
            lambda d: d["sources"].append(copy.deepcopy(d["sources"][0])),
            lambda d: d["sources"][0].update(title="Items"),
            lambda d: d["sources"][0].update(title="Template:Acquisition"),
            lambda d: d["sources"][0].update(related_pages=["Missing"]),
            lambda d: d["sources"][0].update(image_entity="being-6"),
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
        self.assertIn("Not established", text)
        self.assertNotIn("0%", text)
        self.assertIn("budget-dependent", text)
        row["probability"] = {"numerator": 1, "denominator": 8, "scope": "one documented selection"}
        self.assertIn("<nowiki>12.5</nowiki>%", acquisition_probability(row))
        row["probability"] = {"numerator": 1, "denominator": 3, "scope": "one documented selection"}
        self.assertIn("<nowiki>1</nowiki>/<nowiki>3</nowiki>", acquisition_probability(row))

    def test_historical_source_mapping_changes_ownership_not_immutable_records(self):
        catalog = copy.deepcopy(self.catalog)
        entry = next(row for row in self.data["entries"] if row["kind"] == "loot")
        source = catalog["acquisition"]["sources"][0]
        source["existing_entry_ids"] = [entry["id"]]
        locations = page_locations(self.data, catalog)
        owners = entry_owners(self.data, locations, entry_relations(self.data, catalog), catalog)
        previous = entry_owners(self.data, locations, entry_relations(self.data, catalog),
                                {key: value for key, value in catalog.items() if key != "acquisition"})[entry["id"]]
        self.assertEqual(owners[entry["id"]], source["title"])
        pages = build_pages(ROOT, self.data, catalog, self.details)
        self.assertEqual(pages[source["title"]].count('id="entry-' + entry["id"] + '"'), 1)
        self.assertIn('id="entry-' + entry["id"] + '"', pages[previous])
        self.assertIn("[[" + source["title"] + "#entry-" + entry["id"] + "|", pages[previous])
        catalog["acquisition"]["sources"][1]["existing_entry_ids"] = [entry["id"]]
        with self.assertRaises(DataError):
            validate_catalog(catalog, self.data)


if __name__ == "__main__":
    unittest.main()
