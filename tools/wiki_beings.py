"""Creature and character combat sections for being articles."""

from wiki_data import DataError
from wiki_display import grid_argument
from wiki_render import LEGACY_PROPERTIES, PROPERTY_LABELS, anchor, fact_value, literal, profile_value, prose_list
from wiki_views import scroll_open


def being_article(facts, profiles, properties, entities, locations, grids=(), faction=None):
    if not facts and not profiles and not grids:
        return ""
    values = {}
    for profile in profiles:
        for key, value in profile["values"].items():
            if key in values and values[key] != value:
                raise DataError(f"{profile['entity']}: conflicting profile values for {key}")
            values[key] = value
    markers = "".join(anchor("profile", profile["id"]) for profile in profiles)
    remaining = []
    for fact in sorted(facts, key=lambda row: row["id"]):
        field = LEGACY_PROPERTIES.get(fact["id"].removeprefix(fact["id"].split("-base-")[0] + "-base-"))
        if (
            "-base-" in fact["id"] and field in values and fact["value"] == values[field]
            and type(fact["value"]) in {int, float} and type(values[field]) in {int, float}
            and fact["confidence"] == "inferred"
        ):
            markers += anchor("fact", fact["id"])
        else:
            remaining.append(fact)
    by_kind = {grid["kind"]: grid for grid in grids}
    used = set()

    def value(key):
        used.add(key)
        return profile_value(key, values[key], entities, locations)

    summary = []
    if faction is not None:
        summary.append(("Faction", f'[[:Category:{faction["title"]}|{faction["title"]}]]'))
    if "base-xp" in values:
        summary.append(("[[Level progression|XP]] award", value("base-xp") + " XP"))
    if "maximum-ap" in values:
        summary.append(("[[Action points]]", value("maximum-ap") + " per turn"))
    if "health" in by_kind:
        cells = sum(1 for row in by_kind["health"]["rows"] for cell in row if cell)
        summary.append(("Base health", f"[[#Health|{cells} HP]]"))
        used.update({"hp-grid-width", "hp-grid-height", "being-armor"})
    elif "hp-grid-width" in values and "hp-grid-height" in values:
        summary.append(("HP grid size", value("hp-grid-width") + " x " + value("hp-grid-height") + " cells"))
    if "being-armor" in values and "being-armor" not in used:
        summary.append(("Armor", value("being-armor")))
    if "base-speed" in values:
        speed = value("base-speed")
        if "tile-speed" in values:
            speed += " (tile movement " + value("tile-speed") + ")"
        summary.append(("Speed", speed))
    elif "tile-speed" in values:
        summary.append(("Tile movement speed", value("tile-speed")))

    behavior = []
    if "awareness-chance" in values or "awareness-distance" in values:
        parts = []
        if "awareness-chance" in values:
            parts.append(value("awareness-chance") + " chance to choose an eligible target")
        if "awareness-distance" in values:
            parts.append(("within" if parts else "Looks for eligible targets within")
                         + " a distance of " + value("awareness-distance"))
        behavior.append("'''Targeting:''' " + " ".join(parts) + ". [[Bestiary#Aggression_rules|Faction and targeting rules]] decide who is eligible.")
    if "dodge-chance" in values:
        behavior.append("'''Dodging:''' " + value("dodge-chance") + " base chance to dodge an attack.")
    if "block-chance" in values:
        behavior.append("'''Blocking:''' " + value("block-chance") + " chance to stop a whole attack.")
    if "opportunity-chance" in values:
        behavior.append("'''Opportunity attacks:''' " + value("opportunity-chance")
                        + " chance to strike when an opportunity attack is triggered.")
    if "idle-move-chance" in values:
        behavior.append("'''Wandering:''' " + value("idle-move-chance") + " chance to move while idle.")

    def attack(kind, prefix, label):
        keys = {"damage": f"{prefix}damage-class-id", "cost": f"{kind}-ap-cost", "reach": f"{kind}-distance",
                "low": f"{kind}-pattern-min", "high": f"{kind}-pattern-max"}
        grid = by_kind.get(kind)
        if (kind == "ranged" and grid is None and not {keys["damage"], keys["cost"], keys["low"]} & values.keys()
                and type(values.get(keys["reach"], 0)) in {int, float} and values.get(keys["reach"], 0) <= 0):
            if keys["reach"] in values:
                behavior.append("'''Ranged attack:''' none (ranged reach " + value(keys["reach"]) + ").")
            return ""
        if grid is None and not any(key in values for key in keys.values()):
            return ""
        damage = value(keys["damage"]) if keys["damage"] in values else None
        cost = value(keys["cost"]) if keys["cost"] in values else None
        reach = value(keys["reach"]) if keys["reach"] in values else None
        text = "\n" + (anchor("grid", grid["id"]) + "\n" if grid else "") + f"=== {label} ===\n"
        if grid is not None:
            used.update({keys["low"], keys["high"]})
            parts = [part for part in (
                damage and "deals " + damage + " damage", cost and "costs " + cost,
                reach and "reach " + reach) if part]
            if parts:
                sentence = ", ".join(parts)
                text += sentence[:1].upper() + sentence[1:] + ".\n"
            return text + "{{Attack grid|" + grid_argument(grid) + "|label=" + label + "}}\n"
        listed = [part for part in (
            damage and damage + " damage", cost and "a " + cost + " cost", reach and "reach " + reach) if part]
        sentence = "Has no " + label.lower() + " pattern"
        if listed:
            sentence += ", although the game lists " + prose_list(listed, "and")
        text += sentence + ".\n"
        if keys["low"] in values and keys["high"] in values:
            text += ("\nPotential damage: " + value(keys["low"]) + " to " + value(keys["high"])
                     + ", before target overlap, armor and modifiers; it is not guaranteed damage per hit.\n")
        return text

    attacks = attack("melee", "", "Melee attack") + attack("ranged", "ranged-", "Ranged attack")
    for key in sorted(values.keys() - used):
        label = PROPERTY_LABELS.get(key, properties[key]["label"])
        behavior.append(f"'''{literal(label)}:''' {value(key)}.")
    for fact in remaining:
        behavior.append(anchor("fact", fact["id"]) + f"'''{literal(fact['property'])}:''' {fact_value(fact)}. {literal(fact['description'])}")

    text = "\n== Combat ==\n" + markers + "\n"
    if summary:
        lines = ['{| class="wikitable"']
        for index, (label, cell) in enumerate(summary):
            lines.extend((["|-"] if index else []) + [f'! scope="row" | {label}', f"| {cell}"])
        text += scroll_open() + "\n".join([*lines, "|}"]) + "\n</div>\n"
    if behavior:
        text += "\n".join("* " + line for line in behavior) + "\n"
    if profiles:
        text += "\nBase values; equipment, condition and other effects can change them.\n"
    if "health" in by_kind:
        text += "\n" + anchor("grid", by_kind["health"]["id"]) + "\n=== Health ===\n"
        text += "{{Health grid|" + grid_argument(by_kind["health"]) + "}}\n"
    return text + attacks
