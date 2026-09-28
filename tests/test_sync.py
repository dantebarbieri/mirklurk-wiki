import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import sync_wiki
from sync_wiki import (
    Api, ApiError, SyncError, automation_owned, links, normalize, owners, plan_changes, stale_renderings,
    sync, write_order,
)
from wiki_details import load_publication_inputs
from wiki_render import build_pages


PASSWORD = "-".join(["synthetic", "bot", "login", "value"])


class FakeWiki:
    """In-memory stand-in for the parts of the MediaWiki Action API the sync uses."""

    def __init__(self, pages=None, files=(), groups=None):
        self.revisions = {}
        self.clock = 0
        self.next_revid = 100
        self.files = set(files)
        self.groups = dict(groups or {})
        self.calls = []
        self.failures = {}
        self.concurrent = {}
        self.merge = False
        self.username = None
        self.token = None
        self.touches = []
        for title, (text, user, comment) in (pages or {}).items():
            self.store(title, text, user, comment)

    def now(self):
        self.clock += 1
        return (datetime(2026, 9, 28) + timedelta(seconds=self.clock)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def store(self, title, text, user, comment):
        self.next_revid += 1
        stamp = self.now()
        self.revisions.setdefault(title, []).append(
            {"revid": self.next_revid, "user": user, "comment": comment, "text": text, "timestamp": stamp})
        return self.next_revid

    def text(self, title):
        return self.revisions[title][-1]["text"]

    def csrf(self):
        return "token"

    def call(self, params, post=False, retry=True):
        self.calls.append(dict(params))
        if params["action"] == "query" and "revisions" in params.get("prop", ""):
            titles = params["titles"].split("|")
            assert len(titles) <= sync_wiki.BATCH
            pages = []
            for title in titles:
                namespace = 14 if title.startswith("Category:") else 0
                if title not in self.revisions:
                    pages.append({"ns": namespace, "title": title, "missing": True})
                    continue
                revision = self.revisions[title][-1]
                pages.append({"ns": namespace, "title": title, "revisions": [{
                    "revid": revision["revid"], "user": revision["user"], "comment": revision["comment"],
                    "timestamp": revision["timestamp"],
                    "slots": {"main": {"contentmodel": "wikitext", "content": revision["text"]}},
                }]})
            return {"query": {"pages": pages}}
        if params["action"] == "query" and params.get("list") == "users":
            return {"query": {"users": [{"name": name, "groups": ["*", "user", *self.groups.get(name, [])]}
                                        for name in params["ususers"].split("|")]}}
        if params["action"] == "query" and params.get("prop") == "imageinfo":
            return {"query": {"pages": [
                {"ns": 6, "title": title, "imagerepository": "local" if title in self.files else ""}
                for title in params["titles"].split("|")]}}
        if params["action"] == "edit":
            return self.edit(params)
        raise AssertionError(f"Unexpected API call: {params}")

    def edit(self, params):
        title = params["title"]
        failures = self.failures.get(title)
        if failures:
            raise ApiError(failures.pop(0), "synthetic failure")
        if title in self.concurrent and "text" in params:
            self.store(title, *self.concurrent.pop(title))
        exists = title in self.revisions
        if params.get("createonly") and exists:
            raise ApiError("articleexists")
        if params.get("nocreate") and not exists:
            raise ApiError("missingtitle")
        latest = self.revisions[title][-1] if exists else None
        if "undo" in params:
            restored = next(row for row in self.revisions[title] if row["revid"] == int(params["undoafter"]))
            revid = self.store(title, restored["text"], self.username, params["summary"])
            return {"edit": {"result": "Success", "oldrevid": latest["revid"], "newrevid": revid}}
        if "appendtext" in params:
            self.touches.append(title)
            return {"edit": {"result": "Success", "nochange": True}}
        if "baserevid" in params and int(params["baserevid"]) != latest["revid"] and not self.merge:
            raise ApiError("editconflict")
        if exists and normalize(latest["text"]) == normalize(params["text"]):
            return {"edit": {"result": "Success", "nochange": True}}
        revid = self.store(title, normalize(params["text"]), self.username, params["summary"])
        return {"edit": {"result": "Success", "oldrevid": latest["revid"] if latest else 0, "newrevid": revid}}


def logged_in(wiki, username="MirkLurkBot"):
    wiki.username = username
    return wiki


def edits(wiki):
    return [(call["title"], "appendtext" in call) for call in wiki.calls if call["action"] == "edit"]


class OwnershipAndPlanTests(unittest.TestCase):
    accounts = {"WikiAdmin", "MirkLurkBot"}

    def test_normalization_matches_mediawiki_trailing_whitespace_rules_only(self):
        self.assertEqual(normalize("Text\r\nmore \n\n\t"), "Text\nmore")
        self.assertNotEqual(normalize("Text  more"), normalize("Text more"))
        self.assertNotEqual(normalize(" leading"), normalize("leading"))

    def test_only_recognized_automation_revisions_can_be_replaced(self):
        owned = [
            {"user": "WikiAdmin", "comment": "native-publication/v1:c2ad2911"},
            {"user": "WikiAdmin", "comment": "Publish reviewed wiki update 5a61765; preserve history"},
            {"user": "WikiAdmin", "comment": "repo-sync: aa2cc2c"},
            {"user": "MirkLurkBot", "comment": "repo-sync: aa2cc2c"},
            {"user": "imported>Repository seed", "comment": "Original repository seed; evidence and rights caveats apply."},
            {"user": "MediaWiki default", "comment": ""},
            {"user": "Maintenance script", "comment": "anything"},
        ]
        people = [
            {"user": "WikiAdmin", "comment": "Fix a typo"},
            {"user": "DanteB", "comment": "repo-sync: pretending"},
            {"user": "MirkLurkBot", "comment": "manual cleanup"},
            {"user": "", "comment": "repo-sync: hidden user"},
            {"comment": "repo-sync: missing user"},
        ]
        for revision in owned:
            with self.subTest(revision=revision):
                self.assertTrue(automation_owned(revision, self.accounts))
        for revision in people:
            with self.subTest(revision=revision):
                self.assertFalse(automation_owned(revision, self.accounts))

    def test_plan_creates_updates_and_never_replaces_a_person_edit(self):
        live = {
            "Absent": None,
            "Same": {"revid": 1, "user": "DanteB", "comment": "Edited", "text": "Same text\n", "timestamp": ""},
            "Ours": {"revid": 2, "user": "WikiAdmin", "comment": "repo-sync: old", "text": "Old", "timestamp": ""},
            "Theirs": {"revid": 3, "user": "DanteB", "comment": "Better wording", "text": "Mine", "timestamp": ""},
            "Hidden": {"revid": 4, "user": "WikiAdmin", "comment": "repo-sync: x", "text": None, "timestamp": ""},
        }
        pages = {"Absent": "New", "Same": "Same text", "Ours": "New", "Theirs": "New", "Hidden": "New"}
        self.assertEqual(plan_changes(pages, live, self.accounts), {
            "Absent": "create", "Same": "unchanged", "Ours": "update", "Theirs": "skip", "Hidden": "skip",
        })

    def test_owners_precede_the_pages_that_transclude_them(self):
        pages = {
            "A merchant": "{{:Zinc item|view=price}} {{:Bronze item}}",
            "Bronze item": "<onlyinclude>1</onlyinclude> {{:Zinc item}}",
            "Zinc item": "<onlyinclude>2</onlyinclude>",
            "Cycle one": "{{:Cycle two}}", "Cycle two": "{{:Cycle one}}",
        }
        order = write_order(pages, pages)
        self.assertLess(order.index("Zinc item"), order.index("Bronze item"))
        self.assertLess(order.index("Bronze item"), order.index("A merchant"))
        self.assertEqual(sorted(order), sorted(pages))
        self.assertEqual(order, write_order(reversed(list(pages)), pages))

    def test_link_and_owner_extraction(self):
        text = ("[[Turnip (item)|turnips]] [[:Category:Foods]] [[Category:Items]] [[File:Turnip.png|20px]] "
                "[[Longbow_(Cypress)#Stats]] {{:Ranger Bhato|view=offers|item=item-105}} {{:copper Coin}}")
        self.assertEqual(links(text), {"Turnip (item)", "Category:Foods", "File:Turnip.png", "Longbow (Cypress)"})
        self.assertEqual(owners(text), {"Ranger Bhato", "Copper Coin"})

    def test_stale_renderings_follow_write_order(self):
        texts = {
            "Merchant": "{{:Item|view=price}}", "Guide": "See [[New page]].", "New page": "[[Guide]]",
            "Early": "[[Late new page]]", "Late new page": "x", "Unrelated": "[[Item]]", "Item": "price",
        }
        written = ["Item", "Early", "Late new page", "New page"]
        stale = stale_renderings(texts, written, created={"New page", "Late new page"})
        self.assertEqual(stale, ["Early", "Guide", "Merchant"])

class SyncTests(unittest.TestCase):
    def test_dry_run_reads_but_never_writes(self):
        wiki = FakeWiki({"Old": ("Old", "WikiAdmin", "repo-sync: a")}, files={"File:Pic.png"})
        report = sync(wiki, {"Old": "New", "Fresh": "[[File:Pic.png]] [[File:Gone.png]]"}, "repo-sync: b", log=lambda _: None)
        self.assertEqual(edits(wiki), [])
        self.assertEqual((report["create"], report["update"]), (["Fresh"], ["Old"]))
        self.assertEqual(report["missing_files"], ["File:Gone.png"])
        self.assertEqual(wiki.text("Old"), "Old")

    def test_apply_writes_in_dependency_order_with_conflict_guards(self):
        wiki = logged_in(FakeWiki({
            "Merchant": ("{{:Item|view=price}}", "WikiAdmin", "native-publication/v1:x"),
            "Item": ("old price", "WikiAdmin", "native-publication/v1:y"),
            "Talk about it": ("Mine", "DanteB", "Personal note"),
        }))
        pages = {"Merchant": "{{:Item|view=price}} {{:New item}}", "Item": "new price",
                 "New item": "fresh", "Talk about it": "Generated"}
        report = sync(wiki, pages, "repo-sync: abc", apply=True, log=lambda _: None)
        writes = [call for call in wiki.calls if call["action"] == "edit" and "text" in call]
        self.assertEqual([call["title"] for call in writes], ["Item", "New item", "Merchant"])
        self.assertEqual(writes[1]["createonly"], "1")
        self.assertEqual({call["nocreate"] for call in (writes[0], writes[2])}, {"1"})
        self.assertTrue(all(call["baserevid"] for call in (writes[0], writes[2])))
        self.assertTrue(all(call["summary"] == "repo-sync: abc" and call["bot"] == "1" and call["assert"] == "user"
                            for call in writes))
        self.assertEqual(wiki.text("Talk about it"), "Mine")
        self.assertEqual([row["title"] for row in report["skipped"]], ["Talk about it"])
        self.assertEqual((report["created"], report["updated"]), (["New item"], ["Item", "Merchant"]))
        self.assertEqual((report["errors"], report["unverified"], report["conflicts"]), ([], [], []))

    def test_dependents_of_changed_owners_are_refreshed_but_person_edits_are_not_touched(self):
        wiki = logged_in(FakeWiki({
            "Item": ("old", "WikiAdmin", "repo-sync: 1"),
            "Seller": ("{{:Item}}", "WikiAdmin", "repo-sync: 1"),
            "Fan page": ("{{:Item}} and my notes", "DanteB", "Notes"),
            "Index": ("[[Brand new]]", "WikiAdmin", "repo-sync: 1"),
        }))
        pages = {"Item": "new", "Seller": "{{:Item}}", "Fan page": "{{:Item}}", "Index": "[[Brand new]]",
                 "Brand new": "hello"}
        report = sync(wiki, pages, "repo-sync: 2", apply=True, log=lambda _: None)
        self.assertEqual(sorted(report["refreshed"]), ["Index", "Seller"])
        self.assertEqual(sorted(wiki.touches), ["Index", "Seller"])
        self.assertNotIn("Fan page", wiki.touches)

    def test_second_run_is_a_no_op(self):
        wiki = logged_in(FakeWiki({"Item": ("old", "WikiAdmin", "repo-sync: 1")}))
        pages = {"Item": "new", "Other": "[[Item]]"}
        sync(wiki, pages, "repo-sync: 2", apply=True, log=lambda _: None)
        wiki.calls.clear()
        report = sync(wiki, pages, "repo-sync: 3", apply=True, log=lambda _: None)
        self.assertEqual(edits(wiki), [])
        self.assertEqual(report["counts"], {"create": 0, "update": 0, "unchanged": 2, "skip": 0})

    def test_conflicts_rate_limits_and_errors_are_reported_without_stopping(self):
        wiki = logged_in(FakeWiki({
            "Busy": ("old", "WikiAdmin", "repo-sync: 1"), "Slow": ("old", "WikiAdmin", "repo-sync: 1"),
            "Locked": ("old", "WikiAdmin", "repo-sync: 1"),
        }))
        wiki.failures = {"Busy": ["editconflict"], "Slow": ["ratelimited", "ratelimited"], "Locked": ["protectedpage"]}
        pages = {"Busy": "new", "Slow": "new", "Locked": "new", "Fine": "new"}
        with mock.patch.object(sync_wiki.time, "sleep") as sleep:
            report = sync(wiki, pages, "repo-sync: 2", apply=True, log=lambda _: None)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual([row["title"] for row in report["conflicts"]], ["Busy"])
        self.assertEqual([row["title"] for row in report["errors"]], ["Locked"])
        self.assertEqual(sorted(report["created"] + report["updated"]), ["Fine", "Slow"])

    def test_merged_concurrent_edit_is_undone_and_then_left_alone(self):
        wiki = logged_in(FakeWiki({"Busy": ("old", "WikiAdmin", "repo-sync: 1")}))
        wiki.merge = True
        wiki.concurrent = {"Busy": ("old, with a person's fix", "DanteB", "Fix")}
        report = sync(wiki, {"Busy": "new"}, "repo-sync: 2", apply=True, log=lambda _: None)
        self.assertEqual([row["title"] for row in report["conflicts"]], ["Busy"])
        self.assertEqual(report["updated"], [])
        self.assertEqual(wiki.text("Busy"), "old, with a person's fix")
        self.assertFalse(wiki.revisions["Busy"][-1]["comment"].startswith("repo-sync:"))
        later = sync(wiki, {"Busy": "new"}, "repo-sync: 3", apply=True, log=lambda _: None)
        self.assertEqual([row["title"] for row in later["skipped"]], ["Busy"])
        self.assertEqual(wiki.text("Busy"), "old, with a person's fix")

    def test_bot_group_edits_are_recognized_without_logging_in(self):
        wiki = FakeWiki({"Page": ("old", "MirkLurkBot", "repo-sync: 1"),
                         "Mine": ("x", "DanteB", "repo-sync: typed by hand")}, groups={"MirkLurkBot": ["bot"]})
        report = sync(wiki, {"Page": "new", "Mine": "y"}, "repo-sync: 2", log=lambda _: None)
        self.assertEqual(report["update"], ["Page"])
        self.assertEqual([row["title"] for row in report["skipped"]], ["Mine"])

    def test_preview_lists_the_pages_a_publish_would_re_render(self):
        wiki = logged_in(FakeWiki({"Seller": ("{{:Item}}", "WikiAdmin", "repo-sync: 1"),
                                   "Fan page": ("{{:Item}} notes", "DanteB", "Notes"),
                                   "Item": ("price", "WikiAdmin", "repo-sync: 1")}))
        pages = {"Seller": "{{:Item}}", "Fan page": "{{:Item}}", "Item": "new price"}
        preview = sync(wiki, pages, "repo-sync: 2", log=lambda _: None)
        self.assertEqual((preview["refresh"], wiki.touches), (["Seller"], []))
        report = sync(wiki, pages, "repo-sync: 2", apply=True, log=lambda _: None)
        self.assertEqual((report["refreshed"], wiki.touches), (["Seller"], ["Seller"]))
        self.assertEqual(sync(wiki, pages, "repo-sync: 3", apply=True, log=lambda _: None)["refreshed"], [])

    def test_read_only_wiki_stops_the_run(self):
        wiki = logged_in(FakeWiki({"A": ("old", "WikiAdmin", "repo-sync: 1"), "B": ("old", "WikiAdmin", "repo-sync: 1")}))
        wiki.failures = {"A": ["readonly"]}
        with self.assertRaisesRegex(SyncError, "read-only"):
            sync(wiki, {"A": "new", "B": "new"}, "repo-sync: 2", apply=True, log=lambda _: None)
        self.assertEqual(wiki.text("B"), "old")

    def test_mismatched_saved_text_is_flagged(self):
        wiki = logged_in(FakeWiki({"A": ("old", "WikiAdmin", "repo-sync: 1")}))
        original = wiki.edit

        def transforming_edit(params):
            if "text" in params:
                params = dict(params, text=params["text"] + " ~~transformed~~")
            return original(params)

        wiki.edit = transforming_edit
        report = sync(wiki, {"A": "new"}, "repo-sync: 2", apply=True, log=lambda _: None)
        self.assertEqual(report["unverified"], ["A"])

    def test_guards_on_summary_login_and_titles(self):
        wiki = FakeWiki()
        with self.assertRaisesRegex(SyncError, "repo-sync:"):
            sync(wiki, {"A": "x"}, "Manual summary")
        with self.assertRaisesRegex(SyncError, "Log in"):
            sync(wiki, {"A": "x"}, "repo-sync: 1", apply=True)
        with self.assertRaisesRegex(SyncError, "normalized"):
            sync(wiki, {"lower_case": "x"}, "repo-sync: 1")
        with self.assertRaisesRegex(SyncError, "adopted"):
            sync(wiki, {"A": "x"}, "repo-sync: 1", adopt=["Not generated"])

    def test_adopting_a_person_edit_hands_the_page_back_to_the_sync(self):
        wiki = logged_in(FakeWiki({"Price": ("Ported wording", "DanteB", "Clarify"),
                                   "Other": ("Mine", "DanteB", "Mine")}))
        pages = {"Price": "Ported wording, generated", "Other": "Generated"}
        report = sync(wiki, pages, "repo-sync: 2", apply=True, log=lambda _: None, adopt=["price"])
        self.assertEqual(report["updated"], ["Price"])
        self.assertEqual([row["title"] for row in report["skipped"]], ["Other"])
        self.assertEqual(wiki.text("Other"), "Mine")
        later = sync(wiki, dict(pages, Price="Next release"), "repo-sync: 3", apply=True, log=lambda _: None)
        self.assertEqual(later["updated"], ["Price"])


class ResponseHandling(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ApiClientTests(unittest.TestCase):
    def opener(self, *responses):
        opener = mock.Mock()
        opener.open.side_effect = [
            response if isinstance(response, Exception) else ResponseHandling(json.dumps(response).encode())
            for response in responses
        ]
        return opener

    def test_requires_an_api_php_url(self):
        for url in ("ftp://wiki.example.org/api.php", "https://wiki.example.org/index.php", "wiki.example.org/api.php"):
            with self.subTest(url=url), self.assertRaises(SyncError):
                Api(url)

    def test_errors_are_raised_with_their_code(self):
        api = Api("https://wiki.example.org/api.php", opener=self.opener(
            {"errors": [{"code": "editconflict", "text": "Edit conflict."}]}))
        with self.assertRaises(ApiError) as caught:
            api.call({"action": "edit"}, post=True, retry=False)
        self.assertEqual(caught.exception.code, "editconflict")

    def test_reads_retry_transient_failures_but_writes_do_not(self):
        failure = urllib.error.HTTPError("https://wiki.example.org/api.php", 503, "busy", {}, None)
        api = Api("https://wiki.example.org/api.php", opener=self.opener(failure, {"query": {}}))
        with mock.patch.object(sync_wiki.time, "sleep"):
            self.assertEqual(api.call({"action": "query"}), {"query": {}})
        api = Api("https://wiki.example.org/api.php", opener=self.opener(failure, {"edit": {}}))
        with self.assertRaises(ApiError):
            api.call({"action": "edit"}, post=True, retry=False)

    def test_login_checks_rights_and_never_echoes_the_password(self):
        api = Api("https://wiki.example.org/api.php", opener=self.opener(
            {"query": {"tokens": {"logintoken": "t"}}},
            {"login": {"result": "Failed", "reason": "Incorrect password"}},
        ))
        with self.assertRaises(SyncError) as caught:
            api.login("MirkLurkBot@repo-sync", PASSWORD)
        self.assertNotIn(PASSWORD, str(caught.exception))
        api = Api("https://wiki.example.org/api.php", opener=self.opener(
            {"query": {"tokens": {"logintoken": "t"}}},
            {"login": {"result": "Success", "lgusername": "MirkLurkBot"}},
            {"query": {"userinfo": {"rights": ["read", "edit"]}}},
        ))
        with self.assertRaisesRegex(SyncError, "createpage"):
            api.login("MirkLurkBot@repo-sync", PASSWORD)


class CommandLineTests(unittest.TestCase):
    def run_main(self, argv, environment):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            code = sync_wiki.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_apply_requires_credentials_and_an_api_url(self):
        code, _, stderr = self.run_main(["--apply", "--api", "https://wiki.example.org/api.php"], {})
        self.assertEqual(code, 2)
        self.assertIn("MIRKLURK_BOT_PASSWORD", stderr)
        with self.assertRaises(SystemExit):
            self.run_main([], {})

    def test_github_summary_annotations_and_exit_status(self):
        wiki = FakeWiki({"Items": ("Mine", "DanteB", "Notes")})
        with tempfile.TemporaryDirectory() as folder:
            summary = Path(folder) / "summary.md"
            report = Path(folder) / "report.json"
            with mock.patch.object(sync_wiki, "Api", return_value=wiki), \
                    mock.patch.object(sync_wiki, "build_pages", return_value={"Items": "Generated"}):
                code, stdout, _ = self.run_main(
                    ["--summary", "repo-sync: test", "--report", str(report)],
                    {"MIRKLURK_API_URL": "https://wiki.example.org/api.php", "GITHUB_STEP_SUMMARY": str(summary)})
            self.assertEqual(code, 0)
            self.assertIn("::warning title=Not overwritten::Items was last edited by DanteB", stdout)
            self.assertIn("| 0 | 0 | 0 | 1 |", summary.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["skipped"][0]["title"], "Items")


class RealCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = build_pages(ROOT, *load_publication_inputs(ROOT))

    def test_generated_titles_are_normalized_main_or_category_pages(self):
        for title in self.pages:
            self.assertEqual(sync_wiki.title_key(title), title)
            self.assertTrue(":" not in title.split(" (")[0] or title.startswith("Category:"), title)

    def test_every_consumer_ends_up_rendered_after_its_owners(self):
        order = write_order(self.pages, self.pages)
        position = {title: index for index, title in enumerate(order)}
        refreshed = set(stale_renderings(self.pages, order, created=set(self.pages)))
        edges = [(owner, title) for title, text in self.pages.items() for owner in owners(text) - {title}]
        self.assertTrue(edges)
        early = {consumer for owner, consumer in edges if position[owner] > position[consumer]}
        # Only the mutual merchant/item views force an early save; everything else is ordered.
        self.assertTrue(early)
        self.assertLess(len(early), len(self.pages) // 5)
        for owner, consumer in edges:
            self.assertIn(owner, self.pages, f"{consumer} includes a page outside the release")
        self.assertLessEqual(early, refreshed)


if __name__ == "__main__":
    unittest.main()
