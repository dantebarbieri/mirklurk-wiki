"""Validate editorial page identities separately from immutable research records."""

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from wiki_data import (
    CATEGORY_PAGES, DataError, MECHANIC_GUIDE_TITLES, PAGE_FILES, RESEARCH_PAGE_FILES,
    _confidence, _entity_reference, _evidence, _identifier, _item_quantities, _nullable_text, _number,
    _object, _records, _text, _title, entry_page, title_key,
)
from wiki_acquisition import validate_acquisition


DEDICATED_CATEGORIES = {"item", "being", "nature", "skill", "damage_class"}
MAX_CATALOG_BYTES = 224 * 1024
RESERVED_TITLES = {*PAGE_FILES, *RESEARCH_PAGE_FILES, "NPCs", "Source provenance", "Loot mechanics"}
CURRENCY_RULE_TITLES = {
    "coin-denominations": "Denominations",
    "coin-consolidation": "Converting and consolidating coins",
    "coin-weight-units": "Weight and carrying",
    "trade-standard-value": "Buying and selling",
    "trade-stock-and-funds": "Stock and merchant funds",
    "trade-durability": "Durability and resale value",
    "trade-fuel": "Fuel takes priority",
    "trade-rounding": "Change and rounding",
}
RESERVED_TITLES.add("Currency and trading")
RESERVED_TITLES.update(MECHANIC_GUIDE_TITLES)


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


def skill_category_title(entity):
    name = title_key(entity["name"])
    return f'Skill group {entity["id"]}' if re.search(r"[\[\]{}|<>#:/\\]", name) else name


def category_definitions(data, catalog):
    """Resolve the single category graph used by validation and rendering."""
    entities = {row["id"]: row for row in data["entities"]}
    kinds = {row["entity"]: row["kind"] for row in catalog["classifications"]}
    categories = {}
    for row in catalog["pages"]:
        entity = entities[row["entity"]]
        root = "NPCs" if kinds.get(entity["id"]) == "npc" else CATEGORY_PAGES[entity["category"]]
        category = categories.setdefault(root, {
            "title": root, "index": root, "parents": [], "members": [],
            "summary": f"Browse {root} articles and their browsing categories. Each article keeps its own editable facts.",
        })
        category["members"].append(entity["id"])
    taxonomy = catalog.get("taxonomy", {})
    summaries = {row["entity"]: row["summary"] for row in taxonomy.get("skill_groups", [])}
    for entity in data["entities"]:
        if entity["category"] != "skill_group":
            continue
        title = skill_category_title(entity)
        if title in categories:
            raise DataError("taxonomy: duplicate skill or root category")
        categories[title] = {
            "title": title, "index": "Skills", "parents": ["Skills"],
            "members": [row["id"] for row in data["entities"] if row.get("group") == entity["id"]],
            "summary": summaries.get(entity["id"], f"Skills assigned to the localized {entity['name']} group. This is not an additional prerequisite tree."),
            "evidence": entity["evidence"], "confidence": entity["confidence"],
        }
    for row in [*taxonomy.get("groups", []), *taxonomy.get("tags", [])]:
        if row["title"] in categories:
            raise DataError("taxonomy: duplicate category")
        categories[row["title"]] = {
            **row, "parents": row.get("parents", [row["index"]]),
            "summary": row.get("summary", f"An editorial browsing group within {row['index']}. Membership does not establish availability or guarantee an outcome."),
        }
    return categories


def validate_category_graph(categories):
    if len(categories) > 128:
        raise DataError("taxonomy: expected at most 128 categories")
    visited = set()
    active = set()

    def visit(title):
        if title in active:
            raise DataError("taxonomy: category cycle")
        if title in visited:
            return
        active.add(title)
        row = categories[title]
        if not row["parents"] and title != row["index"]:
            raise DataError("taxonomy: orphan category")
        for parent in row["parents"]:
            if parent not in categories or categories[parent]["index"] != row["index"]:
                raise DataError("taxonomy: unknown parent or cross-index category")
            visit(parent)
        active.remove(title)
        visited.add(title)

    children = {parent for row in categories.values() for parent in row["parents"]}
    for title, row in categories.items():
        visit(title)
        if not row["members"] and title not in children:
            raise DataError("taxonomy: empty category leaf")


def validate_catalog(catalog, data):
    _object(catalog, {"schema_version", "pages", "classifications", "entry_links"},
            {"stations", "entry_display", "unit_prices", "currency", "taxonomy", "state_history", "guides",
             "damage_sources", "item_effects", "acquisition", "construction_recipes", "merchant_profiles"}, "catalog")
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
        raise DataError("catalog pages: every dedicated entity needs exactly one page")
    sources = {source["id"]: source for source in data["sources"]}
    damage_sources = set()
    for row in _records(catalog.get("damage_sources", []), "damage sources"):
        _object(row, {"entity", "damage_type", "delivery", "summary", "confidence", "evidence"}, set(), "damage source")
        for field, category in (("entity", "item"), ("damage_type", "damage_class")):
            identity = row[field]
            if not isinstance(identity, str) or identity not in entities or entities[identity]["category"] != category:
                raise DataError("damage source: expected known item and damage type")
        pair = (row["entity"], row["damage_type"])
        if pair in damage_sources or row["delivery"] not in ("ammunition", "thrown"):
            raise DataError("damage source: duplicate relation or unknown delivery")
        damage_sources.add(pair)
        _text(row["summary"], "damage source.summary", 1200)
        _confidence(row["confidence"], "damage source.confidence")
        _evidence(row["evidence"], sources, "damage source.evidence")
    guide_titles = {row["title"] for row in catalog["pages"] if entities[row["entity"]]["category"] == "damage_class"} | MECHANIC_GUIDE_TITLES
    registered_guides = {
        row["title"] for row in _records(catalog.get("guides", []), "guides")
        if isinstance(row, dict) and isinstance(row.get("title"), str)
    }
    guides_seen = set()
    for guide in _records(catalog.get("guides", []), "guides"):
        _object(guide, {"title", "paragraphs", "related_entities", "confidence", "evidence"},
                {"related_pages", "image_entity", "image_caption", "section_titles"}, "guide")
        title = _title(guide["title"])
        if title not in guide_titles or title in guides_seen:
            raise DataError("guide: duplicate or unsupported canonical owner")
        guides_seen.add(title)
        if not isinstance(guide["paragraphs"], list) or not 1 <= len(guide["paragraphs"]) <= 16:
            raise DataError("guide: expected one to sixteen original paragraphs")
        for paragraph in guide["paragraphs"]:
            _text(paragraph, "guide.paragraph", 1200)
        if "section_titles" in guide:
            headings = guide["section_titles"]
            if not isinstance(headings, list) or len(headings) != len(guide["paragraphs"]):
                raise DataError("guide: section titles must match its paragraph count")
            for heading in headings:
                _nullable_text(heading, "guide.section_title")
        related = guide["related_entities"]
        if not isinstance(related, list) or len(related) > 16 or any(
            not isinstance(identity, str) or identity not in required for identity in related
        ):
            raise DataError("guide: expected at most sixteen known related entities")
        if len(related) != len(set(related)):
            raise DataError("guide: duplicate related entity")
        related_pages = guide.get("related_pages", [])
        if not isinstance(related_pages, list) or len(related_pages) > len(guide_titles) or any(
            not isinstance(target, str) or target not in guide_titles or target == title
            for target in related_pages
        ) or len(related_pages) != len(set(related_pages)):
            raise DataError("guide: expected unique related canonical guide titles")
        if not set(related_pages) <= registered_guides:
            raise DataError("guide: related guide has no reviewed content")
        if ("image_entity" in guide) != ("image_caption" in guide):
            raise DataError("guide: contextual pictures require both an entity and an original caption")
        if "image_entity" in guide:
            identity = guide["image_entity"]
            if not isinstance(identity, str) or identity not in required or entities[identity]["category"] == "damage_class":
                raise DataError("guide: image must reference a documented illustrated entity")
            _text(guide["image_caption"], "guide.image_caption", 500)
        _confidence(guide["confidence"], "guide.confidence")
        _evidence(guide["evidence"], sources, "guide.evidence")
    effects_seen = set()
    for effect in _records(catalog.get("item_effects", []), "item effects"):
        _object(effect, {"entity", "paragraphs", "confidence", "evidence"}, set(), "item effect")
        identity = effect["entity"]
        if not isinstance(identity, str) or identity not in required or entities[identity]["category"] != "item" or identity in effects_seen:
            raise DataError("item effect: expected one record per known item")
        effects_seen.add(identity)
        if not isinstance(effect["paragraphs"], list) or not 1 <= len(effect["paragraphs"]) <= 4:
            raise DataError("item effect: expected one to four original paragraphs")
        for paragraph in effect["paragraphs"]:
            _text(paragraph, "item effect.paragraph", 1200)
        _confidence(effect["confidence"], "item effect.confidence")
        _evidence(effect["evidence"], sources, "item effect.evidence")
    classified = set()
    for row in _records(catalog["classifications"], "catalog.classifications"):
        _object(row, {"entity", "kind", "confidence", "evidence", "note"}, {"summary"}, "classification")
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
        if "summary" in row:
            _text(row["summary"], "classification.summary", 500)
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
    merchant_ids = {row["details"]["merchant"] for row in data.get("entries", []) if row["kind"] == "merchant"}
    profiled_merchants = set()
    for row in _records(catalog.get("merchant_profiles", []), "merchant profiles"):
        _object(row, {"entity", "conditions", "spoiler", "confidence", "evidence"}, {"compare_with"}, "merchant profile")
        identity = row["entity"]
        if not isinstance(identity, str) or identity not in merchant_ids or identity in profiled_merchants:
            raise DataError("merchant profile: expected one record per documented stock owner")
        profiled_merchants.add(identity)
        _text(row["conditions"], "merchant profile.conditions", 500)
        if type(row["spoiler"]) is not bool:
            raise DataError("merchant profile: spoiler must be boolean")
        if "compare_with" in row and (
            not isinstance(row["compare_with"], str) or row["compare_with"] not in merchant_ids or row["compare_with"] == identity
        ):
            raise DataError("merchant profile: comparison requires another documented stock owner")
        _confidence(row["confidence"], "merchant profile.confidence")
        _evidence(row["evidence"], sources, "merchant profile.evidence")
    if "merchant_profiles" in catalog and profiled_merchants != merchant_ids:
        raise DataError("merchant profiles: cover every documented stock owner")
    displayed = set()
    for row in _records(catalog.get("entry_display", []), "catalog.entry_display"):
        _object(row, {"entry"}, {"title", "summary", "conditions", "steps", "confidence", "evidence"}, "entry display")
        if not isinstance(row["entry"], str) or row["entry"] not in entry_ids or row["entry"] in displayed or len(row) == 1:
            raise DataError("entry display: expected one nonempty override per known entry")
        displayed.add(row["entry"])
        entry = next(entry for entry in data["entries"] if entry["id"] == row["entry"])
        if entry["kind"] == "merchant" and entry["details"]["merchant"] in profiled_merchants and "conditions" in row:
            raise DataError("entry display: merchant conditions already have a profile owner")
        if ("confidence" in row) != ("evidence" in row):
            raise DataError("entry display: supplementary evidence and confidence must appear together")
        if "evidence" in row:
            _confidence(row["confidence"], "entry display.confidence")
            _evidence(row["evidence"], sources, "entry display.evidence")
        for field, maximum in (("title", 160), ("summary", 1200), ("conditions", 500)):
            if field in row and row[field] is not None:
                _text(row[field], f"entry display.{field}", maximum)
            elif field in row and field != "conditions":
                raise DataError("entry display: title and summary cannot be null")
        if "steps" in row:
            entry = next(entry for entry in data["entries"] if entry["id"] == row["entry"])
            if entry["kind"] != "algorithm" or not isinstance(row["steps"], list) or len(row["steps"]) > 20:
                raise DataError("entry display: steps require at most twenty algorithm steps")
            for step in row["steps"]:
                _text(step, "entry display step", 500)
    if "taxonomy" in catalog:
        taxonomy = catalog["taxonomy"]
        _object(taxonomy, {"groups", "tags"}, {"skill_groups"}, "taxonomy")
        grouped = set()
        group_titles = set(CATEGORY_PAGES.values()) | {"NPCs"}
        classified_kind = {row["entity"]: row["kind"] for row in catalog["classifications"]}
        for field in ("groups", "tags"):
            for group in _records(taxonomy[field], f"taxonomy.{field}"):
                _object(group, {"title", "index", "members"},
                        {"parents", "summary", "confidence", "evidence"}, "taxonomy group")
                title = _title(group["title"])
                if title in group_titles or not isinstance(group["index"], str) or group["index"] not in {"Items", "Bestiary", "Nature"}:
                    raise DataError("taxonomy: duplicate category or unsupported index")
                group_titles.add(title)
                if "parents" in group:
                    parents = group["parents"]
                    if not isinstance(parents, list) or not 1 <= len(parents) <= 4:
                        raise DataError("taxonomy: expected one to four parents")
                    if len({_title(parent) for parent in parents}) != len(parents):
                        raise DataError("taxonomy: duplicate parent")
                    _text(group.get("summary"), "taxonomy.summary", 1200)
                if "summary" in group:
                    _text(group["summary"], "taxonomy.summary", 1200)
                if ("confidence" in group) != ("evidence" in group):
                    raise DataError("taxonomy: evidence and confidence must appear together")
                if "evidence" in group:
                    _confidence(group["confidence"], "taxonomy.confidence")
                    _evidence(group["evidence"], sources, "taxonomy.evidence")
                members = group["members"]
                if not isinstance(members, list) or len(members) > 500 or (field == "groups" and not members):
                    raise DataError("taxonomy: expected at most five hundred members; primary groups cannot be empty")
                seen_members = set()
                for identity in members:
                    if not isinstance(identity, str) or identity not in entities or identity in seen_members:
                        raise DataError("taxonomy: unknown or duplicate member")
                    seen_members.add(identity)
                    entity = entities[identity]
                    if CATEGORY_PAGES[entity["category"]] != group["index"] or (
                        entity["category"] == "being" and classified_kind.get(identity) != "creature"
                    ):
                        raise DataError("taxonomy: group must preserve entity type and NPC separation")
                    if field == "groups":
                        if identity in grouped:
                            raise DataError("taxonomy: each entity needs a single primary group")
                        grouped.add(identity)
        expected = {e["id"] for e in entities.values() if e["category"] in {"item", "nature"}
                    or (e["category"] == "being" and classified_kind.get(e["id"]) == "creature")}
        if grouped != expected:
            raise DataError("taxonomy: primary groups must cover every item, nature record and creature")
        described = set()
        for row in _records(taxonomy.get("skill_groups", []), "taxonomy.skill_groups"):
            _object(row, {"entity", "summary"}, set(), "skill group description")
            identity = row["entity"]
            if not isinstance(identity, str) or identity not in entities or entities[identity]["category"] != "skill_group" or identity in described:
                raise DataError("taxonomy: unknown or duplicate skill group description")
            described.add(identity)
            _text(row["summary"], "skill group.summary", 1200)
        if "skill_groups" in taxonomy and described != {row["id"] for row in entities.values() if row["category"] == "skill_group"}:
            raise DataError("taxonomy: describe every skill group exactly once")
    validate_category_graph(category_definitions(data, catalog))
    for history in _records(catalog.get("state_history", []), "state history"):
        _object(history, {"before", "after", "quest", "summary", "attribution", "recorded_on"}, {"evidence"}, "state history")
        for field in ("before", "after"):
            if not isinstance(history[field], str) or history[field] not in required or entities[history[field]]["category"] != "being":
                raise DataError("state history: expected known being pages")
        if history["before"] == history["after"]:
            raise DataError("state history: distinct states required")
        if not any(e["id"] == history["quest"] and e["kind"] == "quest" for e in data.get("entries", [])):
            raise DataError("state history: expected a known quest")
        _text(history["summary"], "state history.summary", 1200)
        if history["attribution"] != "Wiki operator":
            raise DataError("state history: expected operator attribution")
        try:
            if date.fromisoformat(history["recorded_on"]).isoformat() != history["recorded_on"]:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise DataError("state history: expected ISO date") from error
        if "evidence" in history:
            _evidence(history["evidence"], sources, "state history.evidence")
    construction = _records(catalog.get("construction_recipes", []), "catalog.construction_recipes")
    construction_ids = set()
    for recipe in construction:
        _object(recipe, {"id", "owner_item", "station_id", "station_title", "station_item", "inputs",
                         "base_ap_cost", "result", "condition", "confidence", "evidence"}, set(), "construction recipe")
        identity = _identifier(recipe["id"], "construction recipe.id")
        if identity in construction_ids or identity in {entry["id"] for entry in data.get("entries", [])}:
            raise DataError("construction recipe: duplicate record")
        construction_ids.add(identity)
        _identifier(recipe["station_id"], "construction recipe.station_id")
        _title(recipe["station_title"])
        for field in ("owner_item", "station_item"):
            _entity_reference(recipe[field], entities, "item", "construction recipe." + field)
        _item_quantities(recipe["inputs"], entities, "construction recipe.inputs", require_items=True)
        _number(recipe["base_ap_cost"], "construction recipe.base_ap_cost")
        _object(recipe["result"], {"kind", "description", "quantity"}, set(), "construction recipe.result")
        if recipe["result"]["kind"] != "in-place":
            raise DataError("construction recipe: only in-place outcomes are supported, never inventory outputs")
        _text(recipe["result"]["description"], "construction recipe.result.description", 500)
        _number(recipe["result"]["quantity"], "construction recipe.result.quantity", minimum=1, integer=True)
        _text(recipe["condition"], "construction recipe.condition", 1200)
        _confidence(recipe["confidence"], "construction recipe.confidence")
        _evidence(recipe["evidence"], sources, "construction recipe.evidence")
    methods = set()
    station_ids = set()
    canonical = {row["entity"]: row["title"] for row in catalog["pages"]}
    available_methods = {entry["details"]["station"] for entry in data.get("entries", []) if entry["kind"] == "recipe"}
    for row in _records(catalog.get("stations", []), "catalog.stations"):
        _object(row, {"id", "title", "entity", "methods", "summary", "acquisition", "confidence", "evidence"},
                {"notes", "variants", "reports", "related_entities", "related_stations", "quest_entries"}, "station")
        _identifier(row["id"], "station.id")
        if row["id"] in station_ids:
            raise DataError("station: duplicate ID")
        station_ids.add(row["id"])
        title = _title(row["title"])
        if row["entity"] is not None:
            if not isinstance(row["entity"], str) or row["entity"] not in canonical or entities[row["entity"]]["category"] != "item":
                raise DataError("station: expected a known item or null")
            if canonical[row["entity"]] != title:
                raise DataError("station: reuse the item's canonical page title")
        elif title in titles:
            raise DataError("station: duplicate or reserved page title")
        else:
            titles.add(title)
        if not isinstance(row["methods"], list) or not row["methods"] and not any(
            recipe["station_id"] == row["id"] for recipe in construction
        ):
            raise DataError("station: expected evidenced recipe methods")
        for method in row["methods"]:
            if not isinstance(method, str) or method not in available_methods or method in methods:
                raise DataError("station: missing, duplicate, or unknown recipe method")
            methods.add(method)
        _text(row["summary"], "station.summary", 1200)
        _nullable_text(row["acquisition"], "station.acquisition", 1200)
        _confidence(row["confidence"], "station.confidence")
        _evidence(row["evidence"], sources, "station.evidence")
        if "notes" in row:
            if not isinstance(row["notes"], list) or len(row["notes"]) > 12:
                raise DataError("station.notes: expected at most twelve original notes")
            for note in row["notes"]:
                _text(note, "station.note", 500)
        variants = set()
        for variant in _records(row.get("variants", []), "station.variants"):
            _object(variant, {"id", "title"}, set(), "station variant")
            identity = _identifier(variant["id"], "station variant.id")
            _text(variant["title"], "station variant.title")
            if identity in variants:
                raise DataError("station variant: duplicate ID")
            variants.add(identity)
        reports = set()
        for report in _records(row.get("reports", []), "station.reports"):
            _object(report, {"id", "section", "text", "attribution", "recorded_on"}, set(), "operator report")
            identity = _identifier(report["id"], "operator report.id")
            if identity in reports:
                raise DataError("operator report: duplicate ID")
            reports.add(identity)
            if report["section"] is not None and (not isinstance(report["section"], str) or report["section"] not in variants):
                raise DataError("operator report: unknown variant section")
            _text(report["text"], "operator report.text", 1200)
            if report["attribution"] != "Wiki operator":
                raise DataError("operator report: attribution must identify the wiki operator without personal details")
            _text(report["recorded_on"], "operator report.recorded_on", 10)
            try:
                if date.fromisoformat(report["recorded_on"]).isoformat() != report["recorded_on"]:
                    raise ValueError
            except ValueError as error:
                raise DataError("operator report: expected an ISO calendar date") from error
        related = row.get("related_entities", [])
        if not isinstance(related, list) or len(related) > 12:
            raise DataError("station.related_entities: expected at most twelve identities")
        for identity in related:
            if not isinstance(identity, str) or identity not in entities:
                raise DataError("station.related_entities: unknown entity")
        for identity in _records(row.get("quest_entries", []), "station.quest_entries"):
            if not isinstance(identity, str) or not any(entry["id"] == identity and entry["kind"] == "quest" for entry in data.get("entries", [])):
                raise DataError("station.quest_entries: expected a known quest entry")
    if "stations" in catalog and methods != available_methods:
        raise DataError("station registry must account for every documented recipe method")
    for row in catalog.get("stations", []):
        related = row.get("related_stations", [])
        if not isinstance(related, list) or len(related) > 8:
            raise DataError("station alternatives: expected at most eight stations")
        if any(not isinstance(identity, str) or identity not in station_ids or identity == row["id"] for identity in related):
            raise DataError("station alternatives: expected other known stations")
    if "unit_prices" in catalog:
        prices = catalog["unit_prices"]
        _object(prices, {"schema_version", "unit", "context", "prices", "covered_offers", "unresolved_offers"}, set(), "unit prices")
        if type(prices["schema_version"]) is not int or prices["schema_version"] != 1 or prices["unit"] != "silver coin equivalents":
            raise DataError("unit prices: expected version 1 and verified silver-equivalent units")
        _text(prices["context"], "unit price context", 1200)
        priced = set()
        for price in _records(prices["prices"], "unit prices.prices"):
            _object(price, {"entity", "value", "confidence", "evidence"}, set(), "unit price")
            identity = price["entity"]
            if not isinstance(identity, str) or identity not in entities or entities[identity]["category"] != "item" or identity in priced:
                raise DataError("unit price: missing, duplicate, or non-item identity")
            priced.add(identity)
            _number(price["value"], "unit price.value")
            _confidence(price["confidence"], "unit price.confidence")
            _evidence(price["evidence"], sources, "unit price.evidence")
        offers = [row for row in data.get("entries", []) if row["kind"] == "merchant"]
        for field, known_price in (("covered_offers", True), ("unresolved_offers", False)):
            actual = _records(prices[field], f"unit prices.{field}")
            expected = {row["id"] for row in offers if (row["details"]["item"] in priced) == known_price}
            if any(not isinstance(identity, str) for identity in actual) or len(actual) != len(set(actual)) or set(actual) != expected:
                raise DataError(f"unit prices.{field}: must exactly match the offer-to-item references")
    if "currency" in catalog:
        currency = catalog["currency"]
        _object(currency, {"schema_version", "documented_build", "coins", "rules", "confidence"}, {"standard_merchants"}, "currency")
        if type(currency["schema_version"]) is not int or currency["schema_version"] != 1:
            raise DataError("currency: expected schema version 1")
        _confidence(currency["confidence"], "currency.confidence")
        build = currency["documented_build"]
        _object(build, {"version", "confirmation", "evidence"}, set(), "build confirmation")
        if build["version"] != data["game"]["build"]:
            raise DataError("build confirmation must match the documented game build")
        _text(build["confirmation"], "build confirmation.text", 1200)
        _evidence(build["evidence"], sources, "build confirmation.evidence")
        coins = set()
        for coin in _records(currency["coins"], "currency.coins"):
            _object(coin, {"entity", "value_in_silver", "weight_kg", "weight_grams", "stack_limit", "evidence"}, set(), "coin")
            identity = coin["entity"]
            if not isinstance(identity, str) or identity not in entities or entities[identity]["category"] != "item" or identity in coins:
                raise DataError("coin: missing, duplicate, or non-item identity")
            coins.add(identity)
            for field in ("value_in_silver", "weight_kg", "weight_grams"):
                _number(coin[field], f"coin.{field}")
                if coin[field] == 0:
                    raise DataError("coin values and weights must be positive")
            _number(coin["stack_limit"], "coin.stack_limit", minimum=1, integer=True)
            _evidence(coin["evidence"], sources, "coin.evidence")
        if coins != {"item-72", "item-73", "item-74"}:
            raise DataError("currency requires the three reviewed coin identities")
        offers = {row["details"]["item"] for row in data.get("entries", []) if row["kind"] == "merchant"}
        if coins & offers:
            raise DataError("coin summary rows cannot also serve as merchant price-only transclusions")
        seen_rules = set()
        for rule in _records(currency["rules"], "currency.rules"):
            _object(rule, {"id", "text", "evidence"}, {"qualification"}, "currency rule")
            identity = _identifier(rule["id"], "currency rule.id")
            if identity in seen_rules or identity not in CURRENCY_RULE_TITLES:
                raise DataError("currency rule needs a unique reviewed display title")
            seen_rules.add(identity)
            _text(rule["text"], "currency rule.text", 1200)
            _nullable_text(rule.get("qualification"), "currency rule.qualification", 1200)
            _evidence(rule["evidence"], sources, "currency rule.evidence")
        if not CURRENCY_RULE_TITLES.keys() - {"trade-stock-and-funds"} <= seen_rules:
            raise DataError("currency guide must retain every reviewed rule")
        if ("trade-stock-and-funds" in seen_rules) != ("standard_merchants" in currency):
            raise DataError("currency: stock rules require an explicit merchant scope")
        if "standard_merchants" in currency:
            merchants = _records(currency["standard_merchants"], "currency.standard_merchants")
            offers = [row for row in data.get("entries", []) if row["kind"] == "merchant"]
            expected = {row["details"]["merchant"] for row in offers}
            if any(not isinstance(identity, str) for identity in merchants) or len(merchants) != len(set(merchants)) or set(merchants) != expected:
                raise DataError("currency: standard merchant scope must match the documented stock owners")
            if any(row["details"]["quantity"] is not None for row in offers):
                raise DataError("currency: unlimited stock cannot override an explicit offer quantity")
    station_by_id = {station["id"]: station for station in catalog.get("stations", [])}
    for recipe in construction:
        station = station_by_id.get(recipe["station_id"])
        if station is None or station["entity"] != recipe["station_item"] or station["title"] != recipe["station_title"]:
            raise DataError("construction recipe: station identity does not match the canonical registry")
    if "acquisition" in catalog:
        existing_titles = (
            set(PAGE_FILES) | {"NPCs", "Source provenance"}
            | {title for row in catalog["pages"] for title in [row["title"], *row["aliases"]]}
            | {row["title"] for row in catalog.get("guides", [])}
            | {row["title"] for row in catalog.get("stations", [])}
            | {entry_page(row) for row in data.get("entries", [])}
            | {row["page"] for row in data["facts"]}
        )
        if "currency" in catalog:
            existing_titles.add("Currency and trading")
        if any(row["kind"] == "loot" for row in data.get("entries", [])):
            existing_titles.add("Loot mechanics")
        validate_acquisition(catalog["acquisition"], data, existing_titles)
        construction_notes = {note["item"] for note in catalog["acquisition"].get("item_notes", [])
                              if note["kind"] == "construction-action"}
        if construction_notes != {recipe["owner_item"] for recipe in construction}:
            raise DataError("construction recipes and construction-action notes must have the same canonical owners")
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
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs, parse_float=Decimal)
    except (UnicodeDecodeError, ValueError) as error:
        raise DataError("catalog must be valid UTF-8 JSON without duplicate keys") from error
    if isinstance(value, dict) and "acquisition" in value:
        raise DataError("acquisition records must be stored only in acquisition.json")
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
        result[fact["id"]] = "Action points" if fact["id"] == "turn-minutes" else locations[candidates[0]["id"]] if candidates else (
            "Level progression" if fact["page"] == "Skills" else fact["page"]
        )
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


def entry_owners(data, locations, relations, catalog=None):
    entities = {entity["id"]: entity for entity in data["entities"]}
    result = {}
    source_owners = {identity: source["title"] for source in (catalog or {}).get("acquisition", {}).get("sources", [])
                     for identity in source.get("existing_entry_ids", [])}
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
        target = locations[owner] if owner else entry_page(entry)
        if entry["kind"] == "algorithm" and details["page"] == "Loot tables":
            target = "Loot mechanics"
        if entry["kind"] == "loot" and owner is None:
            target = "Loot mechanics"
        if entry["kind"] == "algorithm" and details["page"] == "Skills" and owner is None:
            target = "Level progression"
        if entry["kind"] == "algorithm" and details["page"] == "Crafting" and catalog and any(
            row["id"] == "inventory-crafting" for row in catalog.get("stations", [])
        ):
            target = "Inventory crafting"
        result[entry["id"]] = source_owners.get(entry["id"], target)
    return result
