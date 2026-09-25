"""Validate editorial page identities separately from immutable research records."""

import json
import re
from pathlib import Path

from wiki_data import (
    CATEGORY_PAGES, DataError, PAGE_FILES, RESEARCH_PAGE_FILES,
    _confidence, _evidence, _object, _records, _text, entry_page,
)


DEDICATED_CATEGORIES = {"item", "being", "nature", "skill"}
MAX_CATALOG_BYTES = 128 * 1024
RESERVED_TITLES = {*PAGE_FILES, *RESEARCH_PAGE_FILES, "NPCs", "Source provenance"}


def title_key(title):
    normalized = " ".join(title.replace("_", " ").split())
    return normalized[:1].upper() + normalized[1:]


def _title(value):
    _text(value, "catalog title")
    if (
        value != title_key(value) or re.search(r"[\[\]{}|<>#:/\\]", value)
        or value in {".", ".."} or value.startswith(".")
    ):
        raise DataError("catalog title: expected a canonical, plain main-namespace title")
    return value


def default_catalog(data):
    """Propose titles for new datasets; publication uses the checked-in registry."""
    names = {}
    for entity in data["entities"]:
        if entity["category"] in DEDICATED_CATEGORIES:
            names.setdefault(title_key(entity["name"]), []).append(entity)
    pages = []
    for name, entities in sorted(names.items()):
        for entity in sorted(entities, key=lambda row: row["id"]):
            title = name
            if len(entities) > 1 or title in RESERVED_TITLES:
                title += f' ({entity["category"]})'
            if re.search(r"[\[\]{}|<>#:/\\]", title):
                title = f'Entity {entity["id"]}'
            pages.append({"entity": entity["id"], "title": title, "aliases": []})
    return {"schema_version": 1, "pages": pages, "classifications": [], "entry_links": []}


def validate_catalog(catalog, data):
    _object(catalog, {"schema_version", "pages", "classifications", "entry_links"}, set(), "catalog")
    if type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1:
        raise DataError("catalog schema_version: expected integer 1")
    entities = {entity["id"]: entity for entity in data["entities"]}
    required = {identity for identity, entity in entities.items() if entity["category"] in DEDICATED_CATEGORIES}
    seen = set()
    titles = set(RESERVED_TITLES)
    for row in _records(catalog["pages"], "catalog.pages"):
        _object(row, {"entity", "title", "aliases"}, set(), "catalog page")
        identity = row["entity"]
        if not isinstance(identity, str) or identity not in required or identity in seen:
            raise DataError("catalog page: missing, duplicate, or unsupported entity")
        seen.add(identity)
        if not isinstance(row["aliases"], list) or len(row["aliases"]) > 8:
            raise DataError("catalog aliases: expected at most eight previous titles")
        for value in [row["title"], *row["aliases"]]:
            title = _title(value)
            if title in titles:
                raise DataError("catalog title: duplicate or reserved title")
            titles.add(title)
    if seen != required:
        raise DataError("catalog pages: every item, being, nature record, and skill needs exactly one page")
    sources = {source["id"]: source for source in data["sources"]}
    classified = set()
    for row in _records(catalog["classifications"], "catalog.classifications"):
        _object(row, {"entity", "kind", "confidence", "evidence", "note"}, set(), "classification")
        identity = row["entity"]
        if (
            not isinstance(identity, str) or identity not in entities
            or entities[identity]["category"] != "being" or identity in classified
        ):
            raise DataError("classification: expected one classification per known being")
        classified.add(identity)
        if row["kind"] not in ("npc", "creature", "unclassified"):
            raise DataError("classification: unknown kind")
        _confidence(row["confidence"], "classification.confidence")
        _evidence(row["evidence"], sources, "classification.evidence")
        _text(row["note"], "classification.note", 500)
    entry_ids = {entry["id"] for entry in data.get("entries", [])}
    linked = set()
    for row in _records(catalog["entry_links"], "catalog.entry_links"):
        _object(row, {"entry", "entities"}, set(), "entry link")
        if not isinstance(row["entry"], str) or row["entry"] not in entry_ids or row["entry"] in linked:
            raise DataError("entry link: missing or duplicate entry")
        linked.add(row["entry"])
        if not isinstance(row["entities"], list) or not 1 <= len(row["entities"]) <= 32:
            raise DataError("entry link: expected one to thirty-two entities")
        found = set()
        for identity in row["entities"]:
            if not isinstance(identity, str) or identity not in entities or identity in found:
                raise DataError("entry link: missing or duplicate entity")
            found.add(identity)
    return catalog


def parse_catalog(raw, data):
    if len(raw) > MAX_CATALOG_BYTES:
        raise DataError("catalog exceeds its size limit")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DataError("catalog has duplicate JSON keys")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, ValueError) as error:
        raise DataError("catalog must be valid UTF-8 JSON without duplicate keys") from error
    return validate_catalog(value, data)


def load_catalog(path, data):
    path = Path(path)
    if path.is_symlink():
        raise DataError("catalog cannot be a symlink")
    with path.open("rb") as stream:
        return parse_catalog(stream.read(MAX_CATALOG_BYTES + 1), data)


def page_locations(data, catalog):
    locations = {
        entity["id"]: f'{CATEGORY_PAGES[entity["category"]]}#entity-{entity["id"]}'
        for entity in data["entities"]
    }
    locations.update({row["entity"]: row["title"] for row in catalog["pages"]})
    return locations


def fact_owners(data, locations):
    result = {}
    for fact in data["facts"]:
        categories = {
            "Items": {"item"}, "Bestiary": {"being"}, "Nature": {"nature"},
            "Game mechanics": {"skill"}, "Skills": {"skill"},
        }.get(fact["page"], set())
        candidates = [
            entity for entity in data["entities"]
            if entity["category"] in categories and entity["name"] == fact["entity"]
        ]
        if len(candidates) > 1:
            raise DataError("fact owner is ambiguous; curate an unambiguous identity before publication")
        result[fact["id"]] = locations[candidates[0]["id"]] if candidates else fact["page"]
    return result


def entry_relations(data, catalog):
    identity_evidence = {}
    for entity in data["entities"]:
        for reference in entity["evidence"]:
            key = tuple(reference[field] for field in ("source", "section", "key"))
            identity_evidence.setdefault(key, set()).add(entity["id"])
    extra = {row["entry"]: set(row["entities"]) for row in catalog["entry_links"]}
    result = {}
    for entry in data.get("entries", []):
        subjects = set(extra.get(entry["id"], set()))
        for reference in entry["evidence"]:
            key = tuple(reference[field] for field in ("source", "section", "key"))
            subjects.update(identity_evidence.get(key, set()))
        details = entry["details"]
        if entry["kind"] == "merchant":
            subjects.update([details["merchant"], details["item"]])
        elif entry["kind"] == "recipe":
            subjects.update(row["item"] for row in details["inputs"] + details["outputs"])
        elif entry["kind"] == "loot" and details["outcome"] is not None:
            subjects.add(details["outcome"])
        result[entry["id"]] = subjects
    return result


def entry_owners(data, locations, relations):
    entities = {entity["id"]: entity for entity in data["entities"]}
    result = {}
    for entry in data.get("entries", []):
        details = entry["details"]
        owner = None
        if entry["kind"] == "merchant":
            owner = details["merchant"]
        elif entry["kind"] == "recipe":
            owner = min(row["item"] for row in details["outputs"])
        elif entry["kind"] == "loot":
            beings = sorted(identity for identity in relations[entry["id"]] if entities[identity]["category"] == "being")
            owner = beings[0] if len(beings) == 1 else details["outcome"]
        elif entry["kind"] == "algorithm" and details["page"] == "Skills":
            identity = entry["id"].removesuffix("-mechanics")
            if identity in entities and entities[identity]["category"] == "skill":
                owner = identity
        result[entry["id"]] = locations[owner] if owner else entry_page(entry)
    return result
