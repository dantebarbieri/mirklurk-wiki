"""Browser geometry on the disposable Vector wiki; screenshots contain only synthetic art."""

import json
from pathlib import Path
import urllib.parse

from wiki_render import image_for, pixel_image


def smoke_browser(api, base, token, data, artifact_dir):
    from playwright.sync_api import sync_playwright

    if urllib.parse.urlsplit(base).hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("Browser smoke may only edit the disposable localhost wiki.")
    folder = Path(artifact_dir)
    folder.mkdir(parents=True, exist_ok=True)
    # Reproduce the old baseline layout in the same skin/font, not a CSS-only proxy.
    old = pixel_image(image_for("item-73", data["illustrations"]), 20, 20, "", "Silver coin")
    title = "Display layout smoke"
    fixture = (
        '<div id="layout-fixture">\n'
        '== Buying ==\n'
        '<p id="old-coins">Previous layout: ' + old + ' <span class="old-text">2 silver</span></p>\n'
        '<p id="new-coins">Standard unit price: {{Coins|250}}. Purchase price per item; not resale value.</p>\n'
        '<table class="wikitable"><tr><th>Seller</th><th>Item</th><th>Price</th></tr>\n'
        '{{Ware row|seller=[[Magus Clay]]|item=Iron Hand Axe|price={{:Iron Hand Axe}}}}\n</table>\n'
        '<p>{{Item|Plant Fiber|quantity=4}} and {{Item|Turnip (item)}}</p>\n'
        '<div id="narrow-coins" style="width:220px;max-width:100%;">{{Coins|999999999999999999}}</div>\n'
        '<div id="narrow-item" style="width:110px;max-width:100%;">{{Item|Survivor\'s Field Kit}}</div>\n'
        '<div id="health-fixture">{{Health grid|0,1,0;1,4,1;0,1,0}}</div>\n'
        '<p>{{Creature|Sceetler}}</p>\n</div>'
    )
    result = api({"action": "edit", "title": title, "text": fixture, "token": token,
                  "summary": "Disposable layout fixture with synthetic art"}, post=True)
    if result.get("edit", {}).get("result") != "Success":
        raise RuntimeError("The disposable browser fixture could not be saved.")
    measurements = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for name, viewport, dpr in (("desktop", {"width": 1440, "height": 1100}, 1),
                                         ("mobile", {"width": 390, "height": 844}, 2)):
                context = browser.new_context(viewport=viewport, device_scale_factor=dpr)
                page = context.new_page()
                page.goto(base + "/index.php?" + urllib.parse.urlencode({"title": title, "useskin": "vector"}),
                          wait_until="networkidle")
                page.evaluate("""async () => {
                    await document.fonts.ready;
                    await Promise.all([...document.images].map(i => i.decode()));
                }""")
                page.screenshot(path=str(folder / (name + "-layout.png")), full_page=True)
                result = page.evaluate("""() => {
                    const root = document.querySelector('#layout-fixture');
                    const rect = e => {
                        const r = e.getBoundingClientRect();
                        return {x:r.x, y:r.y, width:r.width, height:r.height, center:r.y+r.height/2};
                    };
                    const pairs = (selector, label) => [...root.querySelectorAll(selector)].map(e => {
                        const image = e.querySelector('img'), text = e.querySelector(label);
                        const i = rect(image), t = rect(text);
                        return {label:e.textContent.trim(), image:i, text:t, delta:Math.abs(i.center-t.center),
                            width:Number(image.getAttribute('width')), height:Number(image.getAttribute('height')),
                            src:image.currentSrc, srcset:image.getAttribute('srcset'), alt:image.alt};
                    });
                    const oldImage=rect(root.querySelector('#old-coins img'));
                    const oldText=rect(root.querySelector('.old-text'));
                    const narrow = root.querySelector('#narrow-coins');
                    const item = root.querySelector('#narrow-item');
                    const cells = [...root.querySelectorAll('#health-fixture .grid-cell')].map(e => ({
                        box:rect(e), em:parseFloat(getComputedStyle(e).fontSize),
                        height:parseFloat(getComputedStyle(e).height)
                    }));
                    const textStyle=getComputedStyle(root.querySelector('.mirklurk-coin-text'));
                    const canvas=document.createElement('canvas'), ctx=canvas.getContext('2d');
                    ctx.font=textStyle.font;
                    const metrics=ctx.measureText('2 silver');
                    return {
                        oldDelta:Math.abs(oldImage.center-oldText.center),
                        font:textStyle.font, lineHeight:textStyle.lineHeight,
                        glyphAscent:metrics.actualBoundingBoxAscent, glyphDescent:metrics.actualBoundingBoxDescent,
                        coins:pairs('.mirklurk-coin', '.mirklurk-coin-text'),
                        items:pairs('.mirklurk-item', '.mirklurk-item-name'),
                        narrowWidth:narrow.clientWidth, narrowScroll:narrow.scrollWidth,
                        narrowLines:[...narrow.querySelectorAll('.mirklurk-coin')].map(e => rect(e).y),
                        itemWidth:item.clientWidth, itemScroll:item.scrollWidth,
                        itemLines:rect(item.querySelector('.mirklurk-item-name')).height /
                            parseFloat(getComputedStyle(item.querySelector('.mirklurk-item-name')).lineHeight),
                        cells,
                        errors:root.querySelectorAll('.error, .mw-broken-media').length
                    };
                }""")
                measurements.append({"viewport": name, **result})
                (folder / "geometry.json").write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
                if result["errors"] or result["oldDelta"] <= 1:
                    raise RuntimeError("The browser fixture did not reproduce the old baseline misalignment.")
                # Center line boxes, not a baseline+x-height estimate. Half a CSS pixel
                # allows fractional font/layout rounding; it is not a visual offset.
                for kind in ("coins", "items"):
                    if not result[kind]:
                        raise RuntimeError("The browser fixture lost its native " + kind)
                    for pair in result[kind]:
                        if pair["delta"] > 0.5:
                            raise RuntimeError(f"{name} {kind}: icon/text centers differ: {pair}")
                        if pair["srcset"] or "/thumb/" in pair["src"] or not pair["alt"]:
                            raise RuntimeError("Browser display lost original-file/accessibility policy.")
                        if kind == "coins" and (pair["image"]["width"] != 16 or pair["image"]["height"] != 16):
                            raise RuntimeError("Browser coins changed their 16px integer-native size.")
                if (result["narrowScroll"] > result["narrowWidth"]
                        or len(set(result["narrowLines"])) < 2 or result["itemScroll"] > result["itemWidth"]
                        or result["itemLines"] < 1.9):
                    raise RuntimeError("Coin denominations or long item names no longer wrap without overflow.")
                if len(result["cells"]) != 5 or any(cell["height"] < 3 * cell["em"] for cell in result["cells"]):
                    raise RuntimeError("Coin alignment changed health-cell geometry.")
                for article in ("Iron Hand Axe", "Items", "Gurb-Gurb"):
                    page.goto(base + "/index.php?" + urllib.parse.urlencode({"title": article, "useskin": "vector"}),
                              wait_until="networkidle")
                    page.evaluate("""async () => {
                        await document.fonts.ready;
                        await Promise.all([...document.images].map(i => i.decode()));
                    }""")
                    if page.locator(".mw-parser-output .error, .mw-parser-output .mw-broken-media").count():
                        raise RuntimeError("A migrated article has rendered errors.")
                    if not page.locator(".mw-parser-output .mirklurk-item").count():
                        raise RuntimeError("A migrated article does not actually use Item.")
                    article_pairs = page.evaluate("""() => [...document.querySelectorAll(
                        '.mw-parser-output .mirklurk-item, .mw-parser-output .mirklurk-coin'
                    )].filter(e => e.querySelector('img')).map(e => {
                        const i=e.querySelector('img').getBoundingClientRect();
                        const t=e.querySelector('.mirklurk-item-name, .mirklurk-coin-text').getBoundingClientRect();
                        return {label:e.textContent.trim(), delta:Math.abs(i.y+i.height/2-t.y-t.height/2),
                            gap:t.x-i.right, width:i.width, height:i.height};
                    })""")
                    if any(pair["delta"] > 0.5 or pair["gap"] < 0 for pair in article_pairs):
                        raise RuntimeError(f"{name} {article}: real article icons overlap text or are not centered.")
                    measurements.append({"viewport": name, "article": article, "pairs": article_pairs})
                    (folder / "geometry.json").write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
                    if article == "Iron Hand Axe":
                        page.locator("#Buying").scroll_into_view_if_needed()
                    elif article == "Items":
                        page.locator("#Ammunition").scroll_into_view_if_needed()
                    else:
                        page.locator("#Wares").scroll_into_view_if_needed()
                    page.screenshot(path=str(folder / (name + "-" + article.replace(" ", "-") + ".png")))
                context.close()
        finally:
            browser.close()
    print("Vector browser: old baseline reproduced; centered 16px coins/item names, narrow wrapping, "
          "3em health cells and real desktop/mobile articles passed.", flush=True)
