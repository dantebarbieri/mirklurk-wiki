"""Validate isolated or historical tester documentation without overriding stable data."""

from pathlib import Path

from wiki_data import DataError, _evidence, _object, _records, _text, _title, validate_data
from wiki_details import parse_document, read_metadata, validate_details


MAX_TESTER_BYTES = 128 * 1024
TESTER_TITLE = "Version 0.9.9.7"


def load_tester(root, stable):
    document = parse_document(read_metadata(Path(root) / "content" / "facts" / "tester.json",
                                            MAX_TESTER_BYTES), MAX_TESTER_BYTES)
    _object(document, {"schema_version", "stable_build", "channel", "data", "details",
                       "item_notes", "page_notes"}, set(), "tester")
    if (type(document["schema_version"]) is not int or document["schema_version"] != 1
            or document["channel"] != "next_version_tester" or document["stable_build"] != "0.9.6.5"
            or stable["game"]["build"] not in (document["stable_build"], "1.0.0.0", "1.0.1.0")):
        raise DataError("tester: explicit stable build and tester channel required")
    data = validate_data(document["data"])
    if data["game"]["build"] != "0.9.9.7" or data["facts"] or data.get("entries"):
        raise DataError("tester: expected isolated 0.9.9.7 item definitions, not stable fact overrides")
    entities = {row["id"]: row for row in data["entities"]}
    for row in entities.values():
        _title(row["name"])
    stable_entities = {row["id"]: row for row in stable["entities"]}
    historical = stable["game"]["build"] in ("1.0.0.0", "1.0.1.0")
    overlap = entities.keys() & stable_entities.keys()
    if (any(row["category"] != "item" for row in entities.values())
            or not historical and overlap
            or historical and (overlap != entities.keys() or any(
                stable_entities[identity]["category"] != "item"
                or stable_entities[identity]["name"] != row["name"]
                for identity, row in entities.items()))):
        raise DataError("tester: new items must not shadow stable entities")
    if any(row["name"] == stable_row["name"] and row["id"] != stable_row["id"]
           for row in entities.values() for stable_row in stable_entities.values()):
        raise DataError("tester: item titles must not shadow stable entities")
    if len({row["name"] for row in entities.values()}) != len(entities):
        raise DataError("tester: duplicate item page title")
    details = validate_details(document["details"], data)
    if {row["entity"] for row in details["profiles"]} != entities.keys():
        raise DataError("tester: every new item needs its own numeric profile")
    images = data.get("illustrations", [])
    if ({row.get("entity") for row in images} != entities.keys()
            or len(images) != len(entities) or any(row["rights_status"] != "approved" for row in images)):
        raise DataError("tester: every new item needs exactly one approved illustration")
    if historical:
        stable_images = {row["entity"]: row for row in stable.get("illustrations", []) if "entity" in row}
        if any(stable_images.get(row["entity"]) != row for row in images):
            raise DataError("tester: historical items must retain their approved illustrations")
    sources = {row["id"]: row for row in data["sources"]}
    for field, owner in (("item_notes", "entity"), ("page_notes", "page")):
        seen = set()
        for row in _records(document[field], "tester." + field):
            _object(row, {owner, "paragraphs", "evidence"}, set(), "tester note")
            target = _text(row[owner], "tester note target", 160)
            if owner == "page":
                _title(target)
            if target in seen or (owner == "entity" and target not in entities):
                raise DataError("tester: duplicate or unknown note owner")
            seen.add(target)
            paragraphs = _records(row["paragraphs"], "tester note paragraphs")
            if not 1 <= len(paragraphs) <= 6:
                raise DataError("tester: expected one to six paragraphs")
            for paragraph in paragraphs:
                _text(paragraph, "tester paragraph", 1600)
            _evidence(row["evidence"], sources, "tester note evidence")
    return document


def add_tester_pages(root, stable, pages):
    from wiki_render import PROPERTY_LABELS, cell_grid, illustration_markup, literal, profile_value, table

    document = load_tester(root, stable)
    data, details = document["data"], document["details"]
    beta_entities = {row["id"]: row for row in data["entities"]}
    entities = {row["id"]: row for row in stable["entities"]} | beta_entities
    locations = {identity: row["name"] for identity, row in entities.items()}
    properties = {row["id"]: row for row in details["properties"]}
    notes = {row["entity"]: row for row in document["item_notes"]}
    banner = ("'''0.9.9.7 tester only (next_version_tester).''' "
              "These values do not replace the stable 0.9.6.5 reference.\n")
    for identity, entity in sorted(beta_entities.items()):
        title = entity["name"]
        if title in pages:
            raise DataError("tester: item page would replace an existing stable page")
        profiles = [row for row in details["profiles"] if row["entity"] == identity]
        grids = [row for row in details.get("grids", []) if row["entity"] == identity]
        image = next(row for row in data["illustrations"] if row["entity"] == identity)
        text = f"'''{literal(title)}''' is an item defined in the [[{TESTER_TITLE}|0.9.9.7 tester]].\n\n" + banner
        text += illustration_markup(image)
        rows = [[literal(PROPERTY_LABELS.get(key, properties[key]["label"])),
                 profile_value(key, value, entities, locations)]
                for profile in profiles for key, value in sorted(profile["values"].items())
                if not key.startswith("melee-pattern-")]
        text += "\n== Tester stats ==\n" + table(["Base detail (0.9.9.7 tester)", "Value"], rows)
        text += ("Condition and skills can change effective values. Base weight is before crafting "
                 "adjustments; a declared value does not establish merchant stock.\n")
        for grid in grids:
            text += cell_grid(grid, "item", stable.get("illustrations", []))
        if identity in notes:
            text += "\n== Tester use and acquisition ==\n" + "\n\n".join(notes[identity]["paragraphs"]) + "\n"
        text += f"\n[[{TESTER_TITLE}|Tester overview]] | [[Items|Stable items]] | [[Versions]]\n"
        pages[title] = text
    for row in document["page_notes"]:
        title = row["page"]
        if title not in pages or pages[title].startswith("#REDIRECT"):
            raise DataError(f"tester: unavailable stable note target {title}")
        pages[title] += "\n== 0.9.9.7 tester ==\n" + banner + "\n\n".join(row["paragraphs"])
        pages[title] += f"\n\n[[{TESTER_TITLE}|Tester changes and limits]].\n"
