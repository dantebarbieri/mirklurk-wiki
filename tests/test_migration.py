import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_wiki import build_xml
from plan_migration import main, plan_migration, read_snapshot
from wiki_data import DataError


class MigrationTests(unittest.TestCase):
    def test_live_edits_deletions_and_collisions_are_preserved(self):
        base = {
            "Same": "same", "Changed": "old", "Edited": "old", "Both": "old",
            "Deleted": "old", "Retired": "old", "Getting started": "old guidance",
        }
        current = {
            "Same": "same", "Changed": "old", "Edited": "live edit", "Both": "live edit",
            "Retired": "old", "Custom": "community page", "Collision": "unrelated",
            "Getting started": "live guidance",
        }
        desired = {
            "Same": "same", "Changed": "new", "Edited": "old", "Both": "new",
            "Deleted": "new", "New": "new", "Collision": "generated",
            "Getting started": "#REDIRECT [[Research policy]]\n",
        }
        actions = {row["title"]: row["action"] for row in plan_migration(base, current, desired)["pages"]}
        self.assertEqual(actions, {
            "Same": "unchanged", "Changed": "review-update", "Edited": "preserve-live",
            "Both": "conflict", "Deleted": "preserve-deletion", "Retired": "preserve-retired",
            "New": "create", "Custom": "preserve-unmanaged", "Collision": "conflict",
            "Getting started": "conflict",
        })
        self.assertNotIn("delete", actions.values())

    def test_empty_text_is_not_missing_and_report_contains_no_page_text(self):
        report = plan_migration({"Empty": ""}, {"Empty": ""}, {"Empty": "new private text"})
        row = report["pages"][0]
        self.assertEqual(row["action"], "review-update")
        self.assertIsNotNone(row["base_sha256"])
        self.assertNotIn("new private text", str(report))

    def test_snapshot_rejects_missing_or_suppressed_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.xml"
            valid = build_xml({"Title": "current"})
            path.write_bytes(valid)
            self.assertEqual(read_snapshot(path), {"Title": "current"})
            for invalid in (
                b"<unexpected/>",
                valid.replace(b"<text ", b'<text deleted="deleted" '),
                valid.replace(b"<revision>", b"<unused>").replace(b"</revision>", b"</unused>"),
            ):
                path.write_bytes(invalid)
                with self.assertRaises(DataError):
                    read_snapshot(path)

    def test_planner_is_deterministic_and_refuses_output_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.xml"
            output = Path(folder) / "report.json"
            path.write_bytes(build_xml({"Old": "same", "Getting_started": "guide"}))
            args = ["--base-export", str(path), "--current-export", str(path),
                    "--desired-export", str(path), "--output", str(output)]
            self.assertEqual(main(args), 0)
            contents = output.read_bytes()
            self.assertEqual(main(args), 1)
            self.assertEqual(output.read_bytes(), contents)
            self.assertEqual(read_snapshot(path)["Getting started"], "guide")


if __name__ == "__main__":
    unittest.main()
