import subprocess
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from check_publication import ALLOWED_FILES, audit_index, blob_errors, path_errors
from wiki_catalog import default_catalog


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)
        self.git("init", "--quiet")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args, data=None):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        ).stdout

    def stage(self, path, content):
        destination = self.repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        self.git("add", "--force", "--", path)

    def test_gitignore_allows_only_named_authored_files(self):
        (self.repo / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
        negatives = [
            "data.win", "DATA.WIN", "game.exe", "game.DLL", "a.ini", "A.INI",
            "sample.gml", "sample.GML", "Languages/English/Items.ini", "Saves/slot.json",
            "media/image.png", "media/sound.ogg", "media/movie.webm", "media/font.ttf",
            "dumps/functions.txt", "exports/data.json", "raw/notes.md",
            "research/notes.md", "UTMT/tool.exe", "UndertaleModTool/README.md",
            ".env", ".env.production", "LocalSettings.php", "db/state.sql",
            "uploads/page.png", "backups/wiki.sql.gz", "cert.pem", "private.key",
            "README.txt", "content/facts/unreviewed.json", "content/pages/Unreviewed.wiki",
            "docs/raw.txt", "tools/extra.py", ".github/workflows/unreviewed.yml",
            ".local/seed.xml", "deploy/LocalSettings.php", "deploy/.env",
            "deploy/secret.json", "tests/fixtures/raw.json",
            "content/images/Item-2.png", "content/pages/Item-2.png",
            "content/facts/illustrations-raw.json", "docs/Item-2.png", "private-images/Item-2.png",
            "Health-armor-1.png", "content/images/Health-armor-2.png", "tests/fixtures/Health-armor-3.png",
        ]
        positives = sorted(ALLOWED_FILES)
        result = self.git(
            "check-ignore", "--no-index", "-z", "--stdin",
            data=("\0".join(negatives + positives) + "\0").encode(),
        )
        ignored = set(result.decode().strip("\0").split("\0"))
        self.assertEqual(set(negatives), ignored)

    def test_staged_secret_cannot_hide_behind_clean_worktree(self):
        credential = "gh" + "p_" + "A" * 36
        self.stage("README.md", credential.encode())
        (self.repo / "README.md").write_text("Safe working copy.\n", encoding="utf-8")
        count, errors = audit_index(self.repo)
        self.assertEqual(count, 1)
        self.assertTrue(any("GitHub credential" in error for error in errors))
        self.assertFalse(any(credential in error for error in errors))

    def test_worktree_changes_are_not_mistaken_for_index(self):
        self.stage("README.md", b"Original authored documentation.\n")
        (self.repo / "README.md").write_bytes(b"\0not staged")
        self.assertEqual(audit_index(self.repo), (1, []))

    def test_force_added_asset_is_rejected(self):
        self.stage("Languages/English/Items.ini", b"[synthetic]\n")
        self.assertTrue(any("forbidden" in error for error in audit_index(self.repo)[1]))

    def test_allowed_name_cannot_disguise_binary_or_oversize_blob(self):
        for raw, expected in [
            (b"\x89PNG\r\n\x1a\n", "UTF-8"),
            (b"FORM\0data", "binary"),
            (b"x" * (ALLOWED_FILES["README.md"] + 1), "limit"),
        ]:
            with self.subTest(expected=expected):
                self.stage("README.md", raw)
                self.assertTrue(any(expected in error for error in audit_index(self.repo)[1]))

    def test_index_symlink_is_rejected_without_following_target(self):
        object_id = self.git("hash-object", "-w", "--stdin", data=b"outside-target").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", f"120000,{object_id},README.md")
        self.assertTrue(any("links/submodules" in error for error in audit_index(self.repo)[1]))

    def test_unmerged_index_is_rejected(self):
        object_id = self.git("hash-object", "-w", "--stdin", data=b"original").decode().strip()
        self.git("update-index", "--index-info", data=f"100644 {object_id} 1\tREADME.md\n".encode())
        self.assertTrue(any("conflict" in error for error in audit_index(self.repo)[1]))

    def test_empty_index_fails_explicitly(self):
        self.assertIn("empty", audit_index(self.repo)[1][0])

    def test_types_paths_and_names_are_restricted(self):
        for path, mode in [
            ("README.md", "160000"), ("README.md", "100755"),
            ("readme.md", "100644"), ("../README.md", "100644"),
            ("docs\\PROVENANCE.md", "100644"), ("docs/RAW_EXPORT.md", "100644"),
            ("deploy/LocalSettings.php", "100644"), (".env.local", "100644"),
        ]:
            with self.subTest(path=path, mode=mode):
                self.assertTrue(path_errors(path, mode))

    def test_literal_secret_patterns_are_not_real_secret_fixtures(self):
        samples = [
            "-----BEGIN " + "PRIVATE KEY-----",
            "AK" + "IA" + "A" * 16,
            "xox" + "b-" + "1" * 24,
            "sk_" + "live_" + "A" * 24,
            "https://" + "synthetic:synthetic@" + "example.invalid",
            "DB_" + "PASSWORD = '" + "generated-test-value" + "'",
            "C:" + "\\Users\\" + "Synthetic\\private",
            "gml_" + "Object_test_Create_0()",
        ]
        for text in samples:
            with self.subTest(pattern=text[:8]):
                self.assertTrue(blob_errors("README.md", text.encode()))

    def test_normal_security_documentation_is_not_flagged(self):
        text = (
            "# Publication policy\n"
            "Never commit passwords, tokens, LocalSettings.php, or data.win.\n"
            "Use a password file, not an API key in the command line.\n"
            "Secret configuration: read from the mounted file.\n"
            "MW_DB_PASSWORD_FILE=/run/secrets/MIRKLURK_DB_PASSWORD\n"
            "password: <provided-outside-git>\n"
        )
        self.assertEqual(blob_errors("README.md", text.encode()), [])

    def test_facts_blob_is_validated_from_index(self):
        self.stage("content/facts/game.json", b'{"unexpected":"raw export"}')
        self.assertTrue(any("invalid curated facts" in error for error in audit_index(self.repo)[1]))

    def test_supplemental_references_are_checked_against_staged_data(self):
        raw = (ROOT / "content" / "facts" / "game.json").read_bytes()
        self.stage("content/facts/game.json", raw)
        catalog = default_catalog(json.loads(raw))
        valid = json.dumps(catalog).encode()
        catalog["pages"][0]["entity"] = "not-a-curated-entity"
        self.stage("content/facts/catalog.json", json.dumps(catalog).encode())
        (self.repo / "content" / "facts" / "catalog.json").write_bytes(valid)
        errors = audit_index(self.repo)[1]
        self.assertTrue(any("catalog.json: invalid staged references" in error for error in errors))
        self.stage("content/facts/catalog.json", valid)
        self.assertEqual(audit_index(self.repo)[1], [])

    def test_supplemental_metadata_requires_a_valid_staged_base(self):
        self.stage("content/facts/entity_details.json", b'{"schema_version":1,"properties":[],"profiles":[]}')
        self.assertTrue(any("valid staged game.json is required" in error for error in audit_index(self.repo)[1]))

    def test_acquisition_references_use_staged_data_not_the_worktree(self):
        valid = (ROOT / "content" / "facts" / "acquisition.json").read_bytes()
        self.stage("content/facts/acquisition.json", valid)
        self.assertTrue(any("valid staged game.json and catalog.json are required" in error for error in audit_index(self.repo)[1]))
        for filename in ("game.json", "catalog.json"):
            self.stage("content/facts/" + filename, (ROOT / "content" / "facts" / filename).read_bytes())
        self.assertEqual(audit_index(self.repo)[1], [])
        invalid = json.loads(valid)
        invalid["sources"][0]["rows"][0]["item"] = "not-a-curated-item"
        self.stage("content/facts/acquisition.json", json.dumps(invalid).encode())
        (self.repo / "content" / "facts" / "acquisition.json").write_bytes(valid)
        self.assertTrue(any("acquisition.json: invalid staged references" in error for error in audit_index(self.repo)[1]))

    def test_acquisition_has_no_second_embedded_catalog_owner(self):
        catalog = json.loads((ROOT / "content" / "facts" / "catalog.json").read_bytes())
        catalog["acquisition"] = json.loads((ROOT / "content" / "facts" / "acquisition.json").read_bytes())
        self.stage("content/facts/game.json", (ROOT / "content" / "facts" / "game.json").read_bytes())
        self.stage("content/facts/catalog.json", json.dumps(catalog).encode())
        self.assertTrue(any("acquisition records must be stored only" in error for error in audit_index(self.repo)[1]))

    def test_all_repository_publication_files_pass_content_policy(self):
        for path in ALLOWED_FILES:
            with self.subTest(path=path):
                self.assertEqual(blob_errors(path, (ROOT / path).read_bytes()), [])


if __name__ == "__main__":
    unittest.main()
