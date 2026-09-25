"""Strict validation for the deliberately small, public facts format."""

import json
import math
import re
from decimal import Decimal
from pathlib import Path


PAGE_FILES = {
    "Main Page": "Main_Page.wiki",
    "Getting started": "Getting_started.wiki",
    "Game mechanics": "Game_mechanics.wiki",
    "Research policy": "Research_policy.wiki",
    "Evidence and spoilers": "Evidence_and_spoilers.wiki",
    "Items": "Items.wiki",
    "Bestiary": "Bestiary.wiki",
    "Nature": "Nature.wiki",
    "Skills": "Skills.wiki",
    "Damage types": "Damage_types.wiki",
    "Action points": "Action_points.wiki",
    "Health and armor": "Health_and_armor.wiki",
}
RESEARCH_PAGE_FILES = {
    "Quests and journal": "Quests_and_journal.wiki",
    "Merchants": "Merchants.wiki",
    "Crafting": "Crafting.wiki",
    "Loot tables": "Loot_tables.wiki",
    "Weather": "Weather.wiki",
    "Level progression": "Level_progression.wiki",
    "World seed logic": "World_seed_logic.wiki",
}
ENTRY_PAGES = {
    "quest": "Quests and journal",
    "merchant": "Merchants",
    "recipe": "Crafting",
    "loot": "Loot tables",
}
ALGORITHM_PAGES = {"Weather", "Level progression", "World seed logic", "Skills", "Crafting", "Loot tables"}
CATEGORY_PAGES = {
    "item": "Items",
    "being": "Bestiary",
    "nature": "Nature",
    "skill_group": "Skills",
    "skill": "Skills",
    "damage_class": "Damage types",
}
FACT_PAGES = {"Game mechanics", *CATEGORY_PAGES.values(), *RESEARCH_PAGE_FILES}
CONFIDENCES = {"observed", "inferred", "localization-described"}
MAX_FACTS_BYTES = 640 * 1024
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_.-]{0,79}\Z")


class DataError(ValueError):
    """A curated input cannot be published."""


def _object(value, required, optional, location):
    if not isinstance(value, dict):
        raise DataError(f"{location}: expected an object")
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing or unknown:
        raise DataError(
            f"{location}: missing fields {sorted(missing)}, unknown fields {sorted(unknown)}"
        )


def _text(value, location, limit=160):
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > limit
        or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)
        or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        raise DataError(f"{location}: expected short, single-line, trimmed text")
    return value


def _identifier(value, location):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise DataError(f"{location}: invalid stable identifier")
    return value


def _nullable_text(value, location, limit=160):
    if value is not None:
        _text(value, location, limit)


def _records(value, location):
    if not isinstance(value, list) or len(value) > 5000:
        raise DataError(f"{location}: expected an array of at most 5000 records")
    return value


def _evidence(value, sources, location):
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise DataError(f"{location}: expected one to eight evidence references")
    seen = set()
    for index, reference in enumerate(value):
        where = f"{location}[{index}]"
        _object(reference, {"source", "section", "key"}, set(), where)
        source = _identifier(reference["source"], f"{where}.source")
        if source not in sources:
            raise DataError(f"{where}: source ID does not exist")
        _text(reference["section"], f"{where}.section")
        _text(reference["key"], f"{where}.key")
        identity = (source, reference["section"], reference["key"])
        if identity in seen:
            raise DataError(f"{where}: duplicate evidence")
        seen.add(identity)


def _confidence(value, location):
    if not isinstance(value, str) or value not in CONFIDENCES:
        raise DataError(f"{location}: unknown confidence label")


def _number(value, location, minimum=0, maximum=10**15, integer=False):
    types = {int} if integer else {int, float, Decimal}
    if type(value) not in types or (isinstance(value, Decimal) and not value.is_finite()) or not minimum <= value <= maximum:
        raise DataError(f"{location}: expected a finite {'integer' if integer else 'number'} from {minimum} to {maximum}")


def _entity_reference(value, entities, category, location):
    _identifier(value, location)
    if value not in entities or entities[value]["category"] != category:
        raise DataError(f"{location}: must reference a known {category} entity")


def _range(value, location):
    if value is not None:
        _object(value, {"min", "max"}, set(), location)
        _number(value["min"], f"{location}.min", integer=True)
        _number(value["max"], f"{location}.max", minimum=value["min"], integer=True)


def _item_quantities(value, entities, location, require_items=False):
    if not isinstance(value, list) or len(value) > 32 or (require_items and not value):
        raise DataError(f"{location}: expected {'one to' if require_items else 'at most'} 32 item quantities")
    seen = set()
    for index, item in enumerate(value):
        where = f"{location}[{index}]"
        _object(item, {"item", "quantity"}, set(), where)
        _entity_reference(item["item"], entities, "item", f"{where}.item")
        _number(item["quantity"], f"{where}.quantity", minimum=1, integer=True)
        if item["item"] in seen:
            raise DataError(f"{where}: duplicate ingredient/output; combine its quantity")
        seen.add(item["item"])


def entry_page(entry):
    return entry["details"]["page"] if entry["kind"] == "algorithm" else ENTRY_PAGES[entry["kind"]]


def _validate_entries(records, sources, entities, facts):
    seen = set()
    for index, entry in enumerate(_records(records, "entries")):
        where = f"entries[{index}]"
        _object(entry, {"id", "kind", "title", "summary", "conditions", "confidence", "evidence", "details"}, set(), where)
        identity = _identifier(entry["id"], f"{where}.id")
        if identity in seen:
            raise DataError(f"{where}: duplicate entry ID")
        seen.add(identity)
        kind = entry["kind"]
        if not isinstance(kind, str) or kind not in {*ENTRY_PAGES, "algorithm"}:
            raise DataError(f"{where}: unknown research entry kind")
        _text(entry["title"], f"{where}.title")
        _text(entry["summary"], f"{where}.summary", 1200)
        _nullable_text(entry["conditions"], f"{where}.conditions", 500)
        _confidence(entry["confidence"], f"{where}.confidence")
        _evidence(entry["evidence"], sources, f"{where}.evidence")
        details = entry["details"]
        location = f"{where}.details"
        if kind == "quest":
            _object(details, {"quest_id", "stage"}, set(), location)
            _text(details["quest_id"], f"{location}.quest_id")
            _nullable_text(details["stage"], f"{location}.stage")
        elif kind == "merchant":
            _object(details, {"merchant", "item", "quantity", "price", "currency", "location"}, set(), location)
            _entity_reference(details["merchant"], entities, "being", f"{location}.merchant")
            _entity_reference(details["item"], entities, "item", f"{location}.item")
            if details["quantity"] is not None:
                _number(details["quantity"], f"{location}.quantity", minimum=1, integer=True)
            if details["price"] is not None:
                _number(details["price"], f"{location}.price")
                _text(details["currency"], f"{location}.currency")
            else:
                _nullable_text(details["currency"], f"{location}.currency")
            _nullable_text(details["location"], f"{location}.location", 500)
        elif kind == "recipe":
            _object(details, {"station", "inputs", "outputs", "cost"}, set(), location)
            _text(details["station"], f"{location}.station")
            _item_quantities(details["inputs"], entities, f"{location}.inputs")
            _item_quantities(details["outputs"], entities, f"{location}.outputs", require_items=True)
            if details["cost"] is not None:
                _object(details["cost"], {"amount", "unit"}, set(), f"{location}.cost")
                _number(details["cost"]["amount"], f"{location}.cost.amount")
                _text(details["cost"]["unit"], f"{location}.cost.unit")
        elif kind == "loot":
            _object(details, {"table", "outcome", "quantity", "weight", "probability", "rolls"}, set(), location)
            _text(details["table"], f"{location}.table")
            _range(details["quantity"], f"{location}.quantity")
            if details["outcome"] is not None:
                _entity_reference(details["outcome"], entities, "item", f"{location}.outcome")
            elif details["quantity"] not in (None, {"min": 0, "max": 0}):
                raise DataError(f"{location}: explicit empty outcomes require null or exactly zero quantity")
            _range(details["rolls"], f"{location}.rolls")
            if details["weight"] is not None:
                _number(details["weight"], f"{location}.weight")
            if details["probability"] is not None:
                _number(details["probability"], f"{location}.probability", maximum=1)
        else:
            _object(details, {"page", "steps", "fact_ids"}, set(), location)
            if not isinstance(details["page"], str) or details["page"] not in ALGORITHM_PAGES:
                raise DataError(f"{location}.page: unsupported algorithm page")
            steps = details["steps"]
            if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
                raise DataError(f"{location}.steps: expected one to twenty original prose steps")
            for step_index, step in enumerate(steps):
                _text(step, f"{location}.steps[{step_index}]", 500)
            if not isinstance(details["fact_ids"], list) or len(details["fact_ids"]) > 32:
                raise DataError(f"{location}.fact_ids: expected at most 32 numeric fact references")
            references = set()
            for reference in details["fact_ids"]:
                _identifier(reference, f"{location}.fact_ids")
                if reference not in facts or reference in references:
                    raise DataError(f"{location}.fact_ids: missing or duplicate fact reference")
                references.add(reference)


def _validate_illustrations(records, sources, entities, stations=None):
    seen = set()
    titles = set()
    for index, illustration in enumerate(_records(records, "illustrations")):
        where = f"illustrations[{index}]"
        _object(
            illustration,
            {"id", "file_title", "caption", "creator", "sha256", "rights_status",
             "rights_basis", "rights_note", "confidence", "evidence"},
            {"entity", "station", "variant"}, where,
        )
        identity = _identifier(illustration["id"], f"{where}.id")
        if identity in seen:
            raise DataError(f"{where}: duplicate illustration ID")
        seen.add(identity)
        if ("entity" in illustration) == ("station" in illustration):
            raise DataError(f"{where}: provide exactly one entity or station target")
        if "entity" in illustration:
            entity_id = _identifier(illustration["entity"], f"{where}.entity")
            if entity_id not in entities or entities[entity_id]["category"] not in {"item", "being", "nature", "skill"}:
                raise DataError(f"{where}.entity: must reference an item, being, nature record, or skill")
            if "variant" in illustration:
                raise DataError(f"{where}: a variant belongs to a station, not an entity")
        else:
            station_id = _identifier(illustration["station"], f"{where}.station")
            if not stations or station_id not in stations:
                raise DataError(f"{where}.station: must reference a reviewed station")
            if "variant" in illustration:
                variant = _identifier(illustration["variant"], f"{where}.variant")
                if variant not in {row["id"] for row in stations[station_id].get("variants", [])}:
                    raise DataError(f"{where}.variant: must reference a reviewed station variant")
        title = illustration["file_title"]
        if not isinstance(title, str) or not re.fullmatch(r"File:[A-Z][A-Za-z0-9 _.-]{0,119}\.(?:png|jpg|jpeg|webp)", title):
            raise DataError(f"{where}.file_title: expected a plain local File title for a raster image")
        canonical = " ".join(title.replace("_", " ").split())
        if canonical in titles:
            raise DataError(f"{where}.file_title: duplicate canonical File title")
        titles.add(canonical)
        _text(illustration["caption"], f"{where}.caption", 500)
        _nullable_text(illustration["creator"], f"{where}.creator")
        _nullable_text(illustration["rights_basis"], f"{where}.rights_basis")
        _nullable_text(illustration["rights_note"], f"{where}.rights_note", 500)
        digest = illustration["sha256"]
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise DataError(f"{where}.sha256: expected a lowercase SHA-256 of the reviewed image bytes")
        if illustration["rights_status"] not in ("pending", "approved"):
            raise DataError(f"{where}.rights_status: expected pending or approved")
        if illustration["rights_status"] == "approved" and any(
            illustration[key] is None for key in ("creator", "sha256", "rights_basis", "rights_note")
        ):
            raise DataError(f"{where}: approved images require creator, hash, rights basis, and review note")
        _confidence(illustration["confidence"], f"{where}.confidence")
        _evidence(illustration["evidence"], sources, f"{where}.evidence")


def validate_data(data, stations=None):
    _object(data, {"schema_version", "game", "sources", "entities", "facts"}, {"entries", "illustrations"}, "root")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise DataError("schema_version: expected integer 1")
    game = data["game"]
    _object(game, {"name", "developer", "build", "steam_app_id"}, set(), "game")
    if game["name"] != "MirkLurk":
        raise DataError("game.name: expected the marketed title MirkLurk")
    _nullable_text(game["developer"], "game.developer")
    _nullable_text(game["build"], "game.build")
    if type(game["steam_app_id"]) is not int or game["steam_app_id"] != 3972980:
        raise DataError("game.steam_app_id: expected 3972980")

    sources = {}
    for index, source in enumerate(_records(data["sources"], "sources")):
        where = f"sources[{index}]"
        _object(source, {"id", "path", "sha256", "build"}, set(), where)
        identity = _identifier(source["id"], f"{where}.id")
        if identity in sources:
            raise DataError(f"{where}: duplicate source ID")
        path = _text(source["path"], f"{where}.path", 255)
        parts = path.replace("\\", "/").split("/")
        if (
            ":" in path
            or any(part in {"", ".", ".."} for part in parts)
            or not (parts[-1].lower().endswith(".ini") or parts[-1].lower() == "data.win")
        ):
            raise DataError(f"{where}.path: expected an installation-relative INI/data.win path")
        if not isinstance(source["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", source["sha256"]
        ):
            raise DataError(f"{where}.sha256: expected 64 lowercase hexadecimal characters")
        _nullable_text(source["build"], f"{where}.build")
        sources[identity] = source

    entities = {}
    for index, entity in enumerate(_records(data["entities"], "entities")):
        where = f"entities[{index}]"
        _object(
            entity,
            {"id", "category", "name", "confidence", "evidence"},
            {"group"},
            where,
        )
        identity = _identifier(entity["id"], f"{where}.id")
        if identity in entities:
            raise DataError(f"{where}: duplicate entity ID")
        if not isinstance(entity["category"], str) or entity["category"] not in CATEGORY_PAGES:
            raise DataError(f"{where}: unknown entity category")
        _text(entity["name"], f"{where}.name")
        _confidence(entity["confidence"], f"{where}.confidence")
        _evidence(entity["evidence"], sources, f"{where}.evidence")
        if entity["category"] == "skill":
            _identifier(entity.get("group"), f"{where}.group")
        elif "group" in entity:
            raise DataError(f"{where}: only skills may have a group")
        entities[identity] = entity
    for identity, entity in entities.items():
        if entity["category"] == "skill":
            group = entities.get(entity["group"])
            if group is None or group["category"] != "skill_group":
                raise DataError(f"entity {identity}: group must reference a skill_group")

    facts = set()
    for index, fact in enumerate(_records(data["facts"], "facts")):
        where = f"facts[{index}]"
        _object(
            fact,
            {"id", "page", "entity", "property", "value", "description", "confidence", "evidence"},
            set(),
            where,
        )
        identity = _identifier(fact["id"], f"{where}.id")
        if identity in facts:
            raise DataError(f"{where}: duplicate fact ID")
        facts.add(identity)
        if not isinstance(fact["page"], str) or fact["page"] not in FACT_PAGES:
            raise DataError(f"{where}: unsupported destination page")
        _text(fact["entity"], f"{where}.entity")
        _text(fact["property"], f"{where}.property")
        _text(fact["description"], f"{where}.description", 500)
        value = fact["value"]
        if type(value) not in {int, float, bool}:
            raise DataError(f"{where}.value: only numbers and booleans are permitted")
        if type(value) is float and not math.isfinite(value):
            raise DataError(f"{where}.value: expected a finite number")
        if type(value) is not bool and abs(value) > 10**15:
            raise DataError(f"{where}.value: exceeds the supported numeric range")
        _confidence(fact["confidence"], f"{where}.confidence")
        _evidence(fact["evidence"], sources, f"{where}.evidence")
    _validate_entries(data.get("entries", []), sources, entities, facts)
    _validate_illustrations(data.get("illustrations", []), sources, entities, stations)
    return data


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DataError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise DataError("JSON contains a non-finite number")


def parse_data(raw):
    if len(raw) > MAX_FACTS_BYTES:
        raise DataError("curated JSON exceeds the publication size limit")
    try:
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise DataError("curated JSON must be well-formed, UTF-8 JSON") from error
    return validate_data(data)


def load_data(path):
    with Path(path).open("rb") as stream:
        return parse_data(stream.read(MAX_FACTS_BYTES + 1))
