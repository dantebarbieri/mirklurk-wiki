import copy
import re
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wiki_catalog import validate_catalog
from wiki_data import DataError
from wiki_details import load_publication_inputs
from wiki_display import content_model, dependencies, page_namespace
from wiki_render import (
    RETIRED_PAGES, acquisition_probability, audit_report, base_value_text, build_pages, count_range,
    image_for, known, pixel_image, validate_reader_pages, validate_reader_text,
)


def gameplay_record(record):
    """Fingerprint quantities, conditions' IDs and provenance separately from prose."""
    return {
        key: ({k: v for k, v in value.items() if k != "scope"}
              if key == "probability" and isinstance(value, dict) else value)
        for key, value in record.items() if key not in {"condition", "odds_note", "summary"}
    }


class EditorialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)

    def test_base_values_use_coins_and_state_sub_copper_fractions(self):
        for value, expected in ((Decimal("2.2"), "{{Coins|220}}"), (0, "{{Coins|0}}"),
                                (Decimal("0.005"), "{{Coins|1}} per 2"), (Decimal("0.002"), "{{Coins|1}} per 5"),
                                (Decimal("0.001"), "{{Coins|1}} per 10"), (Decimal("0.125"), "{{Coins|25}} per 2")):
            self.assertEqual(base_value_text(value), expected)
        for value in ("-1", "NaN"):
            with self.subTest(value=value), self.assertRaises(DataError):
                base_value_text(Decimal(value))
        self.assertFalse(any("silver equivalents" in text for text in self.pages.values()))
        self.assertIn("|| {{Coins|100}} ||", self.pages["Silver Coin"])

    def test_construction_action_listing_shows_its_world_sprite(self):
        # Finish Raft is never an {{Item}}, but the Items list still shows its reviewed world sprite.
        raft = image_for("item-171", self.data["illustrations"])
        line = next(line for line in self.pages["Items"].splitlines() if 'id="item-Finish_Raft"' in line)
        self.assertNotIn("{{Item|", line)
        self.assertIn(pixel_image(raft, 32, 32, "Finish Raft", "Finish Raft") + " [[Finish Raft|", line)

    def test_complete_publication_is_reader_facing(self):
        validate_reader_pages(self.pages)
        audit = audit_report(self.data, self.catalog, self.details)
        for source in self.data["sources"]:
            self.assertIn(source["sha256"], audit)
            self.assertFalse(any(source["sha256"] in text for text in self.pages.values()))
        self.assertNotIn("25000", self.pages["World generation"])
        self.assertIn('id="area-seed-ceiling"', self.pages["World generation"])
        for title in ("Main Page", "Items", "Bestiary", "NPCs", "Nature", "Skills",
                      "Crafting", "Weather", "Quests and journal", "World generation"):
            intro = re.split(r"\n(?:== |<div|<span)", self.pages[title], maxsplit=1)[0]
            self.assertLess(len(intro.split()), 180, title)

    def test_audit_and_contributor_credits_never_reach_published_pages(self):
        audit = audit_report(self.data, self.catalog, self.details)
        headings = set(re.findall(r"^==+ *(.+?) *==+$", audit, re.M))
        self.assertIn("Artwork review", headings)
        intro = audit.split("\n", 1)[0]
        self.assertFalse([title for title in self.pages if "audit" in title.lower()])
        game_artists, contributors, notes = set(), set(), set()
        for record in self.data["illustrations"]:
            notes.add(record.get("rights_note", ""))
            for part in record.get("creator", "").split(";"):
                part = part.strip()
                if part.lower().startswith("game artwork by "):
                    game_artists.add(part[16:].strip())
                elif part:
                    contributors.add(part.split(" (")[0].strip())
        contributors -= game_artists
        self.assertIn("DavidLokison", contributors)
        for title, text in self.pages.items():
            page_headings = set(re.findall(r"^==+ *(.+?) *==+$", text, re.M))
            self.assertFalse(headings & page_headings, title)
            self.assertNotIn(intro, text, title)
            for name in contributors:
                self.assertNotIn(name, text, title)
            for note in filter(None, notes):
                self.assertNotIn(note, text, title)

    def test_research_retirement_keeps_managed_safe_redirects(self):
        for title, target in RETIRED_PAGES.items():
            self.assertEqual(self.pages[title], f"#REDIRECT [[{target}]]\n")
            self.assertNotIn(target, RETIRED_PAGES)
            self.assertIn(target, self.pages)
        self.assertEqual(self.pages["Getting started"], "#REDIRECT [[Starting equipment]]\n")
        self.assertEqual(self.pages["World seed logic"], "#REDIRECT [[World generation]]\n")

    def test_uncertainty_is_local_not_a_blanket_source_disclaimer(self):
        marker = self.pages["Template:Unverified"]
        self.assertEqual(page_namespace("Template:Unverified"), 10)
        self.assertEqual(content_model("Template:Unverified"), "wikitext")
        self.assertIn("[unverified]", marker)
        self.assertIn('title="This claim has not been confirmed."', marker)
        marked = {title for title, text in self.pages.items()
                  if "{{Unverified}}" in text and not title.startswith("Template:")}
        self.assertEqual(marked, {"Alchemy workstation"})
        self.assertEqual(self.pages["Alchemy workstation"].count("{{Unverified}}"), 2)
        self.assertIn("Template:Unverified", dependencies(self.pages["Alchemy workstation"]))
        self.assertNotIn("{{Unverified}}", self.pages["Strider"])
        self.assertNotIn("{{Unverified}}", self.pages["Ranger Bhato"])
        self.assertEqual(known(None), "Unknown")
        self.assertEqual(count_range(None), "Unknown")
        self.assertEqual(known(0), "<nowiki>0</nowiki>")
        self.assertEqual(known(False), "No")
        # 0.8.9.9 documented the former Unwanted Guard (now Survivor), so it no longer shows Unknown.
        for title in ("Flax", "Linen", "Firesteel", "Mixed ground debris"):
            self.assertIn("Unknown", self.pages[title])
        variable = next(row for source in self.catalog["acquisition"]["sources"]
                        for row in source["rows"] if row["probability"] is None)
        self.assertIn("Unknown", acquisition_probability(variable))
        self.assertNotIn("0%", acquisition_probability(variable))

    def test_visible_text_tooltips_transcluded_copy_and_retired_links_are_checked(self):
        for bad in (
            "Missing evidence", '<span title="Reviewed initializer">5</span>',
            "<span title='Reviewed initializer'>5</span>",
            '<span title = "Missing evidence">5</span>',
            "<span alt\t=\t'Missing evidence'>5</span>",
            '<span aria-label\n =\n "Missing evidence">5</span>',
            "<span title = provenance>5</span>",
            '<span title="Missing evid&#101;nce">5</span>',
            "<onlyinclude>Source-inspected result</onlyinclude>",
            "[[Source provenance#Profiles|More details]]",
            "#REDIRECT [[Research policy]]",
        ):
            with self.subTest(bad=bad), self.assertRaises(DataError):
                validate_reader_pages({"Example": bad})
        validate_reader_text("Example", '<span id="stats-base"></span>Base weight: Unknown.')
        validate_reader_text("Quest", "Collect evidence for Clay's research.")
        self.assertIn("Research in progress", self.pages["Quests and journal"])
        self.assertIn("Search the target ruins for surviving evidence.", self.pages["Quests and journal"])
        with self.assertRaises(DataError):
            validate_reader_pages({"Source provenance": "The former ledger."})

    def test_fact_editorial_overrides_cannot_change_values_or_scope(self):
        for change in (
            {"fact": "turn-minutes", "value": 0},
            {"fact": "turn-minutes", "confidence": "observed"},
            {"fact": "not-a-fact", "description": "Text."},
            {"fact": "turn-minutes", "description": ""},
        ):
            catalog = copy.deepcopy(self.catalog)
            catalog["fact_display"] = [change]
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)

    def test_retirement_respects_human_edits_and_never_deletes(self):
        from test_sync import FakeWiki, ours
        from sync_wiki import sync
        desired = {title: self.pages[title] for title in RETIRED_PAGES}
        wiki = FakeWiki({
            "Source provenance": ours("Old source ledger"),
            "Research policy": ("Human contribution", "Editor", "Update"),
            "Evidence and spoilers": ours("Old caveats"),
        })
        wiki.username = "WikiAdmin"
        report = sync(wiki, desired, "repo-sync: editorial", apply=True, log=lambda _: None)
        self.assertEqual(wiki.text("Source provenance"), desired["Source provenance"].strip())
        self.assertEqual(wiki.text("Evidence and spoilers"), desired["Evidence and spoilers"].strip())
        self.assertEqual(wiki.text("Research policy"), "Human contribution")
        self.assertEqual([row["title"] for row in report["skipped"]], ["Research policy"])
        self.assertFalse(any(call["action"] in {"delete", "move"} for call in wiki.calls))


if __name__ == "__main__":
    unittest.main()
