import copy
import re
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
from wiki_data import DataError, _title, read_authored, title_key
from wiki_catalog import page_locations, primary_groups
from wiki_details import load_publication_inputs
from wiki_display import (
    ASSETS_TITLE, DISPLAY_FILES, DISPLAY_TITLES, MAX_COPPER, content_model, dependencies,
    lua_string, page_namespace,
)
from wiki_render import build_pages, health_armor_icon, image_for, pixel_image, price_text, recipe_groups, row_template
from wiki_views import html_table, scroll_open, selective_view


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

    def test_native_authored_files_use_the_same_strict_reader_as_articles(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "content" / "modules" / "Display.lua"
            path.parent.mkdir(parents=True)
            for data in (b"a" * (16 * 1024 + 1), b"\xff", b"return {}\x01"):
                path.write_bytes(data)
                with self.assertRaises(DataError):
                    read_authored(root, "Module:Display", "modules/Display.lua", directory="", limit=16 * 1024)
            path.write_bytes(b"return {}\r\n")
            self.assertEqual(read_authored(root, "Module:Display", "modules/Display.lua", directory=""), "return {}\n")

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

    def test_scroll_wrappers_keep_tables_and_selective_views_native(self):
        opening = scroll_open()
        self.assertIn('role="group" tabindex="0" aria-label="Table (scroll horizontally)"', opening)
        self.assertIn('style="max-width:100%;overflow-x:auto;"', opening)
        self.assertIn('aria-label="A &quot;quote&quot; &amp; &lt;tag&gt; (scroll horizontally)"',
                      scroll_open('A "quote" & <tag>'))
        table = html_table(["Item", "Price"], ["{{Ware row|item=Iron Hand Axe|price={{:Iron Hand Axe}}}}\n"],
                           normal_only=(1,))
        self.assertTrue(table.startswith(opening + '<table class="wikitable">\n'))
        self.assertTrue(table.endswith("</table>\n</div>\n"))
        self.assertIn('<noinclude><th scope="col">Price</th></noinclude>', table)
        self.assertIn("=" + table + "|#default=}}</onlyinclude>", selective_view(table, "wares"))
        for title in ("Items", "Iron Hand Axe", "Gurb-Gurb", "Alchemy workstation", "World generation"):
            text = self.pages[title]
            self.assertIn('class="mirklurk-scroll noresize"', text, title)
            self.assertEqual(text.count('class="mirklurk-scroll noresize"'),
                             text.count('<table class="wikitable">') + text.count('{| class="wikitable"'), title)
        self.assertIn('<table class="wikitable">\n<tr>', self.pages["Alchemy workstation"])
        self.assertIn("{{:Simple Burn Remedy|view=recipes|station=alchemy-workstation}}", self.pages["Alchemy workstation"])
        self.assertNotIn('class="mirklurk-scroll', self.pages["Template:Recipe row"])
        self.assertNotIn('class="mirklurk-scroll', self.pages["Template:Ware row"])
        self.assertIn(":attr('tabindex', '0')", self.pages["Module:Display"])
        self.assertIn('aria-label="Magus Clay&#x27;s alchemy workstation in the fort&#x27;s basement. '
                      '(scroll horizontally)"', self.pages["Alchemy workstation"])

    def test_creature_lookup_and_existing_lists_use_reviewed_classifications_and_art(self):
        locations = page_locations(self.data, self.catalog)
        creatures = {row["entity"] for row in self.catalog["classifications"] if row["kind"] == "creature"}
        self.assertEqual(len(creatures), 25)
        self.assertEqual(self.pages["Bestiary"].count("{{Creature|"), 25)
        self.assertNotIn("{{Creature|", self.pages["NPCs"])
        assets = self.pages[ASSETS_TITLE]
        for identity in creatures:
            title = locations[identity]
            image = image_for(identity, self.data["illustrations"])
            self.assertIn("[ " + lua_string(title) + " ]", assets)
            self.assertIn(pixel_image(image, 32, 32, title, title + " portrait"), assets)
            self.assertIn("[[" + title + "|<nowiki>" + title + "</nowiki>]]", assets)
            line = next(line for line in self.pages["Bestiary"].splitlines() if 'id="entity-' + identity + '"' in line)
            self.assertTrue(line.endswith("{{Creature|" + title + "}}"))
        for row in self.catalog["classifications"]:
            if row["kind"] == "npc":
                self.assertNotIn("[ " + lua_string(locations[row["entity"]]) + " ]", assets)
        for group in primary_groups(self.catalog):
            if group["index"] == "Bestiary":
                expected = sorted(locations[identity] for identity in group["members"])
                for title, section in (
                    ("Bestiary", self.pages["Bestiary"].split("\n== " + group["title"] + " ==\n")[1].split("\n== ", 1)[0]),
                    ("Category:" + group["title"], self.pages["Category:" + group["title"]]),
                ):
                    self.assertEqual(re.findall(r"\{\{Creature\|([^{}]+)\}\}", section), expected, title)
        self.assertEqual(dependencies(self.pages["Template:Creature"]), {"Module:Display"})
        stale = stale_renderings(self.pages, [ASSETS_TITLE], set())
        self.assertIn("Template:Creature", stale)
        self.assertIn("Bestiary", stale)
        self.assertIn("Category:Scaalmyr faction", stale)

    def test_missing_or_unapproved_creature_art_keeps_explicit_name_only_display(self):
        for missing in (True, False):
            data = copy.deepcopy(self.data)
            if missing:
                data["illustrations"] = [row for row in data["illustrations"] if row.get("entity") != "being-13"]
            else:
                image = image_for("being-13", data["illustrations"])
                image.update(rights_status="pending", creator=None, sha256=None, rights_basis=None, rights_note=None)
            pages = build_pages(ROOT, data, self.catalog, self.details)
            self.assertIn(lua_string("[[Sceetler|<nowiki>Sceetler</nowiki>]]"), pages[ASSETS_TITLE])
            self.assertNotIn("Being-13.png", pages[ASSETS_TITLE])
            self.assertIn("{{Creature|Sceetler}}", pages["Bestiary"])

    def test_item_lookup_uses_exact_catalog_titles_art_and_source_classification(self):
        locations = page_locations(self.data, self.catalog)
        items = {row["id"]: row for row in self.data["entities"] if row["category"] == "item"
                 and row["id"] not in {recipe["owner_item"] for recipe in self.catalog["construction_recipes"]}}
        registry = self.pages[ASSETS_TITLE].split("    items = {\n", 1)[1]
        self.assertEqual(len(items), 246)
        self.assertEqual(registry.count("        [ "), len(items))
        for identity, item in items.items():
            title = locations[identity]
            line = next(line for line in registry.splitlines() if line.startswith("        [ " + lua_string(title) + " ]"))
            self.assertIn("[[" + title + "|<nowiki>" + item["name"] + "</nowiki>]]", line)
            image = image_for(identity, self.data["illustrations"])
            if image:
                self.assertIn(pixel_image(image, 32, 32, title, item["name"]), line)
            else:
                self.assertNotIn("[[File:", line)
            if identity != "item-221":
                self.assertEqual(title, item["name"])
        for title in ("Finish Raft", "Sceetler", "Ranger Bhato", "Turnip", "Turnip (nature)", "item-14"):
            self.assertNotIn("[ " + lua_string(title) + " ]", registry)
        self.assertIn("{{Item|Turnip (item)}}", self.pages["Items"])
        self.assertNotIn("{{Item|Finish Raft", "\n".join(self.pages.values()))
        valid_titles = {locations[identity] for identity in items}
        for source in [*self.pages.values(), (ROOT / "docs" / "TEMPLATES.md").read_text(encoding="utf-8")]:
            for title in re.findall(r"\{\{Item\|([^{}|]+)(?:\||\}\})", source):
                self.assertIn(title, valid_titles)

    def test_item_name_only_fallback_and_literal_label_are_generated_not_guessed(self):
        for missing in (True, False):
            data = copy.deepcopy(self.data)
            if missing:
                data["illustrations"] = [image for image in data["illustrations"] if image.get("entity") != "item-14"]
            else:
                image_for("item-14", data["illustrations"]).update(
                    rights_status="pending", creator=None, sha256=None, rights_basis=None, rights_note=None)
            pages = build_pages(ROOT, data, self.catalog, self.details)
            registry = pages[ASSETS_TITLE].split("    items = {\n", 1)[1]
            self.assertNotIn("Item-14.png", registry)
            self.assertIn("[[Iron Hand Axe|<nowiki>Iron Hand Axe</nowiki>]]", registry)
        self.assertIn("{{Item|Iron Hand Axe}}", self.pages["Items"])
        self.assertEqual(self.pages["Items"].count('id="entity-item-'), 247)

    def test_actual_sources_compose_rows_and_keep_exact_owner_filters(self):
        readers = {title: text for title, text in self.pages.items() if title not in DISPLAY_TITLES}
        self.assertEqual(sum(text.count("{{Ware row\n") for text in readers.values()), 63)
        recipes = [row for row in self.data["entries"] if row["kind"] == "recipe"]
        self.assertEqual((len(recipes), len(recipe_groups(recipes))), (96, 77))
        self.assertEqual(sum(text.count("{{Recipe row\n") for text in readers.values()), 78)
        self.assertEqual(sum(text.count("{{Item|") for text in readers.values()), 1903)
        self.assertIn("|ap=<nowiki>1.2</nowiki>", self.pages["Grilled Turnip"])
        self.assertIn("in-place completion", self.pages["Finish Raft"])
        self.assertEqual(sum(text.count("Standard unit price: ") for text in readers.values()), 42)
        self.assertEqual(dependencies(self.pages["Template:Ware row"]), {"Template:Item"})
        self.assertEqual(dependencies(self.pages["Template:Item"]), {"Module:Display"})
        self.assertIn("Template:Recipe row", dependencies(self.pages["Simple Burn Remedy"]))
        self.assertNotIn("Template:Item", dependencies(self.pages["Random treasure"]))
        for reader in ("Items", "Category:Armor", "Plant harvesting", "Magus Clay"):
            self.assertIn(reader, stale_renderings(self.pages, ["Template:Item"], set()))
        self.assertIn("Campfire", stale_renderings(self.pages, ["Template:Recipe row"], set()))
        self.assertIn("Iron Hand Axe", stale_renderings(self.pages, ["Template:Ware row"], set()))

    def test_nested_named_arguments_leave_colon_views_visible(self):
        text = row_template("Ware row", {"item": "Iron Hand Axe", "price": "<noinclude>{{:Iron Hand Axe}}</noinclude>"})
        self.assertEqual(dependencies(text), {"Template:Ware row", "Iron Hand Axe"})
        from wiki_views import transclusions
        self.assertEqual(transclusions(text), [("Iron Hand Axe", ())])
        recipe = row_template("Recipe row", {
            "ingredients": "{{Item|Plant Fiber|quantity=4}}<br />{{Item|Log (Willow)|quantity=1}}",
            "conditions": "<nowiki>A | B = C {{not a template}}</nowiki>",
        })
        self.assertEqual(dependencies(recipe), {"Template:Recipe row", "Template:Item"})
        self.assertEqual(transclusions(recipe), [])
        self.assertEqual(transclusions("<pre>{{:Not an owner}}</pre><!--{{:Also not}}--><nowiki>{{:Nor this}}</nowiki>"), [])


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

    def test_independent_row_templates_still_follow_modules_and_precede_readers(self):
        pages = {**self.pages, "Template:Recipe row": "<tr><td>{{{ingredients|}}}</td></tr>", "Independent": "Plain text"}
        order = write_order(pages, pages)
        self.assertEqual(order[:2], [ASSETS_TITLE, "Module:Display"])
        self.assertLess(order.index("Template:Recipe row"), order.index("Independent"))

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

    def test_human_creature_template_blocks_new_illustrated_lists(self):
        pages = {**self.pages, "Template:Creature": "{{#invoke:Display|creature}}",
                 "Bestiary": "{{Creature|Sceetler}}", "Category:Scaalmyr faction": "{{Creature|Sceetler}}"}
        wiki = logged_in(FakeWiki({"Template:Creature": ("Human template", "Editor", "Keep this")}))
        report = self.run_sync(wiki, pages, apply=True)
        self.assertEqual(wiki.text("Template:Creature"), "Human template")
        self.assertEqual({row["title"] for row in report["blocked"]}, {"Bestiary", "Category:Scaalmyr faction"})


if __name__ == "__main__":
    unittest.main()
