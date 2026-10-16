"""Family navboxes, set-index pages, sort keys and guide leads."""

import re
from collections import defaultdict

from wiki_portal import TOPIC_GROUPS, browse_order, story_order

NAVBOX = ('<div class="mirklurk-navbox" role="navigation" style="clear:both;border:1px solid #a2a9b1;'
          'border-radius:4px;padding:4px 10px;margin:1.5em 0 0.5em;">')
MAX_FAMILY = 30
TOPIC_LABELS = {"Getting started": "getting-started", "Survival": "survival", "Combat": "combat", "Items and crafting": "item and crafting",
                "World": "world", "People and story": "people and story"}


def families(entities, locations, creatures, items, profile_values, taxonomy):
    """Map each item/creature to (title, kind, ordered members, order note)."""
    def order(identity):
        kind = "creature" if identity in creatures else "item"
        return (ranks.get(identity, ()),) + browse_order(entities[identity]["name"], kind, profile_values.get(identity, {}))

    ranks = weapon_ranks({"taxonomy": taxonomy}, entities, profile_values)
    by_name = {entities[i]["name"]: i for i in sorted(creatures | items, reverse=True)}
    by_name.update({i: i for i in creatures | items})
    sets = [(row["title"], row.get("index"), [by_name[m] for m in row["members"] if m in by_name], row.get("parents", []))
            for field in ("groups", "tags") for row in taxonomy.get(field, [])]
    group = {by_name.get(m): row["title"] for row in taxonomy.get("groups", []) for m in row["members"]}
    nouns = defaultdict(list)
    for identity in items:
        nouns[order(identity)[1], group.get(identity)].append(identity)
    result = {}
    for identity in sorted(creatures | items):
        index = "Bestiary" if identity in creatures else "Items"
        candidates = [(group.get(identity) not in up, len(members), name, "category", members) for name, where, members, up in sets
                      if where == index and identity in members and 2 <= len(members) <= MAX_FAMILY]
        noun = order(identity)[1] if identity in items else None
        same = nouns[noun, group.get(identity)]
        if noun and 2 <= len(same) <= MAX_FAMILY:
            candidates.append((False, 0, shared_suffix([entities[m]["name"] for m in same], noun), "family", same))
        if candidates:
            *_, name, kind, members = min(candidates)
            story = name == "Quest items"
            result[identity] = (name, kind, sorted(set(members), key=lambda i: story_order(entities[i]) if story else order(i)),
                                "story order" if story else "weakest to strongest" if identity in creatures else "lowest to highest value")
    return result, order


def shared_suffix(names, noun):
    """Longest shared trailing words ("Leg Armor"); at least the noun."""
    words = [re.sub(r"\s*\(.*\)", "", name).split(" of ")[0].split() for name in names]
    size = 1
    while all(len(w) > size for w in words) and len({tuple(w[-size - 1:]) for w in words}) == 1:
        size += 1
    return " ".join(words[0][-size:]) if len({tuple(w[-size:]) for w in words}) == 1 else noun


def reference(identity, creatures, locations):
    return ("{{Creature|" if identity in creatures else "{{Item|") + locations[identity] + "}}"


def before_categories(text, addition):
    at = text.rfind("\n[[Category:")
    return text.rstrip("\n") + "\n\n" + addition + "\n" if at < 0 else text[:at] + "\n\n" + addition + text[at:]


def add_families(pages, entities, catalog, locations, creatures, items, profile_values):
    grouped, order = families(entities, locations, creatures, items, profile_values, catalog.get("taxonomy", {}))
    taken = {title.lower() for title in pages}
    family_pages = {}
    for identity, (name, kind, members, note) in sorted(grouped.items()):
        if kind == "family" and name.lower() not in taken and name not in family_pages:
            family_pages[name] = members
    for name, members in sorted(family_pages.items()):
        pages[name] = (f"[[Main Page]] | [[Items]]\n\n'''{name}''' groups {len(members)} items that share a name, "
                       "listed from lowest to highest value.\n\n"
                       '{| class="wikitable"\n! Tier !! Item\n'
                       + "".join(f"|-\n| {rank} || {reference(identity, creatures, locations)}\n"
                                 for rank, identity in enumerate(members, 1))
                       + "|}\n\nBrowse every item on the [[Items]] page.\n")
    for identity, (name, kind, members, note) in sorted(grouped.items()):
        title = locations[identity]
        if "#" in title or title not in pages:
            continue
        if kind == "category" and f"Category:{name}" in pages:
            heading = f"[[:Category:{name}|{name}]]"
        elif kind == "family" and family_pages.get(name) == members:
            heading = f"[[{name}]]"
        else:
            heading = name
        rank = members.index(identity) + 1
        box = (f"{NAVBOX}\n'''{heading}''' ({note}):\n{FLEX}\n"
               + "\n".join(reference(member, creatures, locations) for member in members) + "\n</div></div>")
        sort = f"{{{{DEFAULTSORT:{name} {rank:02d} {entities[identity]['name']}}}}}"
        pages[title] = before_categories(pages[title], box + "\n" + sort)
    add_guide_leads(pages, catalog, entities, locations)
    guides = {guide["title"] for guide in catalog.get("guides", [])}
    for title in guides & set(pages):
        pages[title] = RELATED.sub(related_row, pages[title])
    for title in set(locations.values()) & set(pages):
        pages[title] = see_also(pages[title], guides)
    for title in pages:
        pages[title] = ICON_RUN.sub(icon_grid, pages[title])


ICON_RUN = re.compile(r"(?:^\* (\{\{(?:Item|Creature|Tile)\|[^\n]*\}\})\n){3,}", re.M)
ICON_LINE = re.compile(r"^\* (.+)$", re.M)


def icon_grid(match):
    """Show long icon-link lists as a grid."""
    cells = "".join(f"<div>{entry}</div>\n" for entry in ICON_LINE.findall(match[0]))
    return ('<div class="mirklurk-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(14em,1fr));'
            f'gap:0.3em 1em;margin:0.5em 0;">\n{cells}</div>\n')


RELATED = re.compile(r"^Related entries: (.+)$", re.M)
FLEX = '<div style="display:flex;flex-wrap:wrap;gap:0.25em 1.25em;">'


def related_row(match):
    """{{Item}} ends in a newline; inline joins would start <pre> lines."""
    entries = match[1].split(" | ")
    return ('Related entries:\n' + FLEX.replace("<div", '<div class="mirklurk-related"') + "\n"
            + "\n".join(entries) + "\n</div>")


def see_also(text, guides):
    """Fold stray one-link guide lines into one "See also" line."""
    out, run = [], []
    for line in text.split("\n"):
        if line.startswith("[[") and line.endswith("]]") and line[2:-2] in guides:
            run.append(line)
            continue
        if run and not line:
            continue
        if run:
            out += ["See also: " + " &middot; ".join(run), ""]
            run = []
        out.append(line)
    if run:
        out.append("See also: " + " &middot; ".join(run))
    return "\n".join(out)


def add_guide_leads(pages, catalog, entities, locations):
    """Open each guide with a one-line summary and section links."""
    damage = {locations[i] for i, row in entities.items() if row["category"] == "damage_class"}
    groups = {title: TOPIC_LABELS[heading] for heading, _, titles in TOPIC_GROUPS for title in titles}
    for guide in catalog.get("guides", []):
        title = guide["title"]
        head, marker, rest = pages.get(title, "").partition("\n== How it works ==\n")
        head = head.replace(f"\n'''<nowiki>{title}</nowiki>'''\n", "\n")
        if not marker or any(line[:1].isalnum() or line.startswith("'''") for line in head.splitlines()[1:]):
            continue
        if guide.get("index_page") == "Terrain":
            lead = f"'''{title}''' is one of the [[Terrain|terrain types]]."
        elif guide.get("index_page") == "Areas":
            lead = f"'''{title}''' is one of the [[Areas|areas]] of the Mirk."
        elif title in damage:
            lead = f"'''{title}''' is one of the [[Damage types|damage types]]."
        else:
            lead = f"'''{title}''' is one of the [[Game mechanics|{groups.get(title, 'game mechanics')} topics]]."
        sections = guide.get("section_titles") or []
        if len([s for s in sections if s]) > 1:
            lead += " On this page: " + " &middot; ".join(f"[[#{s.replace(' ', '_')}|{s}]]" for s in sections if s) + "."
        pages[title] = head.rstrip("\n") + "\n\n" + lead + "\n" + marker + rest


SECTIONS = {
    "Clothes": (
        ("Headwear", ("Helmet-slot equipment", "Hood-slot equipment")),
        ("Shirts", ("Shirt-slot equipment",)), ("Outerwear", ("Outer torso equipment",)),
        ("Cloaks", ("Cloak-slot equipment",)), ("Gloves", ("Glove-slot equipment",)),
        ("Pants", ("Pants-slot equipment",)), ("Socks", ("Sock-slot equipment",)),
        ("Footwear", ("Footwear-slot equipment",))),
    "Belts and backpacks": (("Belts", ("Belt-slot equipment",)), ("Backpacks", ("Backpack-slot equipment",))),
    "Consumables": (
        ("Prepared foods", ("Prepared foods",)), ("Raw animal foods", ("Raw animal foods",)),
        ("Plant foods", ("Plant foods",)), ("Other food and drink", ("Food and drink",)),
        ("Remedies", ("Remedies",)), ("Restorative tonics", ("Restorative tonics",)),
        ("Repair kits", ("Repair kits",)), ("Lamp oil", ("Repair and refuelling supplies",)), ("Thrown flasks", ("Thrown flasks",)),
        ("Summoning", ("Summoning supplies",))),
    "Coins and valuables": (("Coins", ("Coins",)), ("Gems", ("Gems",))),
    "Tools": (("Fire-starting stones", ("Fire-starting stones",)), ("Strikers", ("Strikers",)), ("Light", ("Light sources",)),
              ("Mapping", ("Mapping tools",))),
    "Camping and construction": (
        ("Workstations", ("Workstations",)), ("Beds and tents", ("Beds and tents",)), ("Shelters", ("Shelters",)),
        ("Rafts", ("Rafts",)), ("Storage", ("Storage containers",))),
    "Weapons": tuple((label, (label + " weapons",)) for label in ("Sharp", "Blunt", "Force", "Piercing", "Poison", "Fire"))
    + (("Weak", ("Weak-damage weapons",)),),
}


def clothing_subgroups(catalog, members, group="Clothes"):
    """Split a group into tag sections; unclaimed members go under "Other"."""
    tags = {row["title"]: set(row["members"]) for row in catalog.get("taxonomy", {}).get("tags", [])}
    remaining, groups = set(members), []
    for label, titles in SECTIONS.get(group, ()):
        matching = remaining & set().union(*(tags.get(title, set()) for title in titles))
        if matching:
            groups.append((label, matching, [title for title in titles if title in tags]))
            remaining -= matching
    if remaining:
        groups.append(("Other clothing" if group == "Clothes" else "Other", remaining, []))
    return groups


def armor_order(name, values):
    """One armor slot per section: rank by armor points, then price."""
    return tuple(float(values.get(key, "inf")) for key in ("item-armor", "initial-price")) + (name,)



WEAPON_KINDS = ("Daggers and hunting knives", "Swords", "Axes", "Clubs, maces and hammers", "Bows", "Magic weapons")


def weapon_ranks(catalog, entities, values):
    """Rank weapons by kind, then families by their cheapest member: basic to best."""
    taxonomy = catalog.get("taxonomy", {})
    tags = {row["title"]: set(row["members"]) for row in taxonomy.get("tags", [])}
    weapons = next((row["members"] for row in taxonomy.get("groups", []) if row["title"] == "Weapons"), [])
    kinds = {i: next((n for n, kind in enumerate(WEAPON_KINDS) if i in tags.get(kind, ())), len(WEAPON_KINDS)) for i in weapons}
    keys = {i: (kinds[i], browse_order(entities[i]["name"], "item", values.get(i, {}))) for i in weapons}
    cheapest = {}
    for kind, (noun, price, _) in keys.values():
        cheapest[kind, noun] = min(price, cheapest.get((kind, noun), price))
    return {i: (kind, cheapest[kind, key[0]]) for i, (kind, key) in keys.items()}


CAPACITY_KINDS = {"Backpack-slot equipment": "Backpacks", "Belt-slot equipment": "Belts"}


def capacity_kind(slot):
    return CAPACITY_KINDS.get(slot, "Clothing")
