"""Bounded numeric profiles and rights-reviewed image metadata, never image bytes."""

import json
from pathlib import Path

from wiki_data import (
    DataError, _confidence, _evidence, _identifier, _nullable_text, _number,
    _object, _records, _text, _validate_illustrations, load_data,
)
from wiki_catalog import DEDICATED_CATEGORIES, load_catalog


MAX_DETAILS_BYTES = 512 * 1024
MAX_ILLUSTRATIONS_BYTES = 512 * 1024


def empty_details():
    return {"schema_version": 1, "properties": [], "profiles": []}


def parse_document(raw, maximum):
    if len(raw) > maximum:
        raise DataError("reviewed metadata exceeds its size limit")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DataError("reviewed metadata contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, ValueError) as error:
        raise DataError("reviewed metadata must be valid UTF-8 JSON without duplicate keys") from error


def validate_details(details, data):
    _object(details, {"schema_version", "properties", "profiles"}, set(), "entity details")
    if type(details["schema_version"]) is not int or details["schema_version"] != 1:
        raise DataError("entity details schema_version: expected integer 1")
    properties = set()
    for row in _records(details["properties"], "properties"):
        _object(row, {"id", "label", "unit", "description"}, set(), "property")
        identity = _identifier(row["id"], "property.id")
        if identity in properties:
            raise DataError("property: duplicate ID")
        properties.add(identity)
        _text(row["label"], "property.label")
        _nullable_text(row["unit"], "property.unit")
        _text(row["description"], "property.description", 500)
    sources = {source["id"]: source for source in data["sources"]}
    entities = {entity["id"]: entity for entity in data["entities"]}
    profiles = set()
    for row in _records(details["profiles"], "profiles"):
        _object(row, {"id", "entity", "context", "confidence", "evidence", "values"}, set(), "profile")
        identity = _identifier(row["id"], "profile.id")
        if identity in profiles:
            raise DataError("profile: duplicate ID")
        profiles.add(identity)
        entity = row["entity"]
        if not isinstance(entity, str) or entity not in entities or entities[entity]["category"] not in DEDICATED_CATEGORIES:
            raise DataError("profile: unknown or unsupported entity")
        _text(row["context"], "profile.context", 1200)
        _confidence(row["confidence"], "profile.confidence")
        _evidence(row["evidence"], sources, "profile.evidence")
        if not isinstance(row["values"], dict) or not 1 <= len(row["values"]) <= 64:
            raise DataError("profile.values: expected one to sixty-four named numeric/boolean values")
        for key, value in row["values"].items():
            if key not in properties:
                raise DataError("profile value refers to an undeclared property")
            if value is not None and type(value) is not bool:
                _number(value, f"profile.values.{key}", minimum=-(10**15))
    return details


def parse_details(raw, data):
    return validate_details(parse_document(raw, MAX_DETAILS_BYTES), data)


def parse_illustrations(raw, data):
    document = parse_document(raw, MAX_ILLUSTRATIONS_BYTES)
    _object(document, {"schema_version", "illustrations"}, set(), "image metadata")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise DataError("image metadata schema_version: expected integer 1")
    images = _records(document["illustrations"], "illustrations")
    _validate_illustrations(
        [*data.get("illustrations", []), *images],
        {source["id"]: source for source in data["sources"]},
        {entity["id"]: entity for entity in data["entities"]},
    )
    return images


def read_metadata(path, maximum):
    path = Path(path)
    if path.is_symlink():
        raise DataError("reviewed metadata cannot be a symlink")
    with path.open("rb") as stream:
        return stream.read(maximum + 1)


def load_publication_inputs(root):
    folder = Path(root) / "content" / "facts"
    data = load_data(folder / "game.json")
    images = parse_illustrations(read_metadata(folder / "illustrations.json", MAX_ILLUSTRATIONS_BYTES), data)
    data = dict(data, illustrations=[*data.get("illustrations", []), *images])
    catalog = load_catalog(folder / "catalog.json", data)
    details = parse_details(read_metadata(folder / "entity_details.json", MAX_DETAILS_BYTES), data)
    return data, catalog, details
