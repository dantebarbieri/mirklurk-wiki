"""Resolve authored page-title cross-references to the source entity IDs used internally."""

from wiki_data import DataError


# Authored cross-references name an entity by its canonical page title. Each path is a sequence of keys;
# "*" walks every list element. Records keyed by their own subject (pages, classifications, profiles,
# prices, illustrations) and extracted loot-pool memberships keep source IDs.
CATALOG_REFERENCES = (
    ("guides", "*", "related_entities", "*"),
    ("guides", "*", "image_entity"),
    ("classifications", "*", "ability", "related_entities", "*"),
    ("classifications", "*", "location", "related_entities", "*"),
    ("stations", "*", "related_entities", "*"),
    ("taxonomy", "tags", "*", "members", "*"),
    ("taxonomy", "groups", "*", "members", "*"),
    ("aggression", "factions", "*", "members", "*"),
    ("entry_links", "*", "entities", "*"),
    ("state_history", "*", "before"),
    ("state_history", "*", "after"),
    ("currency", "standard_merchants", "*"),
    ("merchant_profiles", "*", "compare_with"),
    ("construction_recipes", "*", "owner_item"),
    ("construction_recipes", "*", "station_item"),
    ("construction_recipes", "*", "inputs", "*", "item"),
    ("damage_sources", "*", "damage_type"),
)
ACQUISITION_REFERENCES = (
    ("sources", "*", "related_entities", "*"),
    ("sources", "*", "image_entity"),
    ("sources", "*", "rows", "*", "item"),
    ("item_notes", "*", "related_items", "*"),
)


def page_title_entities(catalog):
    """Canonical page title -> entity ID, from the catalog's own page registry."""
    pages = catalog.get("pages") if isinstance(catalog, dict) else None
    return {row["title"]: row["entity"] for row in pages if isinstance(row, dict)
            and isinstance(row.get("title"), str) and isinstance(row.get("entity"), str)} if isinstance(pages, list) else {}


def _reference(value, titles, location):
    if not isinstance(value, str) or value not in titles:
        raise DataError(f"{location}: {value!r} is not a canonical page title; name entities by their page title, not an ID")
    return titles[value]


def _resolve_path(node, path, titles, location):
    if not path:
        return _reference(node, titles, location)
    key, rest = path[0], path[1:]
    if key == "*":
        if isinstance(node, list):
            for index, child in enumerate(node):
                node[index] = _resolve_path(child, rest, titles, location)
        return node
    if isinstance(node, dict) and key in node:
        node[key] = _resolve_path(node[key], rest, titles, f"{location}.{key}")
    return node


def _resolve_guide_cells(catalog, titles):
    for guide in catalog.get("guides", []) if isinstance(catalog.get("guides"), list) else []:
        for table in guide.get("tables", []) if isinstance(guide, dict) and isinstance(guide.get("tables"), list) else []:
            for row in table.get("rows", []) if isinstance(table, dict) and isinstance(table.get("rows"), list) else []:
                for cell in row if isinstance(row, list) else []:
                    for ref in cell if isinstance(cell, list) else [cell]:
                        if isinstance(ref, dict) and len(ref) == 1 and "entity" in ref:
                            ref["entity"] = _reference(ref["entity"], titles, "guide.table.cell.entity")


def resolve_references(document, paths, titles, location):
    """Replace authored page titles with entity IDs in place; unknown titles and raw IDs are errors."""
    if isinstance(document, dict):
        for path in paths:
            _resolve_path(document, path, titles, location)
    return document


def resolve_catalog_references(catalog):
    titles = page_title_entities(catalog)
    if isinstance(catalog, dict):
        resolve_references(catalog, CATALOG_REFERENCES, titles, "catalog")
        _resolve_guide_cells(catalog, titles)
    return catalog


def resolve_acquisition_references(acquisition, catalog):
    return resolve_references(acquisition, ACQUISITION_REFERENCES, page_title_entities(catalog), "acquisition")
