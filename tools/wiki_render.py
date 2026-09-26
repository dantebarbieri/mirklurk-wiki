"""Reader-facing wiki pages with one editable owner for each documented detail."""

import html
import json
import re
from collections import defaultdict
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from wiki_catalog import (
    CURRENCY_RULE_TITLES, default_catalog, entry_owners, entry_relations, fact_owners, page_locations,
    validate_catalog,
)
from wiki_data import CATEGORY_PAGES, DataError, HEALTH_ARMOR_ICONS, MECHANIC_GUIDE_TITLES, PAGE_FILES, RESEARCH_PAGE_FILES, entry_page, validate_data
from wiki_details import empty_details, validate_coin_profiles, validate_details
from wiki_views import filtered_row, html_row, html_table, selective_view, validate_transclusions


def literal(value):
    return "<nowiki>" + html.escape(str(value), quote=False) + "</nowiki>"


def linked_prose(text, links):
    if not links:
        return literal(text)
    names = "|".join(re.escape(name) for name in sorted(links, key=len, reverse=True))
    return "".join(
        f"[[{links[part]}|{literal(part)}]]" if part in links else literal(part)
        for part in re.split(r"(?<!\w)(" + names + r")(?!\w)", text) if part
    )


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
    if type(value) in {int, float, Decimal}:
        return literal(decimal_text(Decimal(str(value))))
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
    if value is None or type(value) is bool:
        return known(value)
    if key in PERCENT_PROPERTIES:
        return literal(decimal_text(Decimal(str(value)) * 100)) + "%"
    if key in AP_PROPERTIES:
        return known(value) + " [[Action points|AP]]"
    if key == "initial-weight":
        amount = Decimal(str(value))
        if 0 < abs(amount) < 1:
            return literal(decimal_text(amount * 1000)) + " g"
        return literal(decimal_text(amount)) + " kg"
    if key == "initial-price":
        return known(value) + " silver equivalents"
    if key == "extra-damage":
        amount = Decimal(str(value))
        low = int(amount)
        high = int(((amount - low) * 10).to_integral_value())
        if low < 0 or high < low:
            raise DataError("ammunition bonus must encode an ordered nonnegative range")
        return known(low) if low == high else known(low) + "-" + known(high)
    return known(value)


def decimal_text(value):
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


PERCENT_FACTS = {"rain-min-power", "rain-max-power", "temperature-smoothing"}


def fact_value(fact):
    if fact["id"] in PERCENT_FACTS:
        return known(Decimal(str(fact["value"])) * 100) + "%"
    if fact["property"].endswith("(%)"):
        return known(fact["value"]) + "%"
    return known(fact["value"])


PERCENT_PROPERTIES = {
    "awareness-chance", "break-chance", "dodge-chance", "idle-move-chance",
    "opportunity-chance", "satiation-gain", "sickness-risk", "spark-chance",
    "stone-spark-chance", "tinder-bonus", "waterproof", "insulation",
}
AP_PROPERTIES = {"craft-ap-cost", "item-ap-cost", "maximum-ap", "melee-ap-cost", "ranged-ap-cost", "equip-ap-cost"}

PROPERTY_LABELS = {
    "damage-class-id": "Damage type", "ranged-damage-class-id": "Ranged damage type",
    "initial-price": "Base value (not a shop price)", "initial-weight": "Base weight",
    "awareness-chance": "Targeting chance", "awareness-distance": "Targeting distance",
    "durability-max": "Durability", "being-armor": "Armor", "item-armor": "Armor",
    "insulation": "Insulation", "waterproof": "Waterproofing", "satiation-gain": "Satiation gain",
    "extra-damage": "Bonus damage per attack cell",
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


def price_text(price, images=None):
    if price is None:
        return "Not established"
    amount = Decimal(str(price["value"]))
    if not amount.is_finite() or amount < 0:
        raise DataError("price must be a finite nonnegative amount")
    with localcontext() as context:
        context.prec = max(28, len(amount.as_tuple().digits) + 3)
        copper = amount * 100
    if copper != copper.to_integral_value():
        raise DataError("price has sub-copper precision; an explicit display policy is required")
    remaining = int(copper)
    parts = []
    for size, name, identity, file_title in (
        (1000, "gold", "item-74", "File:Item-74.png"),
        (100, "silver", "item-73", "File:Item-73.png"),
        (1, "copper", "item-72", "File:Item-72.png"),
    ):
        count, remaining = divmod(remaining, size)
        if count:
            picture = ""
            if images is None or any(i.get("entity") == identity and i["file_title"] == file_title
                                     and i["rights_status"] == "approved" for i in images):
                picture = f"[[{file_title}|20px|link=|alt={name.capitalize()} coin]] "
            parts.append(picture + f"{count} {name}")
    return " ".join(parts) or "0 copper"


def recipe_profile_values(profile, recipes, constructions=()):
    if not profile["context"].startswith("Literal initializer values."):
        return {}
    matches = [{
        "confidence": entry["confidence"], "evidence": entry["evidence"],
        "cost": entry["details"]["cost"], "quantity": output["quantity"], "construction": False,
    } for entry in recipes for output in entry["details"]["outputs"] if output["item"] == profile["entity"]]
    matches.extend({
        "confidence": recipe["confidence"], "evidence": recipe["evidence"],
        "cost": {"amount": recipe["base_ap_cost"], "unit": "base AP"},
        "quantity": recipe["result"]["quantity"], "construction": True,
    } for recipe in constructions if recipe["owner_item"] == profile["entity"])
    if not matches:
        return {}

    def traces(references, field):
        return {
            (reference["source"], reference["section"])
            for reference in references if field in reference["key"].replace(".", "/").split("/")
        }

    folded = {}
    for key, field in (("craft-ap-cost", "craftCost"), ("craft-yield", "craftReturn")):
        value = profile["values"].get(key)
        if type(value) not in (int, float):
            continue
        if any(
            (entry["confidence"] != profile["confidence"] and not (
                entry["construction"] and entry["confidence"] == "observed" and profile["confidence"] == "inferred"))
            or not traces(profile["evidence"], field) & traces(entry["evidence"], field)
            for entry in matches
        ):
            continue
        if key == "craft-ap-cost":
            costs = [entry["cost"] for entry in matches]
            if all(cost is not None and cost["unit"] == "base AP" and cost["amount"] == value for cost in costs):
                folded[key] = costs[0]["amount"]
        else:
            quantities = [entry["quantity"] for entry in matches]
            if all(quantity == value for quantity in quantities):
                folded[key] = quantities[0]
    return folded


def stat_table(facts, profiles, properties, entities, locations, price_item=None, price=None, coin=None, recipes=(), images=(), grids=(), constructions=()):
    if not facts and not profiles:
        return ""
    rows = []
    coalesced = set()
    markers = "".join(anchor("profile", profile["id"]) for profile in profiles)
    show_base_value = False
    grid_properties = set()
    for grid in grids:
        if grid["kind"] == "health":
            grid_properties.update({"hp-grid-width", "hp-grid-height", "being-armor"})
        else:
            grid_properties.update({f'{grid["kind"]}-pattern-min', f'{grid["kind"]}-pattern-max'})
    for profile in profiles:
        values = profile["values"]
        folded = recipe_profile_values(profile, recipes, constructions)
        scope = "Potential" if any(key.endswith("-pattern-min") for key in values) else "Base"
        paired = set(grid_properties)
        for low, high, label, separator in PAIRED_PROPERTIES:
            if low in values and high in values and low not in grid_properties:
                paired.update([low, high])
                rows.append([literal(label), known(values[low]) + separator + known(values[high]), scope])
        for key, value in sorted(values.items()):
            if key == "being-armor" and key in grid_properties:
                for fact in facts:
                    if fact["id"] == profile["entity"] + "-base-armor" and fact["value"] == value:
                        markers += anchor("fact", fact["id"])
                        coalesced.add(fact["id"])
            if key in paired or key in folded:
                continue
            if coin is not None and key in {"initial-price", "initial-weight", "stack-limit"}:
                continue
            if key == "initial-price":
                if price is not None and Decimal(str(value)) == Decimal(str(price["value"])):
                    continue
                show_base_value = True
            extra = ""
            for fact in facts:
                field = fact["id"].removeprefix(profile["entity"] + "-base-")
                if (
                    fact["id"].startswith(profile["entity"] + "-base-")
                    and LEGACY_PROPERTIES.get(field) == key and fact["value"] == value
                    and type(fact["value"]) in {int, float} and type(value) in {int, float}
                    and fact["confidence"] == "inferred"
                ):
                    extra += anchor("fact", fact["id"])
                    coalesced.add(fact["id"])
            label = PROPERTY_LABELS.get(key, properties[key]["label"])
            if key == "damage-class-id" and entities[profile["entity"]]["category"] == "being":
                label = "Melee damage type"
            unit = properties[key]["unit"]
            if unit in {"XP", "items", "cells", "normalized height"}:
                label += f" ({unit})"
            rows.append([extra + literal(label), profile_value(key, value, entities, locations), scope])
    for fact in sorted(facts, key=lambda row: row["id"]):
        if fact["id"] not in coalesced:
            is_skill = any(e["category"] == "skill" and e["name"] == fact["entity"] for e in entities.values())
            note = ("Per rank." if "per rank" in fact["property"].lower() else "Base or milestone effect.") if is_skill else fact["description"]
            label = "Temperature adjustment per turn" if fact["id"] == "temperature-smoothing" else fact["property"]
            if fact["id"] == "rain-min-power":
                note = "Lower bound of active rain intensity."
            rows.append([
                anchor("fact", fact["id"]) + literal(label),
                fact_value(fact), literal(note),
            ])
    notes = []
    if profiles and coin is None:
        notes.append("Equipment, condition, and other effects may change effective values.")
    keys = {key for profile in profiles for key in profile["values"]}
    if coin is None and keys & {"initial-weight", "initial-price"}:
        notes.append(
            "Base weight and base value are literal initializer values before recipe postprocessing, "
            "not finalized in-game weights or prices."
        )
    if show_base_value:
        notes.append("Base value is not the price charged by a merchant.")
    if "hp-grid-width" in keys and "hp-grid-width" not in grid_properties:
        notes.append("Grid dimensions are not a stated maximum HP total.")
    if "awareness-chance" in keys:
        notes.append("Targeting parameters do not establish hostility toward the player.")
    if any(key.endswith("-pattern-min") for key in keys - grid_properties):
        notes.append("Potential damage is before target overlap, armor, and modifiers; it is not guaranteed damage per hit.")
    if "extra-damage" in keys:
        notes.append("[[Health and armor|How ammunition bonus rolls modify an attack pattern]].")
    return "\n== Stats ==\n" + markers + "\n" + table(["Detail", "Value", "Applies to / notes"], rows) + " ".join(notes) + "\n"


def health_armor_icon(armor, images):
    image = next((row for row in images if row.get("health_armor") == armor), None)
    if image is None or image["rights_status"] != "approved":
        raise DataError(f"health armor {armor}: an approved shield illustration is required")
    name = HEALTH_ARMOR_ICONS[armor][1].lower()
    label = f'1 HP, {armor} armor {"layer" if armor == 1 else "layers"} ({name} shield)'
    return ('<span class="health-armor-icon" style="image-rendering:pixelated;">'
            f'[[{image["file_title"]}|32px|alt={label}|{label}]]</span>')


def health_armor_legend(images):
    return "\n== Shield legend ==\n" + table(["Shield", "Armor on one HP cell"], [
        [health_armor_icon(armor, images),
         f'{name} shield: {armor} armor {"layer" if armor == 1 else "layers"}']
        for armor, (_, name) in HEALTH_ARMOR_ICONS.items()
    ])


def cell_grid(grid, entity_category, images=()):
    health = grid["kind"] == "health"
    label = "Base health" if health else ("Ranged attack" if grid["kind"] == "ranged" else (
        "Melee attack" if entity_category == "being" else "Attack pattern"))
    rows = grid["rows"]
    occupied = [cell for row in rows for cell in row if cell is not None]
    caption = f"{label}: {len(rows)} rows x {len(rows[0])} columns"
    text = "\n" + anchor("grid", grid["id"]) + f"\n== {label} ==\n"
    text += '<div style="overflow-x:auto;">\n<table class="mirklurk-cell-grid" style="border-collapse:separate;border-spacing:3px;text-align:center;">\n'
    text += "<caption>" + caption + "</caption>\n"
    for y, row in enumerate(rows, 1):
        text += "<tr>\n"
        for x, cell in enumerate(row, 1):
            position = f"Row {y}, column {x}: "
            if cell is None:
                text += f'<td class="grid-hole" aria-label="{position}empty" style="min-width:3em;height:3em;background:transparent;"></td>\n'
                continue
            if health:
                visible = health_armor_icon(cell["armor"], images) if cell["armor"] else "1 HP"
                description = f'1 HP, {cell["armor"]} armor layers'
                color = "#852c36"
            else:
                visible = str(cell["min"]) if cell["min"] == cell["max"] else f'{cell["min"]}-{cell["max"]}'
                description = visible + " damage"
                color = "#852c36"
            title = f'title="{position}{description}" ' if health and cell["armor"] else ""
            text += (f'<td class="grid-cell" aria-label="{position}{description}" {title}'
                     f'style="min-width:3em;height:3em;padding:0.25em;border:2px solid #caa098;background:{color};color:#fff;font-weight:bold;">'
                     + visible + "</td>\n")
        text += "</tr>\n"
    text += "</table>\n</div>\n"
    if health:
        text += f"{len(occupied)} occupied health cells. [[Health and armor|Reading base health, armor layers, and holes]].\n"
    else:
        low, high = (sum(cell[bound] for cell in occupied) for bound in ("min", "max"))
        text += f"Sum of occupied-cell ranges: {low} to {high}. This is not maximum actual damage: target overlap, armor and modifiers affect the result. "
        text += "Blank spaces do not strike; a 0-1 cell is occupied and can roll zero damage.\n"
        text += "[[Health and armor|How pattern overlap, rotation, and armor work]].\n"
    return text


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
    headers = ["Seller", "Item"]
    getters = []
    notes = []
    unknown = []
    normal_only = []
    has_vendor_prices = any(entry["details"]["price"] is not None for entry in entries)
    for field, label in (("quantity", "Quantity"), ("price", "Unit price"), ("currency", "Currency")):
        if field == "price" and standard_prices:
            if not has_vendor_prices:
                normal_only.append(len(headers))
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
        merchant = entry["details"]["merchant"]
        cells = [
            anchor("entry", entry["id"]) + f'[[{locations[merchant]}#entry-{entry["id"]}|{literal(entities[merchant]["name"])}]]',
            item_cell(entry["details"]["item"], images, entities, locations),
            *(getter(entry) for getter in getters),
        ]
        if standard_prices and has_vendor_prices and entry["details"]["price"] is None:
            index = headers.index("Unit price")
            cells[index] = (
                "<noinclude>" + cells[index] + "</noinclude><includeonly>"
                + f'[[{locations[entry["details"]["item"]]}#price-{entry["details"]["item"]}|Standard item price]]'
                + "</includeonly>"
            )
        row = html_row(cells, normal_only)
        rows.append(filtered_row(row, "item", [entry["details"]["item"]]))
    rendered = html_table(headers, rows, normal_only)
    return "\n== Wares ==\n" + selective_view(
        "\n\n".join(notes) + "\n\n" + rendered, "offers",
    ) + "\n"


def recipe_table(entries, stations, images, entities, locations):
    groups = recipe_groups(entries)
    headers = ["Ingredients", "Output", "Crafting method", "Base cost", "Conditions"]
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
            quantities(details["outputs"], images, entities, locations), " &middot; ".join(sorted(links)),
        ]
        cost = details["cost"]
        row.append("Not established" if cost is None else known(cost["amount"]) + (
            " base [[Action points|AP]]" if cost["unit"] == "base AP" else " " + literal(cost["unit"])))
        row.append(known(first["conditions"]))
        station_ids = [stations[entry["details"]["station"]]["id"] for entry in group if entry["details"]["station"] in stations]
        rows.append(selective_view(filtered_row(html_row(row), "station", station_ids), "recipes"))
    return "\n=== Recipes ===\nThese are base recipes; skill and station effects may change costs or consumption.\n\n" + html_table(headers, rows)


def construction_table(recipe, images, entities, locations):
    cells = [
        anchor("entry", recipe["id"]) + quantities(recipe["inputs"], images, entities, locations),
        known(recipe["result"]["quantity"]) + " in-place completion<br />" + literal(recipe["result"]["description"]),
        f'[[{recipe["station_title"]}]]', known(recipe["base_ap_cost"]) + " base [[Action points|AP]]",
        literal(recipe["condition"]),
    ]
    row = selective_view(filtered_row(html_row(cells), "station", [recipe["station_id"]]), "recipes")
    return "\n=== Recipes ===\n" + html_table(["Ingredients", "Output", "Crafting method", "Base cost", "Conditions"], [row])


def loot_table(entries, images, entities, locations, owner):
    headers = ["Source", "Result", "Quantity", "Conditional probability"]
    getters = []
    for field, label, formatter in (
        ("weight", "Reported weight", known),
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
        probability = details["probability"]
        row = [
            anchor("entry", entry["id"]) + f'[[{owner}#entry-{entry["id"]}|{literal(owner)}]]',
            result, count_range(details["quantity"]),
            known(Decimal(str(probability)) * 100) + "%" if probability is not None else "Not established",
            *(getter(entry) for getter in getters),
        ]
        if not same_conditions:
            row.append(known(entry["conditions"]))
        if not same_summary:
            row.append(literal(entry["summary"]))
        rows.append(filtered_row(html_row(row), "item", [details["outcome"] or "empty"]))
    notes = ["Reported weights are not converted to probabilities. A range does not imply equally likely quantities."]
    if same_conditions and conditions:
        notes.append(literal(conditions))
    if same_summary:
        notes.append(literal(summary))
    return "\n== Loot ==\n" + selective_view(
        "\n\n".join(notes) + "\n\n" + html_table(headers, rows), "loot",
    ) + "\n"


def acquisition_probability(row):
    probability = row["probability"]
    if probability is None:
        return "Not established. " + literal(row["odds_note"])
    chance = Fraction(probability["numerator"], probability["denominator"])
    denominator = chance.denominator
    for prime in (2, 5):
        while denominator % prime == 0:
            denominator //= prime
    if denominator == 1:
        with localcontext() as context:
            context.prec = 80
            value = known(Decimal(chance.numerator) * 100 / Decimal(chance.denominator)) + "%"
    else:
        value = known(chance.numerator) + "/" + known(chance.denominator)
    return value + "<br />" + literal(probability["scope"]) + (
        "<br />" + literal(row["odds_note"]) if row.get("odds_note") else "")


def acquisition_table(source, images, entities, locations):
    rows = []
    for row in source["rows"]:
        cells = [
            anchor("acquisition", row["id"]) + f'[[{source["title"]}#acquisition-{row["id"]}|{literal(source["title"])}]]',
            item_cell(row["item"], images, entities, locations), count_range(row["quantity"]),
            acquisition_probability(row), literal(row["condition"]),
        ]
        rows.append(filtered_row(html_row(cells), "item", [row["item"]]))
    return "\n== Contents and acquisition ==\n" + selective_view(html_table(
        ["Source", "Item", "Quantity", "Conditional probability", "Condition"], rows,
    ), "loot") + "\n"


def acquisition_pool_table(pool, owner, entities, locations):
    rows = []
    for identity in sorted(pool["eligible_item_ids"]):
        condition = f'Eligible, not guaranteed. [[{owner}#pool-{pool["id"]}|Rules and value budget]].'
        if identity in pool["item_conditions"]:
            condition += f' [[{owner}#treasure-condition-{identity}|Additional story condition]].'
        cells = [
            anchor("pool-item", pool["id"] + "-" + identity) + entity_link(identity, entities, locations),
            "Budget-dependent", "Not established", condition,
        ]
        rows.append(filtered_row(html_row(cells), "item", [identity]))
    content = html_table(["Item", "Quantity", "Per-item probability", "Eligibility"], rows)
    return selective_view(filtered_row(filtered_row(content, "item", pool["eligible_item_ids"]),
                                       "pool", [pool["id"]]), "pool")


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
    if details.get("grids"):
        lines.extend(["", "== Grid evidence ==", table(["Grid owner", "Confidence", "Evidence", "Scope"], [
            [f'[[{locations[grid["entity"]]}#grid-{grid["id"]}|{literal(locations[grid["entity"]])}]]',
             literal(grid["confidence"]), evidence_text(grid["evidence"]), literal(grid["context"])]
            for grid in sorted(details["grids"], key=lambda row: row["id"])
        ])])
    lines.extend(["", "== Classification evidence ==", table(["Character", "Grouping", "Confidence", "Evidence", "Interpretation"], [
        [f'[[{locations[row["entity"]]}]]', literal(row["kind"]), literal(row["confidence"]), evidence_text(row["evidence"]), literal(row["note"])]
        for row in sorted(catalog["classifications"], key=lambda row: row["entity"])
    ])])
    if "taxonomy" in catalog:
        lines.extend(["", "== Browsing categories ==",
                      "Categories are editorial navigation based on reviewed names, profiles, recipes and operator identifications, not an in-game biological classification. Cross-tags link to the same editable article; they do not create another copy of its facts.",
                      "Scaalmyr includes Sceetler and Scaal as confirmed by the wiki operator. Aquatic creatures is an operator-confirmed browsing label for Mudfin and Razorfin, not a fish classification. Nightmare is grouped with Bugs from its arthropod appearance. NPC separation is unchanged.",
                      "Rodents groups Mirk Runner and Mirk Mauler using their rat sprite associations: " + evidence_text([
                          {"source": "game-data", "section": "gml_Object_databank_Alarm_3", "key": "beingDB[11].sprite/beingDB[29].sprite"}
                      ])])
    if catalog.get("guides"):
        lines.extend(["", '<span id="Combat_and_action_guide_evidence"></span>', "== Guide evidence ==", table(["Editable owner", "Confidence", "Evidence"], [
            [f'[[{guide["title"]}]]', literal(guide["confidence"]), evidence_text(guide["evidence"])]
            for guide in sorted(catalog["guides"], key=lambda row: row["title"])
        ])])
    if catalog.get("item_effects"):
        lines.extend(["", "== Consumption effect evidence ==", table(["Editable owner", "Confidence", "Evidence"], [
            [f'[[{locations[row["entity"]]}#Consumption_effects|{literal(locations[row["entity"]])}]]',
             literal(row["confidence"]), evidence_text(row["evidence"])]
            for row in sorted(catalog["item_effects"], key=lambda row: row["entity"])
        ])])
    acquisition_sources = catalog.get("acquisition", {}).get("sources", [])
    if acquisition_sources:
        rows = []
        for source in acquisition_sources:
            rows.append([literal(source["id"]), f'[[{source["title"]}]]', literal(source["confidence"]), evidence_text(source["evidence"])])
            rows.extend([
                [literal(row["id"]), f'[[{source["title"]}#acquisition-{row["id"]}|{literal(source["title"])}]]',
                 literal(row.get("confidence", source["confidence"])) + "; " + literal(row["coverage"]), evidence_text(row["evidence"])]
                for row in source["rows"]
            ])
            rows.extend([
                [literal(source["id"] + "-" + identity), f'[[{locations[identity]}]]',
                 literal(source["confidence"]), evidence_text(source["evidence"])]
                for identity in sorted(source.get("entity_context", {}))
            ])
        lines.extend(["", "== Acquisition source evidence ==", table(["Record", "Editable owner", "Scope", "Evidence"], rows)])
        if catalog["acquisition"].get("item_notes"):
            lines.extend(["", "== Special acquisition evidence ==", table(["Editable owner", "Scope", "Evidence"], [
                [f'[[{locations[note["item"]]}#How_to_acquire|{literal(locations[note["item"]])}]]',
                 literal(note["kind"]), evidence_text(note["evidence"])]
                for note in sorted(catalog["acquisition"]["item_notes"], key=lambda row: row["item"])
            ])])
        source_titles = {source["id"]: source["title"] for source in acquisition_sources}
        if catalog["acquisition"].get("pools"):
            lines.extend(["", "== Treasure pool evidence ==", table(["Pool", "Editable owner", "Confidence", "Evidence"], [
                [literal(pool["id"]),
                 f'[[{source_titles[pool["owner_source"]]}#pool-{pool["id"]}|{literal(pool["title"])}]]',
                 literal(pool["confidence"]), evidence_text(pool["evidence"])]
                for pool in sorted(catalog["acquisition"]["pools"], key=lambda row: row["id"])
            ])])
    if catalog.get("construction_recipes"):
        lines.extend(["", "== In-place construction evidence ==", table(["Record", "Editable owner", "Confidence", "Evidence"], [
            [literal(recipe["id"]), f'[[{locations[recipe["owner_item"]]}#entry-{recipe["id"]}|{literal(locations[recipe["owner_item"]])}]]',
             literal(recipe["confidence"]), evidence_text(recipe["evidence"])]
            for recipe in catalog["construction_recipes"]
        ])])
    if catalog.get("damage_sources"):
        lines.extend(["", "== Ammunition and thrown damage evidence ==", table(["Editable owner", "Delivery", "Confidence", "Evidence"], [
            [f'[[{locations[row["entity"]]}#Damage_behavior|{literal(locations[row["entity"]])}]]',
             literal(row["delivery"]), literal(row["confidence"]), evidence_text(row["evidence"])]
            for row in sorted(catalog["damage_sources"], key=lambda row: (row["entity"], row["damage_type"]))
        ])])
    skill_records = [row for row in data.get("entries", []) if row["id"].startswith("skill-") and row["id"].endswith("-mechanics")]
    if skill_records:
        lines.extend(["", "== Skill description methodology ==",
                      "Skill effects are original paraphrases of the cited English descriptions. These source descriptions are not independent gameplay measurements; implementation, rounding and other modifiers may affect results. Per-rank benefits and milestone effects are distinguished on the owning skill pages."])
    for history in catalog.get("state_history", []):
        lines.extend(["", "== Character state confirmation ==",
                      f'[[{locations[history["before"]]}#State_history|Character state history]]: '
                      + literal(history["attribution"]) + ", " + literal(history["recorded_on"])
                      + ". The journal remains the owner of the quest instructions."])
        if history.get("evidence"):
            lines.append(evidence_text(history["evidence"]))
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
            table(["Rule", "Methodological qualification"], [
                [literal(rule["id"]), literal(rule["qualification"])]
                for rule in currency["rules"]
                if rule.get("qualification") and rule["id"] in {*CURRENCY_QUALIFICATIONS, "coin-weight-units"}
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


CURRENCY_QUALIFICATIONS = {
    "coin-consolidation": (
        "Change uses the highest denominations first. Copper change is rounded to a whole coin, "
        "so rounding can affect exact results; the fewest possible coins are not guaranteed at every rounding boundary."
    ),
    "trade-standard-value": (
        "An unchanged, full-condition item has the same underlying buy and sell value. Rounding in the "
        "affordability check and copper change can affect fractions smaller than one copper coin."
    ),
}


def currency_page(currency, entities, locations):
    coins = currency["coins"]
    text = "[[Merchants]] | [[Items]] | [[Main Page]]\n\nCoins and barter use a shared value. The coin details below are maintained on the individual coin pages.\n"
    text += "\nCatalog purchase prices use exact gold, silver and copper amounts with the fewest whole coins. This display does not round or alter the price; the game's change and resale rules are explained separately below.\n"
    for rule in currency["rules"]:
        text += "\n" + anchor("currency", rule["id"]) + f'\n== {CURRENCY_RULE_TITLES[rule["id"]]} ==\n'
        if rule["id"] == "coin-denominations":
            text += "Compare each coin's value in silver equivalents:\n\n"
            text += "\n".join("{{:" + locations[coin["entity"]] + "}}" for coin in coins) + "\n"
        elif rule["id"] == "coin-weight-units":
            text += "A coin stack's weight is its per-coin weight multiplied by the quantity. Consolidating equal value into higher denominations reduces carried weight.\n"
        else:
            text += literal(rule["text"]) + "\n"
        qualification = CURRENCY_QUALIFICATIONS.get(rule["id"], rule.get("qualification"))
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
    acquisition_sources = catalog.get("acquisition", {}).get("sources", [])
    acquisition_by_id = {source["id"]: source for source in acquisition_sources}
    acquisition_pools = {pool["id"]: pool for pool in catalog.get("acquisition", {}).get("pools", [])}
    acquisition_notes = {note["item"]: note for note in catalog.get("acquisition", {}).get("item_notes", [])}
    researched = {row["page"] for row in data["facts"]} | {entry_page(row) for row in entries} | set(facts.values()) | set(owners.values())
    active = {title: filename for title, filename in RESEARCH_PAGE_FILES.items() if title in researched}
    pages = {title: read_authored(root, title, filename) for title, filename in {**PAGE_FILES, "NPCs": "NPCs.wiki", **active}.items()}
    if any("health_armor" in image for image in images) or any(
        grid["kind"] == "health" and any(cell and cell["armor"] for row in grid["rows"] for cell in row)
        for grid in details.get("grids", [])
    ):
        pages["Health and armor"] += health_armor_legend(images)
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
        matching = [image for image in images if image.get("entity") == entity["id"]]
        for image in matching:
            text += anchor("illustration", image["id"])
            if image["rights_status"] == "approved":
                text += f'\n[[{image["file_title"]}|thumb|{literal(image["caption"])}]]\n'
            else:
                text += "\nNo reviewed picture is available yet.\n"
        if not matching and entity["category"] != "damage_class":
            text += "\nNo reviewed picture is available yet.\n"
        pages[row["title"]] = text
        for alias in row["aliases"]:
            pages[alias] = f'#REDIRECT [[{row["title"]}]]\n'
    if acquisition_sources and "Loot tables" not in pages:
        pages["Loot tables"] = read_authored(root, "Loot tables", RESEARCH_PAGE_FILES["Loot tables"])
    for source in sorted(acquisition_sources, key=lambda row: row["id"]):
        links = {title: title for title in source["related_pages"]}
        links[source["title"]] = source["title"]
        links.update({entities[identity]["name"]: locations[identity] for identity in source["related_entities"]})
        links.update({entities[row["item"]]["name"]: locations[row["item"]] for row in source["rows"]})
        text = "[[Loot tables]] | [[Main Page]]\n\n" + anchor("source", source["id"])
        if "image_entity" in source:
            image = image_for(source["image_entity"], images)
            if image is None:
                raise DataError("acquisition source: contextual picture has no approved image")
            text += f'\n[[{image["file_title"]}|thumb|{literal(source["image_caption"])}]]\n'
        text += "\n" + linked_prose(source["summary"], links) + "\n"
        text += "\n\n".join(linked_prose(condition, links) for condition in source["conditions"]) + "\n"
        if source.get("loot_context"):
            text += "\n" + selective_view(linked_prose(source["loot_context"], links), "loot") + "\n"
        if source["rows"]:
            text += acquisition_table(source, images, entities, locations)
        owned_pools = [acquisition_pools[identity] for identity in source.get("pool_ids", [])]
        conditions = {identity: condition for pool in owned_pools for identity, condition in pool["item_conditions"].items()}
        if conditions:
            text += "\n== Item-specific treasure conditions ==\n"
            for identity, condition in sorted(conditions.items()):
                gate = "<noinclude>" + anchor("treasure-condition", identity) + "</noinclude>"
                gate += entity_link(identity, entities, locations) + ": " + literal(condition)
                pool_ids = [pool["id"] for pool in owned_pools if identity in pool["item_conditions"]]
                text += selective_view(filtered_row(filtered_row(gate, "item", [identity]), "pool", pool_ids), "pool") + "\n"
        if owned_pools:
            text += "\n== Eligibility and odds ==\n"
            text += "\n\n".join(literal(note) for note in sorted({pool["odds_note"] for pool in owned_pools})) + "\n"
        for pool in sorted(owned_pools, key=lambda row: row["id"]):
            text += "\n" + anchor("pool", pool["id"]) + "\n=== " + literal(pool["title"]) + " ===\n"
            text += literal(pool["summary"]) + "\n\n" + acquisition_pool_table(pool, source["title"], entities, locations) + "\n"
        for reference in source.get("pool_refs", []):
            pool = acquisition_pools[reference["pool"]]
            label = anchor("pool-source", source["id"] + "-" + pool["id"])
            label += f"'''[[{source['title']}]]''': " + literal(reference["condition"])
            text += "\n" + selective_view(filtered_row(label, "pool", [pool["id"]]), "pool-source") + "\n"
            text += "<noinclude>{{:" + acquisition_by_id[pool["owner_source"]]["title"] + "|view=pool|pool=" + pool["id"] + "}}</noinclude>\n"
        if links:
            text += "\nRelated pages: " + " | ".join(f"[[{target}]]" for target in sorted(set(links.values()) - {source["title"]})) + "\n"
        pages[source["title"]] = text
        pages["Loot tables"] += f'\n* [[{source["title"]}]]\n'
        if source["kind"] in {"starting", "fixed-location"}:
            pages["Main Page"] += f'\n[[{source["title"]}]]\n'
        for identity in source["related_entities"]:
            context = source.get("entity_context", {}).get(identity)
            pages[locations[identity]] += (
                "\n" + literal(context) + f' [[{source["title"]}]]\n' if context
                else f'\n[[{source["title"]}|Related acquisition guide]]\n'
            )
    for guide in sorted(catalog.get("guides", []), key=lambda row: row["title"]):
        if guide["title"] not in pages:
            pages[guide["title"]] = "[[Game mechanics]] | [[Main Page]]\n"
            pages["Game mechanics"] += f'\n[[{guide["title"]}]]\n'
            pages["Main Page"] += f'\n[[{guide["title"]}]]\n'
        if "image_entity" in guide:
            image = image_for(guide["image_entity"], images)
            if image is None:
                raise DataError("guide: contextual picture has no approved image metadata")
            pages[guide["title"]] += f'\n[[{image["file_title"]}|thumb|{literal(guide["image_caption"])}]]\n'
        pages[guide["title"]] += "\n== How it works ==\n"
        links = {target: target for target in guide.get("related_pages", [])}
        if "section_titles" in guide:
            links.update({entities[identity]["name"]: locations[identity] for identity in guide["related_entities"]})
        for heading, paragraph in zip(guide.get("section_titles", [None] * len(guide["paragraphs"])), guide["paragraphs"]):
            if heading:
                pages[guide["title"]] += "\n=== " + literal(heading) + " ===\n"
            pages[guide["title"]] += "\n" + linked_prose(paragraph, links) + "\n"
        if guide.get("related_pages"):
            pages[guide["title"]] += "\nRelated guides: " + " | ".join(
                f"[[{target}]]" for target in guide["related_pages"]) + "\n"
        if guide["related_entities"]:
            pages[guide["title"]] += "\nRelated items and skills: " + " | ".join(
                entity_link(identity, entities, locations) for identity in guide["related_entities"]) + "\n"
            for identity in guide["related_entities"]:
                pages[locations[identity]] += f'\n[[{guide["title"]}|{guide["title"]}: effects and related rules]]\n'
        if guide["title"] not in MECHANIC_GUIDE_TITLES:
            pages[guide["title"]] += "\n[[Health and armor|Health shapes and armor layers]] | [[Action points]]\n"
        if guide["title"] == "Foods" and any(group["title"] == "Food and drink" for field in ("groups", "tags")
                                           for group in catalog.get("taxonomy", {}).get(field, [])):
            pages[guide["title"]] += "\n[[:Category:Food and drink|Browse foods and drinks]] | [[Crafting|Find a preparation recipe]]\n"

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
        groups = [group for group in catalog.get("taxonomy", {}).get("groups", []) if group["index"] == title]
        if groups:
            for group in sorted(groups, key=lambda row: row["title"]):
                pages[title] += f'\n== {group["title"]} ==\n[[:Category:{group["title"]}|Browse category]]\n'
                matching = {locations[identity]: targets[locations[identity]] for identity in group["members"]}
                pages[title] += "\n".join(navigation_lines(matching)) + "\n"
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
    previous_owners = entry_owners(data, locations, relations, {key: value for key, value in catalog.items() if key != "acquisition"})
    for entry in entries:
        previous = previous_owners[entry["id"]]
        target = owners[entry["id"]]
        if previous != target:
            pages[previous] += "\n" + anchor("entry", entry["id"]) + f"[[{target}#entry-{entry['id']}|Documented loot source]]\n"

    for title in list(pages):
        entity_ids = {row["entity"] for row in catalog["pages"] if row["title"] == title}
        matching_facts = [row for row in data["facts"] if facts[row["id"]] == title]
        matching_profiles = sorted(
            (row for row in details["profiles"] if row["entity"] in entity_ids),
            key=lambda row: (any(key.endswith("-pattern-min") for key in row["values"]), row["id"]),
        )
        price_item = next(iter(entity_ids & price_items), None)
        coin = next((coins[identity] for identity in entity_ids if identity in coins), None)
        matching_entries = [row for row in entries if owners[row["id"]] == title]
        recipes = [row for row in matching_entries if row["kind"] == "recipe"]
        grids = sorted((grid for grid in details.get("grids", []) if grid["entity"] in entity_ids),
                       key=lambda row: (row["kind"] != "health", row["kind"]))
        pages[title] += stat_table(
            matching_facts, matching_profiles, properties, entities, locations,
            price_item, prices.get(price_item), coin, recipes, images, grids, catalog.get("construction_recipes", []),
        )
        for grid in grids:
            pages[title] += cell_grid(grid, entities[grid["entity"]]["category"], images)
        if coin is not None:
            pages[title] += coin_summary(coin, entities, locations)
        for kind, renderer in (
            ("merchant", lambda rows: merchant_table(rows, images, entities, locations, "unit_prices" in catalog)),
            ("loot", lambda rows: loot_table(rows, images, entities, locations, title)),
        ):
            matching = [row for row in matching_entries if row["kind"] == kind]
            if matching and not (kind == "loot" and any(entities[identity]["category"] == "item" for identity in entity_ids)):
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
                recipes.append(f"* [[{owners[entry['id']]}#Recipes|{literal(owners[entry['id']])}]]")
            elif entry["kind"] == "quest":
                quests.append((quest_order(entry), f"* [[{target}|{literal(entry['title'])}]]"))
            else:
                other.append(f"* [[{target}|{literal(entry['title'])}]]")
        if entities[identity]["category"] == "item":
            pages[title] += '\n<span id="Obtaining"></span>\n== How to acquire ==\n'
            if identity in acquisition_notes:
                note = acquisition_notes[identity]
                links = {entities[target]["name"]: locations[target] for target in note.get("related_items", [])}
                pages[title] += linked_prose(note["text"], links) + "\n"
                if note.get("related_items"):
                    pages[title] += "\nRelated recipes: " + " | ".join(
                        f'[[{locations[target]}#Recipes|{literal(locations[target])}]]'
                        for target in note["related_items"]
                    ) + "\n"
            own_recipes = [entry for entry in entries if entry["kind"] == "recipe" and owners[entry["id"]] == title]
            if own_recipes:
                pages[title] += recipe_table(own_recipes, stations, images, entities, locations)
            for recipe in catalog.get("construction_recipes", []):
                if recipe["owner_item"] == identity:
                    pages[title] += construction_table(recipe, images, entities, locations)
            offers = [entry for entry in entries if entry["kind"] == "merchant" and entry["details"]["item"] == identity]
            if identity in price_items:
                pages[title] += (
                    "\n=== Buying ===\n" + anchor("price", identity) + "Standard unit price: "
                    + selective_view(price_text(prices.get(identity), images), "price", default=True)
                    + ". Purchase price per item; not resale value.\n"
                )
            if offers:
                pages[title] += "\n".join(
                    "{{:" + owner + "|view=offers|item=" + identity + "}}"
                    for owner in sorted({owners[entry["id"]] for entry in offers})
                ) + "\n"
            loot = [entry for entry in entries if entry["kind"] == "loot" and entry["details"]["outcome"] == identity]
            owned_loot = [entry for entry in loot if owners[entry["id"]] == title]
            if owned_loot:
                pages[title] += loot_table(owned_loot, images, entities, locations, title)
            loot_owners = {owners[entry["id"]] for entry in loot if owners[entry["id"]] != title}
            documented_sources = {source["title"] for source in acquisition_sources if any(
                row["item"] == identity for row in source["rows"])}
            loot_owners.update(documented_sources)
            if loot_owners:
                pages[title] += "\n=== Loot sources ===\n" + "\n".join(
                    "{{:" + owner + "|view=loot|item=" + identity + "}}"
                    for owner in sorted(loot_owners)
                ) + "\n"
            eligible_sources = [(source, reference, acquisition_pools[reference["pool"]])
                                for source in acquisition_sources for reference in source.get("pool_refs", [])
                                if identity in acquisition_pools[reference["pool"]]["eligible_item_ids"]]
            if eligible_sources:
                pages[title] += "\n=== Random treasure sources ===\n"
                for source, reference, pool in sorted(eligible_sources, key=lambda row: (row[0]["title"], row[2]["id"])):
                    pages[title] += "\n{{:" + source["title"] + "|view=pool-source|pool=" + pool["id"] + "}}\n"
                    pages[title] += "{{:" + acquisition_by_id[pool["owner_source"]]["title"] + "|view=pool|pool=" + pool["id"] + "|item=" + identity + "}}\n"
            if identity in coins:
                pages[title] += "[[Currency and trading#currency-coin-consolidation|Merchant change and coin consolidation]]\n"
            elif not own_recipes and not offers and not loot and not documented_sources and not eligible_sources and identity not in acquisition_notes:
                pages[title] += "No documented acquisition source is available yet.\n"
        for recipe in catalog.get("construction_recipes", []):
            if any(component["item"] == identity for component in recipe["inputs"]):
                recipes.append(f'* [[{locations[recipe["owner_item"]]}#Recipes|{literal(locations[recipe["owner_item"]])}]]')
        if recipes:
            pages[title] += "\n== Used in ==\n" + "\n".join(sorted(set(recipes))) + "\n"
        if quests:
            pages[title] += "\n== Main quest ==\n" + "\n".join(text for _, text in sorted(quests)) + "\n"
        if other:
            pages[title] += "\n== Related pages ==\n" + "\n".join(sorted(set(other))) + "\n"
        if entities[identity]["category"] != "damage_class" and not any(facts[fact["id"]] == title for fact in data["facts"]) and not any(profile["entity"] == identity for profile in details["profiles"]):
            pages[title] += "\nNumerical stats are not established.\n"

    for entity in entities.values():
        if entity["category"] != "damage_class":
            continue
        uses = defaultdict(set)
        number = int(entity["id"].removeprefix("damage-class-")) if entity["id"].removeprefix("damage-class-").isdigit() else None
        for profile in details["profiles"]:
            for key, label in (("damage-class-id", "Attack"), ("ranged-damage-class-id", "Ranged attack")):
                if number is not None and profile["values"].get(key) == number:
                    uses[profile["entity"]].add(label)
        for source in catalog.get("damage_sources", []):
            if source["damage_type"] == entity["id"]:
                uses[source["entity"]].add(source["delivery"].capitalize())
        text = "\n== Weapons and attacks ==\n"
        if uses:
            text += table(["Source", "Attack"], [
                [entity_link(identity, entities, locations), ", ".join(sorted(labels))]
                for identity, labels in sorted(uses.items(), key=lambda pair: entities[pair[0]]["name"])
            ])
        else:
            text += "No weapon or creature attack is documented for this type yet.\n"
        pages[locations[entity["id"]]] += text
    for source in sorted(catalog.get("damage_sources", []), key=lambda row: (row["entity"], row["damage_type"])):
        pages[locations[source["entity"]]] += (
            "\n== Damage behavior ==\n" + source["delivery"].capitalize() + ": "
            + entity_link(source["damage_type"], entities, locations) + "\n\n" + literal(source["summary"]) + "\n"
        )
    for effect in catalog.get("item_effects", []):
        pages[locations[effect["entity"]]] += "\n== Consumption effects ==\n" + "\n\n".join(
            literal(paragraph) for paragraph in effect["paragraphs"]
        ) + "\n"

    for history in catalog.get("state_history", []):
        before, after = locations[history["before"]], locations[history["after"]]
        pages[before] += "\n== State history ==\n" + literal(history["summary"]) + "\n"
        pages[before] += f'[[{after}|Revived character]] | [[Quests and journal#entry-{history["quest"]}|Return to the dead camp]]\n'
        pages[after] += f"\n== State history ==\n[[{before}#State_history|Earlier identity and revival]]\n"

    if "Crafting" in pages and stations:
        pages["Crafting"] += "\n== Crafting methods ==\n" + "\n".join(
            f'* [[{row["title"]}]]' for row in sorted(catalog["stations"], key=lambda row: row["title"])
        ) + "\n"
    for station in catalog.get("stations", []):
        title = station["title"]
        pages[title] += "\n== Crafting here ==\n" + literal(station["summary"]) + "\n"
        reports = station.get("reports", [])
        if station["entity"] is None and not reports and station["id"] != "inventory-crafting":
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
        if station.get("related_stations"):
            pages[title] += "\n== Alternatives ==\n" + " | ".join(
                f'[[{next(s["title"] for s in catalog["stations"] if s["id"] == identity)}|Alternative crafting method]]'
                for identity in station["related_stations"]
            ) + "\n"
        if station.get("quest_entries"):
            pages[title] += "\nRelated journal: " + " | ".join(
                f'[[Quests and journal#entry-{identity}|{literal(next(entry["title"] for entry in entries if entry["id"] == identity))}]]'
                for identity in station["quest_entries"]
            ) + "\n"
        targets = set()
        for entry in entries:
            if entry["kind"] == "recipe" and entry["details"]["station"] in station["methods"]:
                targets.add(owners[entry["id"]])
        targets.update(locations[recipe["owner_item"]] for recipe in catalog.get("construction_recipes", [])
                       if recipe["station_id"] == station["id"])
        rows = ["{{:" + owner + "|view=recipes|station=" + station["id"] + "}}\n" for owner in sorted(targets)]
        pages[title] += "\n== What you can craft ==\n" + html_table(
            ["Ingredients", "Output", "Crafting method", "Base cost", "Conditions"], rows,
        )
    pages["Source provenance"] = source_page(data, catalog, details, locations, facts, owners)
    if "currency" in catalog:
        pages["Currency and trading"] = currency_page(catalog["currency"], entities, locations)
        for title in ("Main Page", "Merchants"):
            if title in pages:
                pages[title] += "\n[[Currency and trading|Currency, coin weights, and trading]]\n"
        for entry in entries:
            if entry["kind"] == "merchant" and "[[Currency and trading" not in pages[owners[entry["id"]]]:
                pages[owners[entry["id"]]] += "\n[[Currency and trading|How prices, condition, and change work]]\n"
    memberships = defaultdict(set)
    category_parents = {}
    for row in catalog["pages"]:
        entity = entities[row["entity"]]
        root_category = "NPCs" if classified.get(entity["id"]) == "npc" else CATEGORY_PAGES[entity["category"]]
        memberships[row["title"]].add(root_category)
        if entity["category"] == "skill":
            group = entities[entity["group"]]["name"]
            memberships[row["title"]].add(group)
            category_parents[group] = "Skills"
    for group in [*catalog.get("taxonomy", {}).get("groups", []), *catalog.get("taxonomy", {}).get("tags", [])]:
        category_parents[group["title"]] = group["index"]
        for identity in group["members"]:
            memberships[locations[identity]].add(group["title"])
    for title, categories in sorted(memberships.items()):
        pages[title] += "\n" + " ".join(f"[[Category:{category}]]" for category in sorted(categories)) + "\n"
    all_categories = {category for categories in memberships.values() for category in categories}
    for category in sorted(all_categories):
        parent = category_parents.get(category)
        index = parent or category
        pages["Category:" + category] = f"[[{index}|Readable index]] | [[Main Page]]\n\nPages in this browsing group keep their own editable facts.\n"
        if parent:
            pages["Category:" + category] += f"\n[[Category:{parent}]]\n"
    validate_transclusions(pages)
    return pages
