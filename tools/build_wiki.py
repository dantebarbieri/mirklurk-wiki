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
from wiki_catalog import (
    default_catalog, entry_owners, entry_relations, fact_owners,
    page_locations, title_key, validate_catalog,
)
from wiki_details import empty_details, load_publication_inputs, validate_details


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


def entity_link(identity, entities, locations=None):
    entity = entities[identity]
    target = locations[identity] if locations else f'{CATEGORY_PAGES[entity["category"]]}#entity-{identity}'
    return f'[[{target}|{literal(entity["name"])}]]'


def known(value):
    return "Not established" if value is None else literal(value)


def count_range(value):
    return "Not established" if value is None else literal(f'{value["min"]} to {value["max"]}')


def quantities(items, entities, locations=None):
    return "<br />".join(
        f'{literal(item["quantity"])} x {entity_link(item["item"], entities, locations)}'
        for item in sorted(items, key=lambda item: item["item"])
    )


def quest_order(entry):
    quest_id = entry["details"]["quest_id"]
    if quest_id == "First":
        return (0, 0, entry["id"])
    if quest_id.isdecimal():
        return (1, int(quest_id), entry["id"])
    return (2, quest_id, entry["id"])


def render_entry(entry, entities, facts, locations=None, fact_pages=None):
    details = entry["details"]
    lines = [
        f'<span id="entry-{entry["id"]}"></span>',
        f'=== {literal(entry["title"])} ===',
        literal(entry["summary"]),
        "",
        f"'''Conditions:''' {known(entry['conditions'])}",
        "",
    ]
    if entry["kind"] == "quest":
        lines.append(table(["Journal/quest identifier", "Documented stage"], [[
            literal(details["quest_id"]), known(details["stage"]),
        ]]))
    elif entry["kind"] == "merchant":
        lines.append(table(["Merchant", "Item", "Quantity", "Price", "Currency/unit", "Location"], [[
            entity_link(details["merchant"], entities, locations), entity_link(details["item"], entities, locations),
            known(details["quantity"]), known(details["price"]), known(details["currency"]),
            known(details["location"]),
        ]]))
    elif entry["kind"] == "recipe":
        cost = details["cost"]
        lines.append(table(["Station", "Inputs", "Outputs", "Additional cost"], [[
            literal(details["station"]),
            quantities(details["inputs"], entities, locations) if details["inputs"] else "No item inputs in this documented recipe",
            quantities(details["outputs"], entities, locations),
            "Not established" if cost is None else literal(f'{cost["amount"]} {cost["unit"]}'),
        ]]))
    elif entry["kind"] == "loot":
        lines.append(table(["Table/trace", "Outcome", "Quantity range", "Reported weight", "Conditional probability (0-1 fraction)", "Roll-count range"], [[
            literal(details["table"]),
            "Explicit empty result" if details["outcome"] is None else entity_link(details["outcome"], entities, locations),
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
                target = fact_pages[identity] if fact_pages else fact["page"]
                lines.append(f'* [[{target}#fact-{identity}|{literal(identity)}]] - {literal(fact["property"])}')
    lines.extend([
        "", f"'''Evidence status:''' {CONFIDENCE_LABELS[entry['confidence']]}",
        f"'''Source / section / key:''' {evidence_text(entry['evidence'])}",
        f"'''Record ID:''' {literal(entry['id'])}",
    ])
    return "\n".join(lines) + "\n"


def relationship_summary(entry, identity, entities, locations):
    details = entry["details"]
    if entry["kind"] == "merchant":
        return (
            "Sold by " + entity_link(details["merchant"], entities, locations)
            + f'; stock {known(details["quantity"])}; price {known(details["price"])} {known(details["currency"])}'
            + f'; location {known(details["location"])}.'
        )
    if entry["kind"] == "recipe":
        roles = []
        if any(row["item"] == identity for row in details["inputs"]):
            roles.append("Ingredient")
        if any(row["item"] == identity for row in details["outputs"]):
            roles.append("Output")
        cost = details["cost"]
        return (
            (" / ".join(roles) or "Related station") + f'; station {literal(details["station"])}; inputs: '
            + (quantities(details["inputs"], entities, locations) or "No item inputs")
            + "; outputs: " + quantities(details["outputs"], entities, locations)
            + "; additional cost: " + ("Not established" if cost is None else literal(f'{cost["amount"]} {cost["unit"]}')) + "."
        )
    if entry["kind"] == "loot":
        return (
            f'Quantity {count_range(details["quantity"])}; rolls {count_range(details["rolls"])}; '
            f'reported weight {known(details["weight"])}; conditional probability '
            + ("not established (not calculated from weight)" if details["probability"] is None else known(details["probability"]))
            + ". See the record for its roll conditions."
        )
    return "Related context; see the cited record."


def render_illustration(illustration, entities, embed=True):
    lines = [
        f'<span id="illustration-{illustration["id"]}"></span>',
        f'=== {literal(entities[illustration["entity"]]["name"])} ===',
    ]
    if illustration["rights_status"] == "approved" and embed:
        lines.append(f'[[{illustration["file_title"]}|thumb|{literal(illustration["caption"])}]]')
    elif illustration["rights_status"] != "approved":
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


def build_pages(root, data, catalog=None, details=None):
    validate_data(data)
    catalog = validate_catalog(default_catalog(data) if catalog is None else catalog, data)
    details = validate_details(empty_details() if details is None else details, data)
    pages = {}
    researched = {fact["page"] for fact in data["facts"]} | {
        entry_page(entry) for entry in data.get("entries", [])
    }
    active_research = {title: filename for title, filename in RESEARCH_PAGE_FILES.items() if title in researched}
    for title, filename in {**PAGE_FILES, "NPCs": "NPCs.wiki", **active_research}.items():
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
    locations = page_locations(data, catalog)
    classifications = {row["entity"]: row for row in catalog["classifications"]}
    fact_pages = fact_owners(data, locations)
    relations = entry_relations(data, catalog)
    entry_pages = entry_owners(data, locations, relations)
    indexes = {}
    legacy_npcs = []
    skill_groups = {}
    for entity in sorted(data["entities"], key=lambda row: (row["name"].casefold(), row["id"])):
        identity = entity["id"]
        category = entity["category"]
        classification = classifications.get(identity)
        index = "NPCs" if classification and classification["kind"] == "npc" else CATEGORY_PAGES[category]
        group = entity_link(entity["group"], entities_by_id, locations) if "group" in entity else ""
        row = f'<span id="entity-{identity}"></span>' + entity_link(identity, entities_by_id, locations)
        if group:
            row += f" - {group}"
        if category == "being" and (classification is None or classification["kind"] == "unclassified"):
            row += " - classification not established"
        if category in {"skill_group", "damage_class"}:
            row = (
                f'<span id="entity-{identity}"></span>{literal(entity["name"])}'
                f' - {CONFIDENCE_LABELS[entity["confidence"]]}<br />{evidence_text(entity["evidence"])}'
            )
        if category == "skill":
            skill_groups.setdefault(entity["group"], []).append("* " + row)
        elif category != "skill_group":
            indexes.setdefault(index, []).append("* " + row)
        if index == "NPCs":
            legacy_npcs.append(
                f'* <span id="entity-{identity}"></span>{entity_link(identity, entities_by_id, locations)} - see [[NPCs]]'
            )
    for title, rows in indexes.items():
        pages[title] += "\n== Browse ==\n" + "\n".join(rows) + "\n"
    groups = sorted((entity for entity in data["entities"] if entity["category"] == "skill_group"), key=lambda row: (row["name"], row["id"]))
    for group in groups:
        pages["Skills"] += (
            f'\n== {literal(group["name"])} ==\n<span id="entity-{group["id"]}"></span>\n'
            + "\n".join(skill_groups.get(group["id"], [])) + "\n"
            + f'\nGroup evidence: {CONFIDENCE_LABELS[group["confidence"]]}<br />{evidence_text(group["evidence"])}\n'
        )
    if legacy_npcs:
        pages["Bestiary"] += (
            '\n<div class="mw-collapsible mw-collapsed">\nCharacters moved to [[NPCs]]\n'
            '<div class="mw-collapsible-content">\n' + "\n".join(legacy_npcs) + "\n</div></div>\n"
        )

    properties = {row["id"]: row for row in details["properties"]}
    for row in catalog["pages"]:
        entity = entities_by_id[row["entity"]]
        classification = classifications.get(entity["id"])
        index = "NPCs" if classification and classification["kind"] == "npc" else CATEGORY_PAGES[entity["category"]]
        lines = [f"[[Main Page]] | [[{index}]]", "", f"'''{literal(entity['name'])}'''", ""]
        if entity["category"] == "skill":
            lines.append("'''Skill group:''' " + entity_link(entity["group"], entities_by_id, locations))
        if classification:
            label = {"npc": "NPC / character", "creature": "Creature / enemy", "unclassified": "Unclassified being"}
            lines.extend([f"'''Index classification:''' {label[classification['kind']]}", literal(classification["note"])])
        images = sorted((image for image in data.get("illustrations", []) if image["entity"] == entity["id"]), key=lambda image: image["id"])
        for image in images:
            if image["rights_status"] == "approved":
                lines.append(f'[[{image["file_title"]}|thumb|{literal(image["caption"])}]]')
        profiles = sorted((profile for profile in details["profiles"] if profile["entity"] == entity["id"]), key=lambda profile: profile["id"])
        if not any(owner == row["title"] for owner in fact_pages.values()) and not any(
            owner == row["title"] for owner in entry_pages.values()
        ) and not profiles:
            lines.append("No numerical mechanics or primary research entries have been documented for this record yet.")
        for profile in profiles:
            lines.extend([
                "", f'<span id="profile-{profile["id"]}"></span>', "== Documented profile ==",
                literal(profile["context"]), "",
                table(["Property", "Value", "Unit / interpretation"], [
                    [literal(properties[key]["label"]), known(value),
                     known(properties[key]["unit"]) + " - " + literal(properties[key]["description"])]
                    for key, value in sorted(profile["values"].items())
                ]),
                f"'''Evidence status:''' {CONFIDENCE_LABELS[profile['confidence']]}",
                f"'''Source / section / key:''' {evidence_text(profile['evidence'])}",
            ])
        pages[row["title"]] = "\n".join(lines) + "\n"
        for alias in row["aliases"]:
            pages[alias] = f'#REDIRECT [[{row["title"]}]]\n'

    for title in sorted(pages):
        facts = [fact for fact in data["facts"] if fact_pages[fact["id"]] == title]
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
        pages[title] += "\n== Mechanics ==\n"
        pages[title] += table(
            ["Entity", "Property (units in label)", "Value", "Original explanation",
             "Evidence status", "Source / section / key", "Record ID"],
            rows,
        ) + "\n"
    facts_by_id = {fact["id"]: fact for fact in data["facts"]}
    entries = sorted(data.get("entries", []), key=lambda item: item["id"])
    illustrations = sorted(data.get("illustrations", []), key=lambda item: item["id"])
    for title in sorted(pages):
        matching = [entry for entry in entries if entry_pages[entry["id"]] == title]
        if title == "Quests and journal":
            matching.sort(key=quest_order)
        if matching:
            pages[title] += "\n== Documented entries ==\n"
            for entry in matching:
                pages[title] += render_entry(entry, entities_by_id, facts_by_id, locations, fact_pages) + "\n"
                related = sorted(relations[entry["id"]], key=lambda identity: (entities_by_id[identity]["name"], identity))
                if related:
                    pages[title] += "'''Related pages:''' " + " | ".join(
                        entity_link(identity, entities_by_id, locations) for identity in related
                    ) + "\n"
        matching_images = [
            image for image in illustrations
            if locations[image["entity"]] == title
        ]
        if matching_images:
            pages[title] += "\n== Illustration references ==\n"
            pages[title] += "\n".join(render_illustration(image, entities_by_id, embed=False) for image in matching_images)

    for row in catalog["pages"]:
        identity, title = row["entity"], row["title"]
        related = [entry for entry in entries if identity in relations[entry["id"]] and entry_pages[entry["id"]] != title]
        if related:
            pages[title] += "\n== Related research ==\n"
            for entry in related:
                pages[title] += (
                    f'* [[{entry_pages[entry["id"]]}#entry-{entry["id"]}|{literal(entry["title"])}]]'
                    f' - {relationship_summary(entry, identity, entities_by_id, locations)}\n'
                )
        if not any(image["entity"] == identity for image in illustrations):
            pages[title] += "\n== Picture ==\nNo reviewed image is attached to this page yet.\n"
        entity = entities_by_id[identity]
        pages[title] += (
            f'\n== Name and evidence ==\n<span id="entity-{identity}"></span>'
            f'{literal(identity)} - {CONFIDENCE_LABELS[entity["confidence"]]}<br />'
            f'{evidence_text(entity["evidence"])}\n'
            "\nMissing stats, locations, and acquisition conditions are not established. Source records do not prove current availability or runtime behavior. [[Evidence and spoilers|Evidence caveats]].\n"
        )
        if identity in classifications:
            classification = classifications[identity]
            pages[title] += (
                f'\nClassification: {CONFIDENCE_LABELS[classification["confidence"]]}<br />'
                + evidence_text(classification["evidence"]) + "\n"
            )

    for title in {*PAGE_FILES, *active_research}:
        moved_entries = [entry for entry in entries if entry_page(entry) == title and entry_pages[entry["id"]] != title]
        if moved_entries:
            pages[title] += "\n== Research index ==\n"
            for entry in moved_entries:
                pages[title] += (
                    f'* <span id="entry-{entry["id"]}"></span>'
                    f'[[{entry_pages[entry["id"]]}#entry-{entry["id"]}|{literal(entry["title"])}]]\n'
                )
        moved_facts = [fact for fact in data["facts"] if fact["page"] == title and fact_pages[fact["id"]] != title]
        if moved_facts:
            pages[title] += '\n<div class="mw-collapsible mw-collapsed">\nLegacy fact links (details now on entity pages)\n<div class="mw-collapsible-content">\n'
            for fact in sorted(moved_facts, key=lambda item: item["id"]):
                pages[title] += (
                    f'* <span id="fact-{fact["id"]}"></span>'
                    f'[[{fact_pages[fact["id"]]}#fact-{fact["id"]}|{literal(fact["id"])}]]\n'
                )
            pages[title] += "</div></div>\n"
    pages["Source provenance"] = source_page(data)
    return pages


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
        data, catalog, details = load_publication_inputs(root)
        pages = build_pages(root, data, catalog, details)
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
