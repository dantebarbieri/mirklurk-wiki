"""Build deterministic MediaWiki XML; never connect to or modify a live wiki."""

import argparse
import hashlib
import html
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from wiki_data import (
    CATEGORY_PAGES, DataError, PAGE_FILES, RESEARCH_PAGE_FILES,
    entry_page, load_data, validate_data,
)


EXPORT_NS = "http://www.mediawiki.org/xml/export-0.11/"
EXPORT_NAMESPACES = {EXPORT_NS, "http://www.mediawiki.org/xml/export-0.10/"}
SEED_TIMESTAMP = "2000-01-01T00:00:00Z"
CONFIDENCE_LABELS = {
    "observed": "Observed in the named source; not a runtime test",
    "inferred": "Inferred; requires confirmation",
    "localization-described": "Described by localization; not runtime-verified",
}
ET.register_namespace("", EXPORT_NS)


def literal(value):
    return "<nowiki>" + html.escape(str(value), quote=False) + "</nowiki>"


def evidence_text(references):
    references = sorted(references, key=lambda item: (item["source"], item["section"], item["key"]))
    return "<br />".join(
        f'[[Source provenance#{reference["source"]}|{reference["source"]}]]'
        f' / {literal(reference["section"])} / {literal(reference["key"])}'
        for reference in references
    )


def table(headers, rows):
    lines = ['{| class="wikitable"', "! " + " !! ".join(headers)]
    for row in rows:
        lines.extend(["|-", "| " + " || ".join(row)])
    lines.append("|}")
    return "\n".join(lines)


def entity_link(identity, entities):
    entity = entities[identity]
    page = CATEGORY_PAGES[entity["category"]]
    return f'[[{page}#entity-{identity}|{literal(entity["name"])}]]'


def known(value):
    return "Not established" if value is None else literal(value)


def count_range(value):
    return "Not established" if value is None else literal(f'{value["min"]} to {value["max"]}')


def quantities(items, entities):
    return "<br />".join(
        f'{literal(item["quantity"])} x {entity_link(item["item"], entities)}'
        for item in sorted(items, key=lambda item: item["item"])
    )


def render_entry(entry, entities, facts):
    details = entry["details"]
    lines = [
        f'<span id="entry-{entry["id"]}"></span>',
        f'=== {literal(entry["title"])} ===',
        literal(entry["summary"]),
        "",
        f"'''Evidence status:''' {CONFIDENCE_LABELS[entry['confidence']]}",
        f"'''Conditions:''' {known(entry['conditions'])}",
        f"'''Source / section / key:''' {evidence_text(entry['evidence'])}",
        f"'''Record ID:''' {literal(entry['id'])}",
        "",
    ]
    if entry["kind"] == "quest":
        lines.append(table(["Journal/quest identifier", "Documented stage"], [[
            literal(details["quest_id"]), known(details["stage"]),
        ]]))
    elif entry["kind"] == "merchant":
        lines.append(table(["Merchant", "Item", "Quantity", "Price", "Currency/unit", "Location"], [[
            entity_link(details["merchant"], entities), entity_link(details["item"], entities),
            known(details["quantity"]), known(details["price"]), known(details["currency"]),
            known(details["location"]),
        ]]))
    elif entry["kind"] == "recipe":
        cost = details["cost"]
        lines.append(table(["Station", "Inputs", "Outputs", "Additional cost"], [[
            literal(details["station"]),
            quantities(details["inputs"], entities) if details["inputs"] else "No item inputs in this documented recipe",
            quantities(details["outputs"], entities),
            "Not established" if cost is None else literal(f'{cost["amount"]} {cost["unit"]}'),
        ]]))
    elif entry["kind"] == "loot":
        lines.append(table(["Table/trace", "Outcome", "Quantity range", "Reported weight", "Conditional probability (0-1 fraction)", "Roll-count range"], [[
            literal(details["table"]),
            "Explicit empty result" if details["outcome"] is None else entity_link(details["outcome"], entities),
            count_range(details["quantity"]), known(details["weight"]),
            "Not established; not calculated from weight" if details["probability"] is None else literal(details["probability"]),
            count_range(details["rolls"]),
        ]]))
    else:
        lines.extend("# " + literal(step) for step in details["steps"])
        if details["fact_ids"]:
            lines.extend(["", "'''Related numeric facts:'''"])
            for identity in sorted(details["fact_ids"]):
                fact = facts[identity]
                lines.append(f'* [[{fact["page"]}#fact-{identity}|{literal(identity)}]] - {literal(fact["property"])}')
    return "\n".join(lines) + "\n"


def render_illustration(illustration, entities):
    lines = [
        f'<span id="illustration-{illustration["id"]}"></span>',
        f'=== {literal(entities[illustration["entity"]]["name"])} ===',
    ]
    if illustration["rights_status"] == "approved":
        lines.append(f'[[{illustration["file_title"]}|thumb|{literal(illustration["caption"])}]]')
    else:
        lines.append("Artwork publication is pending rights confirmation. No image is embedded.")
    lines.extend([
        f"'''Reserved File title:''' {literal(illustration['file_title'])}",
        f"'''Original caption:''' {literal(illustration['caption'])}",
        f"'''Creator:''' {known(illustration['creator'])}",
        f"'''Reviewed image SHA-256:''' {known(illustration['sha256'])}",
        f"'''Rights review:''' {literal(illustration['rights_status'])}; "
        f"{known(illustration['rights_basis'])}; {known(illustration['rights_note'])}",
        f"'''Evidence status:''' {CONFIDENCE_LABELS[illustration['confidence']]}",
        f"'''Source / section / key:''' {evidence_text(illustration['evidence'])}",
    ])
    return "\n".join(lines) + "\n"


def source_page(data):
    game = data["game"]
    lines = [
        "This register identifies the local source builds used for curated facts.",
        "The source files themselves are not distributed here.",
        "A hash identifies exact bytes, not a release number or permission to redistribute.",
        "",
        f'Marketed game: {literal(game["name"])}. '
        f'Steam application ID: {game["steam_app_id"]}.',
        f'Installed build: {literal(game["build"] or "unidentified")}.',
        "",
        "Paths are relative to the game installation, never to a contributor's user profile.",
        "Section and key identifiers on each catalogue or fact row locate its evidence.",
        "",
        "[[Research policy]] | [[Evidence and spoilers]] | [[Main Page]]",
        "",
        "== Source register ==",
    ]
    rows = []
    for source in sorted(data["sources"], key=lambda item: item["id"]):
        rows.append([
            f'<span id="{source["id"]}"></span>{literal(source["id"])}',
            literal(source["path"].replace("\\", "/")),
            literal(source["sha256"]),
            literal(source["build"] or "unidentified"),
        ])
    lines.append(table(["Source ID", "Installation-relative path", "SHA-256", "Build"], rows))
    return "\n".join(lines) + "\n"


def build_pages(root, data):
    validate_data(data)
    pages = {}
    researched = {fact["page"] for fact in data["facts"]} | {
        entry_page(entry) for entry in data.get("entries", [])
    }
    active_research = {title: filename for title, filename in RESEARCH_PAGE_FILES.items() if title in researched}
    for title, filename in {**PAGE_FILES, **active_research}.items():
        path = Path(root) / "content" / "pages" / filename
        if path.is_symlink():
            raise DataError(f"authored page {filename}: symlinks are not permitted")
        raw = path.read_bytes()
        if len(raw) > 32 * 1024:
            raise DataError(f"authored page {filename}: exceeds its size limit")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DataError(f"authored page {filename}: must be UTF-8") from error
        if any((ord(c) < 32 and c not in "\r\n\t") or 127 <= ord(c) <= 159 for c in text):
            raise DataError(f"authored page {filename}: control characters are not permitted")
        pages[title] = text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"
    if active_research:
        navigation = "\n== More researched topics ==\n" + " | ".join(
            f"[[{title}]]" for title in sorted(active_research)
        ) + "\n"
        pages["Main Page"] += navigation
        pages["Game mechanics"] += navigation

    entities_by_id = {entity["id"]: entity for entity in data["entities"]}
    for title in sorted(set(CATEGORY_PAGES.values())):
        entities = [
            entity for entity in data["entities"] if CATEGORY_PAGES[entity["category"]] == title
        ]
        if not entities:
            continue
        rows = []
        for entity in sorted(entities, key=lambda item: (item["category"], item["name"].casefold(), item["id"])):
            group = entities_by_id[entity["group"]]["name"] if "group" in entity else ""
            rows.append([
                literal(entity["name"]),
                literal(group) if group else ("Skill group" if entity["category"] == "skill_group" else "-"),
                f'<span id="entity-{entity["id"]}"></span>{literal(entity["id"])}',
                evidence_text(entity["evidence"]),
                CONFIDENCE_LABELS[entity["confidence"]],
            ])
        pages[title] += "\n== Curated name index ==\n"
        pages[title] += table(["Name", "Group", "Record ID", "Source / section / key", "Evidence status"], rows) + "\n"

    for title in sorted(pages):
        facts = [fact for fact in data["facts"] if fact["page"] == title]
        if not facts:
            continue
        rows = []
        for fact in sorted(facts, key=lambda item: item["id"]):
            rows.append([
                literal(fact["entity"]),
                literal(fact["property"]),
                literal(json.dumps(fact["value"], ensure_ascii=False, allow_nan=False)),
                literal(fact["description"]),
                CONFIDENCE_LABELS[fact["confidence"]],
                evidence_text(fact["evidence"]),
                f'<span id="fact-{fact["id"]}"></span>{literal(fact["id"])}',
            ])
        pages[title] += "\n== Curated mechanics facts ==\n"
        pages[title] += table(
            ["Entity", "Property (units in label)", "Value", "Original explanation",
             "Evidence status", "Source / section / key", "Record ID"],
            rows,
        ) + "\n"
    facts_by_id = {fact["id"]: fact for fact in data["facts"]}
    entries = sorted(data.get("entries", []), key=lambda item: item["id"])
    illustrations = sorted(data.get("illustrations", []), key=lambda item: item["id"])
    for title in sorted(pages):
        matching = [entry for entry in entries if entry_page(entry) == title]
        if matching:
            pages[title] += "\n== Documented entries ==\n"
            pages[title] += "\n".join(render_entry(entry, entities_by_id, facts_by_id) for entry in matching)
        matching_images = [
            image for image in illustrations
            if CATEGORY_PAGES[entities_by_id[image["entity"]]["category"]] == title
        ]
        if matching_images:
            pages[title] += "\n== Illustration references ==\n"
            pages[title] += "\n".join(render_illustration(image, entities_by_id) for image in matching_images)
    pages["Source provenance"] = source_page(data)
    return pages


def title_key(title):
    # These authored titles all use MediaWiki's standard first-letter namespace.
    normalized = " ".join(title.replace("_", " ").split())
    return normalized[:1].upper() + normalized[1:]


def existing_titles(path):
    try:
        document = ET.parse(path)
    except (ET.ParseError, OSError) as error:
        raise DataError("existing export is unreadable or malformed XML") from error
    root = document.getroot()
    namespace = root.tag.removeprefix("{").split("}", 1)[0]
    if namespace not in EXPORT_NAMESPACES or root.tag != f"{{{namespace}}}mediawiki":
        raise DataError("existing export must be a MediaWiki 0.10/0.11 XML export")
    prefix = f"{{{namespace}}}"
    if root.find(f"{prefix}siteinfo") is None:
        raise DataError("existing export has no siteinfo; use a complete current-page dump")
    titles = set()
    for page in root.findall(f"{prefix}page"):
        title = page.findtext(f"{prefix}title")
        page_namespace = page.findtext(f"{prefix}ns")
        if not title or not title.strip() or page_namespace is None or not page_namespace.isdecimal():
            raise DataError("existing export has an invalid page title or namespace")
        if page_namespace == "0":
            titles.add(title_key(title))
    return titles


def build_xml(pages):
    def element(parent, tag, text=None, **attributes):
        child = ET.SubElement(parent, f"{{{EXPORT_NS}}}{tag}", attributes)
        if text is not None:
            child.text = text
        return child

    root = ET.Element(f"{{{EXPORT_NS}}}mediawiki", {"version": "0.11", "{http://www.w3.org/XML/1998/namespace}lang": "en"})
    siteinfo = element(root, "siteinfo")
    element(siteinfo, "sitename", "MirkLurk Wiki")
    element(siteinfo, "dbname", "mirklurk")
    element(siteinfo, "generator", "MirkLurk curated repository seed")
    element(siteinfo, "case", "first-letter")
    namespaces = element(siteinfo, "namespaces")
    element(namespaces, "namespace", "", key="0", case="first-letter")
    for identifier, title in enumerate(sorted(pages), 1):
        page = element(root, "page")
        element(page, "title", title)
        element(page, "ns", "0")
        element(page, "id", str(identifier))
        revision = element(page, "revision")
        element(revision, "id", str(identifier))
        element(revision, "timestamp", SEED_TIMESTAMP)
        contributor = element(revision, "contributor")
        element(contributor, "username", "Repository seed")
        element(revision, "comment", "Original repository seed; evidence and rights caveats apply.")
        element(revision, "origin", str(identifier))
        element(revision, "model", "wikitext")
        element(revision, "format", "text/x-wiki")
        element(
            revision, "text", pages[title],
            **{"{http://www.w3.org/XML/1998/namespace}space": "preserve",
               "bytes": str(len(pages[title].encode("utf-8")))},
        )
        number = int.from_bytes(hashlib.sha1(pages[title].encode("utf-8"), usedforsecurity=False).digest())
        digest = ""
        while number:
            number, remainder = divmod(number, 36)
            digest = "0123456789abcdefghijklmnopqrstuvwxyz"[remainder] + digest
        element(revision, "sha1", digest.rjust(31, "0"))
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fresh", action="store_true", help="Build all titles for a verified fresh wiki only")
    mode.add_argument("--existing-export", type=Path, help="Complete current-page XML dump; omit all existing titles")
    parser.add_argument("--output", required=True, type=Path, help="New output file; existing files are never overwritten")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        data = load_data(root / "content" / "facts" / "game.json")
        pages = build_pages(root, data)
        total = len(pages)
        excluded = existing_titles(args.existing_export) if args.existing_export else set()
        pages = {title: text for title, text in pages.items() if title_key(title) not in excluded}
        payload = build_xml(pages)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(payload)
    except (DataError, OSError) as error:
        print(f"Seed build failed: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {len(pages)} pages; omitted {total - len(pages)} existing titles.")
    print("No live wiki was contacted. Freeze edits and follow docs/IMPORTING.md before import.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
