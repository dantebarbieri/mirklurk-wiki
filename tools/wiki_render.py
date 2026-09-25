"""Reader-facing wiki pages with one editable owner for each documented detail."""

import html
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from wiki_catalog import (
    CURRENCY_RULE_TITLES, default_catalog, entry_owners, entry_relations, fact_owners, page_locations,
    validate_catalog,
)
from wiki_data import CATEGORY_PAGES, DataError, PAGE_FILES, RESEARCH_PAGE_FILES, entry_page, validate_data
from wiki_details import empty_details, validate_coin_profiles, validate_details


def literal(value):
    return "<nowiki>" + html.escape(str(value), quote=False) + "</nowiki>"


def anchor(kind, identity):
    return f'<span id="{kind}-{identity}"></span>'


def table(headers, rows):
    lines = ['{| class="wikitable"', "! " + " !! ".join(headers)]
    for row in rows:
        lines.extend(["|-", "| " + " || ".join(row)])
    return "\n".join([*lines, "|}"]) + "\n"


def known(value):
    if value is None:
        return "Not established"
    if type(value) is bool:
        return "Yes" if value else "No"
    return literal(value)


def count_range(value):
    if value is None:
        return "Not established"
    if value["min"] == value["max"]:
        return known(value["min"])
    return known(value["min"]) + " to " + known(value["max"])


def entity_link(identity, entities, locations):
    return f'[[{locations[identity]}|{literal(entities[identity]["name"])}]]'


def quest_order(entry):
    quest_id = entry["details"]["quest_id"]
    if quest_id == "First":
        return (0, 0, entry["id"])
    if quest_id.isdecimal():
        return (1, int(quest_id), entry["id"])
    return (2, quest_id, entry["id"])


def display_entry(entry, catalog):
    override = next((row for row in catalog.get("entry_display", []) if row["entry"] == entry["id"]), {})
    shown = {**entry, **{key: value for key, value in override.items() if key != "entry"}}
    if "steps" in override:
        shown["details"] = dict(entry["details"], steps=override["steps"])
    return shown


def image_for(identity, images):
    return next((image for image in images if image.get("entity") == identity and image["rights_status"] == "approved"), None)


def icon(identity, images, entities, locations):
    image = image_for(identity, images)
    if image is None:
        return ""
    return f'[[{image["file_title"]}|32px|link={locations[identity]}|alt={literal(entities[identity]["name"])}]]'


def item_cell(identity, images, entities, locations):
    return icon(identity, images, entities, locations) + " " + entity_link(identity, entities, locations)


def quantities(items, images, entities, locations):
    return "<br />".join(
        item_cell(row["item"], images, entities, locations) + " x " + known(row["quantity"])
        for row in sorted(items, key=lambda row: row["item"])
    ) or "No item inputs"


def profile_value(key, value, entities, locations):
    if key in {"damage-class-id", "ranged-damage-class-id"} and type(value) is int:
        identity = f"damage-class-{value}"
        if identity in entities and entities[identity]["category"] == "damage_class":
            return entity_link(identity, entities, locations)
        return "Damage type not identified"
    return known(value)


PROPERTY_LABELS = {
    "damage-class-id": "Melee damage type", "ranged-damage-class-id": "Ranged damage type",
    "initial-price": "Base value (not a shop price)", "initial-weight": "Base weight",
    "awareness-chance": "Targeting chance", "awareness-distance": "Targeting distance",
}
LEGACY_PROPERTIES = {
    "weight": "initial-weight", "stacklimit": "stack-limit", "durabilitymax": "durability-max",
    "apcost": "item-ap-cost", "armor": "being-armor", "apmax": "maximum-ap", "attackcost": "melee-ap-cost",
}
PAIRED_PROPERTIES = (
    ("hp-grid-width", "hp-grid-height", "HP grid", " x "),
    ("melee-pattern-min", "melee-pattern-max", "Potential melee damage", " to "),
    ("ranged-pattern-min", "ranged-pattern-max", "Potential ranged damage", " to "),
    ("terrain-height-min", "terrain-height-max", "Growth height range", " to "),
)


def price_text(price):
    if price is None:
        return "Not established"
    return format(Decimal(str(price["value"])).normalize(), "f") + " silver"


def stat_table(facts, profiles, properties, entities, locations, price_item=None, price=None, coin=None):
    if not facts and not profiles and price_item is None:
        return ""
    rows = []
    coalesced = set()
    markers = "".join(anchor("profile", profile["id"]) for profile in profiles)
    show_base_value = False
    for profile in profiles:
        values = profile["values"]
        scope = "Potential" if any(key.endswith("-pattern-min") for key in values) else "Base"
        paired = set()
        for low, high, label, separator in PAIRED_PROPERTIES:
            if low in values and high in values:
                paired.update([low, high])
                rows.append([literal(label), known(values[low]) + separator + known(values[high]), scope])
        for key, value in sorted(values.items()):
            if key in paired:
                continue
            if coin is not None and key in {"initial-price", "initial-weight", "stack-limit"}:
                continue
            if key == "initial-price":
                if price is not None and value == price["value"]:
                    continue
                show_base_value = True
            extra = ""
            for fact in facts:
                field = fact["id"].removeprefix(profile["entity"] + "-base-")
                if (
                    fact["id"].startswith(profile["entity"] + "-base-")
                    and LEGACY_PROPERTIES.get(field) == key and fact["value"] == value
                    and type(fact["value"]) is type(value) and fact["confidence"] == "inferred"
                ):
                    extra += anchor("fact", fact["id"])
                    coalesced.add(fact["id"])
            label = PROPERTY_LABELS.get(key, properties[key]["label"])
            unit = properties[key]["unit"]
            if unit and unit != "internal ID":
                label += f" ({unit})"
            rows.append([extra + literal(label), profile_value(key, value, entities, locations), scope])
    for fact in sorted(facts, key=lambda row: row["id"]):
        if fact["id"] not in coalesced:
            rows.append([
                anchor("fact", fact["id"]) + literal(fact["property"]),
                known(fact["value"]), literal(fact["description"]),
            ])
    if price_item is not None:
        rows.append([
            anchor("price", price_item) + "Standard unit price",
            "<onlyinclude>" + price_text(price) + "</onlyinclude>",
            "Purchase price per item; not resale value.",
        ])
    notes = []
    if profiles and coin is None:
        notes.append("Base values can change with equipment, state, crafting adjustments, or other effects.")
    keys = {key for profile in profiles for key in profile["values"]}
    if show_base_value:
        notes.append("Base value is not the price charged by a merchant.")
    if "hp-grid-width" in keys:
        notes.append("Grid dimensions are not a stated maximum HP total.")
    if "awareness-chance" in keys:
        notes.append("Targeting parameters do not establish hostility toward the player.")
    if any(key.endswith("-pattern-min") for key in keys):
        notes.append("Potential damage is before target overlap, armor, and modifiers; it is not guaranteed damage per hit.")
    return "\n== Stats ==\n" + markers + "\n" + table(["Detail", "Value", "Applies to / notes"], rows) + " ".join(notes) + "\n"


def recipe_groups(entries):
    grouped = {}
    for entry in entries:
        details = entry["details"]
        key = json.dumps({
            "inputs": sorted(details["inputs"], key=lambda row: row["item"]),
            "outputs": sorted(details["outputs"], key=lambda row: row["item"]),
            "cost": details["cost"], "conditions": entry["conditions"], "summary": entry["summary"],
        }, sort_keys=True, separators=(",", ":"))
        grouped.setdefault(key, []).append(entry)
    return list(grouped.values())


def shared_field(entries, getter):
    values = [getter(entry) for entry in entries]
    return all(value == values[0] for value in values), values[0]


def merchant_table(entries, images, entities, locations, standard_prices=False):
    headers = ["Item"]
    getters = []
    notes = []
    unknown = []
    for field, label in (("quantity", "Quantity"), ("price", "Unit price"), ("currency", "Currency")):
        if field == "price" and standard_prices:
            headers.append(label)
            getters.append(lambda entry: "{{:" + locations[entry["details"]["item"]] + "}}"
                           if entry["details"]["price"] is None
                           else known(entry["details"]["price"]) + " " + known(entry["details"]["currency"]))
            continue
        if field == "currency" and standard_prices:
            continue
        if any(entry["details"][field] is not None for entry in entries):
            headers.append(label)
            getters.append(lambda entry, field=field: known(entry["details"][field]))
        elif field != "currency":
            unknown.append(label.lower())
    if unknown:
        notes.append(" and ".join(unknown).capitalize() + " are not established." if len(unknown) > 1 else unknown[0].capitalize() + " is not established.")
    same_location, location = shared_field(entries, lambda entry: entry["details"]["location"])
    if same_location:
        notes.append("Location: " + known(location) + ".")
    else:
        headers.append("Location")
        getters.append(lambda entry: known(entry["details"]["location"]))
    same_conditions, conditions = shared_field(entries, lambda entry: entry["conditions"])
    if same_conditions and conditions:
        notes.append(literal(conditions))
    elif not same_conditions:
        headers.append("Conditions")
        getters.append(lambda entry: known(entry["conditions"]))
    rows = []
    for entry in entries:
        rows.append([
            anchor("entry", entry["id"]) + item_cell(entry["details"]["item"], images, entities, locations),
            *(getter(entry) for getter in getters),
        ])
    return "\n== Wares ==\n" + "\n\n".join(notes) + "\n\n" + table(headers, rows)


def recipe_table(entries, stations, images, entities, locations):
    groups = recipe_groups(entries)
    headers = ["Ingredients", "Output", "Crafting method"]
    has_cost = any(group[0]["details"]["cost"] is not None for group in groups)
    if has_cost:
        headers.append("Base cost")
    same_conditions, conditions = shared_field(entries, lambda entry: entry["conditions"])
    if not same_conditions:
        headers.append("Conditions")
    rows = []
    for group in groups:
        first = group[0]
        details = first["details"]
        links = set()
        for entry in group:
            method = entry["details"]["station"]
            station = stations.get(method)
            links.add(f'[[{station["title"]}]]' if station else literal(method))
        row = [
            "".join(anchor("entry", entry["id"]) for entry in group)
            + quantities(details["inputs"], images, entities, locations),
            quantities(details["outputs"], images, entities, locations), " | ".join(sorted(links)),
        ]
        if has_cost:
            cost = details["cost"]
            row.append("Not established" if cost is None else known(cost["amount"]) + " " + literal(cost["unit"]))
        if not same_conditions:
            row.append(known(first["conditions"]))
        rows.append(row)
    notes = ["These are base recipes; skill and station effects may change costs or consumption."]
    if not has_cost:
        notes.append("Additional costs are not established.")
    if same_conditions and conditions:
        notes.append(literal(conditions))
    return "\n== Recipes ==\n" + " ".join(notes) + "\n\n" + table(headers, rows)


def loot_table(entries, images, entities, locations):
    headers = ["Result", "Quantity"]
    getters = []
    for field, label, formatter in (
        ("weight", "Reported weight", known), ("probability", "Conditional probability", known),
        ("rolls", "Rolls", count_range),
    ):
        if any(entry["details"][field] is not None for entry in entries):
            headers.append(label)
            getters.append(lambda entry, field=field, formatter=formatter: formatter(entry["details"][field]))
    same_conditions, conditions = shared_field(entries, lambda entry: entry["conditions"])
    if not same_conditions:
        headers.append("Conditions")
    same_summary, summary = shared_field(entries, lambda entry: entry["summary"])
    if not same_summary:
        headers.append("Notes")
    rows = []
    for entry in entries:
        details = entry["details"]
        result = "No items" if details["outcome"] is None else item_cell(details["outcome"], images, entities, locations)
        row = [anchor("entry", entry["id"]) + result, count_range(details["quantity"]), *(getter(entry) for getter in getters)]
        if not same_conditions:
            row.append(known(entry["conditions"]))
        if not same_summary:
            row.append(literal(entry["summary"]))
        rows.append(row)
    notes = ["Reported weights are not converted to probabilities. A range does not imply equally likely quantities."]
    if same_conditions and conditions:
        notes.append(literal(conditions))
    if same_summary:
        notes.append(literal(summary))
    return "\n== Loot ==\n" + "\n\n".join(notes) + "\n\n" + table(headers, rows)


def evidence_text(references):
    return "<br />".join(
        f'[[Source provenance#{row["source"]}|{row["source"]}]] / {literal(row["section"])} / {literal(row["key"])}'
        for row in sorted(references, key=lambda row: (row["source"], row["section"], row["key"]))
    )


def source_page(data, catalog, details, locations, facts, entries):
    lines = [
        "Technical evidence, identifiers, and methodology are kept here rather than repeated on gameplay pages.",
        "The linked gameplay page is the editable owner of its values or prose; this register does not duplicate them.",
        "Source files and game assets are not distributed with the repository.",
        "", "[[Research policy]] | [[Evidence and spoilers]] | [[Main Page]]",
        "", "== Build identification ==",
        "[[Game mechanics#Version|The installed build]] is confirmed by the wiki operator and corroborated by the menu-label trace below. The operator's statement that it is the latest patch is a user report, not an independent check of all published releases."
        if data["game"]["build"] is not None else "The installed build is not identified in this dataset.",
        "", "== Source files ==",
        table(["Source", "Installation-relative path", "SHA-256", "Build"], [
            [f'<span id="{row["id"]}"></span>' + literal(row["id"]), literal(row["path"].replace("\\", "/")),
             literal(row["sha256"]), known(row["build"])]
            for row in sorted(data["sources"], key=lambda row: row["id"])
        ]),
        "", "Confidence labels describe the evidence, not a guarantee of current gameplay: observed means seen in the cited source; inferred means an interpretation needing confirmation; localization-described means described rather than runtime-tested.",
    ]
    groups = [
        ("Entity identities", data["entities"], lambda row: locations[row["id"]]),
        ("Numeric facts", data["facts"], lambda row: facts[row["id"]] + "#fact-" + row["id"]),
        ("Research records", data.get("entries", []), lambda row: entries[row["id"]] + "#entry-" + row["id"]),
        ("Profiles", details["profiles"], lambda row: locations[row["entity"]] + "#profile-" + row["id"]),
    ]
    for heading, records, target in groups:
        lines.extend(["", f"== {heading} ==", table(["Record", "Editable owner", "Confidence", "Evidence"], [
            [literal(row["id"]), f'[[{target(row)}|{literal(target(row).split("#")[0])}]]',
             literal(row["confidence"]), evidence_text(row["evidence"])]
            for row in sorted(records, key=lambda row: row["id"])
        ])])
    lines.extend(["", "== Property definitions ==", table(["Property", "Label", "Unit", "Interpretation"], [
        [literal(row["id"]), literal(row["label"]), known(row["unit"]), literal(row["description"])]
        for row in sorted(details["properties"], key=lambda row: row["id"])
    ])])
    lines.extend(["", "== Profile methodology ==", table(["Profile", "Scope"], [
        [literal(row["id"]), literal(row["context"])] for row in sorted(details["profiles"], key=lambda row: row["id"])
    ])])
    lines.extend(["", "== Classification evidence ==", table(["Character", "Grouping", "Confidence", "Evidence", "Interpretation"], [
        [f'[[{locations[row["entity"]]}]]', literal(row["kind"]), literal(row["confidence"]), evidence_text(row["evidence"]), literal(row["note"])]
        for row in sorted(catalog["classifications"], key=lambda row: row["entity"])
    ])])
    lines.extend(["", "== Artwork review ==", table(["File", "Creator", "Reviewed image SHA-256", "Rights review", "Evidence"], [
        [literal(row["file_title"]), known(row["creator"]), known(row["sha256"]),
         literal(row["rights_status"]) + "; " + known(row["rights_basis"]) + "; " + known(row["rights_note"]),
         evidence_text(row["evidence"])]
        for row in sorted(data.get("illustrations", []), key=lambda row: row["id"])
    ])])
    lines.extend(["", "== Workstation evidence ==", table(["Station", "Confidence", "Evidence"], [
        [f'[[{row["title"]}]]', literal(row["confidence"]), evidence_text(row["evidence"])]
        for row in sorted(catalog.get("stations", []), key=lambda row: row["id"])
    ])])
    reports = [
        [literal(report["id"]), f'[[{station["title"]}#report-{report["id"]}|{literal(station["title"])}]]',
         "User-reported gameplay", literal(report["attribution"]), literal(report["recorded_on"])]
        for station in sorted(catalog.get("stations", []), key=lambda row: row["id"])
        for report in sorted(station.get("reports", []), key=lambda row: row["id"])
    ]
    if reports:
        lines.extend([
            "", "== Operator reports ==",
            "These reports are attributed to the wiki operator, not independently established by a source-file hash.",
            table(["Report", "Editable owner", "Evidence type", "Attribution", "Recorded on"], reports),
        ])
    if "unit_prices" in catalog:
        prices = catalog["unit_prices"]
        lines.extend([
            "", "== Standard unit prices ==", literal(prices["context"]),
            "The price itself is maintained only on the linked item page. Merchant pages selectively transclude it.",
            table(["Item / editable price", "Confidence", "Evidence"], [
                [f'[[{locations[row["entity"]]}#price-{row["entity"]}|{literal(entities_name(data, row["entity"]))}]]',
                 literal(row["confidence"]), evidence_text(row["evidence"])]
                for row in sorted(prices["prices"], key=lambda row: row["entity"])
            ]),
        ])
    if "currency" in catalog:
        currency = catalog["currency"]
        lines.extend([
            "", "== Currency evidence ==",
            literal(currency["documented_build"]["confirmation"]),
            evidence_text(currency["documented_build"]["evidence"]),
            table(["Rule", "Editable owner", "Confidence", "Evidence"], [
                [literal(rule["id"]), f'[[Currency and trading#currency-{rule["id"]}|{CURRENCY_RULE_TITLES[rule["id"]]}]]',
                 literal(currency["confidence"]), evidence_text(rule["evidence"])]
                for rule in currency["rules"]
            ]),
            table(["Coin owner", "Confidence", "Evidence"], [
                [f'[[{locations[coin["entity"]]}]]', literal(currency["confidence"]), evidence_text(coin["evidence"])]
                for coin in currency["coins"]
            ]),
        ])
    lines.extend([
        "", "== Menu-label trace ==",
        "[[Game mechanics]] owns the observed menu label. Trace: "
        + evidence_text([
            {"source": "game-data", "section": "gml_Object_obj_menu_Create_0", "key": "versionString"},
            {"source": "game-data", "section": "gml_Object_obj_menu_Step_0", "key": "versionCheck"},
        ]) if any(row["id"] == "game-data" for row in data["sources"]) else "",
    ])
    return "\n".join(lines) + "\n"


def entities_name(data, identity):
    return next(row["name"] for row in data["entities"] if row["id"] == identity)


def coin_summary(coin, entities, locations):
    return (
        "\n== Coin value and weight ==\n<onlyinclude>\n"
        + table(["Coin", "Value in silver", "Weight", "Maximum stack"], [[
            anchor("coin", coin["entity"]) + entity_link(coin["entity"], entities, locations),
            known(coin["value_in_silver"]), known(coin["weight_grams"]) + " g", known(coin["stack_limit"]),
        ]]) + "</onlyinclude>\n\n[[Currency and trading|Barter, change, and coin consolidation]]\n"
    )


def currency_page(currency, entities, locations):
    coins = currency["coins"]
    text = "[[Merchants]] | [[Items]] | [[Main Page]]\n\nCoins and barter use a shared value. The coin details below are maintained on the individual coin pages.\n"
    for rule in currency["rules"]:
        text += "\n" + anchor("currency", rule["id"]) + f'\n== {CURRENCY_RULE_TITLES[rule["id"]]} ==\n'
        if rule["id"] == "coin-denominations":
            text += "Compare each coin's value in silver equivalents:\n\n"
            text += "\n".join("{{:" + locations[coin["entity"]] + "}}" for coin in coins) + "\n"
        elif rule["id"] == "coin-weight-units":
            text += "A coin stack's weight is its per-coin weight multiplied by the quantity. Consolidating equal value into higher denominations reduces carried weight.\n"
        else:
            text += literal(rule["text"]) + "\n"
        qualification = rule.get("qualification")
        if qualification and rule["id"] != "coin-weight-units":
            text += "\n" + literal(qualification) + "\n"
    return text


def read_authored(root, title, filename):
    path = Path(root) / "content" / "pages" / filename
    if path.is_symlink():
        raise DataError(f"authored page {title}: symlinks are not permitted")
    raw = path.read_bytes()
    if len(raw) > 32 * 1024:
        raise DataError(f"authored page {title}: exceeds its size limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DataError(f"authored page {title}: must be UTF-8") from error
    if any((ord(c) < 32 and c not in "\r\n\t") or 127 <= ord(c) <= 159 for c in text):
        raise DataError(f"authored page {title}: control characters are not permitted")
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


def build_pages(root, data, catalog=None, details=None):
    if not isinstance(data, dict):
        raise DataError("root: expected an object")
    # Station image targets require the registry after its base entity references are validated.
    base = {key: value for key, value in data.items() if key != "illustrations"}
    validate_data(base)
    catalog = validate_catalog(default_catalog(base) if catalog is None else catalog, base)
    validate_data(data, stations={row["id"]: row for row in catalog.get("stations", [])})
    details = validate_details(empty_details() if details is None else details, data)
    validate_coin_profiles(catalog, details)
    entities = {row["id"]: row for row in data["entities"]}
    properties = {row["id"]: row for row in details["properties"]}
    locations = page_locations(data, catalog)
    facts = fact_owners(data, locations)
    relations = entry_relations(data, catalog)
    owners = entry_owners(data, locations, relations, catalog)
    entries = sorted((display_entry(row, catalog) for row in data.get("entries", [])), key=lambda row: row["id"])
    images = sorted(data.get("illustrations", []), key=lambda row: row["id"])
    prices = {row["entity"]: row for row in catalog.get("unit_prices", {}).get("prices", [])}
    price_items = ({entry["details"]["item"] for entry in entries if entry["kind"] == "merchant"} | prices.keys()) if "unit_prices" in catalog else set()
    coins = {row["entity"]: row for row in catalog.get("currency", {}).get("coins", [])}
    researched = {row["page"] for row in data["facts"]} | {entry_page(row) for row in entries} | set(facts.values()) | set(owners.values())
    active = {title: filename for title, filename in RESEARCH_PAGE_FILES.items() if title in researched}
    pages = {title: read_authored(root, title, filename) for title, filename in {**PAGE_FILES, "NPCs": "NPCs.wiki", **active}.items()}
    if active:
        navigation = "\n== Explore more ==\n" + " | ".join(f"[[{title}]]" for title in sorted(active)) + "\n"
        pages["Main Page"] = pages["Main Page"].replace("== Read the caveats ==", navigation + "\n== Read the caveats ==")
        pages["Game mechanics"] += navigation
    classified = {row["entity"]: row["kind"] for row in catalog["classifications"]}
    stations = {method: row for row in catalog.get("stations", []) for method in row["methods"]}
    if "Loot mechanics" in owners.values():
        pages["Loot mechanics"] = "[[Loot tables]] | [[Main Page]]\n\nHow quantities, treasure budgets, and corpse contents are selected.\n"
        pages["Loot tables"] += "\n[[Loot mechanics|General loot-selection rules]]\n"
    if "Crafting" in pages and not stations:
        pages["Crafting"] = pages["Crafting"].replace("[[Inventory crafting]]", "inventory crafting")
    for station in catalog.get("stations", []):
        if station["entity"] is None:
            pages[station["title"]] = "[[Crafting]] | [[Main Page]]\n"
    for row in catalog["pages"]:
        entity = entities[row["entity"]]
        index = "NPCs" if classified.get(entity["id"]) == "npc" else CATEGORY_PAGES[entity["category"]]
        text = f'[[Main Page]] | [[{index}]]\n\n' + anchor("entity", entity["id"]) + f"'''{literal(entity['name'])}'''\n"
        if entity["category"] == "skill":
            text += "\nGroup: " + entity_link(entity["group"], entities, locations) + "\n"
        if entity["category"] == "being" and classified.get(entity["id"]) not in {"npc", "creature"}:
            text += "\nThis being has not been classified.\n"
        if entity["id"] == "being-9":
            text += "\nA deceased character record.\n"
        matching = [image for image in images if image.get("entity") == entity["id"]]
        for image in matching:
            text += anchor("illustration", image["id"])
            if image["rights_status"] == "approved":
                text += f'\n[[{image["file_title"]}|thumb|{literal(image["caption"])}]]\n'
            else:
                text += "\nNo reviewed picture is available yet.\n"
        if not matching:
            text += "\nNo reviewed picture is available yet.\n"
        pages[row["title"]] = text
        for alias in row["aliases"]:
            pages[alias] = f'#REDIRECT [[{row["title"]}]]\n'

    # Each overview groups historical anchors with its canonical destination.
    navigation = defaultdict(lambda: defaultdict(set))
    legacy = defaultdict(lambda: defaultdict(set))
    for entity in data["entities"]:
        original = CATEGORY_PAGES[entity["category"]]
        index = "NPCs" if classified.get(entity["id"]) == "npc" else original
        target = locations[entity["id"]]
        navigation[index][target].add(("entity", entity["id"]))
        if original != index:
            legacy[original][target].add(("entity", entity["id"]))
    for fact in data["facts"]:
        if facts[fact["id"]] != fact["page"]:
            legacy[fact["page"]][facts[fact["id"]]].add(("fact", fact["id"]))
    for entry in entries:
        if owners[entry["id"]] != entry_page(entry):
            target_group = navigation if entry["kind"] == "merchant" else legacy
            target_group[entry_page(entry)][owners[entry["id"]]].add(("entry", entry["id"]))
    for title, targets in legacy.items():
        for target in list(targets):
            if target in navigation[title]:
                navigation[title][target].update(targets.pop(target))

    def navigation_lines(targets):
        lines = []
        for target, markers in sorted(targets.items()):
            label = target.split("#")[0]
            source_entity = next((row for row in data["entities"] if locations[row["id"]] == target), None)
            if source_entity:
                label = source_entity["name"]
            lines.append("* " + "".join(anchor(kind, identity) for kind, identity in sorted(markers)) + f"[[{target}|{literal(label)}]]")
        return lines

    for title, targets in navigation.items():
        if not targets:
            continue
        if title == "Skills":
            for group in sorted((row for row in data["entities"] if row["category"] == "skill_group"), key=lambda row: (row["name"], row["id"])):
                pages[title] += "\n" + anchor("entity", group["id"]) + f'\n== {literal(group["name"])} ==\n'
                matching = {}
                for entity in data["entities"]:
                    if entity.get("group") == group["id"]:
                        matching[locations[entity["id"]]] = targets[locations[entity["id"]]]
                pages[title] += "\n".join(navigation_lines(matching)) + "\n"
            if "Level progression" in pages:
                pages[title] += "\n[[Level progression|Earning and allocating skill points]]\n"
            continue
        lines = navigation_lines(targets)
        pages[title] += "\n== Browse ==\n" + "\n".join(lines) + "\n"
    for title, targets in legacy.items():
        if not targets:
            continue
        label = "Characters now listed under NPCs" if title == "Bestiary" else "Related pages"
        pages[title] += (
            f'\n<div class="mw-collapsible mw-collapsed">\n{label}\n<div class="mw-collapsible-content">\n'
            + "\n".join(navigation_lines(targets)) + "\n</div></div>\n"
        )

    for title in list(pages):
        entity_ids = {row["entity"] for row in catalog["pages"] if row["title"] == title}
        matching_facts = [row for row in data["facts"] if facts[row["id"]] == title]
        matching_profiles = sorted(
            (row for row in details["profiles"] if row["entity"] in entity_ids),
            key=lambda row: (any(key.endswith("-pattern-min") for key in row["values"]), row["id"]),
        )
        price_item = next(iter(entity_ids & price_items), None)
        coin = next((coins[identity] for identity in entity_ids if identity in coins), None)
        pages[title] += stat_table(matching_facts, matching_profiles, properties, entities, locations, price_item, prices.get(price_item), coin)
        if coin is not None:
            pages[title] += coin_summary(coin, entities, locations)
        matching_entries = [row for row in entries if owners[row["id"]] == title]
        for kind, renderer in (
            ("merchant", lambda rows: merchant_table(rows, images, entities, locations, "unit_prices" in catalog)),
            ("recipe", lambda rows: recipe_table(rows, stations, images, entities, locations)),
            ("loot", lambda rows: loot_table(rows, images, entities, locations)),
        ):
            matching = [row for row in matching_entries if row["kind"] == kind]
            if matching:
                pages[title] += renderer(matching)
        prose = [row for row in matching_entries if row["kind"] in {"quest", "algorithm"}]
        if title == "Quests and journal":
            prose.sort(key=quest_order)
        for entry in prose:
            pages[title] += "\n" + anchor("entry", entry["id"]) + f'\n== {literal(entry["title"])} ==\n{literal(entry["summary"])}\n'
            if entry["conditions"] is not None and (entry["kind"] != "quest" or entry["details"]["stage"] == "Dynamic location"):
                pages[title] += "\n" + literal(entry["conditions"]) + "\n"
            if entry["kind"] == "algorithm":
                pages[title] += "\n".join("# " + literal(step) for step in entry["details"]["steps"]) + "\n"
                targets = sorted({facts[identity] for identity in entry["details"]["fact_ids"] if facts[identity] != title})
                if targets:
                    pages[title] += "\nRelated details: " + " | ".join(f"[[{target}]]" for target in targets) + "\n"
            related = sorted(relations[entry["id"]])
            if related:
                pages[title] += "\nRelated pages: " + " | ".join(entity_link(identity, entities, locations) for identity in related) + "\n"

    for row in catalog["pages"]:
        identity, title = row["entity"], row["title"]
        related = [entry for entry in entries if identity in relations[entry["id"]] and owners[entry["id"]] != title]
        acquisition, recipes, quests, other = [], [], [], []
        for entry in related:
            target = owners[entry["id"]] + "#entry-" + entry["id"]
            if entry["kind"] in {"merchant", "loot"}:
                acquisition.append(f"* [[{target}|{literal(owners[entry['id']])}]]")
            elif entry["kind"] == "recipe":
                recipes.append(f"* [[{target}|{literal(owners[entry['id']])}]]")
            elif entry["kind"] == "quest":
                quests.append((quest_order(entry), f"* [[{target}|{literal(entry['title'])}]]"))
            else:
                other.append(f"* [[{target}|{literal(entry['title'])}]]")
        if entities[identity]["category"] == "item":
            pages[title] += "\n== Obtaining ==\n"
            if any(entry["kind"] == "recipe" and owners[entry["id"]] == title for entry in entries):
                pages[title] += "See [[#Recipes|Recipes]] for the documented crafting options.\n"
            if acquisition:
                pages[title] += "\n".join(sorted(set(acquisition))) + "\n"
            elif not any(entry["kind"] == "recipe" and owners[entry["id"]] == title for entry in entries):
                pages[title] += "Acquisition is not established.\n"
        if recipes:
            pages[title] += "\n== Used in ==\n" + "\n".join(sorted(set(recipes))) + "\n"
        if quests:
            pages[title] += "\n== Main quest ==\n" + "\n".join(text for _, text in sorted(quests)) + "\n"
        if other:
            pages[title] += "\n== Related pages ==\n" + "\n".join(sorted(set(other))) + "\n"
        if not any(facts[fact["id"]] == title for fact in data["facts"]) and not any(profile["entity"] == identity for profile in details["profiles"]):
            pages[title] += "\nNumerical stats are not established.\n"

    if "Crafting" in pages and stations:
        pages["Crafting"] += "\n== Crafting methods ==\n" + "\n".join(
            f'* [[{row["title"]}]]' for row in sorted(catalog["stations"], key=lambda row: row["title"])
        ) + "\n"
    for station in catalog.get("stations", []):
        title = station["title"]
        pages[title] += "\n== Crafting here ==\n" + literal(station["summary"]) + "\n"
        reports = station.get("reports", [])
        if station["entity"] is None and not reports:
            pages[title] += "\n== Obtaining or finding ==\n" + known(station["acquisition"]) + "\n"
        elif station["acquisition"] is not None:
            pages[title] += "\n" + literal(station["acquisition"]) + "\n"
        for note in station.get("notes", []):
            pages[title] += "\n" + literal(note) + "\n"
        for report in reports:
            if report["section"] is None:
                pages[title] += "\n" + anchor("report", report["id"]) + literal(report["text"]) + "\n"
        variant_sections = [(None, None), *[(row["id"], row["title"]) for row in station.get("variants", [])]]
        for identity, heading in variant_sections:
            if heading:
                pages[title] += "\n" + anchor("variant", station["id"] + "-" + identity) + f"\n=== {literal(heading)} ===\n"
            for report in reports:
                if identity is not None and report["section"] == identity:
                    pages[title] += "\n" + anchor("report", report["id"]) + literal(report["text"]) + "\n"
            for image in images:
                if image.get("station") == station["id"] and image.get("variant") == identity:
                    pages[title] += "\n" + anchor("illustration", image["id"])
                    if image["rights_status"] == "approved":
                        pages[title] += f'\n[[{image["file_title"]}|thumb|{literal(image["caption"])}]]\n'
                    else:
                        pages[title] += "\nNo reviewed picture is available yet.\n"
        if station.get("related_entities"):
            pages[title] += "\nRelated pages: " + " | ".join(entity_link(identity, entities, locations) for identity in station["related_entities"]) + "\n"
            for identity in station["related_entities"]:
                if entities[identity]["category"] == "being":
                    pages[locations[identity]] += f'\n== Workstation ==\n[[{title}]]\n'
        if station.get("quest_entries"):
            pages[title] += "\nRelated journal: " + " | ".join(
                f'[[Quests and journal#entry-{identity}|{literal(next(entry["title"] for entry in entries if entry["id"] == identity))}]]'
                for identity in station["quest_entries"]
            ) + "\n"
        targets = {}
        for entry in entries:
            if entry["kind"] == "recipe" and entry["details"]["station"] in station["methods"]:
                for output in entry["details"]["outputs"]:
                    targets.setdefault(output["item"], entry)
        rows = []
        for identity, entry in sorted(targets.items(), key=lambda pair: entities[pair[0]]["name"]):
            target = owners[entry["id"]] + "#entry-" + entry["id"]
            rows.append([icon(identity, images, entities, locations), f'[[{target}|{literal(entities[identity]["name"])}]]'])
        pages[title] += "\n== What you can craft ==\n" + table(["Picture", "Recipe"], rows)
    pages["Source provenance"] = source_page(data, catalog, details, locations, facts, owners)
    if "currency" in catalog:
        pages["Currency and trading"] = currency_page(catalog["currency"], entities, locations)
        for title in ("Main Page", "Merchants"):
            if title in pages:
                pages[title] += "\n[[Currency and trading|Currency, coin weights, and trading]]\n"
        for entry in entries:
            if entry["kind"] == "merchant" and "[[Currency and trading" not in pages[owners[entry["id"]]]:
                pages[owners[entry["id"]]] += "\n[[Currency and trading|How prices, condition, and change work]]\n"
    return pages
