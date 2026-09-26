"""Bounded evidence-backed acquisition sources, separate from historical research."""

from wiki_data import (
    DataError, _confidence, _entity_reference, _evidence, _identifier, _nullable_text,
    _number, _object, _range, _records, _text, _title,
)


MAX_ACQUISITION_BYTES = 256 * 1024
SOURCE_KINDS = {"starting", "fixed-location", "world-feature", "gathering", "container"}
ROW_COVERAGE = {"fixed", "conditional", "base-kill", "gathering", "eligible-pool"}


def validate_acquisition(document, data, existing_titles):
    _object(document, {"schema_version", "build", "sources"}, set(), "acquisition")
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
                {"existing_entry_ids", "image_entity", "image_caption"}, "acquisition source")
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
        _confidence(source["confidence"], "acquisition source.confidence")
        _evidence(source["evidence"], evidence_sources, "acquisition source.evidence")
        related = source["related_entities"]
        if not isinstance(related, list) or len(related) > 16 or any(
            not isinstance(identity, str) or identity not in entities for identity in related
        ) or len(related) != len(set(related)):
            raise DataError("acquisition source: expected unique known related entities")
        if ("image_entity" in source) != ("image_caption" in source):
            raise DataError("acquisition source: contextual images need an entity and caption")
        if "image_entity" in source:
            _entity_reference(source["image_entity"], entities, "item", "acquisition source.image_entity")
            _text(source["image_caption"], "acquisition source.image_caption", 500)
        inherited = _records(source.get("existing_entry_ids", []), "acquisition source.existing_entry_ids")
        for identity in inherited:
            if not isinstance(identity, str) or identity not in entries or entries[identity]["kind"] != "loot" or identity in assigned_entries:
                raise DataError("acquisition source: historical loot entries need one unique source owner")
            assigned_entries.add(identity)
        rows = _records(source["rows"], "acquisition source.rows")
        if len(rows) > 500 or not rows and not inherited:
            raise DataError("acquisition source: expected documented rows or historical loot entries")
        for row in rows:
            _object(row, {"id", "item", "quantity", "probability", "condition", "coverage", "evidence"},
                    {"odds_note"}, "acquisition row")
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
    for source in sources:
        related = source["related_pages"]
        if not isinstance(related, list) or len(related) > 16 or any(
            not isinstance(title, str) or title not in titles or title == source["title"] for title in related
        ) or len(related) != len(set(related)):
            raise DataError("acquisition source: related pages must have unique existing owners")
    return document
