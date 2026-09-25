import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_wiki import EXPORT_NS, build_pages, build_xml, existing_titles, literal, title_key
from wiki_data import DataError, PAGE_FILES, RESEARCH_PAGE_FILES, load_data, parse_data, validate_data


def synthetic_data():
    reference = {"source": "synthetic", "section": "SyntheticTitles", "key": "1"}
    return {
        "schema_version": 1,
        "game": {"name": "MirkLurk", "developer": None, "build": None, "steam_app_id": 3972980},
        "sources": [{
            "id": "synthetic", "path": "Synthetic.ini",
            "sha256": hashlib.sha256(b"synthetic test evidence, not a game file").hexdigest(),
            "build": None,
        }],
        "entities": [{
            "id": "synthetic-item", "category": "item", "name": "Synthetic & <name>",
            "confidence": "observed", "evidence": [reference.copy()],
        }],
        "facts": [{
            "id": "synthetic-fact", "page": "Game mechanics", "entity": "Synthetic",
            "property": "Synthetic toggle", "value": True, "description": "Synthetic test statement.",
            "confidence": "inferred", "evidence": [reference.copy()],
        }],
    }


def research_data():
    data = synthetic_data()
    being = copy.deepcopy(data["entities"][0])
    being.update(id="synthetic-being", category="being", name="Synthetic merchant")
    data["entities"].append(being)
    details = {
        "quest": {"quest_id": "synthetic-journal-1", "stage": None},
        "merchant": {
            "merchant": "synthetic-being", "item": "synthetic-item", "quantity": None,
            "price": 2, "currency": "synthetic units", "location": None,
        },
        "recipe": {
            "station": "Synthetic station",
            "inputs": [{"item": "synthetic-item", "quantity": 2}],
            "outputs": [{"item": "synthetic-item", "quantity": 1}], "cost": None,
        },
        "loot": {
            "table": "synthetic-pool", "outcome": "synthetic-item",
            "quantity": {"min": 1, "max": 2}, "weight": 2, "probability": None,
            "rolls": None,
        },
        "algorithm": {
            "page": "Weather", "steps": ["An original synthetic step."],
            "fact_ids": ["synthetic-fact"],
        },
    }
    data["entries"] = [
        {
            "id": f"synthetic-{kind}", "kind": kind, "title": f"Synthetic {kind}",
            "summary": "Original synthetic summary; not a game claim.", "conditions": None,
            "confidence": "inferred", "evidence": copy.deepcopy(data["facts"][0]["evidence"]),
            "details": value,
        }
        for kind, value in details.items()
    ]
    return data


def illustration_data(approved=False):
    data = synthetic_data()
    data["illustrations"] = [{
        "id": "synthetic-picture", "entity": "synthetic-item", "file_title": "File:Synthetic.png",
        "caption": "Original synthetic caption.", "creator": None, "sha256": None,
        "rights_status": "pending", "rights_basis": None, "rights_note": None,
        "confidence": "inferred", "evidence": copy.deepcopy(data["entities"][0]["evidence"]),
    }]
    if approved:
        data["illustrations"][0].update(
            creator="Synthetic test creator", sha256=hashlib.sha256(b"no image bytes; schema test").hexdigest(),
            rights_status="approved", rights_basis="Synthetic schema fixture only",
            rights_note="This test does not provide or clear any actual artwork.",
        )
    return data


class DataTests(unittest.TestCase):
    def test_curated_payload_and_expected_shape(self):
        data = load_data(ROOT / "content" / "facts" / "game.json")
        baseline = {
            "sources": (5, "8dae164eff56d6bbd220051cded80d2fa6f4dd130b8adff3f471f8c82ed75508"),
            "entities": (336, "947b17faa67b5e8fc50a37d2a0a13ee73157c6c32ea9f2ce80a895a452b8a92e"),
            "facts": (79, "cc0c1c66f198029fffe8fa1de023fcbd1d5c5d59722d328b4d6d320aa358dc7e"),
        }
        for key, (count, digest) in baseline.items():
            records = sorted(data[key][:count], key=lambda record: record["id"])
            raw = json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest, f"Original {key} changed")
        self.assertIsNone(data["game"]["build"])
        self.assertEqual(
            {confidence: sum(f["confidence"] == confidence for f in data["facts"][:79])
             for confidence in ("localization-described", "inferred")},
            {"localization-described": 28, "inferred": 51},
        )
        pages = build_pages(ROOT, data)
        self.assertTrue(set(PAGE_FILES) <= pages.keys())
        self.assertIn("not runtime-verified", pages["Game mechanics"])
        self.assertIn("non-hostile", pages["Bestiary"])

    def test_valid_boolean_and_numeric_values(self):
        for value in (True, False, 0, -4, 2.5):
            data = synthetic_data()
            data["facts"][0]["value"] = value
            self.assertIs(validate_data(data), data)

    def test_invalid_or_unvetted_shapes_are_rejected(self):
        changes = [
            lambda d: d.update(raw_dump="not allowed"),
            lambda d: d.update(schema_version=True),
            lambda d: d["game"].update(steam_app_id=True),
            lambda d: d["sources"][0].update(path="../Synthetic.ini"),
            lambda d: d["sources"][0].update(path="/Synthetic.ini"),
            lambda d: d["sources"][0].update(path="Z:\\Synthetic.ini"),
            lambda d: d["sources"][0].update(path="export.json"),
            lambda d: d["sources"][0].update(sha256="invalid"),
            lambda d: d["sources"].append(copy.deepcopy(d["sources"][0])),
            lambda d: d["entities"][0].update(name="Copied paragraph.\nMore prose."),
            lambda d: d["entities"][0].update(category="enemy"),
            lambda d: d["entities"][0].update(category=[]),
            lambda d: d["entities"][0].update(confidence=[]),
            lambda d: d["entities"][0].update(group="missing"),
            lambda d: d["entities"][0].update(category="skill", group="missing"),
            lambda d: d["entities"].append(copy.deepcopy(d["entities"][0])),
            lambda d: d["facts"][0].update(value="copied text"),
            lambda d: d["facts"][0].update(value=float("nan")),
            lambda d: d["facts"][0].update(value=float("inf")),
            lambda d: d["facts"][0].update(value=10**16),
            lambda d: d["facts"][0].update(page="Template:Injected"),
            lambda d: d["facts"][0].update(confidence="verified"),
            lambda d: d["facts"][0].update(description="x" * 501),
            lambda d: d["facts"][0].update(evidence=[]),
            lambda d: d["facts"][0]["evidence"][0].update(source="missing"),
            lambda d: d["facts"][0]["evidence"].append(copy.deepcopy(d["facts"][0]["evidence"][0])),
        ]
        for number, change in enumerate(changes):
            with self.subTest(case=number):
                data = synthetic_data()
                change(data)
                with self.assertRaises(DataError):
                    validate_data(data)

    def test_duplicate_json_keys_and_nonfinite_constants_fail(self):
        for raw in (b'{"x":1,"x":2}', b'{"value":NaN}', b"\xff"):
            with self.assertRaises(DataError):
                parse_data(raw)

    def test_skill_relationship_requires_a_real_group(self):
        data = synthetic_data()
        group = copy.deepcopy(data["entities"][0])
        group.update(id="synthetic-group", category="skill_group")
        data["entities"][0].update(category="skill", group=group["id"])
        data["entities"].append(group)
        validate_data(data)
        self.assertIn("Synthetic &amp; &lt;name&gt;", build_pages(ROOT, data)["Skills"])


class ResearchTests(unittest.TestCase):
    def test_original_version_one_needs_no_extension_fields(self):
        data = synthetic_data()
        validate_data(data)
        pages = build_pages(ROOT, data)
        self.assertEqual(set(pages), {*PAGE_FILES, "Source provenance"})
        self.assertNotIn("More researched topics", pages["Main Page"])
        self.assertNotIn("Illustration references", pages["Items"])

    def test_typed_entries_render_with_evidence_and_unknowns(self):
        data = research_data()
        pages = build_pages(ROOT, data)
        self.assertIn("Quests and journal", pages)
        self.assertIn("[[Merchants]]", pages["Main Page"])
        self.assertNotIn("World seed logic", pages)
        self.assertNotIn("[[World seed logic]]", pages["Main Page"])
        self.assertIn("Not established", pages["Merchants"])
        self.assertIn("Not established; not calculated from weight", pages["Loot tables"])
        self.assertNotIn("50%", pages["Loot tables"])
        self.assertIn("[[Items#entity-synthetic-item|", pages["Crafting"])
        self.assertIn("[[Game mechanics#fact-synthetic-fact|", pages["Weather"])
        for title in ("Quests and journal", "Merchants", "Crafting", "Loot tables", "Weather"):
            self.assertIn("[[Source provenance#synthetic|synthetic]]", pages[title])
            self.assertIn("Inferred; requires confirmation", pages[title])

    def test_topic_fact_without_entry_activates_only_its_page(self):
        data = synthetic_data()
        data["facts"][0]["page"] = "World seed logic"
        pages = build_pages(ROOT, data)
        self.assertIn("World seed logic", pages)
        self.assertEqual(set(pages) & RESEARCH_PAGE_FILES.keys(), {"World seed logic"})
        self.assertIn("[[World seed logic]]", pages["Main Page"])

    def test_all_algorithm_destinations_are_supported(self):
        for title in ("Weather", "Level progression", "World seed logic", "Skills"):
            data = research_data()
            data["entries"][-1]["details"]["page"] = title
            self.assertIn("An original synthetic step.", build_pages(ROOT, data)[title])

    def test_explicit_empty_result_is_not_an_unknown_item(self):
        data = research_data()
        details = data["entries"][3]["details"]
        details.update(outcome=None, quantity=None, probability=0.25, rolls={"min": 0, "max": 1})
        page = build_pages(ROOT, data)["Loot tables"]
        self.assertIn("Explicit empty result", page)
        self.assertIn("<nowiki>0.25</nowiki>", page)

    def test_invalid_structured_claims_fail(self):
        changes = [
            lambda d: d["entries"][0].update(summary="x" * 1201),
            lambda d: d["entries"][0].update(summary="not\none line"),
            lambda d: d["entries"][0].update(evidence=[]),
            lambda d: d["entries"][0].update(conditions=True),
            lambda d: d["entries"][0].update(kind="unknown"),
            lambda d: d["entries"][0]["details"].update(raw_journal="copied"),
            lambda d: d["entries"].append(copy.deepcopy(d["entries"][0])),
            lambda d: d["entries"][1]["details"].update(merchant="synthetic-item"),
            lambda d: d["entries"][1]["details"].update(item="missing"),
            lambda d: d["entries"][1]["details"].update(quantity=True),
            lambda d: d["entries"][1]["details"].update(quantity=0),
            lambda d: d["entries"][1]["details"].update(price=-1),
            lambda d: d["entries"][1]["details"].update(currency=None),
            lambda d: d["entries"][2]["details"].update(outputs=[]),
            lambda d: d["entries"][2]["details"]["inputs"][0].update(quantity=0.5),
            lambda d: d["entries"][2]["details"]["inputs"].append({"item": "synthetic-item", "quantity": 1}),
            lambda d: d["entries"][2]["details"].update(cost={"amount": -1, "unit": "synthetic"}),
            lambda d: d["entries"][3]["details"].update(probability=1.01),
            lambda d: d["entries"][3]["details"].update(weight=float("nan")),
            lambda d: d["entries"][3]["details"].update(weight=float("inf")),
            lambda d: d["entries"][3]["details"].update(outcome=None),
            lambda d: d["entries"][3]["details"].update(quantity={"min": 2, "max": 1}),
            lambda d: d["entries"][3]["details"].update(rolls={"min": False, "max": 1}),
            lambda d: d["entries"][4]["details"].update(page="Template:Injected"),
            lambda d: d["entries"][4]["details"].update(steps=[]),
            lambda d: d["entries"][4]["details"].update(fact_ids=["missing"]),
            lambda d: d["entries"][4]["details"].update(fact_ids=["synthetic-fact", "synthetic-fact"]),
        ]
        for number, change in enumerate(changes):
            with self.subTest(case=number):
                data = research_data()
                change(data)
                with self.assertRaises(DataError):
                    validate_data(data)

    def test_research_text_is_literal_and_output_is_deterministic(self):
        data = research_data()
        data["entries"][0]["summary"] = '</nowiki>{{No template}}|[[No link]]<script>'
        original = build_xml(build_pages(ROOT, data))
        data["entries"].reverse()
        for key in ("facts", "entities", "sources"):
            data[key].reverse()
        self.assertEqual(original, build_xml(build_pages(ROOT, data)))
        self.assertIn("&amp;lt;/nowiki", original.decode())
        self.assertNotIn("<script>", original.decode())

    def test_pending_images_never_embed_or_link_artwork(self):
        pages = build_pages(ROOT, illustration_data())
        self.assertIn("pending rights confirmation", pages["Items"])
        self.assertNotIn("[[File:", pages["Items"])
        self.assertNotIn("[[:File:", pages["Items"])

    def test_approved_references_have_domain_independent_attribution(self):
        pages = build_pages(ROOT, illustration_data(approved=True))
        self.assertIn("[[File:Synthetic.png|thumb|", pages["Items"])
        self.assertIn("Synthetic test creator", pages["Items"])
        self.assertNotIn("https://", pages["Items"])

    def test_invalid_illustration_metadata_is_rejected(self):
        changes = [
            lambda i: i.update(entity="missing"),
            lambda i: i.update(file_title="https://example.invalid/image.png"),
            lambda i: i.update(file_title="File:../../Image.png"),
            lambda i: i.update(file_title="File:Image.svg"),
            lambda i: i.update(file_title="File:Image.png|link=Injected"),
            lambda i: i.update(file_title="File:Image]].png"),
            lambda i: i.update(rights_status="assumed"),
            lambda i: i.update(rights_status="approved"),
            lambda i: i.update(sha256="invalid"),
            lambda i: i.update(evidence=[]),
        ]
        for number, change in enumerate(changes):
            with self.subTest(case=number):
                data = illustration_data()
                change(data["illustrations"][0])
                with self.assertRaises(DataError):
                    validate_data(data)
        data = illustration_data(approved=True)
        duplicate = copy.deepcopy(data["illustrations"][0])
        duplicate["id"] = "another-picture"
        data["illustrations"].append(duplicate)
        with self.assertRaises(DataError):
            validate_data(data)


class ExportTests(unittest.TestCase):
    def test_deterministic_independent_of_input_order(self):
        data = load_data(ROOT / "content" / "facts" / "game.json")
        original = build_xml(build_pages(ROOT, data))
        reversed_data = copy.deepcopy(data)
        for key in ("sources", "entities", "facts", "entries", "illustrations"):
            if key not in reversed_data:
                continue
            reversed_data[key].reverse()
        for record in reversed_data["entities"] + reversed_data["facts"] + reversed_data.get("entries", []) + reversed_data.get("illustrations", []):
            record["evidence"].reverse()
        self.assertEqual(original, build_xml(build_pages(ROOT, reversed_data)))

    def test_xml_roundtrip_and_byte_counts(self):
        pages = {"A & <title>": "Original <text> & {{literal wiki markup}}\n"}
        root = ET.fromstring(build_xml(pages))
        ns = {"m": EXPORT_NS}
        self.assertEqual(root.findtext("m:page/m:title", namespaces=ns), next(iter(pages)))
        text = root.find("m:page/m:revision/m:text", ns)
        self.assertEqual(text.text, next(iter(pages.values())))
        self.assertEqual(int(text.attrib["bytes"]), len(text.text.encode("utf-8")))

    def test_untrusted_fact_strings_cannot_escape_nowiki(self):
        value = '</nowiki>{{INJECTED}}|[[Injected]]<script>&"'
        escaped = literal(value)
        self.assertEqual(escaped.count("</nowiki>"), 1)
        self.assertNotIn("<script>", escaped)
        self.assertIn("&lt;/nowiki&gt;", escaped)
        data = synthetic_data()
        data["entities"][0]["name"] = value
        payload = build_xml(build_pages(ROOT, data))
        ET.fromstring(payload)
        self.assertIn("&amp;lt;/nowiki", payload.decode())

    def test_existing_title_filter_never_includes_an_existing_page(self):
        with tempfile.TemporaryDirectory() as folder:
            export = Path(folder) / "current.xml"
            export.write_bytes(build_xml({"main_Page": "Live edit, not repository text.\n"}))
            excluded = existing_titles(export)
            pages = build_pages(ROOT, synthetic_data())
            new_pages = {title: text for title, text in pages.items() if title_key(title) not in excluded}
            self.assertNotIn("Main Page", new_pages)
            self.assertEqual(len(new_pages), len(pages) - 1)
            self.assertNotIn("Live edit", build_xml(new_pages).decode())

    def test_incomplete_or_wrong_export_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            export = Path(folder) / "invalid.xml"
            for raw in (
                b"<unexpected/>", b"<mediawiki",
                f'<mediawiki xmlns="{EXPORT_NS}"/>'.encode(),
                f'<mediawiki xmlns="{EXPORT_NS}"><siteinfo/><page><title>x</title></page></mediawiki>'.encode(),
            ):
                export.write_bytes(raw)
                with self.assertRaises(DataError):
                    existing_titles(export)

    def test_cli_requires_mode_and_refuses_output_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "seed.xml"
            command = [sys.executable, str(ROOT / "tools" / "build_wiki.py"), "--output", str(output)]
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            success = subprocess.run(command + ["--fresh"], capture_output=True)
            self.assertEqual(success.returncode, 0, success.stderr.decode())
            original = output.read_bytes()
            self.assertNotEqual(subprocess.run(command + ["--fresh"], capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), original)
            filtered = Path(folder) / "missing.xml"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "build_wiki.py"), "--existing-export",
                 str(output), "--output", str(filtered)],
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(ET.parse(filtered).getroot().findall(f"{{{EXPORT_NS}}}page"), [])


if __name__ == "__main__":
    unittest.main()
