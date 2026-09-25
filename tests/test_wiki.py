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
from wiki_data import DataError, PAGE_FILES, load_data, parse_data, validate_data


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


class DataTests(unittest.TestCase):
    def test_curated_payload_and_expected_shape(self):
        data = load_data(ROOT / "content" / "facts" / "game.json")
        self.assertEqual(len(data["sources"]), 5)
        self.assertEqual(len(data["entities"]), 336)
        self.assertEqual(len(data["facts"]), 79)
        self.assertIsNone(data["game"]["build"])
        self.assertEqual(
            {confidence: sum(f["confidence"] == confidence for f in data["facts"])
             for confidence in ("localization-described", "inferred")},
            {"localization-described": 28, "inferred": 51},
        )
        pages = build_pages(ROOT, data)
        self.assertEqual(len(pages), len(PAGE_FILES) + 1)
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


class ExportTests(unittest.TestCase):
    def test_deterministic_independent_of_input_order(self):
        data = load_data(ROOT / "content" / "facts" / "game.json")
        original = build_xml(build_pages(ROOT, data))
        reversed_data = copy.deepcopy(data)
        for key in ("sources", "entities", "facts"):
            reversed_data[key].reverse()
        for record in reversed_data["entities"] + reversed_data["facts"]:
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
