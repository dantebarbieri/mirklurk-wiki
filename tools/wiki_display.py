"""Finite native display-page registry, serialization and publication dependencies."""

import re

from wiki_data import DataError, read_authored, title_key


DISPLAY_FILES = {
    "Template:Coins": "templates/Coins.wiki",
    "Template:Health grid": "templates/Health_grid.wiki",
    "Template:Attack grid": "templates/Attack_grid.wiki",
    "Template:Creature": "templates/Creature.wiki",
    "Module:Display": "modules/Display.lua",
}
ASSETS_TITLE = "Module:Display assets"
DISPLAY_TITLES = {*DISPLAY_FILES, ASSETS_TITLE}
NAMESPACES = {"": 0, "Template": 10, "Category": 14, "Module": 828}
MAX_COPPER = 10**18 - 1
INERT = re.compile(r"<!--.*?-->|<nowiki\b[^>]*>.*?</nowiki>|<pre\b[^>]*>.*?</pre>", re.I | re.S)
INCLUDE = re.compile(r"(?<!\{)\{\{(?!\{)\s*([^{}|\n]+)")
LUA_LOAD = re.compile(r"""\b(?:mw\.loadData|require)\s*\(\s*(['"])(Module:[^'"\n]+)\1\s*\)""")


def page_namespace(title):
    canonical = title_key(title)
    if ":" not in canonical:
        return 0
    prefix = canonical.split(":", 1)[0]
    if prefix == "Category":
        return 14
    if canonical in DISPLAY_TITLES:
        return NAMESPACES[prefix]
    raise DataError(f"Unsupported publication namespace or display title: {title}")


def content_model(title):
    return "Scribunto" if page_namespace(title) == 828 else "wikitext"


def dependencies(text, lua=False):
    if lua:
        return {title_key(match[1]) for match in LUA_LOAD.findall(text)}
    found = set()
    for raw in INCLUDE.findall(INERT.sub("", text)):
        raw = raw.strip()
        if raw.startswith(":"):
            found.add(title_key(raw[1:]))
        elif raw.lower().startswith("#invoke:"):
            found.add(title_key("Module:" + raw.split(":", 1)[1]))
        elif not raw.startswith("#") and raw not in {"PAGENAME", "FULLPAGENAME", "!"}:
            found.add(title_key(raw if raw.lower().startswith("template:") else "Template:" + raw))
    return found


def validate_display_dependencies(pages):
    graph = {title: dependencies(text, content_model(title) == "Scribunto") for title, text in pages.items()}
    for title, needs in graph.items():
        presentation = {need for need in needs if need.startswith(("Template:", "Module:"))}
        if presentation - pages.keys():
            raise DataError(f"{title}: missing display dependencies: {', '.join(sorted(presentation - pages.keys()))}")
        if title in DISPLAY_TITLES and needs - DISPLAY_TITLES:
            raise DataError(f"{title}: display pages may only depend on registered display pages")
    visited, active = set(), set()

    def visit(title):
        if title in active:
            raise DataError(f"Display dependency cycle at {title}")
        if title in visited:
            return
        active.add(title)
        for needed in graph.get(title, ()):
            if needed in DISPLAY_TITLES:
                visit(needed)
        active.remove(title)
        visited.add(title)

    for title in DISPLAY_TITLES & pages.keys():
        visit(title)


def grid_argument(grid):
    def cell_text(cell):
        if cell is None:
            return "0"
        if grid["kind"] == "health":
            return str(cell["armor"] + 1)
        return str(cell["min"]) if cell["min"] == cell["max"] else f'{cell["min"]}-{cell["max"]}'
    return ";".join(",".join(cell_text(cell) for cell in row) for row in grid["rows"])


def lua_string(text):
    # A Lua long string preserves the shared formatter's exact markup, including escapes.
    equals = "="
    while "]" + equals + "]" in text:
        equals += "="
    return "[" + equals + "[" + text + "]" + equals + "]"


def display_pages(root, coin_icons, shield_icons, creatures):
    pages = {title: read_authored(root, title, filename, directory="",
                                 limit=16 * 1024 if title.startswith("Module:") else 4 * 1024)
             for title, filename in DISPLAY_FILES.items()}
    pages[ASSETS_TITLE] = (
        "-- Generated from approved illustrations metadata by the shared pixel_image formatter.\n"
        "return {\n    coins = {\n"
        + "".join(f"        {name} = {lua_string(icon)},\n" for name, icon in sorted(coin_icons.items()))
        + "    },\n    shields = {\n"
        + "".join(f"        [{armor}] = {lua_string(icon)},\n" for armor, icon in sorted(shield_icons.items()))
        + "    },\n    creatures = {\n"
        + "".join(f"        [ {lua_string(title)} ] = {lua_string(markup)},\n"
                  for title, markup in sorted(creatures.items()))
        + "    }\n}\n"
    )
    return pages
