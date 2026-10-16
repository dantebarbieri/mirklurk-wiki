"""Item articles: an at-a-glance summary box and prose sections for each documented stat."""

from collections import defaultdict
from decimal import Decimal

from wiki_catalog import VALUE_LINK, VALUE_NOTE
from wiki_display import grid_argument
from wiki_render import (
    CAPACITY_NOTE, LEGACY_PROPERTIES, PAIRED_PROPERTIES, PROPERTY_LABELS, anchor, fact_value, known, literal,
    profile_value, prose_list, recipe_profile_values,
)
from wiki_views import scroll_open

ITEM_SUMMARY_ROWS = (
    ("initial-weight", "Weight"), ("stack-limit", "Stack limit"), ("equip-ap-cost", "Equip cost"),
    ("item-ap-cost", "Action cost"), ("initial-price", "Value"), ("value", "Value"),
    ("craft-ap-cost", "Base crafting cost"), ("craft-yield", "Base recipe yield"),
    ("random-treasure-exclusion", "In general random treasure"),
)
# There is no site stylesheet for a media query, so the summary sizes itself from its container: it floats beside
# the article only when the content column is at least SUMMARY_FLOAT_MIN wide and otherwise spans the full width.
SUMMARY_FLOAT_MIN = "36em"
SUMMARY_STYLE = (
    "float:right;clear:right;max-width:100%;"
    f"min-width:min(100%, calc((({SUMMARY_FLOAT_MIN}) - 100%) * 1000));"
    f"margin:0 0 1em clamp(0px, calc((100% - ({SUMMARY_FLOAT_MIN})) * 1000), 1em);"
)
# Vector headings are flow-root, and WebKit squeezes a flow-root box beside a full-width float to zero width
# instead of moving it below. This empty flow-root spacer is full width (so it drops below the summary) only when
# the summary is full width; on wider columns its width resolves to zero and it fits beside the float harmlessly.
SUMMARY_CLEAR_STYLE = f"display:flow-root;height:0;width:min(100%, calc((({SUMMARY_FLOAT_MIN}) - 100%) * 1000));"
ITEM_FIRE_KEYS = ("light-radius", "burn-time", "tinder-bonus", "spark-chance", "stone-spark-chance")
ITEM_SECTION_KEYS = {
    "Protection": ("item-armor", "insulation", "waterproof"),
    "Storage": ("inventory-slots-added", "storage-grid-width", "storage-grid-height"),
    "Chopping and cutting": ("chopping-capability", "cutting-capability"),
    "Fire": ITEM_FIRE_KEYS,
    "Consumption": ("satiation-gain", "sickness-risk"),
    "Resting": ("comfort",),
    "Durability": ("durability-max", "break-chance"),
}

# The game only wears items whose maximum is above 1, and never shows it for coins, gems or quest items.
HIDDEN_DURABILITY = {f"item-{n}" for n in (72, 73, 74, 75, 97, 98, 99, 100, 101)}
DURABILITY_LABELS = {"item-25": ("Portions", "; eating it uses one portion at a time."), "item-112": ("Oil", ".")}
HANDS = {f"item-{n}": text for numbers, text in (
    ((2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 27, 28, 90, 157, 158, 159, 160, 161, 190, 191, 267, 268, 269, 270, 271, 272, 273,
      274), "One-handed; main-hand slot"),
    ((29, 30, 169, 184, 185, 186, 187, 188, 189, 206, 266), "Two-handed; fills the main-hand and off-hand slots"),
    ((44, 93, 105, 106, 179), "Two-handed bow; main-hand slot, leaving the off-hand slot for arrows"),
    ((0, 1, 50, 58, 118, 45, 46, 76, 174, 219, 220, 110, 111), "Off-hand slot only"),
    ((41, 96, 212), "Main-hand or off-hand slot")) for n in numbers}


def item_article(name, facts, profiles, properties, entities, locations, price=None, coin=None, recipes=(), grids=(),
                 constructions=(), armor_guide=False, chop_guide=False):
    """An item's at-a-glance summary box followed by prose sections for its stats and attack patterns."""
    if not facts and not profiles:
        return ""
    values, sources, fact_marks = {}, {}, defaultdict(str)
    folded = set()
    for profile in profiles:
        folded.update(recipe_profile_values(profile, recipes, constructions))
        for key, value in profile["values"].items():
            values.setdefault(key, value)
            sources.setdefault(key, profile["id"])
    skipped = set(folded)
    identity = profiles[0]["entity"] if profiles else None
    if values.get("durability-max", 2) <= 1 or identity in HIDDEN_DURABILITY:
        skipped.add("durability-max")
    if coin is not None:
        skipped.update({"initial-price", "initial-weight", "stack-limit"})
    if "initial-price" in values and ("value" in values or price is not None):
        skipped.add("initial-price")
    coalesced = set()
    for fact in facts:
        for profile in profiles:
            key = LEGACY_PROPERTIES.get(fact["id"].removeprefix(profile["entity"] + "-base-"))
            value = profile["values"].get(key)
            if (fact["id"].startswith(profile["entity"] + "-base-") and key not in skipped and fact["value"] == value
                    and type(fact["value"]) in {int, float} and type(value) in {int, float}
                    and fact["confidence"] == "inferred"):
                fact_marks[key] += anchor("fact", fact["id"])
                coalesced.add(fact["id"])
                break
    remaining = [key for key in sorted(values) if key not in skipped]
    used = {}

    def take(key, section):
        used[key] = section
        return fact_marks[key] + profile_value(key, values[key], entities, locations)

    def label(key):
        text = PROPERTY_LABELS.get(key, properties[key]["label"])
        unit = properties[key]["unit"]
        return text + (f" ({unit})" if unit in {"XP", "items", "cells", "normalized height"} else "")

    sections = []
    rows = []
    for key, heading in ITEM_SUMMARY_ROWS:
        if key not in remaining:
            continue
        if key == "random-treasure-exclusion":
            used[key] = "summary"
            cell = fact_marks[key] + ("No" if values[key] else "Yes") if type(values[key]) is bool else take(key, "summary")
        else:
            cell = take(key, "summary")
        rows.append((heading + (" (items)" if key == "craft-yield" else ""), cell))
    if identity in HANDS:
        rows.insert(0, ("Hands", HANDS[identity]))

    for grid in grids:
        kind = grid["kind"]
        heading = "Ranged attack" if kind == "ranged" else "Attack pattern"
        lines = []
        class_key = "ranged-damage-class-id" if kind == "ranged" else "damage-class-id"
        if class_key in remaining and class_key not in used:
            damage = take(class_key, heading)
            lines.append(f"Deals {damage} damage." if damage.startswith("[[") else damage + ".")
        if kind != "ranged" and "tile-range" in remaining and "tile-range" not in used:
            lines.append("Attack range: " + take("tile-range", heading) + ".")
        for suffix in ("min", "max"):
            used.setdefault(f"{kind}-pattern-{suffix}", heading)
        sections.append([heading, anchor("grid", grid["id"]), " ".join(lines),
                         '<div style="clear:both;">\n{{Attack grid|' + grid_argument(grid) + "|label=" + heading
                         + "}}\n</div>"])

    combat = []
    for key in ("damage-class-id", "ranged-damage-class-id"):
        if key in remaining and key not in used:
            damage = take(key, "Combat")
            kind = "Ranged damage" if key.startswith("ranged") else "Damage"
            combat.append(f"{kind} type: {damage}.")
    if "tile-range" in remaining and "tile-range" not in used:
        combat.append("Attack range: " + take("tile-range", "Combat") + ".")
    for low, high, text, separator in PAIRED_PROPERTIES[1:3]:
        if low in remaining and high in remaining and low not in used:
            used[low] = used[high] = "Combat"
            combat.append(f"{text}: {known(values[low])}{separator}{known(values[high])}, before target overlap, "
                          "armor and modifiers; it is not guaranteed damage per hit.")
    if "extra-damage" in remaining:
        combat.append("Bonus damage per attack cell: " + take("extra-damage", "Combat")
                      + ". [[Health and armor|How ammunition bonus rolls modify an attack pattern]].")
    if combat:
        sections.append(["Combat", "", " ".join(combat), ""])

    def present(section):
        return [key for key in ITEM_SECTION_KEYS[section] if key in remaining and key not in used]

    keys = present("Protection")
    if keys == ["waterproof"]:
        sections.append(["Wetness", "", "Waterproofing: " + take("waterproof", "Wetness")
                         + ", which affects how it gets wet and dries.", ""])
    elif keys:
        parts = [take(key, "Protection") + " " + PROPERTY_LABELS.get(key, properties[key]["label"]).lower()
                 for key in keys]
        text = "It has " + prose_list(parts, "and") + "."
        if "item-armor" in keys and armor_guide:
            text += " [[Armor points|How equipment armor becomes armor layers in combat]]."
        sections.append(["Protection", "", text, ""])

    keys = present("Storage")
    if "inventory-slots-added" in keys:
        text = "While equipped, it adds " + take("inventory-slots-added", "Storage")
        if "storage-grid-width" in keys and "storage-grid-height" in keys:
            used["storage-grid-width"] = used["storage-grid-height"] = "Storage"
            text += (" in its own " + known(values["storage-grid-width"]) + " x " + known(values["storage-grid-height"])
                     + " storage grid (columns x rows)")
        text += ". " + CAPACITY_NOTE + " [[Items#Capacity-granting_equipment|Compare capacity-granting equipment]]."
        sections.append(["Storage", "", text, ""])

    keys = present("Chopping and cutting")
    if keys:
        text = "It has " + prose_list([
            "a " + PROPERTY_LABELS.get(key, properties[key]["label"]).lower() + " of " + take(key, "Chopping and cutting")
            for key in keys], "and") + "."
        if "chopping-capability" in keys and chop_guide:
            text += " [[Tree health and chopping|How chopping strength changes the AP cost of chopping]]."
        sections.append(["Chopping and cutting", "", text, ""])

    keys = present("Fire")
    if keys:
        topics = (["Light"] if "light-radius" in keys else []) + (["fuel"] if "burn-time" in keys else []) + (
            ["fire starting"] if set(keys) & {"tinder-bonus", "spark-chance", "stone-spark-chance"} else [])
        fire = prose_list(topics, "and")
        fire = fire[0].upper() + fire[1:]
        sentences = []
        if "light-radius" in keys:
            sentences.append("When lit, it gives light in a radius of " + take("light-radius", fire) + ".")
        if "burn-time" in keys:
            sentences.append("Its burn duration is " + take("burn-time", fire)
                             + "; the fire or action using it sets how long that lasts.")
        if "tinder-bonus" in keys:
            sentences.append("As tinder it contributes " + take("tinder-bonus", fire)
                             + ", added to other tinder rather than a fire-starting chance on its own.")
        if "spark-chance" in keys:
            sentences.append("Its spark chance is " + take("spark-chance", fire)
                             + ", one part of lighting a fire rather than the overall chance.")
        if "stone-spark-chance" in keys:
            sentences.append("Its stone spark chance is " + take("stone-spark-chance", fire)
                             + "; other ignition requirements still apply.")
        sections.append([fire, "", " ".join(sentences), ""])

    keys = present("Consumption")
    if keys:
        sentences = []
        if "satiation-gain" in keys:
            sentences.append("Consuming it gives " + take("satiation-gain", "Consumption") + " satiation.")
        if "sickness-risk" in keys:
            sentences.append("Base sickness risk: " + take("sickness-risk", "Consumption") + ".")
        sections.append(["Consumption", "", " ".join(sentences), ""])

    if present("Resting"):
        sections.append(["Resting", "", "It provides " + take("comfort", "Resting")
                         + " comfort while resting; this is not a direct recovery amount per turn.", ""])

    keys = present("Durability")
    if keys:
        sentences = []
        if identity in DURABILITY_LABELS:
            text, rest = DURABILITY_LABELS[identity]
            sentences.append(f"{text}: " + take("durability-max", text) + rest)
        elif "durability-max" in keys:
            sentences.append("Maximum durability: " + take("durability-max", "Durability")
                             + ". An individual item's condition can be lower.")
        if "break-chance" in keys:
            sentences.append("Break chance: " + take("break-chance", "Durability")
                             + ", tested when an action uses it.")
        sections.append([DURABILITY_LABELS.get(identity, ("Durability",))[0], "", " ".join(sentences), ""])

    other = [f"* {fact_marks[key]}{literal(label(key))}: " + take(key, "Other details")
             for key in remaining if key not in used]
    other += [f'* {anchor("fact", fact["id"])}{literal(fact["property"])}: {fact_value(fact)}. {literal(fact["description"])}'
              for fact in sorted(facts, key=lambda row: row["id"]) if fact["id"] not in coalesced]
    if other:
        sections.append(["Other details", "", "\n".join(other), ""])

    top = ""
    for profile in profiles:
        places = [used[key] for key in profile["values"] if key in used]
        order = ["summary"] + [section[0] for section in sections]
        place = min(places, key=order.index) if places else "summary"
        mark = anchor("profile", profile["id"])
        if place == "summary":
            top += mark
        else:
            next(section for section in sections if section[0] == place)[1] += mark

    text = "\n" + top + "\n"
    if rows:
        notes = ["Base stats can change with equipment, condition and other effects."] if coin is None else []
        if coin is None and "initial-weight" in values:
            notes.append("Base weight is before crafting adjustments; final weight may differ.")
        if any(key in used and used[key] == "summary" for key in ("initial-price", "value")):
            notes.append(VALUE_NOTE)
        lines = ['{| class="wikitable"', "|+ " + literal(name)]
        for heading, cell in rows:
            lines.extend(["|-", f'! scope="row" | {VALUE_LINK if heading == "Value" else literal(heading)}', "| " + cell])
        if notes:
            lines.extend(["|-", '| colspan="2" style="font-size:85%;max-width:18em;" | ' + " ".join(notes)])
        text += (f'<div class="mirklurk-summary" style="{SUMMARY_STYLE}">\n'
                 + scroll_open("Item summary") + "\n".join([*lines, "|}"]) + "\n</div>\n</div>\n"
                 f'<div class="mirklurk-summary-clear" style="{SUMMARY_CLEAR_STYLE}"></div>\n')
    for heading, marks, body, display in sections:
        text += "\n" + marks + ("\n" if marks else "") + f"== {heading} ==\n"
        text += body + "\n" if body else ""
        text += display + "\n" if display else ""
    return text


def coin_value(coins):
    """Coin pages also state their value in each smaller denomination: 1 gold = 10 silver = 1000 copper."""
    total = int(coins[8:-2])
    return " = ".join([coins] + [f"{{{{Coins|{total}|{unit}}}}}" for unit, size in (("silver", 100), ("copper", 1))
                                 if total > size and total % size == 0])
