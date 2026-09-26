"""Opt-in Docker integration test in an isolated, disposable Compose project."""

import argparse
import hashlib
import http.cookiejar
import io
import json
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from build_wiki import build_pages, build_xml, existing_titles, title_key
from wiki_catalog import entry_owners, entry_relations, page_locations
from wiki_details import load_publication_inputs
from wiki_render import display_entry, image_for, literal, recipe_groups
from wiki_views import selective_view


ROOT = Path(__file__).resolve().parents[1]
MATURE_TREES = {
    "nature-4": (588, 564), "nature-7": (684, 912), "nature-17": (340, 540), "nature-20": (256, 256),
}


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


def smoke_category_memberships(api, pages):
    expected = {
        title: {title_key(target) for target in re.findall(r"\[\[(Category:[^\]|]+)(?:\|[^\]]*)?\]\]", text)}
        for title, text in pages.items()
    }
    titles = sorted(expected)
    for start in range(0, len(titles), 50):
        batch = titles[start:start + 50]
        actual = {title: set() for title in batch}
        seen = set()
        continuation = {}
        tokens = set()
        for _ in range(100):
            result = api({
                "action": "query", "titles": "|".join(batch), "prop": "categories", "cllimit": "max",
                **continuation,
            })
            for row in result["query"]["pages"].values():
                title = title_key(row["title"])
                namespace = 14 if title.startswith("Category:") else 0
                if title not in actual or "missing" in row or "invalid" in row or row["ns"] != namespace:
                    raise RuntimeError(f"Category query returned a missing, unexpected or wrong-namespace page: {title}")
                seen.add(title)
                for category in row.get("categories", []):
                    if category["ns"] != 14:
                        raise RuntimeError(f"Category query returned a non-category membership for {title}.")
                    actual[title].add(title_key(category["title"]))
            if "continue" not in result:
                break
            continuation = result["continue"]
            if (not isinstance(continuation, dict) or "clcontinue" not in continuation
                    or not set(continuation) <= {"continue", "clcontinue"}
                    or not all(isinstance(value, str) for value in continuation.values())):
                raise RuntimeError("Category query returned invalid continuation parameters.")
            token = tuple(sorted(continuation.items()))
            if token in tokens:
                raise RuntimeError("Category query repeated its continuation token.")
            tokens.add(token)
        else:
            raise RuntimeError("Category query exceeded its 100-response continuation bound.")
        if seen != set(batch):
            raise RuntimeError(f"Category query omitted generated pages: {sorted(set(batch) - seen)}")
        for title in batch:
            if actual[title] != expected[title]:
                raise RuntimeError(
                    f"Category membership mismatch for {title}: "
                    f"missing={sorted(expected[title] - actual[title])}, extra={sorted(actual[title] - expected[title])}"
                )
    for title in titles:
        if title != "Skills" and not title.startswith("Category:"):
            continue
        targets = {title_key(target) for target in re.findall(r"\[\[:(Category:[^\]|]+)(?:\|[^\]]*)?\]\]", pages[title])} - {title}
        if not targets <= set(pages):
            raise RuntimeError(f"Category browse links on {title} target pages outside the generated release.")
        parsed = api({"action": "parse", "page": title, "prop": "links"})["parse"]
        resolved = {title_key(link["*"]) for link in parsed["links"] if link["ns"] == 14 and "exists" in link}
        if not targets <= resolved:
            raise RuntimeError(f"Category browse links did not resolve on {title}: {sorted(targets - resolved)}")


def smoke_reader_release(api, pages, data, catalog, details, image_hashes):
    smoke_category_memberships(api, pages)
    locations = page_locations(data, catalog)
    for identity in MATURE_TREES:
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
    for guide in [*catalog["guides"], *catalog.get("acquisition", {}).get("sources", [])]:
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


def wait_for_server_tick(api, minimum=None):
    # MediaWiki invalidates only when cache time < page_touched, both whole seconds.
    query = {"action": "query", "curtimestamp": 1}
    before = api(query)["curtimestamp"]
    if minimum is not None and before < minimum:
        raise RuntimeError("The wiki server clock moved backwards across the recorded cache boundary.")
    for _ in range(20):
        time.sleep(0.1)
        after = api(query)["curtimestamp"]
        if after < before:
            raise RuntimeError("The wiki server clock moved backwards while waiting for its boundary.")
        if after > before:
            return {"before": before, "after": after}
    raise RuntimeError("The wiki server clock did not advance before the operation.")


def bounded_maintenance(run, arguments, timeout):
    if timeout <= 2:
        raise TimeoutError("Insufficient remaining maintenance budget.")
    try:
        return run("exec", "-T", "mirklurk", "timeout", "--kill-after=1s", f"{timeout - 2:.3f}s",
                   "php", "maintenance/run.php", *arguments, timeout=timeout)
    except subprocess.CalledProcessError as error:
        if error.returncode in {124, 137}:
            raise TimeoutError("The bounded maintenance command exhausted its budget.") from error
        raise


def drain_jobs_bounded(run, timeout=90):
    deadline = time.monotonic() + timeout
    output = bounded_maintenance(run, ("runJobs", "--maxjobs", "1000"), deadline - time.monotonic())
    remaining = bounded_maintenance(run, ("showJobs",), deadline - time.monotonic())
    return {"command": "maintenance/run.php runJobs --maxjobs 1000",
            "budget_seconds": timeout, "output_tail": output.decode(errors="replace")[-2000:],
            "remaining_jobs": remaining.decode(errors="replace").strip()}


def check_parser_errors(rendered):
    match = re.search(r'class="[^"]*\berror\b|Template loop detected|[Ee]xpansion[^<]*exceeded|[Ii]nclude size[^<]*exceeded|mw-broken-media|typeof="[^"]*mw:Error[^"]*mw:File', rendered)
    if match:
        raise RuntimeError("A canonical view produced a MediaWiki parser error, expansion limit, or missing image: "
                           + rendered[max(0, match.start() - 120):match.end() + 400])


class RenderedRows(HTMLParser):
    def __init__(self, prefix="entry-recipe-", strip_prefix="entry-", page_title=None):
        super().__init__()
        self.prefix = prefix
        self.strip_prefix = strip_prefix
        self.rows = []
        self.text = ""
        self.current = None
        self.cell = None
        self.link = None
        self.link_tag = None
        self.page_title = page_title

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.current = {"entries": set(), "text": "", "cells": []}
        elif self.current is not None:
            identity = attrs.get("id", "")
            if identity.startswith(self.prefix):
                self.current["entries"].add(identity.removeprefix(self.strip_prefix))
            if tag in {"td", "th"}:
                self.cell = {"text": "", "links": []}
                self.current["cells"].append(self.cell)
            elif tag == "br":
                self.handle_data(" ")
            elif self.cell is not None and (tag == "a" or "selflink" in attrs.get("class", "")):
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(attrs.get("href", "")).query)
                if query.get("title"):
                    attrs["title"] = query["title"][0].replace("_", " ")
                if "selflink" in attrs.get("class", "") or attrs.get("href", "").startswith("#"):
                    attrs.setdefault("title", self.page_title)
                self.link = {"attrs": attrs, "text": ""}
                self.link_tag = tag
                self.cell["links"].append(self.link)

    def handle_endtag(self, tag):
        if tag == self.link_tag:
            self.link = self.link_tag = None
        if tag in {"td", "th"}:
            self.cell = None
        if tag == "tr" and self.current is not None:
            if self.current["entries"]:
                self.rows.append(self.current)
            self.current = None

    def handle_data(self, value):
        self.text += value
        if self.current is not None:
            self.current["text"] += value
        if self.cell is not None:
            self.cell["text"] += value
        if self.link is not None:
            self.link["text"] += value


def plain(value):
    return " ".join(value.split())


def scalar(value):
    if value is None:
        return "Not established"
    if isinstance(value, (int, float, Decimal)):
        return format(Decimal(str(value)).normalize(), "f")
    return str(value)


def interval(value):
    return "Not established" if value is None else (
        str(value["min"]) if value["min"] == value["max"] else f'{value["min"]} to {value["max"]}')


def item_links(cell, locations):
    return [link["attrs"].get("title") for link in cell["links"]
            if link["text"].strip() and link["attrs"].get("title") in locations.values()]


def check_recipe_cells(row, group, locations, stations, quantity_override=None, ap_override=None):
    cells = row["cells"]
    if len(cells) != 5:
        raise RuntimeError("A recipe lost its five ordered data cells.")
    for index, field in enumerate(("inputs", "outputs")):
        entries = sorted(group[0]["details"][field], key=lambda entry: entry["item"])
        quantities = [entry["quantity"] for entry in entries]
        if index == 0 and quantity_override is not None:
            quantities[0] = quantity_override
        if item_links(cells[index], locations) != [locations[entry["item"]] for entry in entries]:
            raise RuntimeError(f"Recipe {row['entries']} cell {index} links {item_links(cells[index], locations)!r} "
                               f"!= {[locations[entry['item']] for entry in entries]!r}; actual {cells[index]['links']!r}")
        if [int(value) for value in re.findall(r"\bx\s+(\d+)", cells[index]["text"])] != quantities:
            raise RuntimeError("A recipe changed its exact ingredient/output quantities.")
    wanted_stations = sorted({stations[entry["details"]["station"]]["title"] for entry in group})
    actual_stations = [link["attrs"].get("title") for link in cells[2]["links"] if link["text"].strip()]
    if actual_stations != wanted_stations:
        raise RuntimeError("A recipe changed its ordered workstation links.")
    cost = group[0]["details"]["cost"]
    expected = "Not established" if cost is None else scalar(ap_override if ap_override is not None else cost["amount"]) + " " + cost["unit"]
    if plain(cells[3]["text"]) != expected or plain(cells[4]["text"]) != plain(scalar(group[0]["conditions"])):
        raise RuntimeError("A recipe changed its numeric AP cell or condition cell.")


def check_probability(cell, expected, scope=None, note=None):
    text = plain(cell["text"])
    if expected is None:
        if not text.startswith("Not established") or note and plain(note) not in text:
            raise RuntimeError("An unknown probability lost its explicit qualification.")
    else:
        match = re.match(r"^(?:(\d+(?:\.\d+)?)%|(\d+)/(\d+))", text)
        actual = None if match is None else (
            Fraction(match[1]) / 100 if match[1] is not None else Fraction(int(match[2]), int(match[3])))
        if actual != expected:
            raise RuntimeError("A loot probability is not the exact documented rational value.")
    if scope and plain(scope) not in text:
        raise RuntimeError("A probability lost its conditional scope.")


def check_construction_cells(row, recipe, locations, ap_override=None):
    expected = {
        "conditions": recipe["condition"], "details": {
            "inputs": recipe["inputs"], "outputs": [], "station": recipe["station_id"],
            "cost": {"amount": recipe["base_ap_cost"], "unit": "base AP"},
        },
    }
    check_recipe_cells(row, [expected], locations, {recipe["station_id"]: {"title": recipe["station_title"]}},
                       ap_override=ap_override)
    if plain(row["cells"][1]["text"]) != str(recipe["result"]["quantity"]) + " in-place completion " + recipe["result"]["description"]:
        raise RuntimeError("The construction action lost its explicit in-place, no-inventory outcome.")


def check_price_cell(cell, value):
    text = plain(cell["text"])
    terms = re.findall(r"(\d+) (gold|silver|copper)", text)
    if " ".join(amount + " " + unit for amount, unit in terms) != text:
        raise RuntimeError("A price cell contains unexpected or missing denomination text.")
    total = sum(Decimal(amount) * {"gold": Decimal(10), "silver": Decimal(1), "copper": Decimal("0.01")}[unit]
                for amount, unit in terms)
    if total != Decimal(str(value)):
        raise RuntimeError("A merchant price differs from its canonical item value.")


def smoke_canonical_views(run, api, pages, data, catalog, token):
    locations = page_locations(data, catalog)
    owners = entry_owners(data, locations, entry_relations(data, catalog), catalog)
    recipes = [display_entry(entry, catalog) for entry in data["entries"] if entry["kind"] == "recipe"]
    groups = recipe_groups(recipes)
    stations = {method: station for station in catalog["stations"] for method in station["methods"]}
    entities = {entity["id"]: entity for entity in data["entities"]}
    prices = {row["entity"]: row["value"] for row in catalog["unit_prices"]["prices"]}
    for station in catalog["stations"]:
        rendered = api({"action": "parse", "page": station["title"], "prop": "text"})["parse"]["text"]["*"]
        check_parser_errors(rendered)
        parsed = RenderedRows(page_title=station["title"])
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
            group = next(group for group in groups if group[0]["id"] in row["entries"])
            check_recipe_cells(row, group, locations, stations)
        construction = RenderedRows("entry-construction-", "entry-", page_title=station["title"])
        construction.feed(rendered)
        wanted = {recipe["id"]: recipe for recipe in catalog.get("construction_recipes", [])
                  if recipe["station_id"] == station["id"]}
        if {identity for row in construction.rows for identity in row["entries"]} != wanted.keys() or len(construction.rows) != len(wanted):
            raise RuntimeError("A workstation lost or duplicated an in-place construction action.")
        for row in construction.rows:
            check_construction_cells(row, wanted[next(iter(row["entries"]))], locations)
    price_owners = {locations[entry["details"]["item"]] for entry in data["entries"] if entry["kind"] == "merchant"}
    default_text = "\n".join("<div>{{:" + title + "}}</div>" for title in sorted(price_owners))
    rendered = api({"action": "parse", "title": "Synthetic default views", "text": default_text, "prop": "text"}, post=True)["parse"]["text"]["*"]
    check_parser_errors(rendered)
    if re.search(r'id="(?:entity-|entry-|profile-|Recipes|How_to_acquire)', rendered) or "Ingredients" in rendered:
        raise RuntimeError("A default price view leaked owner content, a recipe, or merchant availability.")
    if not catalog["unit_prices"]["unresolved_offers"] and "Not established" in rendered:
        raise RuntimeError("A fully documented merchant price still renders as unresolved.")
    for title in price_owners:
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        check_parser_errors(rendered)
        if 'id="How_to_acquire"' not in rendered or 'id="entity-' not in rendered:
            raise RuntimeError("A normal item article lost its acquisition section or identity.")
    for merchant in {owners[entry["id"]] for entry in data["entries"] if entry["kind"] == "merchant"}:
        offered = [display_entry(entry, catalog) for entry in data["entries"]
                   if entry["kind"] == "merchant" and owners[entry["id"]] == merchant]
        for item in [None, *sorted({entry["details"]["item"] for entry in offered})]:
            query = {"action": "parse", "page": merchant, "prop": "text|templates"} if item is None else {
                "action": "parse", "title": "Synthetic seller view",
                "text": "{{:" + merchant + "|view=offers|item=" + item + "}}", "prop": "text|templates"}
            result = api(query, post=item is not None)["parse"]
            rendered = result["text"]["*"]
            check_parser_errors(rendered)
            parsed = RenderedRows("entry-merchant-", "entry-", page_title=merchant if item is None else None)
            parsed.feed(rendered)
            wanted = {entry["id"]: entry for entry in offered if item is None or entry["details"]["item"] == item}
            if {identity for row in parsed.rows for identity in row["entries"]} != wanted.keys() or len(parsed.rows) != len(wanted):
                raise RuntimeError("A seller view lost or duplicated an exact offer.")
            if item is not None and ({row["*"] for row in result.get("templates", [])} != {merchant} or "Unit price" in rendered):
                raise RuntimeError("A seller view recursively transcluded item prices.")
            for row in parsed.rows:
                entry = wanted[next(iter(row["entries"]))]
                detail, cells = entry["details"], row["cells"]
                if plain(cells[0]["text"]) != entities[detail["merchant"]]["name"] or item_links(cells[1], locations) != [locations[detail["item"]]]:
                    raise RuntimeError("An offer changed its seller or item cell.")
                index = 2
                if any(entry["details"]["quantity"] is not None for entry in offered):
                    if plain(cells[index]["text"]) != scalar(detail["quantity"]):
                        raise RuntimeError("An offer changed its documented quantity.")
                    index += 1
                elif "Quantity is not established." not in parsed.text:
                    raise RuntimeError("An offer invented stock quantity or lost the unknown-quantity note.")
                if item is None:
                    check_price_cell(cells[index], prices[detail["item"]])
                    index += 1
                for field in ("location", "conditions"):
                    values = [entry["conditions"] if field == "conditions" else entry["details"][field] for entry in offered]
                    expected = entry["conditions"] if field == "conditions" else detail[field]
                    if len(set(values)) > 1:
                        if plain(cells[index]["text"]) != plain(scalar(expected)):
                            raise RuntimeError("An offer changed its location/condition cell.")
                        index += 1
                    elif expected is not None and plain(expected) not in plain(parsed.text):
                        raise RuntimeError("A filtered offer lost its shared location/condition.")
                if len(cells) != index:
                    raise RuntimeError("An offer has unexpected ordered data cells.")
    for owner in {owners[entry["id"]] for entry in data["entries"] if entry["kind"] == "loot"}:
        loot = [display_entry(entry, catalog) for entry in data["entries"]
                if entry["kind"] == "loot" and owners[entry["id"]] == owner]
        for item in sorted({entry["details"]["outcome"] or "empty" for entry in loot}):
            text = "{{:" + owner + "|view=loot|item=" + item + "}}"
            rendered = api({"action": "parse", "title": "Synthetic loot view", "text": text, "prop": "text"}, post=True)["parse"]["text"]["*"]
            check_parser_errors(rendered)
            parsed = RenderedRows(("entry-loot-", "entry-corpse-"), "entry-")
            parsed.feed(rendered)
            expected = {entry["id"]: entry for entry in loot if (entry["details"]["outcome"] or "empty") == item}
            if {identity for row in parsed.rows for identity in row["entries"]} != expected.keys() or len(parsed.rows) != len(expected):
                raise RuntimeError("A loot view lost, duplicated or leaked an outcome row.")
            for row in parsed.rows:
                entry = expected[next(iter(row["entries"]))]
                detail, cells = entry["details"], row["cells"]
                if item != "empty" and item_links(cells[1], locations) != [locations[item]]:
                    raise RuntimeError("A historical loot row changed its item link.")
                if item == "empty" and plain(cells[1]["text"]) != "No items":
                    raise RuntimeError("An empty-result row implies an inventory item.")
                if plain(cells[2]["text"]) != interval(detail["quantity"]):
                    raise RuntimeError("A historical loot row changed its quantity.")
                check_probability(cells[3], None if detail["probability"] is None else Fraction(Decimal(str(detail["probability"]))))
                index = 4
                for field in ("weight", "rolls"):
                    if any(entry["details"][field] is not None for entry in loot):
                        expected_value = interval(detail[field]) if field == "rolls" else scalar(detail[field])
                        if plain(cells[index]["text"]) != expected_value:
                            raise RuntimeError("A historical loot row changed its rolls or weight.")
                        index += 1
                for field in ("conditions", "summary"):
                    if len({entry[field] for entry in loot}) > 1:
                        if plain(cells[index]["text"]) != plain(scalar(entry[field])):
                            raise RuntimeError("A historical loot row changed its condition or notes.")
                        index += 1
                    elif entry[field] and plain(entry[field]) not in plain(parsed.text):
                        raise RuntimeError("A historical loot view lost its shared condition or notes.")
                if len(cells) != index:
                    raise RuntimeError("A historical loot row has unexpected ordered cells.")
            source = next((source for source in catalog["acquisition"]["sources"] if source["title"] == owner), None)
            if source and source.get("loot_context") and plain(source["loot_context"]) not in plain(parsed.text):
                raise RuntimeError("A historical loot outcome lost its shared interruption qualifier.")
    for source in catalog.get("acquisition", {}).get("sources", []):
        for item in sorted({row["item"] for row in source["rows"]}):
            text = "{{:" + source["title"] + "|view=loot|item=" + item + "}}"
            result = api({"action": "parse", "title": "Synthetic acquisition view", "text": text,
                          "prop": "text|templates"}, post=True)["parse"]
            rendered = result["text"]["*"]
            check_parser_errors(rendered)
            parsed = RenderedRows("acquisition-", "acquisition-")
            parsed.feed(rendered)
            if source.get("loot_context") and source["loot_context"] not in parsed.text:
                raise RuntimeError("A filtered acquisition view omitted its shared interruption/eligibility qualifier.")
            expected = {row["id"]: row for row in source["rows"] if row["item"] == item}
            if {identity for row in parsed.rows for identity in row["entries"]} != expected.keys():
                raise RuntimeError("A fixed acquisition view leaked another item or omitted a documented condition.")
            if len(parsed.rows) != len(expected) or {row["*"] for row in result.get("templates", [])} != {source["title"]}:
                raise RuntimeError("An acquisition view duplicated rows or included an unexpected owner.")
            if 'id="source-' in rendered or source["summary"] in rendered:
                raise RuntimeError("An acquisition view leaked the source article.")
            for rendered_row in parsed.rows:
                row = expected[next(iter(rendered_row["entries"]))]
                cells = rendered_row["cells"]
                if len(cells) != 5 or item_links(cells[1], locations) != [locations[item]] or plain(cells[2]["text"]) != interval(row["quantity"]):
                    raise RuntimeError("An acquisition row changed its ordered item/quantity cells.")
                probability = row["probability"]
                check_probability(cells[3], None if probability is None else Fraction(probability["numerator"], probability["denominator"]),
                                  probability["scope"] if probability else None, row.get("odds_note"))
                if plain(row["condition"]) != plain(cells[4]["text"]):
                    raise RuntimeError("An acquisition view lost its exact difficulty/location condition.")
                if row["coverage"] == "fixed" and "100%" not in rendered_row["text"]:
                    raise RuntimeError("A fixed acquisition view lost its explicitly conditional certainty.")
    original = pages["Dead camp"]
    row = next(row for row in re.findall(r"<tr>.*?</tr>", original, re.DOTALL)
               if 'id="acquisition-dead-camp-item-41"' in row)
    changed = row.replace("<nowiki>1</nowiki>", "<nowiki>703</nowiki>", 1)
    if changed == row:
        raise RuntimeError("The synthetic acquisition edit missed the canonical quantity.")
    api({"action": "parse", "page": locations["item-41"], "prop": "text"})
    wait_for_server_tick(api)
    edit = api({"action": "edit", "title": "Dead camp", "text": original.replace(row, changed, 1), "token": token}, post=True)
    if edit.get("edit", {}).get("result") != "Success":
        raise RuntimeError("The canonical acquisition quantity edit failed.")
    rendered = refreshed_transclusion(run, api, locations["item-41"], "703", 'id="source-dead-camp"', "Dead camp")
    parsed = RenderedRows("acquisition-", "acquisition-")
    parsed.feed(rendered)
    if not any("dead-camp-item-41" in row["entries"] and plain(row["cells"][2]["text"]) == "703" for row in parsed.rows):
        raise RuntimeError("The changed quantity did not reach the item's exact acquisition row.")
    restored = api({"action": "edit", "title": "Dead camp", "text": original, "token": token}, post=True)
    if restored.get("edit", {}).get("result") != "Success":
        raise RuntimeError("The synthetic acquisition edit could not be restored.")
    smoke_acquisition_pools(run, api, pages, data, catalog, token)
    for recipe in catalog.get("construction_recipes", []):
        owner = locations[recipe["owner_item"]]
        original = pages[owner]
        row = next(row for row in re.findall(r"<tr>.*?</tr>", original, re.DOTALL)
                   if 'id="entry-' + recipe["id"] + '"' in row)
        before = "<nowiki>" + scalar(recipe["base_ap_cost"]) + "</nowiki> base [[Action points|AP]]"
        changed = row.replace(before, "<nowiki>991</nowiki> base [[Action points|AP]]", 1)
        if changed == row:
            raise RuntimeError("The construction AP edit did not identify its exact cost cell.")
        api({"action": "parse", "page": recipe["station_title"], "prop": "text"})
        wait_for_server_tick(api)
        edit = api({"action": "edit", "title": owner, "text": original.replace(row, changed, 1), "token": token}, post=True)
        if edit.get("edit", {}).get("result") != "Success":
            raise RuntimeError("The ordinary-editor construction edit failed.")
        rendered = refreshed_transclusion(run, api, recipe["station_title"], "991", 'id="entity-item-171"', owner)
        parsed = RenderedRows("entry-construction-", "entry-", page_title=recipe["station_title"])
        parsed.feed(rendered)
        if len(parsed.rows) != 1:
            raise RuntimeError("The changed construction row was not retained exactly once.")
        check_construction_cells(parsed.rows[0], recipe, locations, 991)
        restored = api({"action": "edit", "title": owner, "text": original, "token": token}, post=True)
        if restored.get("edit", {}).get("result") != "Success":
            raise RuntimeError("The construction fixture could not be restored.")
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
            parsed = RenderedRows(page_title=target)
            parsed.feed(rendered)
            if not any(fixture[0]["id"] in row["entries"] and expected in row["text"] for row in parsed.rows):
                raise RuntimeError("The changed recipe value did not reach its exact station row.")
            changed_row = next(row for row in parsed.rows if fixture[0]["id"] in row["entries"])
            check_recipe_cells(changed_row, fixture, locations, stations, 701, 997 if expected == "997" else None)
        rendered = api({"action": "parse", "page": owner, "prop": "text"})["parse"]["text"]["*"]
        check_parser_errors(rendered)
        if expected not in rendered or 'id="entity-item-141"' not in rendered:
            raise RuntimeError("A selective recipe edit broke the normal owner article.")
        block = replacement
    print("Named views passed: every workstation variant, default prices, filtered sellers/loot, separate quantity/AP edits.")


def smoke_acquisition_pools(run, api, pages, data, catalog, token):
    locations = page_locations(data, catalog)
    sources = {source["id"]: source for source in catalog.get("acquisition", {}).get("sources", [])}
    pools = {pool["id"]: pool for pool in catalog.get("acquisition", {}).get("pools", [])}
    for pool in pools.values():
        owner = sources[pool["owner_source"]]["title"]
        for item in sorted({*pool["eligible_item_ids"], "item-48"}):
            text = "{{:" + owner + "|view=pool|pool=" + pool["id"] + "|item=" + item + "}}"
            result = api({"action": "parse", "title": "Synthetic pool view", "text": text,
                          "prop": "text|templates"}, post=True)["parse"]
            rendered = result["text"]["*"]
            check_parser_errors(rendered)
            parsed = RenderedRows("pool-item-", "pool-item-")
            parsed.feed(rendered)
            expected = {pool["id"] + "-" + item} if item in pool["eligible_item_ids"] else set()
            actual = {identity for row in parsed.rows for identity in row["entries"]}
            if actual != expected or len(parsed.rows) != len(expected):
                raise RuntimeError("A pool view omitted an eligible item or admitted an ineligible member.")
            if {row["*"] for row in result.get("templates", [])} != {owner} or pool["summary"] in parsed.text:
                raise RuntimeError("A pool view added dependencies or copied its full budget explanation.")
            if expected and ("Budget-dependent" not in parsed.text or "Not established" not in parsed.text):
                raise RuntimeError("A pool view lost its quantity/odds qualification.")
            for row in parsed.rows:
                cells = row["cells"]
                if len(cells) != 4 or item_links(cells[0], locations) != [locations[item]]:
                    raise RuntimeError("A pool member changed its ordered item cell.")
                if plain(cells[1]["text"]) != "Budget-dependent" or plain(cells[2]["text"]) != "Not established":
                    raise RuntimeError("A pool member gained an invented quantity or probability.")
            for identity, condition in pool["item_conditions"].items():
                if (condition in parsed.text) != (item == identity):
                    raise RuntimeError("The canonical story gate did not follow the filtered pool member.")
    for source in sources.values():
        for reference in source.get("pool_refs", []):
            text = "{{:" + source["title"] + "|view=pool-source|pool=" + reference["pool"] + "}}"
            result = api({"action": "parse", "title": "Synthetic pool source", "text": text,
                          "prop": "text|templates"}, post=True)["parse"]
            check_parser_errors(result["text"]["*"])
            parsed = RenderedRows("pool-item-", "pool-item-")
            parsed.feed(result["text"]["*"])
            if reference["condition"] not in parsed.text or parsed.rows:
                raise RuntimeError("A source-context view lost its condition or included pool member tables.")
            if {row["*"] for row in result.get("templates", [])} != {source["title"]}:
                raise RuntimeError("A source-context view introduced an unexpected nested dependency.")
    if not pools:
        return
    counts = {entity["id"]: sum(entity["id"] in pools[reference["pool"]]["eligible_item_ids"]
                              for source in sources.values() for reference in source.get("pool_refs", []))
              for entity in data["entities"] if entity["category"] == "item"}
    for item in {max(counts, key=counts.get), "item-127"}:
        rendered = api({"action": "parse", "page": locations[item], "prop": "text"})["parse"]["text"]["*"]
        check_parser_errors(rendered)
        parsed = RenderedRows("pool-item-", "pool-item-")
        parsed.feed(rendered)
        expected = {reference["pool"] + "-" + item for source in sources.values()
                    for reference in source.get("pool_refs", []) if item in pools[reference["pool"]]["eligible_item_ids"]}
        if {identity for row in parsed.rows for identity in row["entries"]} != expected:
            raise RuntimeError("A complete item page lost a pool variant or exceeded its expansion budget.")
    gate = next(pool["item_conditions"]["item-127"] for pool in pools.values() if "item-127" in pool["item_conditions"])
    chest_condition = sources["treasure-chests"]["pool_refs"][0]["condition"]
    for owner, before, after, expected, targets in (
        ("Random treasure", gate, "Synthetic story requirement 997", "Synthetic story requirement 997",
         ["Summoning Stone", "Treasure chests"]),
        ("Treasure chests", chest_condition, chest_condition.replace("88.2%", "81.7%"), "81.7%", ["Summoning Stone"]),
    ):
        original = pages[owner]
        if original.count(literal(before)) != 1:
            raise RuntimeError("A synthetic pool edit did not identify exactly one canonical value.")
        for target in targets:
            api({"action": "parse", "page": target, "prop": "text"})
        wait_for_server_tick(api)
        edit = api({"action": "edit", "title": owner, "text": original.replace(literal(before), literal(after), 1), "token": token}, post=True)
        if edit.get("edit", {}).get("result") != "Success":
            raise RuntimeError("The canonical pool/source edit failed.")
        for target in targets:
            refreshed_transclusion(run, api, target, expected, 'id="source-' + ("random-treasure" if owner == "Random treasure" else "treasure-chests") + '"', owner)
        wait_for_server_tick(api)
        restored = api({"action": "edit", "title": owner, "text": original, "token": token}, post=True)
        if restored.get("edit", {}).get("result") != "Success":
            raise RuntimeError("The synthetic pool/source edit could not be restored.")
    print("Acquisition pools passed: exact members, rejected members, story gates, source conditions and canonical edit propagation.")


def capture_view_fixtures(api, pages, catalog):
    station = next(row["id"] for row in catalog["stations"] if row["title"] == "Alchemy workstation")
    cases = [
        ("price", "Longbow (Cypress)", {}),
        ("coin", "Copper Coin", {}),
        ("recipes", "Simple Burn Remedy", {"view": "recipes", "station": station}),
        ("construction", "Finish Raft", {"view": "recipes", "station": "raft-base"}),
        ("offers", "Ranger Bhato", {"view": "offers", "item": "item-105"}),
        ("fixed-loot", "Dead camp", {"view": "loot", "item": "item-13"}),
        ("world-loot", "Searching boulders", {"view": "loot", "item": "item-60"}),
        ("insect-loot", "Harvested insects", {"view": "loot", "item": "item-243"}),
        ("pool-source", "Treasure chests", {"view": "pool-source", "pool": "chest-common"}),
        ("pool-story-gate", "Random treasure", {"view": "pool", "pool": "chest-common", "item": "item-127"}),
    ]
    fixtures = []
    for name, owner, parameters in cases:
        original = api({"action": "parse", "page": owner, "prop": "wikitext"})["parse"]["wikitext"]["*"]
        if original != pages[owner]:
            raise RuntimeError("A named-view fixture owner differs from the frozen desired seed.")
        invocation = "{{:" + owner + "".join("|" + key + "=" + value for key, value in parameters.items()) + "}}"
        expanded = api({"action": "expandtemplates", "text": invocation, "prop": "wikitext"}, post=True)["expandtemplates"]["wikitext"]
        render_context = "table" if parameters.get("view") == "recipes" else "block"
        render_text = "<table>" + invocation + "</table>" if render_context == "table" else invocation
        result = api({"action": "parse", "title": "Synthetic contract view", "text": render_text,
                      "prop": "text|templates"}, post=True)["parse"]
        check_parser_errors(result["text"]["*"])
        fixture = {
            "name": name, "owner": owner, "owner_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "parameters": parameters, "invocation": invocation, "expanded_wikitext": expanded,
            "render_context": render_context,
            "html": result["text"]["*"], "templates": sorted(row["*"] for row in result.get("templates", [])),
            "scope": "Disposable MediaWiki with synthetic artwork; image URLs and cache metadata are not portable.",
        }
        fixtures.append(fixture)
        print("VIEW_CONTRACT_JSON=" + json.dumps(fixture, ensure_ascii=False), flush=True)
    return fixtures


def refreshed_transclusion(run, api, title, expected, forbidden_anchor, owner=None):
    # Imports and edits enqueue deferred link updates; allow their bounded completion.
    for attempt in range(10):
        drain_jobs_bounded(run)
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


def synthetic_image_specs(data):
    # Original solid-color RGB/RGBA pixels, not game artwork or a committed fixture.
    specs = {"Synthetic-thumbnail.png": (64, 32, bytes((37, 149, 211)), 16)}
    specs.update({f"Health-armor-{armor}.png": (64, 64, bytes((40 * armor, 149, 211, 128)), 32)
                  for armor in (1, 2, 3)})
    for index, image in enumerate(sorted(data["illustrations"], key=lambda row: row["file_title"])):
        filename = image["file_title"].removeprefix("File:")
        specs.setdefault(filename, (64, 64, bytes((index % 256, index // 256, 73, 255)), 32))
    for identity, (width, height) in MATURE_TREES.items():
        filename = image_for(identity, data["illustrations"])["file_title"].removeprefix("File:")
        specs[filename] = (width, height, specs[filename][2], 32)
    specs.update({f"Nature-{number}.png": (64, 64, bytes((200 + number, 40, 70, 255)), 32)
                  for number in (4, 7, 17, 20)})
    if len({value[2] for value in specs.values()}) != len(specs):
        raise RuntimeError("Synthetic fixture colors are not unique; image import could skip duplicates.")
    return specs


def require_image_coverage(specs, *corpora):
    for pages in corpora:
        references = {title.removeprefix("File:") for text in pages.values()
                      for title in re.findall(r"\[\[(File:[^\]|]+)", text)}
        if not references <= specs.keys():
            raise RuntimeError("Rendered image references lack synthetic fixtures: " + ", ".join(sorted(references - specs.keys())))


def smoke_images(run, api, base, data, *corpora):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    signature = b"\x89PNG\r\n\x1a\n"
    specs = synthetic_image_specs(data)
    require_image_coverage(specs, *corpora)
    originals = {}
    run("exec", "-T", "--user", "www-data", "mirklurk", "mkdir", "/tmp/mirklurk-smoke-images")
    for filename, (width, height, pixel, _) in specs.items():
        original = (signature
                    + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6 if len(pixel) == 4 else 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress((b"\0" + pixel * width) * height))
                    + chunk(b"IEND", b""))
        originals[filename] = original
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        for filename, original in originals.items():
            member = tarfile.TarInfo(filename)
            member.size, member.mode = len(original), 0o600
            bundle.addfile(member, io.BytesIO(original))
    run("exec", "-T", "--user", "www-data", "mirklurk", "tar", "--extract", "--no-same-owner",
        "--file", "-", "--directory", "/tmp/mirklurk-smoke-images", input_bytes=archive.getvalue())
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
    print(f"Synthetic CLI import and anonymous decoded PNG reads passed: {len(specs)} fixtures, all active/retired images, thumbnail and alpha.")
    return {filename: hashlib.sha256(payload).hexdigest() for filename, payload in originals.items()}


def smoke(evidence_dir=None):
    from smoke_native import NativeSmoke, docker
    from publication_journal import Journal
    from smoke_prefix import (
        PREVIOUS_AUTHORED_COMMIT, STORED_BASELINE_BINDING, Rehearsal, SETTINGS_KEYS,
        canonical_bytes, capture_installer_welcome, managed_titles,
        materialize_desired, reconstruct_baseline, settings_hash,
    )

    project = "mirklurk-smoke-" + secrets.token_hex(6)
    with tempfile.TemporaryDirectory(prefix="mirklurk-smoke-") as folder:
        workspace = Path(folder)
        previous_authored, previous_payload, baseline, baseline_payload, baseline_catalog = reconstruct_baseline(ROOT, workspace)
        source_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT, check=True)
        evidence = {"stored-baseline-binding.json": STORED_BASELINE_BINDING}
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
        override = workspace / "native-compose.json"
        override.write_text(json.dumps({"services": {"mirklurk": {"volumes": [
            "native-images:/var/www/html/images", f"{ROOT / 'tools'}:/native/tools:ro",
            f"{ROOT / 'tests'}:/native/tests:ro",
        ]}}, "volumes": {"native-images": {}}}), encoding="utf-8")
        compose += ["--file", str(override)]
        observer = None
        native = None

        def run(*args, input_bytes=None, timeout=None):
            if observer and args[0] == "exec" and "mirklurk" in args:
                arguments = list(args[1:])
                arguments[arguments.index("-T")] = "-i"
                arguments[arguments.index("mirklurk")] = observer
                if "runJobs" in arguments:
                    arguments = ["-e", "MW_READ_ONLY=", *arguments]
                return docker("exec", *arguments, input_bytes=input_bytes, timeout=timeout or 120)
            return subprocess.run(
                [*compose, *args], cwd=ROOT, env=environment, input=input_bytes,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=timeout,
            ).stdout

        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        base = f"http://localhost:{port}"
        minimum_edit_interval = 0
        last_edit_at = 0

        def api(parameters, post=False, expected_error=None, timeout=30):
            nonlocal last_edit_at
            if parameters.get("action") == "edit" and minimum_edit_interval:
                time.sleep(max(0, minimum_edit_interval - (time.monotonic() - last_edit_at)))
                last_edit_at = time.monotonic()
            encoded = urllib.parse.urlencode(dict(format="json", **parameters)).encode()
            url = base + "/api.php" + ("" if post else "?" + encoded.decode())
            with opener.open(url, data=encoded if post else None, timeout=timeout) as response:
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
            authored = build_pages(ROOT, data, catalog, details)
            extensions = api({"action": "query", "meta": "siteinfo", "siprop": "extensions"})["query"]["extensions"]
            parser_functions = next((row for row in extensions if row["name"] == "ParserFunctions"), None)
            if not parser_functions or not parser_functions.get("version"):
                raise RuntimeError("The installed ParserFunctions registry has no loaded version.")
            projection_code = (
                "$config = MediaWiki\\MediaWikiServices::getInstance()->getMainConfig();"
                "$projection = []; foreach (" + json.dumps(list(SETTINGS_KEYS)) + " as $key) {"
                "$projection[$key] = $config->get($key); } "
                "echo json_encode($projection, JSON_THROW_ON_ERROR);\n"
            )
            projection = json.loads(run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "eval", "--quiet",
                                        input_bytes=projection_code.encode()))
            container = run("ps", "--quiet", "mirklurk").decode().strip()
            image_id = subprocess.check_output(["docker", "inspect", "--format", "{{.Image}}", container], text=True).strip()
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                raise RuntimeError("The rebuilt disposable image has no immutable image identity.")
            runtime = {
                "mediawiki_image_pin": (ROOT / "deploy" / "Dockerfile").read_text().splitlines()[0].removeprefix("FROM "),
                "runtime_php_sha256": hashlib.sha256((ROOT / "deploy" / "mirklurk-runtime.php").read_bytes()).hexdigest(),
                "settings_template_sha256": hashlib.sha256((ROOT / "deploy" / "LocalSettings.template.php").read_bytes()).hexdigest(),
                "generator": general["generator"], "ParserFunctions_version": parser_functions["version"],
                "runtime_image_id": image_id, "effective_settings_sha256": settings_hash(projection),
            }
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
            user = api({"action": "query", "meta": "userinfo", "uiprop": "groups|rights"})["query"]["userinfo"]
            if user["name"] != "WikiAdmin" or "sysop" not in user["groups"]:
                raise RuntimeError("Disposable materialization requires the authenticated test operator.")
            actor = {"id": user["id"], "name": user["name"]}
            welcome_messages = json.loads(run(
                "exec", "-T", "mirklurk", "php", "-r",
                "$messages = json_decode(file_get_contents('includes/installer/i18n/en.json'), true, 512, JSON_THROW_ON_ERROR);"
                "echo json_encode([$messages['mainpagetext'], $messages['mainpagedocfooter']], JSON_THROW_ON_ERROR);",
            ))
            welcome = capture_installer_welcome(api, "\n\n".join(welcome_messages), actor)
            deletion = api({"action": "delete", "title": "Main Page", "token": csrf,
                            "reason": "Replace only the fresh disposable installer's welcome before frozen baseline import."},
                           post=True).get("delete", {})
            if deletion.get("title") != "Main Page" or not isinstance(deletion.get("logid"), int) or managed_titles(api):
                raise RuntimeError("Disposable welcome replacement did not remove exactly the one verified page.")
            evidence["bootstrap-welcome.json"] = {
                "schema_version": 1, "scope": "fresh-disposable-before-prefix-zero-only",
                "source_head_sha": source_head, "runtime": runtime, "actor": actor,
                "welcome": welcome, "deletion_logid": deletion["logid"],
                "baseline_seed_sha256": hashlib.sha256(baseline_payload).hexdigest(),
            }
            native = NativeSmoke(ROOT, workspace, run, api, runtime, source_head)
            native.faults(csrf)
            if managed_titles(api):
                raise RuntimeError("Native synthetic fault fixtures left managed pages behind.")
            current = workspace / "current.xml"
            run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "importDump", input_bytes=baseline_payload)
            if managed_titles(api) != set(baseline):
                raise RuntimeError("The initial import is not exactly the frozen baseline title set.")
            pages, evidence["storage-materialization.json"] = materialize_desired(
                api, previous_authored, baseline, authored, source_head, runtime, actor,
                previous_source_head=PREVIOUS_AUTHORED_COMMIT,
            )
            if (evidence["storage-materialization.json"]["baseline_seed_sha256"] != hashlib.sha256(baseline_payload).hexdigest()
                    or evidence["storage-materialization.json"]["previous_authored_seed_sha256"]
                    != hashlib.sha256(previous_payload).hexdigest()):
                raise RuntimeError("Materialization no longer binds the exact previous-authored and stored baseline XML.")
            image_hashes = smoke_images(run, api, base, data, baseline, authored, pages)
            native.prepare_thumbnails(baseline, authored, pages)
            wait_for_server_tick(api)
            baseline_titles = sorted(baseline)
            for offset in range(0, len(baseline_titles), 50):
                api({"action": "purge", "titles": "|".join(baseline_titles[offset:offset + 50]),
                     "forcelinkupdate": 1}, post=True)
            def drain_jobs(timeout=90):
                return drain_jobs_bounded(run, timeout)
            def job_status(timeout=5):
                return bounded_maintenance(run, ("showJobs",), timeout).decode(errors="replace").strip()
            drain_jobs()
            rehearsal = Rehearsal(api, sys.modules[__name__], baseline, pages, data, catalog,
                                  baseline_catalog, runtime, source_head)
            public_base = base
            run("stop", "mirklurk")
            public_state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
            public_sessions = native.root_sql("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE USER='mirklurk';"
                                              "SELECT COUNT(*) FROM information_schema.INNODB_TRX;")
            if public_state["Running"] or public_sessions.split() != [b"0", b"0"]:
                raise RuntimeError("Public PHP/DB requests are not positively drained.")
            try:
                urllib.request.urlopen(public_base + "/api.php", timeout=3)
            except (OSError, urllib.error.URLError):
                pass
            else:
                raise RuntimeError("Stopped public frontend still accepts requests.")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                observer_port = probe.getsockname()[1]
            observer_name = project + "-private-observer"
            run("run", "-d", "--no-deps", "--name", observer_name,
                "--publish", f"127.0.0.1:{observer_port}:80", "--env",
                "MW_READ_ONLY=Disposable native publication barrier", "--env",
                f"MW_SERVER_URL=http://localhost:{observer_port}", "mirklurk")
            observer = observer_name
            base = f"http://localhost:{observer_port}"
            deadline = time.monotonic() + 60
            while True:
                try:
                    api({"action": "query", "meta": "siteinfo"})
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() > deadline:
                        raise RuntimeError("Private read-only observer did not become responsive.")
                    time.sleep(0.2)
            api({"action": "edit", "title": "Native denied frontend", "text": "Must not save",
                 "token": csrf}, post=True, expected_error="readonly")
            native.proof["barrier"] = {"public_php_exited": not public_state["Running"],
                                       "public_db_requests": 0, "public_transactions": 0,
                                       "public_http_unreachable": True, "private_observer_edit_error": "readonly",
                                       "worker_surface": "CLI-only; no published ports"}
            save = native.full_run(rehearsal, {
                key: evidence["storage-materialization.json"][field]
                for key, field in (("previous_authored", "previous_authored_seed_sha256"),
                                   ("baseline", "baseline_seed_sha256"), ("authored", "authored_seed_sha256"),
                                   ("desired", "desired_seed_sha256"))
            })
            rehearsal.run(save, wait_for_server_tick, drain_jobs, job_status)
            evidence.update(rehearsal.artifacts())
            if len(rehearsal.prefixes) != 450 or len(native.release_journal.accepted) != 449:
                raise RuntimeError("Native full-prefix proof is incomplete.")
            native.release_journal.verify_resume(native.states(native.release_journal.manifest,
                                                                native.release_journal.accepted))
            native.release_journal.close()
            with Journal(workspace / "native-release-journal") as replayed:
                if len(replayed.accepted) != 449:
                    raise RuntimeError("Native durable release replay is incomplete.")
            evidence["native-publication-proof.json"] = native.proof
            if set(pages) != managed_titles(api):
                raise RuntimeError("Imported page titles differ from the deterministic bundle.")
            drain_jobs()
            smoke_reader_release(api, pages, data, catalog, details, image_hashes)
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
            docker("stop", observer)
            docker("rm", observer)
            observer = None
            base = public_base
            # Only the same final-capable disposable image resumes for ordinary-editor behavior tests.
            run("start", "mirklurk")
            run("up", "-d", "--wait", "mirklurk")
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
            # Respect the stricter three-edits/minute newcomer policy without exempting the account.
            minimum_edit_interval = 21
            csrf = api({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
            evidence["desired-view-contracts.json"] = capture_view_fixtures(api, pages, catalog)
            smoke_canonical_views(run, api, pages, data, catalog, csrf)
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
            drain_jobs()
            run("stop", "mirklurk")
            evidence["native-recovery-proof.json"] = native.recovery()
            print(
                "Disposable Docker smoke passed: install, health, access policy, CAPTCHA, seed, "
                "edit preservation, CLI image import, resized thumbnail, web uploads disabled."
            )
            if evidence_dir is not None:
                evidence_dir.mkdir(parents=True, exist_ok=False)
                for name, value in evidence.items():
                    with (evidence_dir / name).open("xb") as stream:
                        stream.write(canonical_bytes(value))
                for name, payload in (("previous-authored-seed.xml", previous_payload),
                                      ("baseline-seed.xml", baseline_payload), ("authored-seed.xml", build_xml(authored)),
                                      ("desired-seed.xml", build_xml(pages))):
                    with (evidence_dir / name).open("xb") as stream:
                        stream.write(payload)
                hashes = {path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                          for path in sorted(evidence_dir.iterdir())}
                with (evidence_dir / "artifact-manifest.json").open("xb") as stream:
                    stream.write(canonical_bytes({"source_head_sha": source_head, "artifacts": hashes,
                                                 "notice": "Disposable rehearsal only. Expectations require independent review; no live writes authorized."}))
        except subprocess.CalledProcessError as error:
            # The child only receives mounted secret paths, never literal secrets in argv.
            sys.stderr.write(error.stdout.decode(errors="replace"))
            sys.stderr.write(error.stderr.decode(errors="replace"))
            raise
        finally:
            if native is not None:
                native.close()
            if observer:
                docker("rm", "-f", observer)
            run("down", "--volumes", "--remove-orphans")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, action="store_true", help="Create and remove test-only Docker resources")
    parser.add_argument("--evidence-dir", type=Path, help="New output directory for nonsecret disposable evidence")
    args = parser.parse_args()
    smoke(args.evidence_dir)


if __name__ == "__main__":
    main()
