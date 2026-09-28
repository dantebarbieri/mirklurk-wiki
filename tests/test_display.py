import copy
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_wiki import EXPORT_NS, build_xml, existing_titles
from sync_wiki import SyncError, fetch_live, stale_renderings, sync, write_order
from test_sync import FakeWiki, edits, logged_in, ours
from wiki_data import DataError, _title, title_key
from wiki_details import load_publication_inputs
from wiki_display import (
    ASSETS_TITLE, DISPLAY_FILES, DISPLAY_TITLES, MAX_COPPER, content_model, dependencies,
    lua_string, page_namespace,
)
from wiki_render import build_pages, health_armor_icon, image_for, pixel_image, price_text


class DisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)

    def test_finite_registry_and_truthful_xml_models(self):
        display = {title: self.pages[title] for title in DISPLAY_TITLES}
        document = ET.fromstring(build_xml(display))
        ns = {"w": EXPORT_NS}
        for page in document.findall("w:page", ns):
            title = page.findtext("w:title", namespaces=ns)
            self.assertEqual(page.findtext("w:ns", namespaces=ns), str(page_namespace(title)))
            self.assertEqual(page.findtext("w:revision/w:model", namespaces=ns), content_model(title))
            self.assertEqual(page.findtext("w:revision/w:format", namespaces=ns),
                             "text/plain" if title.startswith("Module:") else "text/x-wiki")
            self.assertEqual(page.findtext("w:revision/w:text", namespaces=ns), display[title])
        with tempfile.TemporaryDirectory() as folder:
            export = Path(folder) / "current.xml"
            export.write_bytes(build_xml(display))
            self.assertEqual(existing_titles(export), DISPLAY_TITLES)
        for title in ("Template:Other", "Module:Other", "User:Someone", "Help:Title", "File:Pic.png"):
            with self.subTest(title=title), self.assertRaises(DataError):
                page_namespace(title)
        for title in ("template:coins", "module:display_assets", "category: armor"):
            self.assertEqual(title_key(title), {"template:coins": "Template:Coins",
                                               "module:display_assets": ASSETS_TITLE,
                                               "category: armor": "Category:Armor"}[title])
            with self.assertRaises(DataError):
                _title(title)

    def test_assets_reuse_exact_reviewed_image_policy_and_escaping(self):
        assets = self.pages[ASSETS_TITLE]
        for name, identity in (("gold", "item-74"), ("silver", "item-73"), ("copper", "item-72")):
            image = image_for(identity, self.data["illustrations"])
            self.assertIn(lua_string(pixel_image(image, 20, 20, "", name.capitalize() + " coin")), assets)
        for armor in (1, 2, 3):
            self.assertIn(lua_string(health_armor_icon(armor, self.data["illustrations"])), assets)
        image = copy.deepcopy(image_for("item-72", self.data["illustrations"]))
        image["caption"] = '</nowiki><script>"&{{Coins|4}}]=]'
        escaped = pixel_image(image)
        self.assertIn("&lt;/nowiki&gt;&lt;script&gt;", escaped)
        self.assertNotIn("<script>", escaped)
        self.assertTrue(lua_string(escaped).startswith("[==["))
        self.assertNotIn("pixel_art", self.pages["Module:Display"])
        self.assertNotIn("File:", self.pages["Module:Display"])

    def test_exact_price_conversion_and_boundaries(self):
        for copper in (0, 1, 99, 100, 999, 1000, 1234, 9007199254740993, MAX_COPPER):
            self.assertEqual(price_text({"value": Decimal(copper) / 100}), "{{Coins|" + str(copper) + "}}")
        for value in ("-1", "1.001", "1.00000000000000000000000000001", "NaN", "Infinity", str(Decimal(MAX_COPPER + 1) / 100)):
            with self.subTest(value=value), self.assertRaises(DataError):
                price_text({"value": Decimal(value)})

    def test_grid_migration_has_only_the_authorized_templates(self):
        articles = {title: text for title, text in self.pages.items() if title not in DISPLAY_TITLES}
        self.assertEqual(sum(text.count("{{Health grid|") for text in articles.values()), 36)
        self.assertEqual(sum(text.count("{{Attack grid|") for text in articles.values()), 82)
        self.assertEqual(sum(text.count("|label=Ranged attack}}") for text in articles.values()), 7)
        self.assertFalse(any('class="mirklurk-cell-grid"' in text for text in articles.values()))
        for title in ("Sceetler", "Nightmare"):
            self.assertIn("== Base health ==", self.pages[title])
            self.assertIn("== Melee attack ==", self.pages[title])
        self.assertIn("{{Health grid|0,1,0;1,4,1;0,1,0}}", self.pages["Sceetler"])
        self.assertEqual({title for title in self.pages if title.startswith("Template:")}, set(DISPLAY_FILES) - {"Module:Display"})


class DisplayPublisherTests(unittest.TestCase):
    def setUp(self):
        self.pages = {
            ASSETS_TITLE: "return { value = 1 }",
            "Module:Display": "local p = {}; function p.coins() return mw.loadData('Module:Display assets').value end; return p",
            "Template:Coins": "{{#invoke:Display|coins}}",
            "Item": "<onlyinclude>{{Coins|1234}}</onlyinclude>",
            "Merchant": "{{:Item}}",
        }

    def run_sync(self, wiki, pages=None, **kwargs):
        return sync(wiki, self.pages if pages is None else pages, "repo-sync: display", log=lambda _: None, **kwargs)

    def test_dependency_extraction_ignores_parameters_and_literal_documentation(self):
        self.assertEqual(dependencies("<nowiki>{{Other}}</nowiki><!--{{No}}-->{{ Coins |{{{1|0}}}}} {{template:health_grid|1}}"),
                         {"Template:Coins", "Template:Health grid"})
        self.assertEqual(dependencies(self.pages["Module:Display"], lua=True), {ASSETS_TITLE})
        self.assertEqual(dependencies("require('Module:Display assets')", lua=True), {ASSETS_TITLE})
        self.assertEqual(dependencies(self.pages["Template:Coins"]), {"Module:Display"})

    def test_order_and_transitive_refresh_include_assets_through_item_and_merchant(self):
        self.assertEqual(write_order(self.pages, self.pages), [ASSETS_TITLE, "Module:Display", "Template:Coins", "Item", "Merchant"])
        self.assertEqual(stale_renderings(self.pages, [ASSETS_TITLE], set()),
                         ["Item", "Merchant", "Module:Display", "Template:Coins"])
        wiki = logged_in(FakeWiki())
        report = self.run_sync(wiki, apply=True)
        self.assertEqual(edits(wiki), write_order(self.pages, self.pages))
        self.assertEqual(report["errors"], [])
        writes = [call for call in wiki.calls if call["action"] == "edit"]
        for call in writes:
            self.assertEqual(call["contentmodel"], content_model(call["title"]))
        changed = dict(self.pages, **{ASSETS_TITLE: "return { value = 2 }"})
        report = self.run_sync(wiki, changed, apply=True)
        self.assertEqual(report["refreshed"], ["Item", "Merchant", "Module:Display", "Template:Coins"])

    def test_missing_runtime_namespace_model_engine_and_invalid_lua_prevent_all_edits(self):
        for failure in ("extension", "namespace", "model", "engine", "live-model", "syntax"):
            wiki = logged_in(FakeWiki({ASSETS_TITLE: ours(self.pages[ASSETS_TITLE])}))
            original = wiki.call

            def call(params, **kwargs):
                result = original(params, **kwargs)
                if params.get("meta") == "siteinfo":
                    if failure == "extension":
                        result["query"]["extensions"] = []
                    elif failure == "namespace":
                        result["query"]["namespaces"]["828"]["canonical"] = "Not module"
                elif params["action"] == "paraminfo" and failure == "model":
                    result["paraminfo"]["modules"][0]["parameters"][0]["type"] = ["wikitext"]
                elif params["action"] == "scribunto-console" and failure in {"engine", "syntax"}:
                    return {"type": "error", "message": "Cannot execute or compile"}
                return result

            wiki.call = call
            if failure == "live-model":
                wiki.models[ASSETS_TITLE] = "wikitext"
            with self.subTest(failure=failure), self.assertRaises(SyncError):
                self.run_sync(wiki, apply=True)
            self.assertEqual(edits(wiki), [])

    def test_dry_preview_has_no_console_login_tokens_or_edits(self):
        wiki = FakeWiki()
        self.run_sync(wiki)
        self.assertTrue(all(call["action"] in {"query", "paraminfo"} for call in wiki.calls))
        self.assertFalse(any(call.get("meta") == "tokens" for call in wiki.calls))

    def test_missing_dependencies_and_presentation_cycles_fail_before_writes(self):
        for pages in (
            {key: value for key, value in self.pages.items() if key != ASSETS_TITLE},
            dict(self.pages, **{ASSETS_TITLE: "return require('Module:Display')"}),
            dict(self.pages, **{"Template:Coins": "{{Coins}}"}),
            dict(self.pages, **{"Template:Coins": "{{:Item}}"}),
        ):
            wiki = logged_in(FakeWiki())
            with self.assertRaises(DataError):
                self.run_sync(wiki, pages, apply=True)
            self.assertEqual(edits(wiki), [])

    def test_human_display_definitions_are_preserved_and_block_transitive_new_readers(self):
        for title in (ASSETS_TITLE, "Module:Display", "Template:Coins"):
            with self.subTest(title=title):
                wiki = logged_in(FakeWiki({title: ("Human edit", "Editor", "Do not replace")}))
                report = self.run_sync(wiki, apply=True)
                self.assertEqual(wiki.text(title), "Human edit")
                self.assertNotIn("Item", edits(wiki))
                self.assertNotIn("Merchant", edits(wiki))
                self.assertIn(title, [row["title"] for row in report["skipped"]])
                self.assertTrue({"Item", "Merchant"} <= {row["title"] for row in report["blocked"]})
                report = self.run_sync(wiki, apply=True, adopt=[title])
                self.assertEqual(report["blocked"], [])
                self.assertEqual(wiki.text(title), self.pages[title])

    def test_concurrent_or_failed_module_save_never_publishes_dependent_templates(self):
        for failure in ("concurrent", "error"):
            wiki = logged_in(FakeWiki())
            if failure == "concurrent":
                wiki.concurrent[ASSETS_TITLE] = ("Human edit", "Editor", "Concurrent")
            else:
                wiki.failures[ASSETS_TITLE] = ["permissiondenied"]
            report = self.run_sync(wiki, apply=True)
            self.assertEqual(edits(wiki), [ASSETS_TITLE])
            self.assertTrue(report["conflicts"] or report["errors"])
            self.assertEqual({row["title"] for row in report["blocked"]}, set(self.pages) - {ASSETS_TITLE})


if __name__ == "__main__":
    unittest.main()
