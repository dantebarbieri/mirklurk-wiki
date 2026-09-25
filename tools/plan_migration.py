"""Compare private wiki snapshots without editing, importing, or deleting pages."""

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from build_wiki import EXPORT_NAMESPACES, title_key
from wiki_data import DataError


def read_snapshot(path):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise DataError("Snapshot must be a readable MediaWiki current-page XML export") from error
    namespace = root.tag.removeprefix("{").split("}", 1)[0]
    if namespace not in EXPORT_NAMESPACES or root.tag != f"{{{namespace}}}mediawiki":
        raise DataError("Snapshot uses an unsupported MediaWiki export format")
    prefix = f"{{{namespace}}}"
    if root.find(f"{prefix}siteinfo") is None:
        raise DataError("Snapshot must include siteinfo and all current pages")
    result = {}
    for page in root.findall(f"{prefix}page"):
        title = page.findtext(f"{prefix}title")
        page_namespace = page.findtext(f"{prefix}ns")
        if not title or not title.strip() or page_namespace is None or not page_namespace.isdecimal():
            raise DataError("Snapshot contains an invalid page identity")
        if page_namespace not in {"0", "14"}:
            continue
        if (page_namespace == "14") != title_key(title).startswith("Category:"):
            raise DataError("Snapshot contains a title/namespace mismatch")
        revisions = page.findall(f"{prefix}revision")
        if len(revisions) != 1:
            raise DataError("Snapshot must contain exactly one current revision per managed-namespace page")
        text = revisions[0].find(f"{prefix}text")
        if text is None or "deleted" in text.attrib or "location" in text.attrib:
            raise DataError("Snapshot has unavailable page text; cannot safely compare it")
        identity = title_key(title)
        if identity in result:
            raise DataError("Snapshot contains duplicate normalized page titles")
        result[identity] = text.text or ""
    return result


def text_hash(text):
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan_migration(base, current, desired):
    records = []
    for title in sorted(base.keys() | current.keys() | desired.keys()):
        previous = base.get(title)
        live = current.get(title)
        target = desired.get(title)
        if target is None:
            action = "preserve-unmanaged" if previous is None else "preserve-retired"
        elif live == target:
            action = "unchanged"
        elif live is None:
            action = "create" if previous is None else "preserve-deletion"
        elif previous is None:
            action = "conflict"
        elif target == previous:
            action = "preserve-live"
        elif live == previous:
            action = "review-update"
        else:
            action = "conflict"
        records.append({
            "title": title, "action": action,
            "base_sha256": text_hash(previous), "current_sha256": text_hash(live),
            "desired_sha256": text_hash(target),
        })
    dependencies = []
    new_page_dependencies = []
    for title, text in sorted(desired.items()):
        targets = sorted({title_key(target) for target in re.findall(r"\{\{:([^{}\n|]+)\}\}", text)})
        for target in targets:
            wanted = desired.get(target, "")
            if "<onlyinclude>" not in wanted:
                continue
            live = current.get(target, "")
            dependencies.append({
                "page": title, "price_owner": target,
                "current_price_block_ready": live.count("<onlyinclude>") == 1 and live.count("</onlyinclude>") == 1,
            })
        linked_titles = {title_key(target.lstrip(":").split("#", 1)[0])
                         for target in re.findall(r"\[\[([^\]|]+)", text)}
        for target in sorted(linked_titles & (desired.keys() - base.keys())):
            if target != title:
                new_page_dependencies.append({
                    "page": title, "target": target, "current_target_exists": target in current,
                })
    return {
        "schema_version": 1,
        "notice": "Review only. No writes authorized. Freeze writers and verify current hashes before any operator action.",
        "pages": records,
        "price_dependencies": dependencies,
        "new_page_dependencies": new_page_dependencies,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-export", required=True, type=Path)
    parser.add_argument("--current-export", required=True, type=Path)
    parser.add_argument("--desired-export", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = plan_migration(
            read_snapshot(args.base_export), read_snapshot(args.current_export),
            read_snapshot(args.desired_export),
        )
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    except (DataError, OSError) as error:
        print(f"Migration planning failed: {error}", file=sys.stderr)
        return 1
    conflicts = sum(page["action"] == "conflict" for page in report["pages"])
    print(f"Review plan written for {len(report['pages'])} titles; {conflicts} conflicts. No wiki modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
