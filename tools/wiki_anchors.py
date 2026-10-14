"""Readable, kind-prefixed section anchors and the checks that keep links to them working.

An anchor is a kind prefix plus MediaWiki's HTML5 fragment form of a canonical
title (spaces become underscores). An anchor on its own entity's page omits the
entity, because the page already identifies it. No identifier-based or retired
anchors are kept.
"""

import html
import re
from collections import Counter

from wiki_data import DataError
from wiki_display import INERT


ENTITY_PREFIX = re.compile(r"(?:item|being|nature|skill|damage-class|skill-group)-\d+(?:-\d+)?-")
ENTITY_KINDS = {"item": "item", "being": "creature", "nature": "nature", "skill": "skill",
                "damage_class": "damage-type", "skill_group": "skill-group"}
READABLE = {"currency", "dialogue", "pool", "pool-source", "report", "source", "variant"}
FRAGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:'(),?!-]{0,159}\Z")
SPAN_ID = re.compile(r'<span id="([^"{}]+)"></span>')
HEADING = re.compile(r"^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*$", re.M)
LINK = re.compile(r"\[\[([^\[\]|{}#\n]*)#([^\[\]|{}\n]+)(?:\|[^\[\]\n]*)?\]\]")
REDIRECT = re.compile(r"#REDIRECT \[\[([^\]#|]+)")


def encode(title):
    """MediaWiki's HTML5 fragment form of a title."""
    return title.strip().replace(" ", "_")


def titled(kind, title, number=1):
    return f"{kind}-{encode(title)}" + (f"-{number}" if number > 1 else "")


def span(fragment):
    return f'<span id="{fragment}"></span>'


def local(identity):
    """Drop the owning entity's identifier; the page already names the entity."""
    return ENTITY_PREFIX.sub("", identity, count=1) if ENTITY_PREFIX.match(identity) else identity


def fragment(kind, identity):
    """Anchors derived from a record's own identity on its owner's page."""
    rest = local(identity)
    if kind == "fact":
        return rest
    if kind == "profile":
        return "stats-" + ("base" if rest == "initializer" else rest)
    if kind == "grid":
        return "health-grid" if rest == "health" else "attack-grid-" + rest
    if kind in READABLE:
        return f"{kind}-{identity}"
    raise DataError(f"anchor: unsupported kind {kind}")


def illustration_fragment(image):
    rest = image["id"].removesuffix("-illustration").removesuffix("illustration")
    for owner in (image.get("entity"), image.get("station")):
        if owner and (rest == owner or rest.startswith(owner + "-")):
            rest = rest[len(owner) + 1:]
    return "image" + ("-" + rest if rest else "")


def entity_fragment(entity, title, npc=False):
    return titled("npc" if npc else ENTITY_KINDS[entity["category"]], title)


def entry_fragments(entries, owners, locations, constructions=()):
    """Readable entry anchors, numbered when one owner page repeats a name.

    Recipe anchors are numbered across the whole wiki because workstation pages
    transclude recipe rows, anchors included, from many owners.
    """
    counts, result = Counter(), {}

    def add(identity, owner, base):
        owner = None if base.startswith("recipe-") else owner
        counts[owner, base] += 1
        result[identity] = base + (f"-{counts[owner, base]}" if counts[owner, base] > 1 else "")

    for entry in sorted(entries, key=lambda row: row["id"]):
        details, owner = entry["details"], owners[entry["id"]]
        if entry["kind"] == "merchant":
            add(entry["id"], owner, titled("offer", locations[details["item"]]))
        elif entry["kind"] == "loot":
            add(entry["id"], owner, titled("loot", locations[details["outcome"]] if details["outcome"] else "nothing"))
        elif entry["kind"] == "recipe":
            add(entry["id"], owner, titled("recipe", locations[details["outputs"][0]["item"]]))
        else:
            add(entry["id"], owner, titled("quest" if entry["kind"] == "quest" else "rules", entry["title"]))
    for recipe in constructions:
        owner = locations[recipe["owner_item"]]
        add(recipe["id"], owner, titled("recipe", owner))
    return result


def acquisition_fragments(source, locations):
    counts, result = Counter(), {}
    for row in source["rows"]:
        base = titled("acquisition", locations[row["item"]])
        counts[base] += 1
        result[row["id"]] = base + (f"-{counts[base]}" if counts[base] > 1 else "")
    return result


def valid_fragment(value, location):
    if not isinstance(value, str) or not FRAGMENT.match(value):
        raise DataError(f"{location}: invalid readable anchor")
    return value


def heading_id(text):
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    return encode(html.unescape(re.sub(r"<[^>]*>", "", text)))


def anchor_ids(text):
    """Explicit span anchors plus MediaWiki's numbered heading anchors, in page order."""
    ids = SPAN_ID.findall(text)
    headings = Counter()
    for _, heading in HEADING.findall(text):
        base = heading_id(heading)
        headings[base] += 1
        ids.append(base if headings[base] == 1 else f"{base}_{headings[base]}")
    return ids


def canonical(title, pages):
    title = title.strip().replace("_", " ")
    title = title[:1].upper() + title[1:]
    for _ in range(3):
        match = REDIRECT.match(pages.get(title, ""))
        if not match:
            break
        title = match.group(1).strip()
    return title


def validate_anchors(pages, lenient=()):
    """Each anchor is unique on its page and every generated [[Page#anchor]] resolves.

    Lowercase fragments are generated anchors and must exist; capitalized ones are
    section headings that authored pages may reference before their data exists.
    Links from ``lenient`` (authored) pages are skipped when their target is absent,
    since partial builds omit pages and records that complete builds check strictly.
    """
    known = {}
    for title, text in pages.items():
        if title.startswith(("Module:", "MediaWiki:")):
            continue
        ids = anchor_ids(text)
        repeated = sorted(key for key, count in Counter(ids).items() if count > 1)
        if repeated:
            raise DataError(f"{title}: repeated anchors {', '.join(repeated[:5])}")
        known[title] = set(ids)
    for title, text in pages.items():
        if title not in known:
            continue
        for target, part in LINK.findall(INERT.sub("", text)):
            if target.startswith((":", "Category:", "File:", "Special:")):
                continue
            page = canonical(target, pages) if target.strip() else title
            if title in lenient and (page not in known or encode(part) not in known[page]):
                continue
            if page not in known:
                raise DataError(f"{title}: linked page is missing: {target}#{part}")
            if encode(part) not in known[page] and part[:1].islower():
                raise DataError(f"{title}: missing anchor {page}#{part}")
