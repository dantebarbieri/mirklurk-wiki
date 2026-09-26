"""Bounded evidence-backed acquisition sources, separate from historical research."""

from wiki_data import (
    DataError, _confidence, _entity_reference, _evidence, _identifier, _nullable_text,
    _number, _object, _range, _records, _text, _title,
)


MAX_ACQUISITION_BYTES = 256 * 1024
SOURCE_KINDS = {"starting", "fixed-location", "world-feature", "gathering", "container",
                "loot-rules", "random-container", "enemy", "story", "item-use"}
ROW_COVERAGE = {"fixed", "conditional", "base-kill", "gathering", "eligible-pool"}


def validate_acquisition(document, data, existing_titles):
    _object(document, {"schema_version", "build", "sources"}, {"pools", "item_notes"}, "acquisition")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise DataError("acquisition: expected schema version 1")
    if document["build"] != data["game"]["build"]:
        raise DataError("acquisition: evidence build must match the documented game build")
    entities = {row["id"]: row for row in data["entities"]}
    evidence_sources = {row["id"]: row for row in data["sources"]}
    entries = {row["id"]: row for row in data.get("entries", [])}
    sources = _records(document["sources"], "acquisition.sources")
    if len(sources) > 100:
        raise DataError("acquisition: expected at most one hundred reviewed source owners")
    titles = set(existing_titles)
    identities, row_ids, assigned_entries = set(), set(), set()
    for source in sources:
        _object(source, {"id", "title", "kind", "summary", "conditions", "rows", "related_entities",
                         "related_pages", "confidence", "evidence"},
                {"existing_entry_ids", "image_entity", "image_caption", "pool_ids", "pool_refs", "loot_context",
                 "entity_context"}, "acquisition source")
        identity = _identifier(source["id"], "acquisition source.id")
        title = _title(source["title"])
        if identity in identities or title in titles:
            raise DataError("acquisition source: duplicate ID or conflicting canonical title")
        identities.add(identity)
        titles.add(title)
        if not isinstance(source["kind"], str) or source["kind"] not in SOURCE_KINDS:
            raise DataError("acquisition source: unsupported source kind")
        _text(source["summary"], "acquisition source.summary", 1200)
        if not isinstance(source["conditions"], list) or len(source["conditions"]) > 16:
            raise DataError("acquisition source: expected at most sixteen condition paragraphs")
        for condition in source["conditions"]:
            _text(condition, "acquisition source.condition", 1200)
        if "loot_context" in source:
            _text(source["loot_context"], "acquisition source.loot_context", 1200)
        _confidence(source["confidence"], "acquisition source.confidence")
        _evidence(source["evidence"], evidence_sources, "acquisition source.evidence")
        related = source["related_entities"]
        if not isinstance(related, list) or len(related) > 16 or any(
            not isinstance(identity, str) or identity not in entities for identity in related
        ) or len(related) != len(set(related)):
            raise DataError("acquisition source: expected unique known related entities")
        context = source.get("entity_context", {})
        if not isinstance(context, dict) or not context.keys() <= set(related):
            raise DataError("acquisition source: entity context must target related entities")
        for text in context.values():
            _text(text, "acquisition source.entity_context", 1200)
        if ("image_entity" in source) != ("image_caption" in source):
            raise DataError("acquisition source: contextual images need an entity and caption")
        if "image_entity" in source:
            identity = _identifier(source["image_entity"], "acquisition source.image_entity")
            if identity not in entities or entities[identity]["category"] not in {"item", "being", "nature"}:
                raise DataError("acquisition source: contextual image requires an item, being, or nature entity")
            _text(source["image_caption"], "acquisition source.image_caption", 500)
        inherited = _records(source.get("existing_entry_ids", []), "acquisition source.existing_entry_ids")
        for identity in inherited:
            if not isinstance(identity, str) or identity not in entries or entries[identity]["kind"] != "loot" or identity in assigned_entries:
                raise DataError("acquisition source: historical loot entries need one unique source owner")
            assigned_entries.add(identity)
        rows = _records(source["rows"], "acquisition source.rows")
        if len(rows) > 500 or not any((rows, inherited, source.get("pool_ids"), source.get("pool_refs"))):
            raise DataError("acquisition source: expected documented rows or historical loot entries")
        for row in rows:
            _object(row, {"id", "item", "quantity", "probability", "condition", "coverage", "evidence"},
                    {"odds_note", "confidence"}, "acquisition row")
            identity = _identifier(row["id"], "acquisition row.id")
            if identity in row_ids:
                raise DataError("acquisition row: duplicate stable ID")
            row_ids.add(identity)
            _entity_reference(row["item"], entities, "item", "acquisition row.item")
            if row["quantity"] is not None:
                _range(row["quantity"], "acquisition row.quantity")
            _text(row["condition"], "acquisition row.condition", 500)
            if not isinstance(row["coverage"], str) or row["coverage"] not in ROW_COVERAGE:
                raise DataError("acquisition row: unsupported coverage")
            _evidence(row["evidence"], evidence_sources, "acquisition row.evidence")
            if "confidence" in row:
                _confidence(row["confidence"], "acquisition row.confidence")
            probability = row["probability"]
            if probability is None:
                _text(row.get("odds_note"), "acquisition row.odds_note", 500)
            else:
                _object(probability, {"numerator", "denominator", "scope"}, set(), "acquisition probability")
                _number(probability["numerator"], "probability numerator", integer=True)
                _number(probability["denominator"], "probability denominator", minimum=1, integer=True)
                if probability["numerator"] > probability["denominator"]:
                    raise DataError("acquisition probability: numerator exceeds denominator")
                _text(probability["scope"], "acquisition probability.scope", 500)
                _nullable_text(row.get("odds_note"), "acquisition row.odds_note", 500)
            if row["coverage"] == "fixed" and (
                probability is None or probability["numerator"] != probability["denominator"] or row["quantity"] is None
            ):
                raise DataError("fixed acquisition rows require a certain conditional probability and known quantity")
    source_by_id = {source["id"]: source for source in sources}
    pools, item_conditions = {}, {}
    for pool in _records(document.get("pools", []), "acquisition.pools"):
        _object(pool, {"id", "title", "owner_source", "summary", "eligible_item_ids", "quantity",
                       "probability", "odds_note", "item_conditions", "confidence", "evidence"},
                set(), "acquisition pool")
        identity = _identifier(pool["id"], "acquisition pool.id")
        owner = _identifier(pool["owner_source"], "acquisition pool.owner_source")
        if identity in pools or owner not in source_by_id:
            raise DataError("acquisition pool: duplicate pool or missing canonical owner")
        pools[identity] = pool
        _title(pool["title"])
        _text(pool["summary"], "acquisition pool.summary", 1200)
        members = _records(pool["eligible_item_ids"], "acquisition pool.eligible_item_ids")
        if not members:
            raise DataError("acquisition pool: expected verified eligible items")
        for member in members:
            _entity_reference(member, entities, "item", "acquisition pool member")
        if len(members) != len(set(members)):
            raise DataError("acquisition pool: duplicate eligible item")
        if pool["quantity"] is not None or pool["probability"] is not None:
            raise DataError("acquisition pool: eligibility is not a quantity or per-item probability")
        _text(pool["odds_note"], "acquisition pool.odds_note", 500)
        _confidence(pool["confidence"], "acquisition pool.confidence")
        _evidence(pool["evidence"], evidence_sources, "acquisition pool.evidence")
        if not isinstance(pool["item_conditions"], dict):
            raise DataError("acquisition pool: expected item-specific condition map")
        for member, condition in pool["item_conditions"].items():
            if member not in members:
                raise DataError("acquisition pool: condition must qualify a member")
            _text(condition, "acquisition pool.item_condition", 500)
            key = (owner, member)
            if key in item_conditions and item_conditions[key] != condition:
                raise DataError("acquisition pool: shared item condition has conflicting definitions")
            item_conditions[key] = condition
    assigned_pools = set()
    for source in sources:
        for identity in _records(source.get("pool_ids", []), "acquisition source.pool_ids"):
            if not isinstance(identity, str) or identity not in pools or identity in assigned_pools:
                raise DataError("acquisition source: each declared pool requires one canonical owner")
            if pools[identity]["owner_source"] != source["id"]:
                raise DataError("acquisition source: pool owner does not match its declaration")
            assigned_pools.add(identity)
        references = set()
        for reference in _records(source.get("pool_refs", []), "acquisition source.pool_refs"):
            _object(reference, {"pool", "condition"}, set(), "acquisition pool reference")
            identity = _identifier(reference["pool"], "acquisition pool reference.pool")
            if identity not in pools or identity in references:
                raise DataError("acquisition source: unknown or repeated pool reference")
            references.add(identity)
            _text(reference["condition"], "acquisition pool reference.condition", 500)
        related = source["related_pages"]
        if not isinstance(related, list) or len(related) > 16 or any(
            not isinstance(title, str) or title not in titles or title == source["title"] for title in related
        ) or len(related) != len(set(related)):
            raise DataError("acquisition source: related pages must have unique existing owners")
    if assigned_pools != pools.keys():
        raise DataError("acquisition pool: every pool must be declared by its owner")
    notes = set()
    for note in _records(document.get("item_notes", []), "acquisition.item_notes"):
        _object(note, {"item", "kind", "text", "evidence"}, {"related_items"}, "acquisition item note")
        _entity_reference(note["item"], entities, "item", "acquisition item note.item")
        if note["item"] in notes:
            raise DataError("acquisition item note: duplicate owner")
        notes.add(note["item"])
        if not isinstance(note["kind"], str) or note["kind"] not in {"built-in", "construction-action", "unverified"}:
            raise DataError("acquisition item note: unsupported scope")
        _text(note["text"], "acquisition item note.text", 1200)
        _evidence(note["evidence"], evidence_sources, "acquisition item note.evidence")
        related = _records(note.get("related_items", []), "acquisition item note.related_items")
        for identity in related:
            _entity_reference(identity, entities, "item", "acquisition item note.related_item")
        if len(related) != len(set(related)) or note["item"] in related:
            raise DataError("acquisition item note: related items must be distinct")
    return document
