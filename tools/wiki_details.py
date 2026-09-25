"""Bounded numeric profiles and rights-reviewed image metadata, never image bytes."""

import json
from decimal import Decimal
from pathlib import Path

from wiki_data import (
    DataError, _confidence, _evidence, _identifier, _nullable_text, _number,
    _object, _records, _text, _validate_illustrations, load_data,
)
from wiki_catalog import DEDICATED_CATEGORIES, load_catalog


MAX_DETAILS_BYTES = 768 * 1024
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
    _object(details, {"schema_version", "properties", "profiles"}, {"grids"}, "entity details")
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
    grid_ids = set()
    grid_owners = set()
    grids = _records(details.get("grids", []), "grids")
    if len(grids) > 256:
        raise DataError("grids: expected at most 256 reviewed grids")
    for grid in grids:
        _object(grid, {"id", "entity", "kind", "rows", "context", "confidence", "evidence"}, set(), "grid")
        identity = _identifier(grid["id"], "grid.id")
        if identity in grid_ids:
            raise DataError("grid: duplicate ID")
        grid_ids.add(identity)
        entity = grid["entity"]
        kind = grid["kind"]
        if not isinstance(entity, str) or entity not in entities or entities[entity]["category"] not in {"item", "being"}:
            raise DataError("grid: expected known item or being")
        if not isinstance(kind, str) or kind not in {"health", "melee", "ranged"} or (entity, kind) in grid_owners:
            raise DataError("grid: unsupported or duplicate entity/kind")
        grid_owners.add((entity, kind))
        if kind == "health" and entities[entity]["category"] != "being":
            raise DataError("grid: health belongs to beings")
        _text(grid["context"], "grid.context", 1200)
        _confidence(grid["confidence"], "grid.confidence")
        _evidence(grid["evidence"], sources, "grid.evidence")
        rows = grid["rows"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
            raise DataError("grid: expected one to thirty-two rows")
        if not isinstance(rows[0], list) or not 1 <= len(rows[0]) <= 32:
            raise DataError("grid: expected one to thirty-two columns")
        width = len(rows[0])
        occupied = []
        for row in rows:
            if not isinstance(row, list) or len(row) != width:
                raise DataError("grid: rows must be rectangular; use null for holes")
            for cell in row:
                if cell is None:
                    continue
                if kind == "health":
                    _object(cell, {"health", "armor"}, set(), "health cell")
                    if type(cell["health"]) is not int or cell["health"] != 1:
                        raise DataError("health cell: base health is exactly one; wounded states are not base health")
                    _number(cell["armor"], "health cell.armor", maximum=3, integer=True)
                else:
                    _object(cell, {"min", "max"}, set(), "attack cell")
                    _number(cell["min"], "attack cell.min", maximum=1000, integer=True)
                    _number(cell["max"], "attack cell.max", minimum=max(1, cell["min"]), maximum=1000, integer=True)
                occupied.append(cell)
        if kind == "health" and not occupied:
            raise DataError("health grid: at least one occupied cell required")
        values = {key: value for profile in details["profiles"] if profile["entity"] == entity
                  for key, value in profile["values"].items()}
        if kind == "health":
            expected = {"hp-grid-width": width, "hp-grid-height": len(rows)}
        else:
            expected = {f"{kind}-pattern-{bound}": sum(cell[bound] for cell in occupied) for bound in ("min", "max")}
        if any(key not in values or values[key] != value for key, value in expected.items()):
            raise DataError("grid: shape or occupied-cell totals disagree with reviewed scalar profile")
    return details


def parse_details(raw, data):
    return validate_details(parse_document(raw, MAX_DETAILS_BYTES), data)


def parse_illustrations(raw, data, catalog=None):
    document = parse_document(raw, MAX_ILLUSTRATIONS_BYTES)
    _object(document, {"schema_version", "illustrations"}, set(), "image metadata")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise DataError("image metadata schema_version: expected integer 1")
    images = _records(document["illustrations"], "illustrations")
    _validate_illustrations(
        [*data.get("illustrations", []), *images],
        {source["id"]: source for source in data["sources"]},
        {entity["id"]: entity for entity in data["entities"]},
        {row["id"]: row for row in catalog.get("stations", [])} if catalog else None,
    )
    return images


def read_metadata(path, maximum):
    path = Path(path)
    if path.is_symlink():
        raise DataError("reviewed metadata cannot be a symlink")
    with path.open("rb") as stream:
        return stream.read(maximum + 1)


def validate_coin_profiles(catalog, details):
    for coin in catalog.get("currency", {}).get("coins", []):
        matching = [row for row in details["profiles"] if row["entity"] == coin["entity"]]
        for field, property_id in (("value_in_silver", "initial-price"), ("weight_kg", "initial-weight"), ("stack_limit", "stack-limit")):
            if not any(row["values"].get(property_id) is not None
                       and Decimal(str(row["values"][property_id])) == Decimal(str(coin[field])) for row in matching):
                raise DataError("coin summary must agree with its reviewed initializer profile")
        if Decimal(str(coin["weight_kg"])) * 1000 != Decimal(str(coin["weight_grams"])):
            raise DataError("coin kilogram and gram values disagree")


def load_publication_inputs(root):
    folder = Path(root) / "content" / "facts"
    data = load_data(folder / "game.json")
    catalog = load_catalog(folder / "catalog.json", data)
    images = parse_illustrations(read_metadata(folder / "illustrations.json", MAX_ILLUSTRATIONS_BYTES), data, catalog)
    data = dict(data, illustrations=[*data.get("illustrations", []), *images])
    details = parse_details(read_metadata(folder / "entity_details.json", MAX_DETAILS_BYTES), data)
    validate_coin_profiles(catalog, details)
    return data, catalog, details
