"""Audit Git's staged blobs, never substitute the working tree for publication."""

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from wiki_data import DataError, MAX_FACTS_BYTES, PAGE_FILES, RESEARCH_PAGE_FILES, parse_data
from wiki_catalog import MAX_CATALOG_BYTES, parse_catalog, validate_catalog
from wiki_acquisition import MAX_ACQUISITION_BYTES
from wiki_details import MAX_DETAILS_BYTES, MAX_ILLUSTRATIONS_BYTES, parse_details, parse_document, parse_illustrations, validate_coin_profiles


ALLOWED_FILES = {
    ".gitignore": 16 * 1024,
    ".gitattributes": 4 * 1024,
    ".dockerignore": 4 * 1024,
    "README.md": 32 * 1024,
    "CONTRIBUTING.md": 32 * 1024,
    "docs/PROVENANCE.md": 40 * 1024,
    "docs/IMPORTING.md": 32 * 1024,
    "docs/PUBLICATION.md": 32 * 1024,
    "docs/DEPLOYMENT.md": 32 * 1024,
    "docs/IMAGES.md": 32 * 1024,
    "content/facts/game.json": MAX_FACTS_BYTES,
    "content/facts/catalog.json": MAX_CATALOG_BYTES,
    "content/facts/entity_details.json": MAX_DETAILS_BYTES,
    "content/facts/illustrations.json": MAX_ILLUSTRATIONS_BYTES,
    "content/facts/acquisition.json": MAX_ACQUISITION_BYTES,
    "content/pages/NPCs.wiki": 32 * 1024,
    "tools/check_publication.py": 32 * 1024,
    "tools/wiki_data.py": 32 * 1024,
    "tools/wiki_catalog.py": 40 * 1024,
    "tools/wiki_details.py": 32 * 1024,
    "tools/wiki_render.py": 96 * 1024,
    "tools/wiki_views.py": 16 * 1024,
    "tools/wiki_acquisition.py": 16 * 1024,
    "tools/plan_migration.py": 32 * 1024,
    "tools/build_wiki.py": 32 * 1024,
    "tools/smoke_deploy.py": 80 * 1024,
    "tools/smoke_prefix.py": 64 * 1024,
    "tests/test_safety.py": 48 * 1024,
    "tests/test_wiki.py": 48 * 1024,
    "tests/test_catalog.py": 64 * 1024,
    "tests/test_views.py": 32 * 1024,
    "tests/test_acquisition.py": 32 * 1024,
    "tests/test_migration.py": 32 * 1024,
    "tests/test_prefix.py": 32 * 1024,
    "tests/test_runtime.php": 32 * 1024,
    "deploy/Dockerfile": 8 * 1024,
    "deploy/compose.dev.yml": 16 * 1024,
    "deploy/LocalSettings.template.php": 16 * 1024,
    "deploy/mirklurk-runtime.php": 16 * 1024,
    "deploy/install.php": 16 * 1024,
    "deploy/healthcheck.php": 8 * 1024,
    ".github/workflows/validate.yml": 8 * 1024,
    **{f"content/pages/{name}": 32 * 1024 for name in (*PAGE_FILES.values(), *RESEARCH_PAGE_FILES.values())},
}
FORBIDDEN_DIRECTORIES = {
    "languages", "saves", "dumps", "exports", "raw", "research", "raw-research",
    "db", "database", "uploads", "backups", "secrets", ".secrets", ".ssh",
    ".local", ".venv", "__pycache__", "node_modules",
}
FORBIDDEN_SUFFIXES = {
    ".win", ".ini", ".gml", ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    ".pak", ".pck", ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg",
    ".ogg", ".wav", ".mp3", ".flac", ".aiff", ".mp4", ".webm", ".avi",
    ".ttf", ".otf", ".woff", ".woff2", ".pem", ".key", ".p12", ".pfx",
    ".sql", ".sqlite", ".sqlite3", ".db", ".bak", ".backup",
}
SECRET_PATTERNS = {
    "private-key material": re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    "GitHub credential": re.compile(
        r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,255}"
        r"|github_pat_[A-Za-z0-9_]{60,255})(?![A-Za-z0-9_])"
    ),
    "AWS access identifier": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Slack credential": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,255}\b"),
    "Stripe live credential": re.compile(r"\bsk_live_[A-Za-z0-9]{20,255}\b"),
    "credential-bearing URL": re.compile(
        r"\b[a-z][a-z0-9+.-]*://[^\s/:@<>]{1,128}:[^\s/@<>]{1,256}@",
        re.IGNORECASE,
    ),
    "personal absolute path": re.compile(
        r"(?:[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/][^\\/\s]+"
        r"|(?<![A-Za-z0-9])/(?:home|Users)/[A-Za-z0-9_.-]+[\\/])"
    ),
    "decompiled game function": re.compile(
        r"^\s*(?:function\s+)?gml_(?:Script|Object)_[A-Za-z0-9_]+\s*\(",
        re.MULTILINE,
    ),
}
ASSIGNMENT = re.compile(
    r"""^\s*(?:export\s+|\$)?["']?([A-Za-z_][A-Za-z0-9_]*)["']?\s*[:=]\s*(.*?)\s*[,;]?\s*$"""
)
SECRET_KEYS = {
    "password", "passwd", "secret", "token", "api_key", "apikey", "access_key",
    "private_key", "wpsecretkey", "wpupgradekey", "wpdbpassword",
}
PLACEHOLDERS = {"", "null", "none", "true", "false", "changeme", "example", "redacted"}


def _git(root, *args, input_bytes=None):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        # Git errors can quote content or local paths; keep diagnostics bounded.
        raise RuntimeError(f"git {args[0]} failed (exit {result.returncode})")
    return result.stdout


def path_errors(path, mode):
    problems = []
    if mode != "100644":
        problems.append("only regular, non-executable text blobs are allowed (no links/submodules)")
    parts = path.split("/")
    lower_parts = [part.lower() for part in parts]
    name = lower_parts[-1]
    if (
        "\\" in path
        or path.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or any(ord(c) < 32 or ord(c) == 127 for c in path)
    ):
        problems.append("non-canonical repository path")
    if (
        any(part in FORBIDDEN_DIRECTORIES for part in lower_parts)
        or any("utmt" in part or "undertalemodtool" in part for part in lower_parts)
        or name.startswith(".env")
        or name == "localsettings.php"
        or PurePosixPath(name).suffix in FORBIDDEN_SUFFIXES
        or name.startswith(("dump-", "dump_", "export-", "export_", "raw-", "raw_"))
    ):
        problems.append("forbidden game asset, raw research, runtime state, or secret path")
    if path not in ALLOWED_FILES:
        problems.append("path is not on the exact-file publication allowlist")
    return problems


def _secret_assignment(line):
    match = ASSIGNMENT.fullmatch(line)
    if not match:
        return False
    key, value = match.groups()
    key = key.lower()
    if key not in SECRET_KEYS and not key.endswith(
        ("_password", "_passwd", "_token", "_secret", "_api_key", "_private_key", "_access_key")
    ):
        return False
    quoted = len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]
    if quoted:
        value = value[1:-1]
    if value.lower() in PLACEHOLDERS or value.startswith(("<", "${", "$env:", "os.environ")):
        return False
    return bool(value) and (quoted or bool(re.fullmatch(r"[A-Za-z0-9_+/.=-]{12,}", value)))


def blob_errors(path, raw):
    problems = []
    maximum = ALLOWED_FILES.get(path)
    if maximum is None:
        return ["content has no publication type or size policy"]
    if len(raw) > maximum:
        return [f"blob exceeds its {maximum}-byte limit"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ["blob is not UTF-8 text"]
    if text.startswith("\ufeff") or any(
        (ord(c) < 32 and c not in "\t\r\n") or 127 <= ord(c) <= 159 for c in text
    ):
        problems.append("binary/control characters or a byte-order mark are not allowed")
    for label, pattern in SECRET_PATTERNS.items():
        match = pattern.search(text)
        if match:
            line = text.count("\n", 0, match.start()) + 1
            problems.append(f"{label} detected near line {line}; content not echoed")
    for number, line in enumerate(text.splitlines(), 1):
        if _secret_assignment(line):
            problems.append(f"possible literal secret assignment near line {number}; content not echoed")
    if path == "content/facts/game.json":
        try:
            parse_data(raw)
        except DataError as error:
            problems.append(f"invalid curated facts: {error}")
    elif path in {"content/facts/catalog.json", "content/facts/entity_details.json", "content/facts/illustrations.json", "content/facts/acquisition.json"}:
        try:
            parse_document(raw, maximum)
        except DataError as error:
            problems.append(f"invalid reviewed metadata: {error}")
    return problems


def audit_index(root):
    entries = _git(root, "ls-files", "--stage", "-z")
    problems = []
    count = 0
    staged_metadata = {}
    if not entries:
        return 0, ["Git index is empty; there is nothing to validate"]
    for entry in entries.rstrip(b"\0").split(b"\0"):
        metadata, raw_path = entry.split(b"\t", 1)
        mode, object_id, stage = metadata.decode("ascii").split()
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            problems.append("index contains a non-UTF-8 path")
            continue
        count += 1
        label = ascii(path)
        if stage != "0":
            problems.append(f"{label}: unresolved index conflict")
            continue
        errors = path_errors(path, mode)
        if not errors:
            kind = _git(root, "cat-file", "-t", object_id).strip()
            size = int(_git(root, "cat-file", "-s", object_id).strip())
            if kind != b"blob":
                errors.append("index entry is not a blob")
            elif size > ALLOWED_FILES[path]:
                errors.append(f"blob exceeds its {ALLOWED_FILES[path]}-byte limit")
            else:
                raw = _git(root, "cat-file", "blob", object_id)
                errors.extend(blob_errors(path, raw))
                if path.startswith("content/facts/") and not errors:
                    staged_metadata[path] = raw
        problems.extend(f"{label}: {error}" for error in errors)
    validators = {
        "content/facts/catalog.json": parse_catalog,
        "content/facts/entity_details.json": parse_details,
        "content/facts/illustrations.json": parse_illustrations,
    }
    for path, validator in validators.items():
        if path in staged_metadata:
            if "content/facts/game.json" not in staged_metadata:
                problems.append(f"{path}: valid staged game.json is required for reference validation")
                continue
            try:
                data = parse_data(staged_metadata["content/facts/game.json"])
                if path == "content/facts/illustrations.json":
                    catalog_raw = staged_metadata.get("content/facts/catalog.json")
                    catalog = parse_catalog(catalog_raw, data) if catalog_raw is not None else None
                    validator(staged_metadata[path], data, catalog)
                else:
                    validator(staged_metadata[path], data)
            except DataError as error:
                problems.append(f"{path}: invalid staged references: {error}")
    if all(path in staged_metadata for path in ("content/facts/game.json", "content/facts/catalog.json", "content/facts/entity_details.json")):
        try:
            data = parse_data(staged_metadata["content/facts/game.json"])
            catalog = parse_catalog(staged_metadata["content/facts/catalog.json"], data)
            details = parse_details(staged_metadata["content/facts/entity_details.json"], data)
            validate_coin_profiles(catalog, details)
        except DataError as error:
            problems.append(f"staged coin/profile consistency: {error}")
    acquisition_path = "content/facts/acquisition.json"
    if acquisition_path in staged_metadata:
        try:
            if not all(path in staged_metadata for path in ("content/facts/game.json", "content/facts/catalog.json")):
                raise DataError("valid staged game.json and catalog.json are required")
            data = parse_data(staged_metadata["content/facts/game.json"])
            catalog = parse_catalog(staged_metadata["content/facts/catalog.json"], data)
            acquisition = parse_document(staged_metadata[acquisition_path], MAX_ACQUISITION_BYTES)
            validate_catalog(dict(catalog, acquisition=acquisition), data)
        except DataError as error:
            problems.append(f"{acquisition_path}: invalid staged references: {error}")
    return count, problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        count, problems = audit_index(args.repo)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Publication check could not run: {error}", file=sys.stderr)
        return 2
    if problems:
        print("Publication blocked:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print(f"Publication check passed: {count} indexed text blobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
