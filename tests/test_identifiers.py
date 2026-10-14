"""Reader- and editor-visible names use canonical titles, never opaque source IDs."""

import copy
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from plan_file_moves import plan
from wiki_anchors import validate_readable_identifiers
from wiki_catalog import page_locations
from wiki_data import SOURCE_ID, DataError, validate_data
from wiki_details import load_publication_inputs

# File:<page title> <role>[ (<qualifier>[, <qualifier>])].png
CONVENTION = re.compile(r"File:(?P<page>.+?) (?:icon|portrait|sprite|exterior|ability|mechanics|tile|area|shield)"
                        r"(?: \((?P<qualifier>[^()]+)\))?\.png")


class IdentifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.locations = page_locations(cls.data, cls.catalog)

    def titles(self, row):
        return [row["file_title"]] + ([row["cropped_from"]["file_title"]] if "cropped_from" in row else [])

    def test_file_titles_follow_the_page_title_and_role_convention(self):
        for row in self.data["illustrations"]:
            for title in self.titles(row):
                with self.subTest(title=title):
                    match = CONVENTION.fullmatch(title)
                    self.assertIsNotNone(match)
                    self.assertIsNone(SOURCE_ID.search(title))
                    if "entity" in row and "station" not in row:
                        self.assertEqual(match["page"], self.locations[row["entity"]])
            if "cropped_from" in row:
                # A crop names its preserved original plus the "cropped" qualifier.
                source = re.sub(r"(?: \(cropped\)|, cropped\))\.png$", lambda m: ")" * m[0].startswith(",") + ".png",
                                row["file_title"])
                self.assertEqual(source, row["cropped_from"]["file_title"])
            else:
                self.assertNotIn("cropped", row["file_title"])

    def test_validator_rejects_source_id_file_titles_in_any_case(self):
        base = copy.deepcopy(self.data)
        index = next(i for i, row in enumerate(base["illustrations"]) if "cropped_from" in row)
        for field in ("file_title", "source"):
            for title in ("File:Being-8 sprite.png", "File:ITEM-27 icon.png", "File:Skill-group-1 icon.png",
                          "File:Damage-class-0 icon.png", "File:Nature-4 tile.png", "File:Skill-0-2.png"):
                data = copy.deepcopy(base)
                row = data["illustrations"][index]
                (row if field == "file_title" else row["cropped_from"])["file_title"] = title
                with self.subTest(field=field, title=title), self.assertRaisesRegex(DataError, "source ID"):
                    validate_data(data, stations={row["id"]: row for row in self.catalog["stations"]})

    def test_generated_pages_reject_source_id_anchors_views_and_files(self):
        good = {"Iron Hand Axe": '<span id="item-Iron_Hand_Axe"></span>\n== Uses ==\n'
                                 "{{:Items|view=price|item=Iron Hand Axe}}\n[[File:Iron Hand Axe icon.png|64px]]\n",
                "Module:Data": "-- being-7 is a Lua key, not a reader-visible name\n"}
        validate_readable_identifiers(good)
        for text in ('<span id="creature-being-7"></span>', '<div id="item-27-price"></div>',
                     "== Being-7 ==", "{{:Items|view=price|item=item-27}}", "{{:Bestiary| item = being-7 }}",
                     "[[File:Being-8-overworld.png|64px]]", "[[:File:item-27.png]]", "[[File:Area-Nature-3 area.png]]"):
            with self.subTest(text=text), self.assertRaisesRegex(DataError, "source ID"):
                validate_readable_identifiers({"Page": text})
        with self.assertRaisesRegex(DataError, "source ID"):
            validate_readable_identifiers({"Module:Data": "[[File:Item-27.png]]"})
        validate_readable_identifiers({"Page": "<nowiki>[[File:Being-8.png]]</nowiki> {{Item|Bark (Cypress)}}"})


def document(*rows):
    return {"schema_version": 1, "illustrations": [dict(row) for row in rows]}


class MovePlanTests(unittest.TestCase):
    OLD = document({"id": "a", "file_title": "File:Item-1.png", "sha256": "1"},
                   {"id": "b", "file_title": "File:Item-2-cropped.png", "sha256": "2",
                    "cropped_from": {"file_title": "File:Item-2.png", "sha256": "3"}},
                   {"id": "c", "file_title": "File:Kept icon.png", "sha256": "4"})

    def renamed(self, a="File:Axe icon.png", b="File:Bow icon (cropped).png", source="File:Bow icon.png"):
        new = copy.deepcopy(self.OLD)
        new["illustrations"][0]["file_title"] = a
        new["illustrations"][1]["file_title"] = b
        new["illustrations"][1]["cropped_from"]["file_title"] = source
        return new

    def test_plans_every_retitled_file_and_crop_source_by_record_id(self):
        self.assertEqual(plan(self.OLD, self.renamed()), [
            ("File:Item-1.png", "File:Axe icon.png"),
            ("File:Item-2-cropped.png", "File:Bow icon (cropped).png"),
            ("File:Item-2.png", "File:Bow icon.png"),
        ])
        self.assertEqual(plan(self.OLD, copy.deepcopy(self.OLD)), [])

    def test_rejects_other_edits_collisions_duplicates_and_source_ids(self):
        changed = self.renamed()
        changed["illustrations"][0]["sha256"] = "changed"
        cases = [(changed, "only File titles"),
                 (self.renamed(a="File:Kept icon.png"), "unique"),
                 (self.renamed(a="File:Item-2.png", source="File:Bow icon.png"), "reuses an old one"),
                 (self.renamed(a="File:Item-9 icon.png"), "source ID")]
        for new, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(DataError, message):
                plan(self.OLD, new)

    def test_planner_has_no_network_code(self):
        source = (ROOT / "tools" / "plan_file_moves.py").read_text(encoding="utf-8")
        for forbidden in ("urllib", "http", "requests", "sync_wiki", "Api("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
