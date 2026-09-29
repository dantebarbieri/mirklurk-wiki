import json
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_wiki import EXPORT_NS, build_xml, existing_titles
from smoke_editing import MERCHANT, OWNER, SCROLL, editor_fixtures
from sync_wiki import SyncError, fetch_live, sync
from test_sync import FakeWiki, edits, logged_in
from wiki_data import DataError, title_key
from wiki_details import load_publication_inputs
from wiki_display import DISPLAY_FILES, content_model, page_namespace
from wiki_render import build_pages


class EditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data, catalog, details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, data, catalog, details)

    def test_template_metadata_matches_arguments_and_actual_defaults(self):
        required = {
            "Item": {"1"}, "Creature": {"1"}, "Coins": {"1"}, "Health grid": {"1"},
            "Attack grid": {"1"}, "Recipe row": set(), "Ware row": {"item"}, "Unverified": set(),
        }
        defaults = {
            "Attack grid": {"label": "Attack pattern"},
            "Recipe row": {"ingredients": "No item inputs", **dict.fromkeys(
                ("output", "methods", "cost", "conditions"), "Unknown")},
            "Ware row": {"seller": "Unknown"},
        }
        for title in DISPLAY_FILES:
            if not title.startswith("Template:"):
                continue
            text = self.pages[title]
            body = re.fullmatch(r"<includeonly>(.*?)</includeonly><noinclude>(.*?)</noinclude>\n", text, re.S)
            self.assertIsNotNone(body, title)
            self.assertNotIn("<templatedata>", body[1])
            matches = re.findall(r"<templatedata>(.*?)</templatedata>", body[2], re.S)
            self.assertEqual(len(matches), 1)
            data = json.loads(matches[0])
            arguments = set(re.findall(r"\{\{\{([^|{}]+)(?:\||\}\}\})", body[1]))
            self.assertEqual(set(data["params"]), arguments, title)
            self.assertEqual(set(data["paramOrder"]), arguments)
            self.assertEqual(len(data["paramOrder"]), len(arguments))
            name = title.removeprefix("Template:")
            self.assertEqual({key for key, value in data["params"].items() if value.get("required")}, required[name])
            self.assertEqual({key: value["default"] for key, value in data["params"].items() if "default" in value},
                             defaults.get(name, {}))
            self.assertNotIn("autovalue", matches[0], "Examples/defaults must not add new factual values.")
            for param in data["params"].values():
                self.assertTrue(param["label"] and param["description"])
                self.assertIn(param["type"], {"string", "number", "wiki-page-name", "content"})

    def test_help_is_finitely_allowlisted_and_exported_without_reseeding(self):
        title = "Help:Editing"
        self.assertEqual(title_key("help:editing"), title)
        self.assertEqual(page_namespace(title), 12)
        self.assertEqual(content_model(title), "wikitext")
        for unsupported in ("Help:Other", "Help:Editing/subpage", "User:TestEditor"):
            with self.assertRaises(DataError):
                page_namespace(unsupported)
        xml = build_xml({title: self.pages[title]})
        ns = {"w": EXPORT_NS}
        document = ET.fromstring(xml)
        self.assertEqual(document.findtext("w:page/w:ns", namespaces=ns), "12")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "existing.xml"
            path.write_bytes(xml)
            self.assertEqual(existing_titles(path), {title})
        wiki = logged_in(FakeWiki())
        report = sync(wiki, {title: self.pages[title]}, "repo-sync: help", apply=True, log=lambda _: None)
        self.assertEqual(report["created"], [title])
        wiki.store(title, "Community onboarding edit.", "New contributor", "Clarify instructions")
        before = fetch_live(wiki, {title})
        report = sync(wiki, {title: self.pages[title]}, "repo-sync: help again", apply=True, log=lambda _: None)
        self.assertEqual([row["title"] for row in report["skipped"]], [title])
        self.assertEqual(fetch_live(wiki, {title}), before)

    def test_templatedata_runtime_failure_stops_publication_before_any_edit(self):
        wiki = logged_in(FakeWiki())
        original = wiki.call

        def call(params, **kwargs):
            result = original(params, **kwargs)
            if params.get("meta") == "siteinfo":
                result["query"]["extensions"] = [
                    row for row in result["query"]["extensions"] if row["name"] != "TemplateData"
                ]
            return result

        wiki.call = call
        with self.assertRaisesRegex(SyncError, "TemplateData"):
            sync(wiki, self.pages, "repo-sync: missing metadata runtime", apply=True, log=lambda _: None)
        self.assertEqual(edits(wiki), [])

    def test_onboarding_and_fixtures_preserve_source_editing_boundaries(self):
        help_text = self.pages["Help:Editing"]
        self.assertLess(len(help_text.split()), 600)
        for term in ("Edit source", "Show preview", "summary", "onlyinclude", "noinclude", "includeonly",
                     "#switch", "#if", "merchant", "workstation", "CAPTCHA", "rate limit"):
            self.assertIn(term, help_text)
        fixtures = editor_fixtures()
        self.assertIn("<onlyinclude>{{#switch:", fixtures[OWNER])
        self.assertIn(SCROLL, fixtures[OWNER])
        self.assertIn("{{#switch:{{{station|}}}", fixtures[OWNER])
        self.assertIn("{{Recipe row", fixtures[OWNER])
        self.assertIn("|price=<noinclude>{{:" + OWNER + "}}</noinclude>", fixtures[MERCHANT])
        self.assertIn('<noinclude><th scope="col">Price</th></noinclude>', fixtures[MERCHANT])


if __name__ == "__main__":
    unittest.main()
