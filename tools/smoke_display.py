"""Real disposable MediaWiki/Scribunto checks; called only by smoke_deploy."""

import re
import urllib.parse

from sync_wiki import SyncError, fetch_live, sync
from wiki_catalog import page_locations
from wiki_display import ASSETS_TITLE, DISPLAY_TITLES, content_model, page_namespace


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
    for template in ("Coins", "Health grid", "Attack grid"):
        rendered = api({"action": "parse", "title": "Display escape smoke",
                        "text": "{{" + template + "|" + injected + "}}", "prop": "text"}, post=True)["parse"]["text"]["*"]
        if "Display error:" not in rendered or "<script>" in rendered or "alert(1)" in rendered:
            raise RuntimeError("Invalid template input escaped or was reflected into markup.")
    rendered = api({"action": "parse", "title": "Label escape smoke",
                    "text": "{{Attack grid|1|label=" + injected + "}}", "prop": "text"}, post=True)["parse"]["text"]["*"]
    if "Display error:" not in rendered or "alert(1)" in rendered:
        raise RuntimeError("Attack caption allowed arbitrary injected markup.")
    print("Native displays: all 118 grids, exact coins, images, accessibility, invalid inputs and resource bounds passed.", flush=True)


def smoke_display_propagation(run, api, pages, token, wait_tick, refreshed):
    # Ordinary edits, no imports or reseeding; each dependency layer must invalidate readers.
    examples = (
        ("Template:Coins", pages["Template:Coins"].replace("<includeonly>", "<includeonly>native-template-marker ", 1), "native-template-marker"),
        ("Module:Display", pages["Module:Display"].replace("return table.concat(parts, ' ')", "return 'native-module-marker ' .. table.concat(parts, ' ')"), "native-module-marker"),
        (ASSETS_TITLE, pages[ASSETS_TITLE].replace("gold = [=[", "gold = [=[native-assets-marker ", 1), "native-assets-marker"),
    )
    for owner, edited, marker in examples:
        if edited == pages[owner]:
            raise RuntimeError("Native propagation test did not modify its intended owner.")
        api({"action": "parse", "page": "Gurb-Gurb", "prop": "text"})
        wait_tick(api)
        result = api({"action": "edit", "title": owner, "text": edited, "token": token,
                      "summary": "Disposable ordinary display edit"}, post=True)
        if result.get("edit", {}).get("result") != "Success":
            raise RuntimeError("An ordinary display edit was rejected.")
        refreshed(run, api, "Gurb-Gurb", marker, 'id="entity-item-220"', owner)
        wait_tick(api)
        api({"action": "edit", "title": owner, "text": pages[owner], "token": token,
             "summary": "Restore disposable display fixture"}, post=True)
        rendered = refreshed(run, api, "Gurb-Gurb", "2 gold", 'id="entity-item-220"', owner)
        if marker in rendered:
            raise RuntimeError("Restoring a display owner did not invalidate the cached reader.")
