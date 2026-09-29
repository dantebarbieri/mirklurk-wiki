"""Phone/desktop checks on real disposable Vector articles, never live content."""

import hashlib
import json
from pathlib import Path
import urllib.parse


ARTICLES = (
    "Items", "Bestiary", "Iron Hand Axe", "Survivor's Field Kit", "Gurb-Gurb",
    "Alchemy workstation", "Campfire", "Scaal", "Nightmare", "World generation",
)
REGIONS = ".mirklurk-scroll, .pixel-art-figure"


def measure(page):
    return page.evaluate("""() => {
        const root = document.querySelector('.mw-parser-output');
        const rect = e => {
            const r = e.getBoundingClientRect();
            return {x:r.x, y:r.y, width:r.width, height:r.height, right:r.right};
        };
        const regions = [...root.querySelectorAll('.mirklurk-scroll, .pixel-art-figure')];
        const tables = [...root.querySelectorAll('table.wikitable, table.mirklurk-cell-grid')];
        const semantics = tables.map(t => ({
            caption:t.caption?.textContent.trim() || '',
            rows:[...t.rows].map(r => [...r.cells].map(c => ({
                tag:c.tagName, text:c.textContent.trim(), label:c.getAttribute('aria-label'),
                title:c.getAttribute('title'), scope:c.getAttribute('scope'),
                colspan:c.colSpan, rowspan:c.rowSpan,
                links:[...c.querySelectorAll('a')].map(a => [a.textContent, a.getAttribute('href')])
            })))
        }));
        const images = [...root.querySelectorAll('.pixel-art img, .health-armor-icon img')].map(i => ({
            ...rect(i), src:i.currentSrc, srcset:i.getAttribute('srcset'), alt:i.alt,
            originalWidth:Number(i.getAttribute('width')), originalHeight:Number(i.getAttribute('height')),
            rendering:getComputedStyle(i).imageRendering
        }));
        return {
            viewport:window.innerWidth, client:document.documentElement.clientWidth,
            scroll:document.documentElement.scrollWidth,
            visualWidth:window.visualViewport.width, scale:window.visualViewport.scale,
            meta:document.querySelector('meta[name="viewport"]')?.content,
            font:parseFloat(getComputedStyle(root).fontSize), content:rect(root),
            errors:root.querySelectorAll('.error, .mw-broken-media').length,
            regions:regions.map(e => ({
                box:rect(e), width:e.clientWidth, scroll:e.scrollWidth,
                overflow:getComputedStyle(e).overflowX, tabindex:e.getAttribute('tabindex'),
                role:e.getAttribute('role'), label:e.getAttribute('aria-label')
            })),
            tables:tables.map(t => ({
                box:rect(t), display:getComputedStyle(t).display,
                wrapped:t.parentElement.matches('.mirklurk-scroll')
            })),
            cells:[...root.querySelectorAll('.grid-cell, .grid-hole')].map(c => ({
                box:rect(c), em:parseFloat(getComputedStyle(c).fontSize),
                minWidth:parseFloat(getComputedStyle(c).minWidth)
            })),
            coins:[...root.querySelectorAll('.mirklurk-coin')].map(c => {
                const i=rect(c.querySelector('img')), t=rect(c.querySelector('.mirklurk-coin-text'));
                return {image:i, text:t, delta:Math.abs(i.y+i.height/2-t.y-t.height/2)};
            }),
            items:[...root.querySelectorAll('.mirklurk-item')].filter(e => e.querySelector('img')).map(e => {
                const i=rect(e.querySelector('img')), t=rect(e.querySelector('.mirklurk-item-name'));
                return {delta:Math.abs(i.y+i.height/2-t.y-t.height/2), gap:t.x-i.right};
            }),
            images, semantics
        };
    }""")


def check_layout(result, width, assets):
    if result["errors"]:
        raise RuntimeError("Responsive article contains parser/image errors.")
    if (result["viewport"] != width or result["client"] != width or result["scroll"] > width + 1
            or abs(result["visualWidth"] - width) > 1 or abs(result["scale"] - 1) > 0.01):
        raise RuntimeError("Article has a scaled/fixed viewport or whole-page horizontal overflow.")
    if "width=device-width" not in result["meta"] or "user-scalable=no" in result["meta"]:
        raise RuntimeError("Vector did not emit an accessible device-width viewport.")
    if result["font"] < 14:
        raise RuntimeError("Responsive content was made unreadably small.")
    for region in result["regions"]:
        if (region["tabindex"] != "0" or region["role"] != "region" or not region["label"]
                or region["overflow"] != "auto" or region["box"]["right"] > width + 1):
            raise RuntimeError("A local scroll container lost its bounds or accessible keyboard contract.")
    if any(not t["wrapped"] or t["display"] != "table" for t in result["tables"]):
        raise RuntimeError("A wiki table lost its external wrapper or native table layout.")
    if any(c["minWidth"] < 3 * c["em"] or c["box"]["height"] < 3 * c["em"] for c in result["cells"]):
        raise RuntimeError("Health/attack cells shrank below their existing 3em geometry.")
    for coin in result["coins"]:
        if coin["delta"] > 0.5 or coin["image"]["width"] != 16 or coin["image"]["height"] != 16:
            raise RuntimeError("Responsive layout changed coin size or line-box centering.")
    if any(i["delta"] > 0.5 or i["gap"] < -0.5 for i in result["items"]):
        raise RuntimeError("Responsive layout overlaps item labels or changes their centering.")
    for image in result["images"]:
        name = urllib.parse.unquote(urllib.parse.urlsplit(image["src"]).path).rsplit("/", 1)[-1]
        pixels = assets[name]
        scale = image["width"] / (pixels["width"] / pixels["source_scale"])
        if (image["srcset"] or "/thumb/" in image["src"] or not image["alt"]
                or image["rendering"] != "pixelated" or scale < 1 or abs(scale - round(scale)) > 0.01
                or abs(image["height"] - pixels["height"] / pixels["source_scale"] * scale) > 0.1
                or image["originalWidth"] != pixels["width"] or image["originalHeight"] != pixels["height"]):
            raise RuntimeError("An article image lost its original-file, integer-native or accessible display.")


def check_keyboard(page, index):
    region = page.locator(REGIONS).nth(index)
    region.scroll_into_view_if_needed()
    region.focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    if not region.evaluate("(e) => document.activeElement === e"):
        raise RuntimeError("The horizontal scroll region is not in the native Tab sequence.")
    focus = region.evaluate("""e => {
        const s=getComputedStyle(e);
        return {visible:e.matches(':focus-visible'), width:parseFloat(s.outlineWidth), style:s.outlineStyle};
    }""")
    if not focus["visible"] or focus["width"] <= 0 or focus["style"] == "none":
        raise RuntimeError("Keyboard scroll focus has no visible indicator.")
    page.keyboard.press("ArrowRight")
    page.wait_for_function("(e) => e.scrollLeft > 0", arg=region.element_handle())
    page.keyboard.press("Tab")
    if region.evaluate("(e) => document.activeElement === e"):
        raise RuntimeError("The horizontal scroll region traps keyboard focus.")
    return {"scrollLeft": region.evaluate("(e) => e.scrollLeft"), "focus": focus}


def check_touch(context, page, index):
    region = page.locator(REGIONS).nth(index)
    region.scroll_into_view_if_needed()
    region.evaluate("(e) => { e.scrollLeft = 0; }")
    box = region.bounding_box()
    top = max(box["y"], 140)
    bottom = min(box["y"] + box["height"], page.viewport_size["height"])
    x, y = box["x"] + box["width"] * 0.8, top + min((bottom - top) / 2, 80)
    session = context.new_cdp_session(page)
    try:
        session.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        for step in range(1, 7):
            session.send("Input.dispatchTouchEvent", {
                "type": "touchMove", "touchPoints": [{"x": x - step * 22, "y": y}],
            })
            page.wait_for_timeout(30)
        session.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_function("(e) => e.scrollLeft > 0", arg=region.element_handle())
        return {"scrollLeft": region.evaluate("(e) => e.scrollLeft")}
    finally:
        session.detach()


def smoke_responsive(base, data, artifact_dir):
    from playwright.sync_api import sync_playwright

    if urllib.parse.urlsplit(base).hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("Responsive smoke may only visit the disposable localhost wiki.")
    folder = Path(artifact_dir)
    folder.mkdir(parents=True, exist_ok=True)
    assets = {i["file_title"].removeprefix("File:").replace(" ", "_"): i["pixel_art"]
              for i in data["illustrations"] if i["rights_status"] == "approved"}
    records, baseline = [], {}

    def save():
        (folder / "responsive-geometry.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for name, width, mobile, javascript in (
                ("desktop", 1440, False, True), ("phone", 320, True, True),
                ("phone-wide", 390, True, True), ("tablet", 768, True, True),
                ("no-js-phone", 320, True, False),
            ):
                context = browser.new_context(viewport={"width": width, "height": 900},
                                              is_mobile=mobile, has_touch=mobile,
                                              device_scale_factor=2 if mobile else 1,
                                              java_script_enabled=javascript)
                page = context.new_page()
                for article in ARTICLES:
                    page.goto(base + "/index.php?" + urllib.parse.urlencode({
                        "title": article, "useskin": "vector-2022",
                    }), wait_until="networkidle")
                    page.evaluate("""async () => {
                        await document.fonts.ready;
                        await Promise.all([...document.images].map(i => i.decode()));
                    }""")
                    result = measure(page)
                    semantics = result.pop("semantics")
                    result["semanticHash"] = hashlib.sha256(json.dumps(semantics, sort_keys=True).encode()).hexdigest()
                    record = {"viewport": name, "article": article, **result}
                    records.append(record)
                    save()
                    try:
                        check_layout(result, width, assets)
                        image_sizes = [(i["src"], i["width"], i["height"]) for i in result["images"]]
                        if name == "desktop":
                            baseline[article] = (result["semanticHash"], image_sizes)
                            record["unwrappedTableWidths"] = page.evaluate("""() => {
                                const wrappers=[...document.querySelectorAll(
                                    '.mirklurk-scroll'
                                )].filter(e => e.querySelector(':scope > table.wikitable'));
                                wrappers.forEach(e => { e.style.display='contents'; });
                                const widths=[...document.querySelectorAll(
                                    '.mw-parser-output table.wikitable, .mw-parser-output table.mirklurk-cell-grid'
                                )].map(t => t.getBoundingClientRect().width);
                                wrappers.forEach(e => { e.style.removeProperty('display'); });
                                return widths;
                            }""")
                            if record["unwrappedTableWidths"] != [t["box"]["width"] for t in result["tables"]]:
                                raise RuntimeError("Local scroll wrappers changed the desktop table widths.")
                        elif baseline[article] != (result["semanticHash"], image_sizes):
                            raise RuntimeError("Responsive mode changed table content, coordinates, links or sprite geometry.")
                        overflowing = [i for i, r in enumerate(result["regions"]) if r["scroll"] > r["width"] + 1]
                        if name == "phone" and article in {"Scaal", "Alchemy workstation"}:
                            if not overflowing:
                                raise RuntimeError("The wide real grid/recipe table did not exercise local scrolling.")
                            index = overflowing[0]
                            record["keyboard"] = check_keyboard(page, index)
                            record["touch"] = check_touch(context, page, index)
                        if name == "no-js-phone" and article == "Scaal":
                            if not overflowing:
                                raise RuntimeError("The no-JavaScript page did not retain local scrolling.")
                            record["keyboard"] = check_keyboard(page, overflowing[0])
                        if article == "Nightmare" and not any(
                            c["title"] and c["title"].endswith("0-1 damage")
                            for t in semantics for r in t["rows"] for c in r
                        ):
                            raise RuntimeError("The real attack grid lost its occupied zero-range cells.")
                        if name in {"desktop", "phone", "no-js-phone"} and article in {
                            "Items", "Gurb-Gurb", "Alchemy workstation", "Scaal", "Nightmare",
                        }:
                            target = ("#Wares" if article == "Gurb-Gurb" else
                                      "#Base_health" if article in {"Scaal", "Nightmare"} else
                                      "#Ammunition" if article == "Items" else "#What_you_can_craft")
                            page.locator(target).scroll_into_view_if_needed()
                            page.screenshot(path=str(folder / (name + "-responsive-" + article.replace(" ", "-") + ".png")))
                        if name == "desktop" and article == "Scaal":
                            page.set_viewport_size({"width": 320, "height": 900})
                            check_layout(measure(page), 320, assets)
                            page.set_viewport_size({"width": width, "height": 900})
                            restored = measure(page)
                            check_layout(restored, width, assets)
                            if [t["box"]["width"] for t in restored["tables"]] != [t["box"]["width"] for t in result["tables"]]:
                                raise RuntimeError("Resizing back to desktop did not restore table layout.")
                            record["resizeRestored"] = True
                    except Exception:
                        page.screenshot(path=str(folder / ("failed-" + name + "-" + article.replace(" ", "-") + ".png")),
                                        full_page=True)
                        raise
                    finally:
                        save()
                context.close()
        finally:
            browser.close()
    print("Responsive Vector: real articles at 320/390/768/1440px, no-JS, native pixels, unchanged "
          "tables/grids, local keyboard/touch scrolling and desktop resize passed.", flush=True)
