"""Reader navigation: Main Page and Game mechanics portal cards, and index-list ordering."""

import re

# Pages are shown only when published; any other top-level guide falls into "Other guides".
# Icons name entities whose figure is published; a missing figure simply shows no icon.
NEW_PLAYER_PATH = [
    ("Starting equipment", "what you carry at the start", None),
    ("Action points", "every step, swing and craft costs AP", None),
    ("Satiation", "hunger and eating", "Loaf of Bread"),
    ("Foods", "what to eat and what makes you sick", "Pleasant Vegetable Soup"),
    ("Resting", "recover focus and stamina", "Great Bedroll"),
    ("Health and armor", "how hits land on your body", "Steel Shield"),
    ("Bestiary", "know what hunts in the Mirk", "Mirkfang"),
]
EXPLORE_ICONS = {
    "Items": "Iron Longsword", "Bestiary": "Giant Mirkfang", "Nature": "Log (Willow)", "Skills": "Shield Savant",
    "Damage types": "Orb of Poison", "Health and armor": "Steel Shield", "Game mechanics": "Campfire",
}
TOPIC_GROUPS = [
    ("Survival", "Campfire", ["Satiation", "Foods", "Stamina", "Focus", "Temperature", "Wellbeing", "Resting", "Weather"]),
    ("Combat", "Iron Shortsword", ["Action points", "Strict move", "Health and armor", "Armor points", "Damage types",
                                   "Magic weapons", "Skills", "Level progression"]),
    ("Items and crafting", "Iron Felling Axe", ["Items", "Starting equipment", "Crafting", "Placing objects", "Planting",
                                                "Tree health and chopping", "Loot tables", "Currency and trading", "Merchants"]),
    ("World", "Map of area", ["Areas", "Terrain", "Nature", "World generation", "Survivors' camp", "Dead camp"]),
    ("People and story", None, ["NPCs", "Quests and journal", "Bestiary"]),
]
CARD_GRID = '<div class="mirklurk-cards" style="display:flex;flex-wrap:wrap;gap:12px;margin:0.5em 0 1em;">'
CARD = ('<div class="mirklurk-card" style="flex:1 1 16em;min-width:0;border:1px solid #a2a9b1;'
        'border-radius:4px;padding:6px 12px;">')
EXPLORE_ROW = re.compile(r"^\* \[\[([^]|]+)\]\] - (.+)$", re.M)


def browse_order(name, kind, values):
    """Sort key for index lists: items by family noun (Worn/Decent/Fine Socks share "Socks"), then
    cheapest first, so tiers read basic to best; creatures weakest (least XP) first."""
    rank = values.get("base-xp" if kind == "creature" else "initial-price")
    rank = float("inf") if rank is None else float(rank)
    if kind == "creature":
        return ("", rank, name)
    base = re.sub(r"\s*\(.*\)", "", name)
    return ((base.split(" of ")[0] if " of " in base else base).split()[-1], rank, name)


def published(title, pages):
    return title in pages and not pages[title].startswith("#REDIRECT")


def card(picture, heading, body):
    return f"{CARD}\n{picture}{heading}<br />\n{body}\n</div>"


def grid(cards):
    return CARD_GRID + "\n" + "\n".join(cards) + "\n</div>\n" if cards else ""


def explore_cards(text, picture):
    """Turn the authored "* [[Page]] - description" Explore list into icon cards."""
    rows = list(EXPLORE_ROW.finditer(text))
    if not rows:
        return text
    cards = [card(picture(EXPLORE_ICONS.get(row[1]), row[1]), f"'''[[{row[1]}]]'''", row[2]) for row in rows]
    return text[:rows[0].start()] + grid(cards).rstrip("\n") + text[rows[-1].end():]


def topic_cards(pages, extra, picture, exclude=()):
    groups = [(heading, icon, [title for title in titles if published(title, pages) and title not in exclude])
              for heading, icon, titles in TOPIC_GROUPS]
    shown = {title for _, _, titles in groups for title in titles}
    others = sorted(title for title in set(extra) - shown - set(exclude) if published(title, pages))
    if others:
        groups.append(("Other guides", None, others))
    return grid([card(picture(icon, titles[0]), f"'''{heading}'''", " &middot; ".join(f"[[{title}]]" for title in titles))
                 for heading, icon, titles in groups if titles])


def new_player_steps(pages, picture):
    steps = [f"# {picture(icon, title)}'''[[{title}]]''' - {description}"
             for title, description, icon in NEW_PLAYER_PATH if published(title, pages)]
    return "Read these in order for a first run:\n" + "\n".join(steps) + "\n" if steps else ""


def compose_portals(pages, extra, images, entities):
    from wiki_render import image_for, pixel_image  # wiki_render imports this module

    by_name = {row["name"]: identity for identity, row in entities.items()}

    def picture(name, link):
        image = image_for(by_name.get(name), images) if name else None
        return pixel_image(image, 32, 32, link, link) + " " if image else ""

    main = explore_cards(pages["Main Page"], picture)
    for heading, body in (("== New to the Mirk? ==", new_player_steps(pages, picture)),
                          ("== Guides by topic ==", topic_cards(pages, extra, picture))):
        main = main.replace(heading + "\n", heading + "\n" + body) if body else main.replace(heading + "\n\n", "")
    pages["Main Page"] = main
    if "Game mechanics" in pages:
        pages["Game mechanics"] = (pages["Game mechanics"].rstrip("\n") + "\n\n== Guides by topic ==\n"
                                   + topic_cards(pages, extra, picture, exclude={"Game mechanics"}))
