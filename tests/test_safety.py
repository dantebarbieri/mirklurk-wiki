import subprocess
import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from check_publication import ALLOWED_FILES, audit_index, blob_errors, path_errors
from wiki_catalog import default_catalog
from smoke_deploy import BRANDING_IMAGES, branding_paths, smoke_branding


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.base = "https://wiki.example.invalid"
        self.paths = branding_paths()
        self.html = (
            f'<link rel="icon" href="{self.paths["MW_FAVICON_URL"]}">'
            f'<img class="mw-logo-icon" src="{self.paths["MW_LOGO_ICON_URL"]}" width="50" height="50">'
        )
        self.payloads = {
            self.base + self.paths[variable]: b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + struct.pack(">II", size, size)
            for variable, (_, size, _) in BRANDING_IMAGES.items()
        }
        self.hashes = {
            filename: hashlib.sha256(self.payloads[self.base + self.paths[variable]]).hexdigest()
            for variable, (filename, _, _) in BRANDING_IMAGES.items()
        }
        self.api = lambda params: {"query": {"general": {"logo": self.paths["MW_LOGO_URL"]}}}
        self.mime = "image/png"

    def open_media(self, url, timeout):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers.get_content_type.return_value = self.mime
        response.read.return_value = self.payloads[url] if url in self.payloads else self.html.encode()
        return response

    def check_branding(self):
        smoke_branding(self.api, self.base, self.paths, self.hashes, self.open_media)

    def test_configured_branding_markup_and_images(self):
        self.check_branding()

    def test_wrong_logo_or_favicon_markup_is_rejected(self):
        original = self.html
        for old, new in [
            (self.paths["MW_LOGO_ICON_URL"], "/wrong.png"),
            (self.paths["MW_FAVICON_URL"], "/wrong.png"),
            ('width="50"', 'width="256"'),
            ('class="mw-logo-icon"', 'class="unrelated"'),
        ]:
            with self.subTest(old=old):
                self.html = original.replace(old, new)
                with self.assertRaises(RuntimeError):
                    self.check_branding()

    def test_wrong_legacy_logo_is_rejected(self):
        self.api = lambda params: {"query": {"general": {"logo": self.paths["MW_LOGO_ICON_URL"]}}}
        with self.assertRaisesRegex(RuntimeError, "legacy logo"):
            self.check_branding()

    def test_wrong_branding_bytes_or_mime_are_rejected(self):
        for variable in BRANDING_IMAGES:
            url = self.base + self.paths[variable]
            original = self.payloads[url]
            self.payloads[url] += b"changed"
            with self.subTest(variable=variable), self.assertRaisesRegex(RuntimeError, "imported bytes"):
                self.check_branding()
            self.payloads[url] = original
        self.mime = "text/html"
        with self.assertRaisesRegex(RuntimeError, "readable as PNG"):
            self.check_branding()


class PublicationTests(unittest.TestCase):
    def test_ci_checks_every_change_and_publishes_main_only_after_the_smoke(self):
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        self.assertIn("  push:\n    branches: [main]\n  pull_request:\n  workflow_dispatch:\n", workflow)
        self.assertIn("group: ${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.run_id || github.ref }}", workflow)
        self.assertIn("  queue: max\n", workflow)
        self.assertNotIn("cancel-in-progress", workflow)
        publication, rest = workflow.split("\njobs:\n", 1)[1].split("  docker-smoke:\n", 1)
        smoke, rest = rest.split("  preview:\n", 1)
        preview, publish = rest.split("  publish:\n", 1)
        self.assertNotIn("\n    if:", publication + smoke)
        self.assertNotIn("cargo_prototype", workflow)
        self.assertNotIn("cargo-prototype.yml", workflow)
        self.assertIn("python3 -m unittest discover -s tests -v", publication)
        self.assertIn("php tests/test_runtime.php", publication)
        self.assertIn("needs: publication", smoke)
        self.assertIn("    timeout-minutes: 30\n", smoke)
        self.assertIn("run: python3 tools/smoke_deploy.py --run\n", smoke)
        self.assertIn("github.event.pull_request.head.sha || github.sha", smoke)
        self.assertIn("if: github.event_name == 'pull_request'", preview)
        self.assertIn("continue-on-error: true", preview)
        self.assertIn("python3 tools/sync_wiki.py\n", preview)
        self.assertNotIn("secrets.", preview)
        self.assertIn("if: github.event_name != 'pull_request' && github.ref == 'refs/heads/main'", publish)
        self.assertIn("needs: [publication, docker-smoke]", publish)
        self.assertIn("python3 tools/sync_wiki.py --apply --adopt \"$ADOPT\"\n", publish)
        self.assertIn("ADOPT: ${{ inputs.adopt }}", publish)
        self.assertIn("MIRKLURK_BOT_PASSWORD: ${{ secrets.MIRKLURK_BOT_PASSWORD }}", publish)
        self.assertEqual(workflow.count("secrets."), 2)
        # Dispatch input reaches the shell only through a quoted environment variable.
        self.assertFalse(any("${{ inputs." in line for line in workflow.splitlines() if "run:" in line or "python3" in line))
        prototype_workflow = (ROOT / ".github" / "workflows" / "cargo-prototype.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read", prototype_workflow)
        self.assertNotIn("secrets.", prototype_workflow)
        self.assertNotIn("sync_wiki.py", prototype_workflow)
        self.assertIn("python3 tools/prototype_cargo.py --run --artifacts", prototype_workflow)
        self.assertNotIn("workflow_call:", prototype_workflow)
        self.assertIn("name: cargo-prototype", prototype_workflow)
        for required_check in ("publication", "docker-smoke"):
            self.assertNotIn(f"  {required_check}:", prototype_workflow)
            self.assertNotIn(f"name: {required_check}", prototype_workflow)

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
        catalog["acquisition"] = {}
        self.stage("content/facts/game.json", (ROOT / "content" / "facts" / "game.json").read_bytes())
        self.stage("content/facts/catalog.json", json.dumps(catalog).encode())
        self.assertTrue(any("acquisition records must be stored only" in error for error in audit_index(self.repo)[1]))

    def test_all_repository_publication_files_pass_content_policy(self):
        for path in ALLOWED_FILES:
            with self.subTest(path=path):
                self.assertEqual(blob_errors(path, (ROOT / path).read_bytes()), [])

    def test_complete_render_uses_staged_authors_and_generator(self):
        for path in ALLOWED_FILES:
            self.stage(path, (ROOT / path).read_bytes())
        self.assertEqual(audit_index(self.repo)[1], [])
        path = "content/pages/Main_Page.wiki"
        original = (ROOT / path).read_bytes()
        self.stage(path, original + b"\nMissing evidence ledger.\n")
        (self.repo / path).write_bytes(original)
        self.assertTrue(any("staged rendered publication failed" in error for error in audit_index(self.repo)[1]))
        self.stage(path, original)
        path = "tools/wiki_render.py"
        original = (ROOT / path).read_bytes()
        changed = original.replace(b'pages["Source provenance"] = "#REDIRECT [[Game mechanics]]\\n"',
                                   b'pages["Source provenance"] = "Old evidence ledger"')
        self.assertNotEqual(changed, original)
        self.stage(path, changed)
        (self.repo / path).write_bytes(original)
        self.assertTrue(any("staged rendered publication failed" in error for error in audit_index(self.repo)[1]))


if __name__ == "__main__":
    unittest.main()
