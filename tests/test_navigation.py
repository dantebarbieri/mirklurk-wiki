import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from check_publication import ALLOWED_FILES, blob_errors, path_errors
from smoke_navigation import SIDEBAR_LINKS, SIDEBAR_TITLE, install_sidebar_fixture, sidebar_text
from sync_wiki import markdown, sync
from wiki_data import DataError
from wiki_details import load_publication_inputs
from wiki_display import page_namespace
from wiki_render import build_pages


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = build_pages(ROOT, *load_publication_inputs(ROOT))

    def test_exact_native_sidebar_and_message_conventions(self):
        lines = sidebar_text().splitlines()
        self.assertEqual([line for line in lines if not line.startswith("**")],
                         ["* navigation", "* Contribute", "* SEARCH", "* TOOLBOX", "* LANGUAGES"])
        self.assertEqual([line[3:] for line in lines if line.startswith("** ")], [
            "mainpage|mainpage-description", "Items|Items", "Bestiary|Bestiary", "NPCs|NPCs",
            "Merchants|Merchants", "Crafting|Crafting and workstations",
            "Game mechanics|Survival and game mechanics", "randompage-url|randompage",
            "Help:Editing|Editing help", "recentchanges-url|recentchanges",
        ])
        self.assertNotIn("://", sidebar_text())
        self.assertNotIn("index.php", sidebar_text())
        self.assertNotIn("[[", sidebar_text())

    def test_destinations_are_canonical_except_explicit_help_dependency(self):
        for title in SIDEBAR_LINKS.values():
            if title.startswith("Special:") or title == "Help:Editing":
                continue
            with self.subTest(title=title):
                self.assertIn(title, self.pages)
                self.assertNotIn("#REDIRECT", self.pages[title].upper())
        self.assertIn("[[Inventory crafting]]", self.pages["Crafting"])
        self.assertIn("survival", self.pages["Game mechanics"])
        documentation = (ROOT / "docs" / "PUBLISHING.md").read_text(encoding="utf-8")
        self.assertIn("Help:Editing", documentation)
        self.assertIn("before activating", documentation)

    def test_interface_is_not_generated_imported_synced_or_adoptable(self):
        self.assertNotIn(SIDEBAR_TITLE, self.pages)
        with self.assertRaises(DataError):
            page_namespace(SIDEBAR_TITLE)
        api = mock.Mock()
        api.username = "Publisher"
        with self.assertRaises(DataError):
            sync(api, {SIDEBAR_TITLE: sidebar_text()}, "repo-sync: test", apply=True)
        with self.assertRaisesRegex(RuntimeError, "Only generated pages can be adopted"):
            sync(api, {"Items": "An article"}, "repo-sync: test", adopt=[SIDEBAR_TITLE])
        api.call.assert_not_called()
        api.csrf.assert_not_called()

    def test_artifact_has_exact_path_and_small_size_budget(self):
        path = "content/interface/Sidebar.wiki"
        self.assertEqual(ALLOWED_FILES[path], 2 * 1024)
        self.assertEqual(path_errors(path, "100644"), [])
        self.assertEqual(blob_errors(path, sidebar_text().encode()), [])
        self.assertTrue(blob_errors(path, b"x" * (2 * 1024 + 1)))
        self.assertTrue(path_errors("content/interface/Common.js", "100644"))
        self.assertTrue(path_errors("content/interface/Unreviewed.wiki", "100644"))

    def test_sync_report_does_not_claim_interface_publication(self):
        report = {"mode": "dry-run", "summary": "repo-sync: test",
                  "counts": dict(create=0, update=0, unchanged=0, skip=0)}
        for key in ("refresh", "skipped", "conflicts", "blocked", "errors", "unverified",
                    "adopt_pending", "create", "update", "created", "updated", "refreshed", "missing_files"):
            report[key] = []
        for mode in ("dry-run", "apply"):
            report["mode"] = mode
            text = markdown(report, "https://wiki.example.invalid/api.php")
            self.assertIn("MediaWiki:Sidebar is not published by this sync", text)
            self.assertIn("content/interface/Sidebar.wiki", text)

    def test_fixture_refuses_live_wiki_or_existing_sidebar(self):
        api = mock.Mock()
        with self.assertRaisesRegex(RuntimeError, "localhost"):
            install_sidebar_fixture(api, "https://wiki.example.invalid", "token")
        api.assert_not_called()
        api.side_effect = [
            {"query": {"userinfo": {"rights": ["editinterface"]}}},
            {"query": {"pages": {"1": {"title": SIDEBAR_TITLE}, "-1": {"title": "Help:Editing", "missing": ""}}}},
        ]
        with self.assertRaisesRegex(RuntimeError, "overwrite"):
            install_sidebar_fixture(api, "http://localhost:8080", "token")
        self.assertTrue(all(call.args[0]["action"] == "query" for call in api.call_args_list))


if __name__ == "__main__":
    unittest.main()
