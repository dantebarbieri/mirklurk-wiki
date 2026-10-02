"""NPC-owned conversation summaries, curfew facts and safe publication."""

import copy
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from test_views import expand_selective_view
from wiki_catalog import page_locations, validate_catalog
from wiki_data import DataError
from wiki_details import load_publication_inputs
from wiki_render import audit_report, build_pages, literal, validate_reader_pages


class DialogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)
        cls.locations = page_locations(cls.data, cls.catalog)
        cls.topics = {
            cls.locations[row["entity"]]: row["dialogue"]
            for row in cls.catalog["classifications"] if "dialogue" in row
        }

    def topic(self, owner, identity):
        return next(topic for topic in self.topics[owner] if topic["id"] == identity)

    def rendered_topic(self, owner, identity):
        return self.pages[owner].split(f'<span id="dialogue-{identity}"></span>', 1)[1].split(
            '<span id="dialogue-', 1
        )[0].split("== Stats ==", 1)[0]

    def test_covers_available_conversations_without_inventing_missing_dialogue(self):
        self.assertEqual(set(self.topics), {
            "Soldier", "Captain Eir", "Magus Clay", "Ranger Bhato",
            "Viend", "Commander Tain", "Gurb-Gurb", "Ihar",
        })
        self.assertEqual(sum(map(len, self.topics.values())), 20)
        for title in self.topics:
            self.assertEqual(self.pages[title].count("== Dialogue and guidance =="), 1)
        for title in ("Wilda", "Unwanted Guard", "Dead Unwanted"):
            self.assertNotIn("== Dialogue and guidance ==", self.pages[title])
        self.assertIn("not a separate Information or Advice option", self.pages["Commander Tain"])
        self.assertEqual(self.topic("Gurb-Gurb", "field-kit-tip")["title"], "Field-kit tip during Trade")
        for title in ("Viend", "Ihar"):
            topic = self.topic(title, "information")
            self.assertEqual(topic["title"], "Information")
            self.assertEqual(topic["confidence"], "localization-described")
            self.assertTrue(any("104/105" in ref["key"] for ref in topic["evidence"]))

    def test_curfew_hours_trigger_geometry_and_retaliation_are_explicit(self):
        topic = self.topic("Captain Eir", "fort-curfew")
        prose = " ".join(topic["paragraphs"])
        for phrase in (
            "escort-out scene, not a night-only attack",
            "after a turn advances the clock",
            "21:00 through 05:00 inclusive",
            "At exactly 05:00 it still applies",
            "after 05:00 and before 21:00 it does not",
            "fixed hours", "10-tile radius", "not its entire world-map zone",
            "throughout that interior", "outdoor escort also advances another turn",
            "does not require a nearby Soldier or Eir",
            "skipped while a screen transition is already running",
            "retaliation rules are separate",
        ):
            self.assertIn(phrase, prose)
        self.assertEqual(topic["confidence"], "observed")
        self.assertFalse(topic["spoiler"])
        self.assertTrue(any("hour>=21||hour<=5" in ref["key"] for ref in topic["evidence"]))
        self.assertTrue(any(ref["section"] == "gml_Object_obj_screenfader_Step_0" for ref in topic["evidence"]))
        source = next(row for row in self.data["sources"] if row["id"] == "game-data")
        self.assertEqual(source["sha256"], "163d02abb9e514b603736633121bb3e6240e88dc81fb66a83b6f43f3d7660205")

    def test_permissions_distinguish_sample_handover_from_viend_and_midnight(self):
        topic = self.topic("Captain Eir", "curfew-permissions")
        prose = " ".join(topic["paragraphs"])
        for phrase in (
            "deliver the three rift samples to Clay",
            "outdoor perimeter restriction still applies",
            "Continue his conversation",
            "bring Viend back and speak with Eir",
            "invitation to meet Commander Tain",
            "Wooden Recorder or reaching the next midnight does not lift it",
        ):
            self.assertIn(phrase, prose)
        self.assertTrue(topic["spoiler"])
        self.assertTrue(any("main<15/area30/main<6" in ref["key"] for ref in topic["evidence"]))
        self.assertEqual({link["target"] for link in topic["links"]}, {
            "Quests and journal#entry-journal-5",
            "Quests and journal#entry-journal-13",
            "Quests and journal#entry-journal-15",
        })
        advice = " ".join(self.topic("Captain Eir", "advice")["paragraphs"])
        self.assertIn("goes straight to her survival tips", advice)
        quest = " ".join(self.topic("Captain Eir", "quest-guidance")["paragraphs"])
        self.assertIn("Returning immediately at midnight can still trigger the curfew", quest)

    def test_every_topic_has_one_owner_with_working_links_and_private_evidence(self):
        audit = audit_report(self.data, self.catalog, self.details)
        self.assertIn("== NPC dialogue evidence ==", audit)
        for owner, topics in self.topics.items():
            for topic in topics:
                with self.subTest(owner=owner, topic=topic["id"]):
                    self.assertEqual(self.pages[owner].count(f'id="dialogue-{topic["id"]}"'), 1)
                    self.assertIn(f"[[{owner}#dialogue-{topic['id']}|", audit)
                    for ref in topic["evidence"]:
                        self.assertIn(ref["section"], audit)
                        if ref["source"] == "game-data":
                            self.assertNotIn(ref["section"], self.pages[owner])
                    for link in topic["links"]:
                        target, separator, fragment = link["target"].partition("#")
                        self.assertIn(target, self.pages)
                        if separator:
                            self.assertIn(f'id="{fragment}"', self.pages[target])
                        self.assertIn(f'[[{link["target"]}|{literal(link["label"])}]]', self.pages[owner])
        validate_reader_pages(self.pages)

    def test_story_topics_are_collapsed_and_normal_topics_are_not(self):
        for owner, topics in self.topics.items():
            for topic in topics:
                rendered = self.rendered_topic(owner, topic["id"])
                if topic["spoiler"]:
                    self.assertIn('<div class="mw-collapsible mw-collapsed">\nStory spoilers', rendered)
                    self.assertIn('<div class="mw-collapsible-content">', rendered)
                    self.assertIn("</div></div>", rendered)
                else:
                    self.assertNotIn("mw-collapsible-content", rendered)

    def test_guidance_stays_out_of_filtered_merchant_offers(self):
        count = 0
        for entry in self.data["entries"]:
            if entry["kind"] != "merchant":
                continue
            owner = self.locations[entry["details"]["merchant"]]
            if owner not in self.topics:
                continue
            count += 1
            selected = expand_selective_view(self.pages[owner], {
                "view": "offers", "item": entry["details"]["item"],
            })
            self.assertNotIn("Dialogue and guidance", selected)
            self.assertNotIn('id="dialogue-', selected)
            self.assertNotIn("Healing-popup.png", selected)
            self.assertNotIn("Viend automatically heals", selected)
            for topic in self.topics[owner]:
                for paragraph in topic["paragraphs"]:
                    self.assertNotIn(paragraph, selected)
        self.assertEqual(count, 63)

    def test_curfew_crosslinks_preserve_single_detailed_owner(self):
        for owner in ("Soldier", "Magus Clay", "NPCs"):
            self.assertIn("[[Captain Eir#dialogue-fort-curfew|", self.pages[owner])
            self.assertNotIn("21:00 through 05:00", self.pages[owner])
        for owner in ("Magus Clay", "Viend"):
            self.assertIn("[[Captain Eir#dialogue-curfew-permissions|", self.pages[owner])
        for target in ("Tree and shrub harvesting", "Mixed ground debris", "Campfire", "Temperature"):
            self.assertIn(f"[[{target}|", self.pages["Captain Eir"])
        for target in ("Searching boulders", "Health and armor", "Damage types"):
            self.assertIn(f"[[{target}|", self.pages["Magus Clay"])
        for target in ("Level progression", "Resting", "Poison", "Minor Antidote", "Armor workstation"):
            self.assertIn(f"[[{target}|", self.pages["Ranger Bhato"])

    def test_dialogue_only_changes_expected_pages_and_preserves_existing_sections(self):
        baseline_catalog = copy.deepcopy(self.catalog)
        for row in baseline_catalog["classifications"]:
            row.pop("dialogue", None)
        baseline = build_pages(ROOT, self.data, baseline_catalog, self.details)
        changed = {title for title in self.pages if self.pages[title] != baseline[title]}
        self.assertEqual(changed, set(self.topics))
        for owner in self.topics:
            self.assertEqual(
                self.pages[owner].split("== Stats ==", 1)[1],
                baseline[owner].split("== Stats ==", 1)[1],
            )
        self.assertEqual(self.pages["Quests and journal"], baseline["Quests and journal"])

    def test_viend_healing_and_dialogue_coexist_in_order_without_duplicate_content(self):
        page = self.pages["Viend"]
        healing = page.index("== <nowiki>Healing</nowiki> ==")
        dialogue = page.index("== Dialogue and guidance ==")
        stats = page.index("== Stats ==")
        self.assertLess(healing, dialogue)
        self.assertLess(dialogue, stats)
        self.assertEqual(page.count("Viend automatically heals"), 1)
        self.assertEqual(page.count("[[File:Healing-popup.png|"), 1)
        self.assertIn("[[File:Healing-popup.png|", page[healing:dialogue])
        self.assertNotIn("dialogue-information", page[healing:dialogue])
        self.assertIn('id="dialogue-information"', page[dialogue:stats])
        self.assertIn('id="dialogue-quest-guidance"', page[dialogue:stats])
        self.assertNotIn("Viend automatically heals", page[dialogue:stats])
        audit = audit_report(self.data, self.catalog, self.details)
        self.assertIn("[[Viend#Healing|", audit)
        self.assertIn("[[Viend#dialogue-information|", audit)

        catalog = copy.deepcopy(self.catalog)
        viend = next(row for row in catalog["classifications"] if row["entity"] == "being-19")
        viend["location"] = {
            "paragraphs": ["Synthetic location for the combined section-order regression."],
            "related_entities": [],
            "confidence": "observed",
            "evidence": copy.deepcopy(viend["evidence"]),
        }
        validate_catalog(catalog, self.data)
        page = build_pages(ROOT, self.data, catalog, self.details)["Viend"]
        headings = ("== Location and access ==", "== <nowiki>Healing</nowiki> ==",
                    "== Dialogue and guidance ==", "== Stats ==")
        self.assertEqual([page.index(heading) for heading in headings],
                         sorted(page.index(heading) for heading in headings))

    def test_schema_rejects_unbounded_unsafe_and_incomplete_topics(self):
        base = self.topic("Captain Eir", "fort-curfew")
        mutations = [
            {"id": "../escape"}, {"title": "{{Unsafe}}"}, {"spoiler": "false"},
            {"paragraphs": []}, {"paragraphs": ["x"] * 5}, {"paragraphs": ["x" * 1201]},
            {"evidence": []}, {"confidence": "certain"}, {"links": {}},
            {"links": [{"label": "Missing label", "target": "Bestiary"}]},
            {"links": [{"label": "Aggression rules", "target": "Bestiary|Injected"}]},
            {"links": [{"label": "Aggression rules", "target": "Bestiary#"}]},
            {"links": [{"label": "Aggression rules", "target": "Bestiary#bad#anchor"}]},
            {"links": [{"label": "Aggression rules", "target": "https://example.invalid"}]},
            {"links": [{"label": "Aggression rules", "target": "Bestiary"}] * 2},
            *({"paragraphs": paragraphs,
               "links": [{"label": label, "target": "Resting"} for label in labels]}
              for paragraphs, labels in (
                  (["Resting"], ["Rest"]), (["_Rest Rest1"], ["Rest"]),
                  (["Rest stop"], ["Rest", "Rest stop"]),
                  (["Rest", "stop"], ["Rest stop"]),
              )),
            {"unknown": "field"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                catalog = copy.deepcopy(self.catalog)
                row = next(row for row in catalog["classifications"] if row["entity"] == "being-6")
                row["dialogue"] = [dict(copy.deepcopy(base), **mutation)]
                with self.assertRaises(DataError):
                    validate_catalog(catalog, self.data)
        for value in ([], [base] * 2, [base] * 9):
            catalog = copy.deepcopy(self.catalog)
            row = next(row for row in catalog["classifications"] if row["entity"] == "being-6")
            row["dialogue"] = copy.deepcopy(value)
            with self.assertRaises(DataError):
                validate_catalog(catalog, self.data)
        catalog = copy.deepcopy(self.catalog)
        row = next(row for row in catalog["classifications"] if row["kind"] == "creature")
        row["dialogue"] = [copy.deepcopy(base)]
        with self.assertRaises(DataError):
            validate_catalog(catalog, self.data)

    def test_renderer_rejects_nonexistent_pages_and_anchors(self):
        for target in ("Nonexistent destination", "Captain Eir#dialogue-missing", "Quests and journal#entry-missing"):
            catalog = copy.deepcopy(self.catalog)
            row = next(row for row in catalog["classifications"] if row["entity"] == "being-5")
            row["dialogue"][0]["links"][0]["target"] = target
            validate_catalog(catalog, self.data)
            with self.assertRaisesRegex(DataError, "NPC dialogue: missing linked page or explicit anchor"):
                build_pages(ROOT, self.data, catalog, self.details)

    def test_plain_prose_cannot_execute_wiki_markup(self):
        catalog = copy.deepcopy(self.catalog)
        topic = next(row for row in catalog["classifications"] if row["entity"] == "being-5")["dialogue"][0]
        topic["paragraphs"] = ["Synthetic <b>text</b> and {{Unsafe}}. Rest stop.", "Rest! [Rest+]"]
        topic["links"] = [{"label": label, "target": "Resting"} for label in ("Rest", "Rest stop", "Rest+")]
        validate_catalog(catalog, self.data)
        page = build_pages(ROOT, self.data, catalog, self.details)["Soldier"]
        self.assertIn("<nowiki>Synthetic &lt;b&gt;text&lt;/b&gt; and {{Unsafe}}. </nowiki>", page)
        for link in topic["links"]:
            self.assertEqual(page.count(f'[[Resting|{literal(link["label"])}]]'), 1)
        visible = re.sub(r"<nowiki>.*?</nowiki>", "", page, flags=re.S)
        self.assertNotIn("{{Unsafe}}", visible)


if __name__ == "__main__":
    unittest.main()
