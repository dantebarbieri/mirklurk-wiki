"""Opt-in Docker integration test in an isolated, disposable Compose project."""

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser
from pathlib import Path

from build_wiki import build_pages, build_xml, existing_titles, title_key
from wiki_catalog import entry_owners, entry_relations, page_locations
from wiki_details import load_publication_inputs
from wiki_render import display_entry, image_for, recipe_groups
from wiki_views import selective_view


ROOT = Path(__file__).resolve().parents[1]


class RenderedGrids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.grids = []
        self.active = False
        self.cell = None
        self.images = []
        self.links = []
        self.icon_styles = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and "mirklurk-cell-grid" in attrs.get("class", "").split():
            self.active = True
            self.grids.append([])
        elif self.active and tag == "tr":
            self.grids[-1].append([])
        elif self.active and tag == "td":
            self.cell = {"attrs": attrs, "text": "", "images": [], "links": [], "icon_styles": []}
            self.grids[-1][-1].append(self.cell)
        if tag == "img":
            self.images.append(attrs)
            if self.cell is not None:
                self.cell["images"].append(attrs)
        elif tag == "a":
            self.links.append(attrs)
            if self.cell is not None:
                self.cell["links"].append(attrs)
        elif tag == "span" and "health-armor-icon" in attrs.get("class", "").split():
            self.icon_styles.append(attrs.get("style", ""))
            if self.cell is not None:
                self.cell["icon_styles"].append(attrs.get("style", ""))

    def handle_endtag(self, tag):
        if tag == "table":
            self.active = False
        elif tag == "td":
            self.cell = None

    def handle_data(self, data):
        if self.active and self.cell is not None:
            self.cell["text"] += data


def check_shield_icon(images, links, styles, armor):
    name = {1: "bronze", 2: "silver", 3: "gold"}[armor]
    label = f'1 HP, {armor} armor {"layer" if armor == 1 else "layers"} ({name} shield)'
    if len(images) != 1 or any(images[0].get(key) != value for key, value in (
        ("alt", label), ("width", "32"), ("height", "32"),
    )):
        raise RuntimeError("A health shield lost its exact size or accessible HP/armor label.")
    filename = f"Health-armor-{armor}.png"
    if filename not in urllib.parse.unquote(images[0].get("src", "")):
        raise RuntimeError("A health cell displays the wrong armor sprite.")
    if len(links) != 1 or "File:" + filename not in urllib.parse.unquote(links[0].get("href", "")):
        raise RuntimeError("A shield no longer links to its canonical local File page.")
    if len(styles) != 1 or "image-rendering:pixelated" not in styles[0].replace(" ", ""):
        raise RuntimeError("MediaWiki stripped the shield's pixel rendering style.")


def smoke_reader_release(api, pages, data, catalog, details, image_hashes):
    locations = page_locations(data, catalog)
    for identity in ("nature-4", "nature-7", "nature-17"):
        image = image_for(identity, data["illustrations"])
        filename = image["file_title"].removeprefix("File:")
        old_filename = identity.capitalize() + ".png"
        parsed = api({"action": "parse", "page": locations[identity], "prop": "text|images"})["parse"]
        check_parser_errors(parsed["text"]["*"])
        if filename not in parsed["images"] or old_filename in parsed["images"]:
            raise RuntimeError("A tree page does not use its reviewed mature composition exclusively.")
        if "representative shape assembled" not in parsed["text"]["*"]:
            raise RuntimeError("A mature-tree caption lost its assembly qualification.")
        info = next(iter(api({"action": "query", "titles": "File:" + old_filename,
                              "prop": "imageinfo", "iiprop": "url"})["query"]["pages"].values()))
        with urllib.request.urlopen(info["imageinfo"][0]["url"], timeout=30) as response:
            if hashlib.sha256(response.read()).hexdigest() != image_hashes[old_filename]:
                raise RuntimeError("A legacy tree image was removed or changed during the seed import.")
    for guide in catalog["guides"]:
        if "image_entity" not in guide:
            continue
        image = image_for(guide["image_entity"], data["illustrations"])
        parsed = api({"action": "parse", "page": guide["title"], "prop": "text|images|links"})["parse"]
        check_parser_errors(parsed["text"]["*"])
        if image["file_title"].removeprefix("File:") not in parsed["images"]:
            raise RuntimeError("A mechanics guide lost its approved contextual image.")
        if not set(guide.get("related_pages", [])) <= {link["*"] for link in parsed["links"] if link["ns"] == 0}:
            raise RuntimeError("A mechanics guide lost its related guide links.")
        images = RenderedGrids()
        images.feed(parsed["text"]["*"])
        if not any(image["file_title"].removeprefix("File:") in urllib.parse.unquote(row.get("src", "")) for row in images.images):
            raise RuntimeError("A contextual guide illustration did not resolve to an actual rendered image.")
    for title, category in (("Nightmare", "Bugs"), ("Mirk Runner", "Rodents"),
                            ("Sceetler", "Scaalmyr"), ("Mudfin", "Aquatic creatures")):
        result = api({"action": "query", "titles": title, "prop": "categories"})["query"]["pages"]
        categories = next(iter(result.values())).get("categories", [])
        if "Category:" + category not in {row["title"] for row in categories}:
            raise RuntimeError("Imported category membership is missing.")
    for title in ("Thorns of Wackah", "Nightmare"):
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        parsed = RenderedGrids()
        parsed.feed(rendered)
        if not parsed.grids:
            raise RuntimeError("MediaWiki did not render the cell grid.")
        rows = parsed.grids[0]
        if title == "Thorns of Wackah":
            if len(rows) != 4 or any(len(row) != 2 for row in rows):
                raise RuntimeError("Thorns attack grid orientation changed.")
            if any(cell["text"].strip() != "1-4" for row in rows for cell in row):
                raise RuntimeError("Thorns attack cells lost their per-cell ranges.")
        else:
            holes = {(y, x) for y, row in enumerate(rows) for x, cell in enumerate(row)
                     if "grid-hole" in cell["attrs"].get("class", "")}
            if len(rows) != 7 or any(len(row) != 3 for row in rows) or holes != {(y, 2 if y % 2 == 0 else 0) for y in range(7)}:
                raise RuntimeError("Nightmare base-health shape lost its alternating holes.")
        for row in rows:
            for cell in row:
                if not cell["attrs"].get("aria-label", "").startswith("Row "):
                    raise RuntimeError("Grid cell accessibility labels were stripped.")
                if "grid-cell" in cell["attrs"].get("class", "") and "background" not in cell["attrs"].get("style", ""):
                    raise RuntimeError("Grid cell styling was stripped.")
                if cell["images"]:
                    raise RuntimeError("An unarmored health cell, attack cell or hole gained a shield.")
    locations = page_locations(data, catalog)
    seen_armor = set()
    for title in ("Scaal", "Sceetler"):
        grid = next(grid for grid in details["grids"] if grid["kind"] == "health" and locations[grid["entity"]] == title)
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        parsed = RenderedGrids()
        parsed.feed(rendered)
        if not parsed.grids or [len(row) for row in parsed.grids[0]] != [len(row) for row in grid["rows"]]:
            raise RuntimeError("An armored health grid changed its dimensions.")
        for y, (expected_row, row) in enumerate(zip(grid["rows"], parsed.grids[0]), 1):
            for x, (expected, cell) in enumerate(zip(expected_row, row), 1):
                position = f"Row {y}, column {x}: "
                attrs = cell["attrs"]
                if expected is None:
                    if (attrs.get("aria-label") != position + "empty" or cell["images"] or cell["text"].strip()
                            or "grid-hole" not in attrs.get("class", "").split()):
                        raise RuntimeError("A health-grid hole gained content or lost its coordinates.")
                    continue
                armor = expected["armor"]
                description = position + f"1 HP, {armor} armor layers"
                if attrs.get("aria-label") != description or "grid-cell" not in attrs.get("class", "").split():
                    raise RuntimeError("A shield changed the underlying one-HP cell semantics.")
                style = attrs.get("style", "").replace(" ", "")
                if not all(part in style for part in ("min-width:3em", "height:3em", "padding:0.25em", "background:#852c36")):
                    raise RuntimeError("A shield changed cell dimensions or retained the old brown fill.")
                if armor:
                    if attrs.get("title") != description or cell["text"].strip():
                        raise RuntimeError("A shield lost its cell tooltip or retained duplicate visible labels.")
                    check_shield_icon(cell["images"], cell["links"], cell["icon_styles"], armor)
                    seen_armor.add(armor)
                elif cell["images"] or cell["text"].strip() != "1 HP":
                    raise RuntimeError("An unarmored health cell changed.")
    if seen_armor != {1, 2, 3}:
        raise RuntimeError("The armored-cell smoke fixtures did not exercise all three shield levels.")
    guide = api({"action": "parse", "page": "Health and armor", "prop": "text|images"})["parse"]
    if set(guide["images"]) != {f"Health-armor-{armor}.png" for armor in (1, 2, 3)}:
        raise RuntimeError("The shield legend did not resolve exactly the three reviewed File references.")
    legend = RenderedGrids()
    legend.feed(guide["text"]["*"])
    if len(legend.images) != 3 or len(legend.icon_styles) != 3 or "Shield legend" not in guide["text"]["*"]:
        raise RuntimeError("The guide lost its compact three-shield legend.")
    for armor in (1, 2, 3):
        filename = f"Health-armor-{armor}.png"
        links = [link for link in legend.links if "File:" + filename in urllib.parse.unquote(link.get("href", ""))]
        check_shield_icon([legend.images[armor - 1]], links, [legend.icon_styles[armor - 1]], armor)
    for title, expected in (
        ("Survivor's Field Kit", "2 gold"), ("Gurb-Gurb", "2 gold"),
        ("Fine Wool Socks", "50%"), ("Steel Hand Axe", "AP"),
    ):
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        if expected not in rendered:
            raise RuntimeError("Reader-facing coin, percentage or AP formatting did not survive parsing.")
    for title in ("Poison", "Sharp", "Blunt", "Force", "Piercing", "Fire", "Weak", "Action points"):
        if title not in pages:
            raise RuntimeError("A required canonical guide is missing.")


def wait_for_server_tick(api):
    # MediaWiki invalidates only when cache time < page_touched, both whole seconds.
    query = {"action": "query", "curtimestamp": 1}
    before = api(query)["curtimestamp"]
    for _ in range(20):
        time.sleep(0.1)
        if api(query)["curtimestamp"] > before:
            return
    raise RuntimeError("The wiki server clock did not advance before the synthetic edit.")


def check_parser_errors(rendered):
    if re.search(r'class="[^"]*\berror\b|Template loop detected|[Ee]xpansion[^<]*exceeded|[Ii]nclude size[^<]*exceeded', rendered):
        raise RuntimeError("A canonical view produced a MediaWiki parser error or expansion limit.")


class RecipeRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current = {"entries": set(), "text": ""}
        elif self.current is not None:
            identity = dict(attrs).get("id", "")
            if identity.startswith("entry-recipe-"):
                self.current["entries"].add(identity.removeprefix("entry-"))

    def handle_endtag(self, tag):
        if tag == "tr" and self.current is not None:
            if self.current["entries"]:
                self.rows.append(self.current)
            self.current = None

    def handle_data(self, value):
        if self.current is not None:
            self.current["text"] += value


def smoke_canonical_views(run, api, pages, data, catalog, token):
    locations = page_locations(data, catalog)
    owners = entry_owners(data, locations, entry_relations(data, catalog), catalog)
    recipes = [display_entry(entry, catalog) for entry in data["entries"] if entry["kind"] == "recipe"]
    groups = recipe_groups(recipes)
    for station in catalog["stations"]:
        rendered = api({"action": "parse", "page": station["title"], "prop": "text"})["parse"]["text"]["*"]
        check_parser_errors(rendered)
        parsed = RecipeRows()
        parsed.feed(rendered)
        expected = [group for group in groups if any(entry["details"]["station"] in station["methods"] for entry in group)]
        # Item workstations also retain the recipe used to make the workstation itself.
        expected += [group for group in groups if owners[group[0]["id"]] == station["title"]
                     and not any(entry["details"]["station"] in station["methods"] for entry in group)]
        if {frozenset(row["entries"]) for row in parsed.rows} != {
            frozenset(entry["id"] for entry in group) for group in expected
        } or len(parsed.rows) != len(expected):
            raise RuntimeError(f"{station['title']} lost a recipe variant, added a foreign row, or duplicated a row.")
        for row in parsed.rows:
            entry = next(entry for entry in recipes if entry["id"] in row["entries"])
            if entry["details"]["cost"] is not None and "AP" not in row["text"]:
                raise RuntimeError("A workstation recipe lost its action-point cost.")
    price_owners = {locations[entry["details"]["item"]] for entry in data["entries"] if entry["kind"] == "merchant"}
    default_text = "\n".join("<div>{{:" + title + "}}</div>" for title in sorted(price_owners))
    rendered = api({"action": "parse", "title": "Synthetic default views", "text": default_text, "prop": "text"}, post=True)["parse"]["text"]["*"]
    check_parser_errors(rendered)
    if re.search(r'id="(?:entity-|entry-|profile-|Recipes|How_to_acquire)', rendered) or "Ingredients" in rendered:
        raise RuntimeError("A default price view leaked owner content, a recipe, or merchant availability.")
    for title in price_owners:
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        check_parser_errors(rendered)
        if 'id="How_to_acquire"' not in rendered or 'id="entity-' not in rendered:
            raise RuntimeError("A normal item article lost its acquisition section or identity.")
    for merchant in {owners[entry["id"]] for entry in data["entries"] if entry["kind"] == "merchant"}:
        offered = [entry for entry in data["entries"] if entry["kind"] == "merchant" and owners[entry["id"]] == merchant]
        entry = offered[0]
        text = "{{:" + merchant + "|view=offers|item=" + entry["details"]["item"] + "}}"
        result = api({"action": "parse", "title": "Synthetic seller view", "text": text, "prop": "text|templates"}, post=True)["parse"]
        rendered = result["text"]["*"]
        check_parser_errors(rendered)
        wanted = {row["id"] for row in offered if row["details"]["item"] == entry["details"]["item"]}
        if set(re.findall(r'id="entry-(merchant-[^"]+)"', rendered)) != wanted:
            raise RuntimeError("An item seller view leaked another item's stock or omitted an offer.")
        if {row["*"] for row in result.get("templates", [])} != {merchant} or "Unit price" in rendered:
            raise RuntimeError("A seller view recursively transcluded item prices.")
    for owner in {owners[entry["id"]] for entry in data["entries"] if entry["kind"] == "loot"}:
        loot = [entry for entry in data["entries"] if entry["kind"] == "loot"
                and owners[entry["id"]] == owner and entry["details"]["outcome"] is not None]
        if not loot:
            continue
        item = loot[0]["details"]["outcome"]
        text = "{{:" + owner + "|view=loot|item=" + item + "}}"
        rendered = api({"action": "parse", "title": "Synthetic loot view", "text": text, "prop": "text"}, post=True)["parse"]["text"]["*"]
        check_parser_errors(rendered)
        expected = {entry["id"] for entry in loot if entry["details"]["outcome"] == item}
        found = set(re.findall(r'id="entry-([^"]+)"', rendered))
        if found != expected or 'id="entity-' in rendered or "Conditional probability" not in rendered:
            raise RuntimeError("A loot view lost its exact outcome rows or leaked the source article.")
    fixture = next(group for group in groups if locations[group[0]["details"]["outputs"][0]["item"]] == "Simple Burn Remedy" and len(group) > 1)
    owner = owners[fixture[0]["id"]]
    targets = {station["title"] for station in catalog["stations"] if any(
        entry["details"]["station"] in station["methods"] for entry in fixture)}
    original = pages[owner]
    block = next(block for block in re.findall(r"<onlyinclude>.*?</onlyinclude>", original, re.DOTALL)
                 if f'id="entry-{fixture[0]["id"]}"' in block)
    changed = original
    for before, after, expected in (
        (" x <nowiki>1</nowiki>", " x <nowiki>701</nowiki>", "701"),
        ("<nowiki>2.4</nowiki> base", "<nowiki>997</nowiki> base", "997"),
    ):
        replacement = block.replace(before, after, 1)
        if replacement == block:
            raise RuntimeError("The synthetic recipe edit missed its canonical value.")
        changed = changed.replace(block, replacement, 1)
        for target in targets:
            api({"action": "parse", "page": target, "prop": "text"})
        wait_for_server_tick(api)
        edit = api({"action": "edit", "title": owner, "text": changed, "token": token}, post=True)
        if edit.get("edit", {}).get("result") != "Success":
            raise RuntimeError("The canonical recipe edit failed.")
        for target in targets:
            rendered = refreshed_transclusion(run, api, target, expected, 'id="entity-item-141"', owner)
            check_parser_errors(rendered)
            parsed = RecipeRows()
            parsed.feed(rendered)
            if not any(fixture[0]["id"] in row["entries"] and expected in row["text"] for row in parsed.rows):
                raise RuntimeError("The changed recipe value did not reach its exact station row.")
        rendered = api({"action": "parse", "page": owner, "prop": "text"})["parse"]["text"]["*"]
        check_parser_errors(rendered)
        if expected not in rendered or 'id="entity-item-141"' not in rendered:
            raise RuntimeError("A selective recipe edit broke the normal owner article.")
        block = replacement
    print("Named views passed: every workstation variant, default prices, filtered sellers/loot, separate quantity/AP edits.")


def refreshed_transclusion(run, api, title, expected, forbidden_anchor, owner=None):
    # Imports and edits enqueue deferred link updates; allow their bounded completion.
    for attempt in range(10):
        run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "runJobs", "--maxjobs", "1000")
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        check_parser_errors(rendered)
        if forbidden_anchor in rendered:
            raise RuntimeError("Selective transclusion leaked the full owner article.")
        if expected in rendered:
            return rendered
        if attempt < 9:
            time.sleep(2)
    if owner:
        cache_diagnostics(api, title, owner, rendered)
        print("Remaining jobs:", run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "showJobs").decode(), flush=True)
    raise RuntimeError(f"The {title} view did not refresh its owner value after ten job-drain checks.")


def cache_diagnostics(api, title, owner, rendered):
    state = api({"action": "query", "titles": title + "|" + owner, "prop": "info|revisions",
                 "rvprop": "ids|timestamp", "curtimestamp": 1})
    print("Transclusion timestamps:", json.dumps({
        "server": state["curtimestamp"],
        "cached": re.findall(r"(?:Cached time:|timestamp)\s*(\d{14})", rendered),
        "pages": [{key: page[key] for key in ("title", "touched", "lastrevid", "revisions")}
                  for page in state["query"]["pages"].values()],
    }), flush=True)


def smoke_images(run, api, base, data, catalog):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    signature = b"\x89PNG\r\n\x1a\n"
    # Original solid-color RGB/RGBA pixels, not game artwork or a committed fixture.
    specs = {"Synthetic-thumbnail.png": (64, 32, bytes((37, 149, 211)), 16)}
    specs.update({f"Health-armor-{armor}.png": (64, 64, bytes((40 * armor, 149, 211, 128)), 32)
                  for armor in (1, 2, 3)})
    contextual = sorted({image_for(guide["image_entity"], data["illustrations"])["file_title"].removeprefix("File:")
                         for guide in catalog["guides"] if "image_entity" in guide})
    contextual += [image_for(identity, data["illustrations"])["file_title"].removeprefix("File:")
                   for identity in ("nature-4", "nature-7", "nature-17")]
    specs.update({filename: (64, 64, bytes((130 + index, 91, 73, 255)), 32)
                  for index, filename in enumerate(contextual)})
    for identity, (width, height) in {
        "nature-4": (588, 564), "nature-7": (684, 912), "nature-17": (340, 540),
    }.items():
        filename = image_for(identity, data["illustrations"])["file_title"].removeprefix("File:")
        specs[filename] = (width, height, specs[filename][2], 32)
    specs.update({f"Nature-{number}.png": (64, 64, bytes((200 + number, 40, 70, 255)), 32)
                  for number in (4, 7, 17)})
    originals = {}
    run("exec", "-T", "--user", "www-data", "mirklurk", "mkdir", "/tmp/mirklurk-smoke-images")
    for filename, (width, height, pixel, _) in specs.items():
        original = (signature
                    + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6 if len(pixel) == 4 else 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress((b"\0" + pixel * width) * height))
                    + chunk(b"IEND", b""))
        originals[filename] = original
        run(
            "exec", "-T", "--user", "www-data", "mirklurk", "php", "-r",
            "$image = stream_get_contents(STDIN); "
            f"if (file_put_contents('/tmp/mirklurk-smoke-images/{filename}', $image) !== strlen($image)) "
            "{ throw new RuntimeException('Synthetic PNG staging failed.'); }",
            input_bytes=original,
        )
    imported = run(
        "exec", "-T", "--user", "www-data", "mirklurk", "php", "maintenance/run.php",
        "importImages", "/tmp/mirklurk-smoke-images", "--extensions", "png",
        "--user", "WikiAdmin", "--skip-dupes",
        "--comment", "Original synthetic solid-color PNG generated only for this disposable test.",
    )
    if f"Added: {len(specs)}".encode() not in imported.splitlines() or any(
        line.startswith((b"Failed:", b"Skipped:", b"Overwritten:")) for line in imported.splitlines()
    ):
        raise RuntimeError("The synthetic CLI image import did not add the exact fixture set.")
    for filename, (width, height, pixel, thumbwidth) in specs.items():
        thumbheight = (2 * height * thumbwidth + width) // (2 * width)
        result = api({
            "action": "query", "titles": "File:" + filename, "prop": "imageinfo",
            "iiprop": "url|size|mime", "iiurlwidth": thumbwidth,
        })
        page = next(iter(result["query"]["pages"].values()))
        info = page.get("imageinfo", [{}])[0]
        if info.get("mime") != "image/png" or (info.get("width"), info.get("height")) != (width, height):
            raise RuntimeError("The CLI-imported synthetic PNG is missing or has incorrect dimensions.")
        if (info.get("thumbwidth"), info.get("thumbheight")) != (thumbwidth, thumbheight):
            raise RuntimeError("MediaWiki did not generate the requested thumbnail dimensions.")
        thumbnail_url = info.get("thumburl")
        if not thumbnail_url or thumbnail_url == info["url"]:
            raise RuntimeError("The thumbnail URL is missing or falls back to the original image.")
        for url, expected_size in ((info["url"], (width, height)), (thumbnail_url, (thumbwidth, thumbheight))):
            if urllib.parse.urlsplit(url)[:2] != urllib.parse.urlsplit(base)[:2]:
                raise RuntimeError("The synthetic image URL points outside the disposable wiki.")
            # A fresh opener proves anonymous HTTP access, independent of the API session.
            with urllib.request.urlopen(url, timeout=30) as response:
                if response.status != 200 or response.headers.get_content_type() != "image/png":
                    raise RuntimeError("The synthetic image could not be read as a PNG over HTTP.")
                body = response.read()
            if len(body) < 24 or body[:8] != signature or body[12:16] != b"IHDR":
                raise RuntimeError("The served image is not a PNG with a dimension header.")
            if struct.unpack(">II", body[16:24]) != expected_size:
                raise RuntimeError("The served image dimensions differ from the requested size.")
            if expected_size == (width, height) and body != originals[filename]:
                raise RuntimeError("The served original differs from the synthetic imported bytes.")
            decoded = run(
                "exec", "-T", "--user", "www-data", "mirklurk", "/usr/bin/convert",
                "png:-", "-depth", "8", "rgba:-" if len(pixel) == 4 else "rgb:-", input_bytes=body,
            )
            if decoded != pixel * (expected_size[0] * expected_size[1]):
                raise RuntimeError("The served PNG did not decode to the expected resized pixels and alpha.")
    print("Synthetic CLI import and anonymous decoded PNG reads passed: thumbnail, shields and contextual guide images.")
    return {filename: hashlib.sha256(payload).hexdigest() for filename, payload in originals.items()}


def smoke():
    project = "mirklurk-smoke-" + secrets.token_hex(6)
    with tempfile.TemporaryDirectory(prefix="mirklurk-smoke-") as folder:
        workspace = Path(folder)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        environment = dict(os.environ, MIRKLURK_SECRETS_DIR=folder, MIRKLURK_DEV_PORT=str(port), MW_READ_ONLY="")
        for name in ("DB_PASSWORD", "DB_ROOT_PASSWORD", "SECRET_KEY", "UPGRADE_KEY", "ADMIN_PASSWORD"):
            destination = workspace / ("MIRKLURK_" + name)
            destination.write_text(secrets.token_hex(40), encoding="utf-8")
            destination.chmod(0o444)
        question = "Type the temporary test word."
        questions = workspace / "MIRKLURK_CAPTCHA_QUESTIONS"
        questions.write_text(json.dumps({question: [secrets.token_hex(8)]}), encoding="utf-8")
        questions.chmod(0o444)
        compose = ["docker", "compose", "--project-name", project, "--file", str(ROOT / "deploy" / "compose.dev.yml")]

        def run(*args, input_bytes=None):
            return subprocess.run(
                [*compose, *args], cwd=ROOT, env=environment, input=input_bytes,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            ).stdout

        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        base = f"http://localhost:{port}"

        def api(parameters, post=False, expected_error=None):
            encoded = urllib.parse.urlencode(dict(format="json", **parameters)).encode()
            url = base + "/api.php" + ("" if post else "?" + encoded.decode())
            with opener.open(url, data=encoded if post else None, timeout=30) as response:
                value = json.load(response)
            if expected_error is not None:
                if value.get("error", {}).get("code") != expected_error:
                    raise RuntimeError(f"API request did not fail with the expected {expected_error} error.")
            elif "error" in value:
                raise RuntimeError(f"API request failed: {value['error'].get('code', 'unknown')}")
            return value

        try:
            run("config", "--quiet")
            run("build", "--pull")
            run("up", "-d", "--wait", "mirklurk-db")
            password_file = workspace / "MIRKLURK_ADMIN_PASSWORD"
            install = (
                "run", "--rm", "--no-deps", "--volume",
                f"{password_file}:/run/secrets/MIRKLURK_ADMIN_PASSWORD:ro",
                "mirklurk", "php", "/usr/local/lib/mirklurk/install.php",
                "--admin", "WikiAdmin", "--password-file", "/run/secrets/MIRKLURK_ADMIN_PASSWORD",
            )
            run(*install)
            try:
                run(*install)
            except subprocess.CalledProcessError:
                pass
            else:
                raise RuntimeError("Installer did not refuse the already populated database.")
            run("up", "-d", "--wait", "mirklurk")
            try:
                image_help = run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "importImages", "--help")
            except subprocess.CalledProcessError as error:
                if error.returncode != 1:
                    raise
                # MediaWiki 1.43's maintenance help deliberately exits with status 1.
                image_help = error.stdout + error.stderr
            if not all(flag in image_help for flag in (
                b"Usage: php maintenance/run.php importImages", b"--dry", b"--comment-ext", b"--skip-dupes",
            )):
                raise RuntimeError("The pinned image does not expose the documented operator image-import options.")
            rights = api({"action": "query", "meta": "userinfo", "uiprop": "rights"})["query"]["userinfo"]["rights"]
            if not {"read", "createaccount"} <= set(rights) or "edit" in rights:
                raise RuntimeError("Anonymous permissions violate the public-read/account-edit policy.")
            general = api({"action": "query", "meta": "siteinfo", "siprop": "general"})["query"]["general"]
            if "uploadsenabled" in general:
                raise RuntimeError("Web uploads are unexpectedly enabled.")
            data, catalog, details = load_publication_inputs(ROOT)
            image_hashes = smoke_images(run, api, base, data, catalog)
            with opener.open(base + "/index.php?title=Special:CreateAccount", timeout=30) as response:
                registration = response.read().decode()
            if 'name="captchaWord"' not in registration or question not in registration:
                raise RuntimeError("Open registration did not render the configured CAPTCHA.")
            requests = api({
                "action": "query", "meta": "authmanagerinfo", "amirequestsfor": "create",
            })["query"]["authmanagerinfo"]["requests"]
            captcha = next((request for request in requests if request["id"] == "CaptchaAuthenticationRequest"), None)
            if captcha is None:
                raise RuntimeError("The account-creation API did not require a CAPTCHA.")
            create_token = api({
                "action": "query", "meta": "tokens", "type": "createaccount",
            })["query"]["tokens"]["createaccounttoken"]
            editor_password = secrets.token_hex(24)
            creation = api({
                "action": "createaccount", "username": "TestEditor",
                "password": editor_password, "retype": editor_password,
                "createreturnurl": base, "createtoken": create_token,
                "captchaId": captcha["fields"]["captchaId"]["value"],
                "captchaWord": json.loads(questions.read_text(encoding="utf-8"))[question][0],
            }, post=True)
            if creation.get("createaccount", {}).get("status") != "PASS":
                raise RuntimeError("Open self-registration with the configured CAPTCHA failed.")
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            token = api({"action": "query", "meta": "tokens", "type": "login"})["query"]["tokens"]["logintoken"]
            login = api({
                "action": "login", "lgname": "WikiAdmin",
                "lgpassword": password_file.read_text(encoding="utf-8"), "lgtoken": token,
            }, post=True)
            if login.get("login", {}).get("result") != "Success":
                raise RuntimeError("The freshly created administrator cannot log in.")
            csrf = api({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
            api({
                "action": "upload", "filename": "Web-upload-must-stay-disabled.png", "token": csrf,
            }, post=True, expected_error="uploaddisabled")
            pages = build_pages(ROOT, data, catalog, details)
            edit = api({"action": "edit", "title": "Main Page", "text": pages["Main Page"], "token": csrf}, post=True)
            if edit.get("edit", {}).get("result") != "Success":
                raise RuntimeError("Authenticated editing failed.")

            current = workspace / "current.xml"
            current.write_bytes(run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "dumpBackup", "--current"))
            excluded = existing_titles(current)
            missing = {title: text for title, text in pages.items() if title_key(title) not in excluded}
            run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "importDump", input_bytes=build_xml(missing))
            indexed = []
            for namespace in (0, 14):
                indexed.extend(api({"action": "query", "list": "allpages", "apnamespace": namespace,
                                    "aplimit": "max"})["query"]["allpages"])
            if set(pages) != {page["title"] for page in indexed}:
                raise RuntimeError("Imported page titles differ from the deterministic bundle.")
            run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "runJobs", "--maxjobs", "1000")
            smoke_reader_release(api, pages, data, catalog, details, image_hashes)
            smoke_canonical_views(run, api, pages, data, catalog, csrf)
            for title, expected_links in {
                "Items": {"Wood Buckler", "Turnip (item)"},
                "NPCs": {"Captain Eir", "Magus Clay", "Ranger Bhato"},
                "Nature": {"Turnip (nature)"},
                "Skills": {"Strider", "Focused Mind"},
            }.items():
                parsed_links = api({"action": "parse", "page": title, "prop": "links"})["parse"]["links"]
                if not expected_links <= {link["*"] for link in parsed_links if link["ns"] == 0}:
                    raise RuntimeError("MediaWiki did not resolve the encyclopedia's canonical entity links.")
            redirect = api({"action": "query", "titles": "Getting started", "redirects": "1"})["query"].get("redirects", [])
            if not any(row["from"] == "Getting started" and row["to"] == "Research policy" for row in redirect):
                raise RuntimeError("The reviewed guidance compatibility redirect was not imported correctly.")
            for title, anchor in {"Strider": "entry-skill-0-0-mechanics", "Ranger Bhato": "entity-being-12"}.items():
                rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
                if f'id="{anchor}"' not in rendered:
                    raise RuntimeError("MediaWiki did not render the entity page's primary record anchor.")
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            token = api({"action": "query", "meta": "tokens", "type": "login"})["query"]["tokens"]["logintoken"]
            login = api({
                "action": "login", "lgname": "TestEditor", "lgpassword": editor_password, "lgtoken": token,
            }, post=True)
            if login.get("login", {}).get("result") != "Success":
                raise RuntimeError("A self-registered editor cannot log in.")
            editor = api({"action": "query", "meta": "userinfo", "uiprop": "rights|groups"})["query"]["userinfo"]
            if "edit" not in editor["rights"] or "sysop" in editor["groups"]:
                raise RuntimeError("The ordinary registered-editor permissions are incorrect.")
            csrf = api({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
            price_title = "Longbow (Cypress)"
            original_item = pages[price_title]
            price_blocks = [block for block in re.findall(r"<onlyinclude>.*?</onlyinclude>", original_item, re.DOTALL)
                            if "|page|price|=" in block]
            if len(price_blocks) != 1:
                raise RuntimeError("The item does not expose exactly one canonical price view.")
            cached_merchant = api({"action": "parse", "page": "Ranger Bhato", "prop": "text"})["parse"]["text"]["*"]
            if "111.23 silver" in cached_merchant or 'id="entity-item-105"' in cached_merchant:
                raise RuntimeError("The merchant price-edit precondition is invalid.")
            cache_diagnostics(api, "Ranger Bhato", price_title, cached_merchant)
            updated_item = original_item.replace(price_blocks[0], selective_view("111.23 silver", "price", True), 1)
            wait_for_server_tick(api)
            price_edit = api({"action": "edit", "title": price_title, "text": updated_item, "token": csrf}, post=True)
            if price_edit.get("edit", {}).get("result") != "Success":
                raise RuntimeError("A registered editor cannot update the canonical item price.")
            print("Owner edit timestamp:", price_edit["edit"]["newtimestamp"], flush=True)
            sellers = {page_locations(data, catalog)[entry["details"]["merchant"]] for entry in data["entries"]
                       if entry["kind"] == "merchant" and page_locations(data, catalog)[entry["details"]["item"]] == price_title}
            for seller in sellers:
                refreshed_transclusion(run, api, seller, "111.23 silver", 'id="entity-item-105"', price_title)
            item_html = api({"action": "parse", "page": price_title, "prop": "text"})["parse"]["text"]["*"]
            if "111.23 silver" not in item_html or 'id="entity-item-105"' not in item_html or 'id="Stats"' not in item_html:
                raise RuntimeError("Selective price transclusion removed the item's normal full article.")
            coin_title = "Copper Coin"
            coin_text = pages[coin_title].replace("<nowiki>25</nowiki> g", "<nowiki>26</nowiki> g")
            if coin_text == pages[coin_title]:
                raise RuntimeError("The synthetic coin-weight edit did not target its canonical value.")
            cached_currency = api({"action": "parse", "page": "Currency and trading", "prop": "text"})["parse"]["text"]["*"]
            if "25 g" not in cached_currency or 'id="entity-item-72"' in cached_currency:
                raise RuntimeError("The coin-weight edit precondition is invalid.")
            cache_diagnostics(api, "Currency and trading", coin_title, cached_currency)
            wait_for_server_tick(api)
            coin_edit = api({"action": "edit", "title": coin_title, "text": coin_text, "token": csrf}, post=True)
            if coin_edit.get("edit", {}).get("result") != "Success":
                raise RuntimeError("A registered editor cannot update a coin-owned weight.")
            print("Owner edit timestamp:", coin_edit["edit"]["newtimestamp"], flush=True)
            refreshed_transclusion(run, api, "Currency and trading", "26 g", 'id="entity-item-72"', coin_title)
            api({
                "action": "upload", "filename": "Web-upload-must-stay-disabled.png", "token": csrf,
            }, post=True, expected_error="uploaddisabled")
            preserved = "Original live edit for the disposable integration test."
            edit = api({"action": "edit", "title": "Game mechanics", "text": preserved, "token": csrf}, post=True)
            if edit.get("edit", {}).get("result") != "Success":
                raise RuntimeError("An ordinary self-registered editor cannot save a page.")
            current.write_bytes(run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "dumpBackup", "--current"))
            excluded = existing_titles(current)
            missing = {title: text for title, text in pages.items() if title_key(title) not in excluded}
            if missing:
                raise RuntimeError("Additive reimport unexpectedly includes an existing title.")
            run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "importDump", input_bytes=build_xml(missing))
            parsed = api({"action": "parse", "page": "Game mechanics", "prop": "wikitext"})
            if parsed["parse"]["wikitext"]["*"] != preserved:
                raise RuntimeError("Additive reimport changed a live edit.")
            print(
                "Disposable Docker smoke passed: install, health, access policy, CAPTCHA, seed, "
                "edit preservation, CLI image import, resized thumbnail, web uploads disabled."
            )
        except subprocess.CalledProcessError as error:
            # The child only receives mounted secret paths, never literal secrets in argv.
            sys.stderr.write(error.stdout.decode(errors="replace"))
            sys.stderr.write(error.stderr.decode(errors="replace"))
            raise
        finally:
            run("down", "--volumes", "--remove-orphans")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, action="store_true", help="Create and remove test-only Docker resources")
    parser.parse_args()
    smoke()


if __name__ == "__main__":
    main()
