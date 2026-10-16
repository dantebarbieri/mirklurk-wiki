"""Main Page and Game mechanics portal cards, and index-list ordering."""

import re

# Pages are shown only when published; any other top-level guide falls into "Other guides".
# Icons name entities whose figure is published; a missing figure simply shows no icon.
NEW_PLAYER_PATH = [
    ("Difficulty", "Easy, Medium or Hard", "Shoddy Dagger"),
    ("Controls", "mouse, keyboard and controller", "Map of area"),
    ("Starting equipment", "what you carry at the start", "Small Backpack"),
    ("Action points", "every step, swing and craft costs AP", "Strider"),
    ("Satiation", "hunger and eating", "Loaf of Bread"),
    ("Foods", "what to eat and what makes you sick", "Pleasant Vegetable Soup"),
    ("Resting", "recover focus and stamina", "Great Bedroll"),
    ("Combat basics", "turns, attacking and escaping", "Iron Hand Axe"),
    ("Health and armor", "how hits land on your body", ("Steel Shield", 24)),
    ("Death", "what kills you and what happens next", "File:Dead Unwanted portrait.png"),
    ("Bestiary", "know what hunts in the Mirk", "Mirk Runner"),
]
# An icon is an entity name or a File title, optionally with its box size in pixels (default 32).
EIR = "File:Captain Eir portrait.png"
EXPLORE_ICONS = {
    "Items": "Iron Longsword", "Bestiary": ("Giant Slug", 48), "NPCs": EIR, "Nature": "Log (Willow)",
    "Skills": "Shield Savant", "Damage types": "Orb of Poison", "Health and armor": "Steel Chestplate",
    "Game mechanics": "Campfire", "Action points": "Fast Feet",
}
TOPIC_GROUPS = [
    ("Getting started", "Torch", ["Difficulty", "Controls", "Starting equipment", "Death"]),
    ("Survival", "Survivor's Field Kit", ["Satiation", "Foods", "Stamina", "Focus", "Temperature",
                                          "Wellbeing", "Resting", "Weather"]),
    ("Combat", "Iron Battleaxe", ["Combat basics", "Action points", "Strict move", "Health and armor", "Armor points",
                                  "Damage types", "Magic weapons", "Skills", "Level progression"]),
    ("Items and crafting", "Storage Chest", ["Items", "Crafting", "Placing objects", "Planting",
                                             "Tree health and chopping", "Loot tables", "Currency and trading", "Merchants"]),
    ("World", "Map Ledger", ["Areas", "Terrain", "Nature", "World generation", "Survivors' camp", "Dead camp"]),
    ("People and story", "File:Magus Clay portrait.png", ["NPCs", "Quests and journal", "Bestiary"]),
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
    if name in ("Rock", "Flint", "Drake Jasper", "Dragon Flint"):
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
    return grid([card(picture(icon, titles[0]), f"'''{heading}'''", links(titles))
                 for heading, icon, titles in groups if titles])


def links(titles):
    """Inline link list that wraps only between entries, never inside a title or before a separator."""
    return " ".join(f'<span style="white-space:nowrap;">[[{title}]]{" &middot;" if i < len(titles) - 1 else ""}</span>'
                    for i, title in enumerate(titles))


def new_player_steps(pages, picture):
    steps = [f"# {picture(icon, title)}'''[[{title}]]''' - {description}"
             for title, description, icon in NEW_PLAYER_PATH if published(title, pages)]
    return "Read these in order for a first run:\n" + "\n".join(steps) + "\n" if steps else ""


def compose_portals(pages, extra, images, entities, context=None):
    from wiki_render import image_for, pixel_image  # wiki_render imports this module

    by_name = {row["name"]: identity for identity, row in entities.items()}

    by_file = {image["file_title"]: image for image in images}

    def picture(icon, link, lead=False):
        name, size = icon if isinstance(icon, tuple) else (icon, 32)
        image = (by_file.get(name) if str(name).startswith("File:")
                 else image_for(by_name.get(name), images) if name else None)
        if not image:
            return ""
        # Fit the sprite to the box: whole zoom from 2x up, else fractional, so portraits shrink.
        pixels = image["pixel_art"]
        fit = min(size * pixels["source_scale"] / pixels["width"], size * pixels["source_scale"] / pixels["height"])
        fit = max(1, int(fit)) if lead or fit >= 2 else round(fit, 3)
        art = re.sub(r"zoom:calc\([\d.]+ /", f"zoom:calc({fit} /", pixel_image(image, size, size, link, link), count=1)
        return (f'<span style="display:inline-block;width:{size}px;text-align:center;vertical-align:middle;'
                f'margin-right:4px;">{art}</span>')

    # Topic pages lead with their homepage icon at whole native scale; link previews use it.
    for title, icon in ({t: i for t, _, i in NEW_PLAYER_PATH} | EXPLORE_ICONS).items():
        art = picture((icon[0] if isinstance(icon, tuple) else icon, 64), None, True).replace("|class=notpageimage", "").replace("width:64px;", "")
        if art and published(title, pages):
            pages[title] = f'<div style="float:right;margin-left:1em;">{art}</div>\n' + pages[title]
    main = explore_cards(pages["Main Page"], picture)
    for heading, body in (("== New to the Mirk? ==", new_player_steps(pages, picture)),
                          ("== Guides by topic ==", topic_cards(pages, extra, picture))):
        main = main.replace(heading + "\n", heading + "\n" + body) if body else main.replace(heading + "\n\n", "")
    pages["Main Page"] = main
    if context:
        from wiki_families import add_families
        add_families(pages, entities, *context)
    if "Game mechanics" in pages:
        pages["Game mechanics"] = (pages["Game mechanics"].rstrip("\n") + "\n\n== Guides by topic ==\n"
                                   + topic_cards(pages, extra, picture, exclude={"Game mechanics"}))


STORY = ("Wooden Recorder", "Glowing Rune", "Clay's Strange Potion", "Ancient Strongbox", "Ward Breaker",
         "Head of The Terror", "Magus' Shard")


def story_order(entity):
    name = entity["name"]
    return (STORY.index(name) if name in STORY else len(STORY), name)


# Spoiler-heavy factions go last so readers only meet them by scrolling.
def section_order(row):
    return ({"Scaalmyr faction": 1, "Nightmare faction": 2}.get(row["title"], 0), row["title"])
