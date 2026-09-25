"""Strict validation for the deliberately small, public facts format."""

import json
import math
import re
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
}
CATEGORY_PAGES = {
    "item": "Items",
    "being": "Bestiary",
    "nature": "Nature",
    "skill_group": "Skills",
    "skill": "Skills",
    "damage_class": "Damage types",
}
FACT_PAGES = {"Game mechanics", *CATEGORY_PAGES.values()}
CONFIDENCES = {"observed", "inferred", "localization-described"}
MAX_FACTS_BYTES = 512 * 1024
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


def _nullable_text(value, location):
    if value is not None:
        _text(value, location)


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


def validate_data(data):
    _object(data, {"schema_version", "game", "sources", "entities", "facts"}, set(), "root")
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
