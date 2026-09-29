"""Real disposable MediaWiki/Scribunto checks; called only by smoke_deploy."""

import copy
import re
import urllib.parse

from sync_wiki import SyncError, fetch_live, sync
from wiki_catalog import page_locations, primary_groups
from wiki_display import ASSETS_TITLE, DISPLAY_TITLES, content_model, lua_string, page_namespace
from wiki_render import image_for, merchant_table, pixel_geometry


def smoke_display_install(publisher, pages):
    display = {title: pages[title] for title in DISPLAY_TITLES}
    before = fetch_live(publisher, display)
    bad = dict(display, **{"Module:Display": "this is not valid Lua !!!"})
    try:
        sync(publisher, bad, "repo-sync: invalid unsaved Lua", apply=True, log=lambda _: None)
    except SyncError:
        pass
    else:
        raise RuntimeError("Invalid Lua did not abort publication before writes.")
    if fetch_live(publisher, display) != before:
        raise RuntimeError("An invalid-Lua preflight changed a page.")
    report = sync(publisher, display, "repo-sync: native display bootstrap", apply=True, log=lambda _: None)
    if (set(report["created"]) != DISPLAY_TITLES or report["errors"] or report["blocked"]
            or report["conflicts"] or report["unverified"] or report["missing_files"]):
        raise RuntimeError(f"Native display API bootstrap failed: {report}")
    if report["created"][:2] != [ASSETS_TITLE, "Module:Display"]:
        raise RuntimeError("The display assets and implementation modules were not saved first.")


def smoke_display_rendering(api, pages, data, catalog, details, parse_grids, check_errors, check_shield, dom):
    def parse(text):
        result = api({"action": "parse", "title": "Display rendering smoke", "text": text,
                      "contentmodel": "wikitext", "prop": "text"}, post=True)["parse"]["text"]["*"]
        check_errors(result)
        return result

    revisions = api({"action": "query", "titles": "|".join(sorted(DISPLAY_TITLES)), "prop": "revisions",
                     "rvprop": "content", "rvslots": "main"}, post=True)["query"]["pages"]
    for page in revisions.values():
        title = page["title"]
        if page["ns"] != page_namespace(title) or page["revisions"][0]["slots"]["main"]["contentmodel"] != content_model(title):
            raise RuntimeError("An imported/API-published display page has the wrong namespace or content model.")

    locations = page_locations(data, catalog)
    constructions = {recipe["owner_item"] for recipe in catalog.get("construction_recipes", [])}
    items = {row["id"]: row for row in data["entities"] if row["category"] == "item" and row["id"] not in constructions}
    for identity, item in items.items():
        title = locations[identity]
        rendered = parse("{{Item|" + title + "|quantity=4}}")
        projection = dom(rendered, "Item")
        parsed = parse_grids()
        parsed.feed(rendered)
        if (len(parsed.items) != 1 or parsed.items[0].get("aria-label") != title
                or parsed.items[0].get("title") != title or projection.text.strip() != item["name"] + " x 4"):
            raise RuntimeError(f"{title}: Item lost its canonical identity, original label or quantity.")
        image = image_for(identity, data["illustrations"])
        if [link["target"] for link in projection.wiki_links] != [title] * (2 if image else 1):
            raise RuntimeError("Item icon/name links lost their canonical destination.")
        if any(link["redlink"] for link in projection.wiki_links):
            raise RuntimeError("Item produced a red link for a registered title.")
        if len(parsed.images) != (1 if image else 0):
            raise RuntimeError("Item guessed or dropped a reviewed image.")
        if image:
            actual = parsed.images[0]
            pixels = image["pixel_art"]
            scale = pixel_geometry(image, 32, 32)[2]
            if (image["file_title"].removeprefix("File:") not in urllib.parse.unquote(actual.get("src", ""))
                    or actual.get("alt") != item["name"] or actual.get("width") != str(pixels["width"])
                    or actual.get("height") != str(pixels["height"]) or "srcset" in actual
                    or "/thumb/" in actual.get("src", "") or len(parsed.pixel_styles) != 1
                    or f'zoom:calc({scale}/{pixels["source_scale"]})' not in parsed.pixel_styles[0].replace(" ", "")):
                raise RuntimeError(f"{title}: Item diverged from the shared approved image policy.")
    for raw, title in ((" iron_Hand_Axe ", "Iron Hand Axe"), ("turnip_(item)", "Turnip (item)")):
        if f'aria-label="{title}"' not in parse("{{Item|" + raw + "}}"):
            raise RuntimeError("Item does not use MediaWiki canonical title normalization.")
    for title, source in pages.items():
        if title.startswith(("Template:", "Module:")):
            continue
        if title == "Items" or title.startswith("Category:") and "{{Item|" in source:
            expected = re.findall(r"\{\{Item\|([^{}|]+)\}\}", source)
            rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
            check_errors(rendered)
            parsed = parse_grids()
            parsed.feed(rendered)
            if [entry.get("aria-label") for entry in parsed.items] != expected:
                raise RuntimeError(f"{title}: authored Item entries changed their order or membership.")
    creatures = {locations[row["entity"]]: image_for(row["entity"], data["illustrations"])
                 for row in catalog["classifications"] if row["kind"] == "creature"}
    for title, image in creatures.items():
        rendered = parse("{{Creature|" + title + "}}")
        parsed = parse_grids()
        parsed.feed(rendered)
        projection = dom(rendered, "Creature")
        if (len(parsed.creatures) != 1 or parsed.creatures[0].get("title") != title
                or parsed.creatures[0].get("aria-label") != title or projection.text.strip() != title):
            raise RuntimeError("A creature lost its canonical visible name, tooltip or accessible label.")
        links = projection.wiki_links
        if [link["target"] for link in links] != [title, title] or any(link["redlink"] for link in links):
            raise RuntimeError("Creature portrait/name links did not resolve to the same canonical article.")
        if image is None or len(parsed.images) != 1 or len(parsed.pixel_styles) != 1:
            raise RuntimeError("The curated creature fixture lacks its reviewed portrait.")
        pixels = image["pixel_art"]
        actual = parsed.images[0]
        filename = image["file_title"].removeprefix("File:")
        if (filename not in urllib.parse.unquote(actual.get("src", "")) or actual.get("alt") != title + " portrait"
                or actual.get("width") != str(pixels["width"]) or actual.get("height") != str(pixels["height"])
                or "srcset" in actual or "/thumb/" in actual.get("src", "")):
            raise RuntimeError("Creature icon lost its reviewed identity, full upload or accessible alt.")
        scale = pixel_geometry(image, 32, 32)[2]
        style = parsed.pixel_styles[0].replace(" ", "")
        if f'zoom:calc({scale}/{pixels["source_scale"]})' not in style or "image-rendering:pixelated" not in style:
            raise RuntimeError("Creature icon diverged from the shared integer-native sizing policy.")
        if "mirklurk-cell-grid" in rendered or "occupied health cells" in rendered:
            raise RuntimeError("Creature display unexpectedly copied statistics.")
    groups = sorted((group for group in primary_groups(catalog) if group["index"] == "Bestiary"), key=lambda g: g["title"])
    surfaces = {"Bestiary": [locations[i] for group in groups for i in sorted(group["members"], key=lambda i: locations[i])]}
    surfaces.update({"Category:" + group["title"]: sorted(locations[i] for i in group["members"]) for group in groups})
    for title, expected in surfaces.items():
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        check_errors(rendered)
        parsed = parse_grids()
        parsed.feed(rendered)
        if [entry.get("aria-label") for entry in parsed.creatures] != expected:
            raise RuntimeError(f"{title}: native creature icons changed existing list order or membership.")
    for argument, title in ((" sceetler ", "Sceetler"), ("nightmare", "Nightmare"), ("Mirk_Runner", "Mirk Runner")):
        if f'aria-label="{title}"' not in parse("{{Creature|" + argument + "}}"):
            raise RuntimeError("Creature title normalization differs from MediaWiki.")
    totals = {0: 0, 1: 0, 2: 0, 3: 0}
    # Parse generated articles, not a parallel Python rendering of their cells.
    for identity in sorted({grid["entity"] for grid in details["grids"]}):
        title = locations[identity]
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        check_errors(rendered)
        parsed = parse_grids()
        parsed.feed(rendered)
        expected_grids = sorted((g for g in details["grids"] if g["entity"] == identity), key=lambda g: g["id"])
        if len(parsed.grids) != len(expected_grids):
            raise RuntimeError(f"{title}: generated article lost a native grid.")
        for expected, rows in zip(expected_grids, parsed.grids):
            if [len(row) for row in rows] != [len(row) for row in expected["rows"]]:
                raise RuntimeError(f"{expected['id']}: dimensions or orientation changed.")
            if f'id="grid-{expected["id"]}"' not in rendered:
                raise RuntimeError(f"{expected['id']}: anchor missing.")
            count, low, high = 0, 0, 0
            for y, (wanted_row, row) in enumerate(zip(expected["rows"], rows), 1):
                for x, (wanted, cell) in enumerate(zip(wanted_row, row), 1):
                    attrs = cell["attrs"]
                    prefix = f"Row {y}, column {x}: "
                    if wanted is None:
                        if (attrs.get("aria-label") != prefix + "empty" or attrs.get("class") != "grid-hole"
                                or cell["text"].strip() or cell["images"]):
                            raise RuntimeError(f"{expected['id']}: a hole moved or gained contents.")
                        continue
                    count += 1
                    if expected["kind"] == "health":
                        armor = wanted["armor"]
                        totals[armor] += 1
                        description = f"1 HP, {armor} armor layers"
                        if armor:
                            check_shield(cell["images"], cell["links"], cell["icon_styles"], armor)
                            if cell["text"].strip():
                                raise RuntimeError("An armored cell gained duplicate HP text.")
                        elif cell["images"] or cell["text"].strip() != "1 HP":
                            raise RuntimeError("An unarmored cell no longer means one HP.")
                    else:
                        low += wanted["min"]
                        high += wanted["max"]
                        visible = str(wanted["min"]) if wanted["min"] == wanted["max"] else f'{wanted["min"]}-{wanted["max"]}'
                        description = visible + " damage"
                        if cell["images"] or cell["text"].strip() != visible:
                            raise RuntimeError("An attack cell changed damage or gained a shield.")
                    if attrs.get("aria-label") != prefix + description or attrs.get("title") != prefix + description:
                        raise RuntimeError(f"{expected['id']}: occupied cell lost its tooltip or accessible coordinates.")
                    style = attrs.get("style", "").replace(" ", "")
                    if not all(token in style for token in ("min-width:3em", "height:3em", "background:#852c36")):
                        raise RuntimeError("Native cells lost red/3em geometry.")
            if expected["kind"] == "health":
                if f"{count} occupied health cells" not in rendered:
                    raise RuntimeError("Health count differs from curated data.")
            elif f"Sum of occupied-cell ranges: {low} to {high}." not in rendered or "not maximum actual damage" not in rendered:
                raise RuntimeError("Attack sums or caveats changed.")
        if "overflow-x:auto" not in rendered.replace(" ", ""):
            raise RuntimeError("Native grids lost horizontal overflow.")
    if totals != {0: 259, 1: 189, 2: 22, 3: 10}:
        raise RuntimeError("The 36 native health grids differ from the reviewed HP/armor totals.")

    for amount in (0, 1, 99, 100, 999, 1000, 1234, 9007199254740993, 999999999999999999):
        rendered = parse("{{Coins|" + str(amount) + "}}")
        parsed = dom(rendered, "Coins")
        terms = [(int(count), name) for count, name in re.findall(r"(\d+) (gold|silver|copper)", parsed.text)]
        gold, rest = divmod(amount, 1000)
        silver, copper = divmod(rest, 100)
        expected = [(count, name) for count, name in ((gold, "gold"), (silver, "silver"), (copper, "copper")) if count]
        expected = expected or [(0, "copper")]
        if terms != expected:
            raise RuntimeError(f"Coins {amount}: exact denomination arithmetic failed ({terms}).")
        images = parse_grids()
        images.feed(rendered)
        for image, (_, name) in zip(images.images, expected):
            file = {"gold": "Item-74.png", "silver": "Item-73.png", "copper": "Item-72.png"}[name]
            if (image.get("alt") != name.capitalize() + " coin" or file not in urllib.parse.unquote(image.get("src", ""))
                    or image.get("width") != "128" or image.get("height") != "128"
                    or "srcset" in image or "/thumb/" in image.get("src", "")):
                raise RuntimeError("Native Coins swapped denomination identity or image policy.")
        if len(images.images) != len(expected) or len(images.pixel_styles) != len(expected) or images.links:
            raise RuntimeError("Coins lost nonlinked, accessible denomination icons.")
        if any("zoom:calc(1/8)" not in style.replace(" ", "") for style in images.pixel_styles):
            raise RuntimeError("Native coin icons no longer follow shared integer-native sizing.")

    valid = {
        "{{Coins| 0001234 }}": ("1 gold", None),
        "{{Health grid| 0,1,0 ; 1,4,1 ; 0,1,0 }}": ("5 occupied health cells", [3, 3, 3]),
        "{{Attack grid|0-1,0;0,1000}}": ("Sum of occupied-cell ranges: 1000 to 1001.", [2, 2]),
        "{{Attack grid|0}}": ("Sum of occupied-cell ranges: 0 to 0.", [1]),
        "{{Health grid|" + ";".join([",".join(["1"] * 32)] * 32) + "}}": ("1024 occupied health cells", [32] * 32),
        "{{Attack grid|" + ";".join([",".join(["1000"] * 32)] * 32) + "}}": ("1024000 to 1024000", [32] * 32),
    }
    for invocation, (text, shape) in valid.items():
        rendered = parse(invocation)
        if text not in rendered:
            raise RuntimeError("Native whitespace/boundary/zero semantics failed.")
        if shape is not None:
            parsed = parse_grids()
            parsed.feed(rendered)
            if len(parsed.grids) != 1 or [len(row) for row in parsed.grids[0]] != shape:
                raise RuntimeError("A boundary grid changed dimensions.")
    invalid = {
        "Coins": ["", "-1", "1.5", "+1", "1e3", "1,000", "NaN", "１２", "1000000000000000000", "0" * 19],
        "Health grid": ["", "0", "0,0", "5", "-1", "1.0", "1,,1", "1;", ";1", "1,1;1", "1:4", "1-4",
                        "1," * 32 + "1", ";".join(["1"] * 33), "1" * 16385],
        "Attack grid": ["", "0-0", "2-1", "1:4", "1.4", "-1", "1001", "0-1001", "1,", "1;;1", "1,2;3",
                        "0 - 1", "1e2", "1 " * 8193],
        "Creature": ["", "Not a creature", "Ranger Bhato", "Unwanted Guard", "being-13", "Template:Coins",
                     "Sceetler#Stats", "File:Being-13.png", "NIGHTMARE", "x" * 161],
        "Item": ["", "Sceetler", "Ranger Bhato", "Finish Raft", "item-14", "File:Item-14.png", "Item:Iron Hand Axe",
                 "Turnip", "Turnip (nature)", "Iron Hand Axe#Stats", "IRON HAND AXE", "x" * 161,
                 "Plant Fiber|quantity=0", "Plant Fiber|quantity=-1", "Plant Fiber|quantity=1.2",
                 "Plant Fiber|quantity=1e3", "Plant Fiber|quantity=" + "9" * 19],
    }
    for template, values in invalid.items():
        for value in values:
            rendered = api({"action": "parse", "title": "Invalid display", "text": "{{" + template + "|" + value + "}}",
                            "prop": "text"}, post=True)["parse"]["text"]["*"]
            if 'mirklurk-display-error' not in rendered or "Display error:" not in rendered or 'role="alert"' not in rendered:
                raise RuntimeError(f"{template}: invalid input did not produce a visible alert.")
            if 'class="mirklurk-cell-grid"' in rendered or '<img ' in rendered:
                raise RuntimeError("Invalid input produced a success-shaped grid or coin display.")
    injected = '<nowiki>"><script>alert(1)</script>&</nowiki>'
    for template in ("Coins", "Health grid", "Attack grid", "Creature", "Item"):
        rendered = api({"action": "parse", "title": "Display escape smoke",
                        "text": "{{" + template + "|" + injected + "}}", "prop": "text"}, post=True)["parse"]["text"]["*"]
        if "Display error:" not in rendered or "<script>" in rendered or "alert(1)" in rendered:
            raise RuntimeError("Invalid template input escaped or was reflected into markup.")
    rendered = api({"action": "parse", "title": "Label escape smoke",
                    "text": "{{Attack grid|1|label=" + injected + "}}", "prop": "text"}, post=True)["parse"]["text"]["*"]
    if "Display error:" not in rendered or "alert(1)" in rendered:
        raise RuntimeError("Attack caption allowed arbitrary injected markup.")
    rows = parse('<table>{{Recipe row|ingredients={{Item|Plant Fiber|quantity=4}}'
                 '|output={{Item|Bandage|quantity=1}}|methods=[[Inventory crafting]]|ap=1.2'
                 '|conditions=<nowiki>A | B = C {{literal}}</nowiki>}}</table>')
    parsed = dom(rows, "Recipe row")
    if len(parsed.rows) != 1 or [cell["text"] for cell in parsed.rows[0]["cells"]] != [
        "Plant Fiber x 4", "Bandage x 1", "Inventory crafting", "1.2 base AP", "A | B = C {{literal}}"
    ]:
        raise RuntimeError("Recipe row lost named arguments, nesting, fractional AP or literal escaping.")
    for args, cost in (("", "Unknown"), ("|ap=0", "0 base AP"), ("|cost=3 turns", "3 turns")):
        parsed = dom(parse("<table>{{Recipe row" + args + "}}</table>"), "Recipe row")
        if [cell["text"] for cell in parsed.rows[0]["cells"]] != [
            "No item inputs", "Unknown", "Unknown", cost, "Unknown"
        ]:
            raise RuntimeError("Recipe row invented a default value or lost a custom/zero cost.")
    print("Native displays: all 118 grids, exact coins, 246 items, 25 creature portraits and authored lists, "
          "images, accessibility, invalid inputs and resource bounds passed.", flush=True)


def smoke_vendor_rows(api, pages, data, catalog, token, dom, check_errors):
    locations = page_locations(data, catalog)
    entities = {row["id"]: row for row in data["entities"]}
    offers = copy.deepcopy([entry for entry in data["entries"] if entry["kind"] == "merchant"][:2])
    offers[0]["details"].update(price=19, currency="silver", quantity=3, location="First place")
    offers[1]["details"].update(location="Second place")
    offers[0]["conditions"], offers[1]["conditions"] = "First condition", "Second condition"
    title = "Vendor exception smoke"
    text = merchant_table(offers, data["illustrations"], entities, locations, standard_prices=True)
    result = api({"action": "edit", "title": title, "text": text, "token": token,
                  "summary": "Disposable mixed vendor prices"}, post=True)
    if result.get("edit", {}).get("result") != "Success":
        raise RuntimeError("Vendor-price fixture could not be saved.")
    full = api({"action": "parse", "page": title, "prop": "text|templates"})["parse"]
    for index in (None, 0, 1):
        result = full if index is None else api({
            "action": "parse", "title": locations[offers[index]["details"]["item"]],
            "text": "{{:" + title + "|view=offers|item=" + offers[index]["details"]["item"] + "}}",
            "prop": "text|templates"}, post=True)["parse"]
        rendered = result["text"]["*"]
        check_errors(rendered)
        projection = dom(rendered, title)
        if len(projection.rows) != (2 if index is None else 1):
            raise RuntimeError("Mixed vendor-price views lost exact offer filtering.")
        for row in projection.rows:
            if row["headers"] != ["Seller", "Item", "Quantity", "Unit price", "Location", "Conditions"] or len(row["cells"]) != 6:
                raise RuntimeError("Mixed vendor prices misaligned headers and cells.")
        if index in (None, 0) and "1 gold 9 silver" not in projection.text:
            raise RuntimeError("A vendor exception no longer uses the exact Coins value.")
        if index is not None:
            dependencies = {row["*"] for row in result.get("templates", [])}
            if dependencies & set(locations.values()):
                raise RuntimeError("A mixed-price item view recursively included an item article.")
            if index == 1 and projection.rows[0]["cells"][3]["text"] != "Standard item price":
                raise RuntimeError("A mixed-price standard row lost its nonrecursive price link.")


def smoke_display_propagation(run, api, pages, token, wait_tick, refreshed):
    # Ordinary edits, no imports or reseeding; each dependency layer must invalidate readers.
    owner_anchor = re.search(r'id="entity-[^"]+"', pages["Survivor's Field Kit"]).group()
    examples = (
        ("Template:Item", pages["Template:Item"].replace("<includeonly>", "<includeonly>native-item-marker ", 1),
         "native-item-marker", "Items", 'aria-label="Iron Hand Axe"', 'id="price-item-14"'),
        ("Template:Item", pages["Template:Item"].replace("<includeonly>", "<includeonly>native-item-row-marker ", 1),
         "native-item-row-marker", "Gurb-Gurb", "mirklurk-item", 'id="price-item-14"'),
        ("Template:Recipe row", pages["Template:Recipe row"].replace("<td>", "<td>native-recipe-marker ", 1),
         "native-recipe-marker", "Campfire", "base", 'id="entity-item-141"'),
        ("Template:Ware row", pages["Template:Ware row"].replace("<td>", "<td>native-ware-marker ", 1),
         "native-ware-marker", "Iron Hand Axe", "Magus Clay", 'id="entity-being-8"'),
        ("Template:Coins", pages["Template:Coins"].replace("<includeonly>", "<includeonly>native-template-marker ", 1),
         "native-template-marker", "Gurb-Gurb", "2 gold", owner_anchor),
        ("Module:Display", pages["Module:Display"].replace("return table.concat(parts, ' ')", "return 'native-module-marker ' .. table.concat(parts, ' ')"),
         "native-module-marker", "Gurb-Gurb", "2 gold", owner_anchor),
        (ASSETS_TITLE, pages[ASSETS_TITLE].replace("gold = [=[", "gold = [=[native-assets-marker ", 1),
         "native-assets-marker", "Gurb-Gurb", "2 gold", owner_anchor),
        ("Template:Creature", pages["Template:Creature"].replace("<includeonly>", "<includeonly>native-creature-template-marker ", 1),
         "native-creature-template-marker", "Bestiary", 'aria-label="Sceetler"', 'id="grid-being-13-health"'),
        ("Module:Display", pages["Module:Display"].replace("return tostring(mw.html.create('span')",
                                                        "return 'native-creature-module-marker ' .. tostring(mw.html.create('span')"),
         "native-creature-module-marker", "Bestiary", 'aria-label="Sceetler"', 'id="grid-being-13-health"'),
        (ASSETS_TITLE, pages[ASSETS_TITLE].replace("Sceetler portrait", "native-creature-assets-marker"),
         "native-creature-assets-marker", "Bestiary", 'aria-label="Sceetler"', 'id="grid-being-13-health"'),
    )
    for owner, edited, marker, reader, restored_marker, forbidden_anchor in examples:
        if edited == pages[owner]:
            raise RuntimeError("Native propagation test did not modify its intended owner.")
        api({"action": "parse", "page": reader, "prop": "text"})
        wait_tick(api)
        result = api({"action": "edit", "title": owner, "text": edited, "token": token,
                      "summary": "Disposable ordinary display edit"}, post=True)
        if result.get("edit", {}).get("result") != "Success":
            raise RuntimeError("An ordinary display edit was rejected.")
        refreshed(run, api, reader, marker, forbidden_anchor, owner)
        wait_tick(api)
        api({"action": "edit", "title": owner, "text": pages[owner], "token": token,
             "summary": "Restore disposable display fixture"}, post=True)
        rendered = refreshed(run, api, reader, restored_marker, forbidden_anchor, owner)
        if marker in rendered:
            raise RuntimeError("Restoring a display owner did not invalidate the cached reader.")
    prefix = "        [ " + lua_string("Sceetler") + " ] = "
    lines = pages[ASSETS_TITLE].splitlines()
    original = next(line for line in lines if line.startswith(prefix))
    name_only = prefix + lua_string("[[Sceetler|<nowiki>Sceetler</nowiki>]]") + ","
    assets_without_portrait = pages[ASSETS_TITLE].replace(original, name_only)
    wait_tick(api)
    api({"action": "edit", "title": ASSETS_TITLE, "text": assets_without_portrait, "token": token,
         "summary": "Disposable missing approved portrait fixture"}, post=True)
    rendered = api({"action": "parse", "title": "Missing portrait smoke", "text": "{{Creature|Sceetler}}",
                    "prop": "text"}, post=True)["parse"]["text"]["*"]
    if "no reviewed image" in rendered or "<img " in rendered or 'title="Sceetler"' not in rendered:
        raise RuntimeError("A missing creature portrait did not render an explicit linked-name-only display.")
    wait_tick(api)
    api({"action": "edit", "title": ASSETS_TITLE, "text": pages[ASSETS_TITLE], "token": token,
         "summary": "Restore disposable portrait fixture"}, post=True)
