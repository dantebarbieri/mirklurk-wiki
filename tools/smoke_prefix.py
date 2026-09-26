"""Disposable, revision-bound baseline-to-desired rehearsal; never a live executor."""

import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import time
import urllib.parse
from collections import Counter
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from build_wiki import build_xml
from plan_migration import plan_migration, read_snapshot, text_hash
from wiki_catalog import MAX_CATALOG_BYTES, entry_owners, entry_relations, page_locations, title_key
from wiki_details import parse_document
from wiki_render import display_entry, recipe_groups
from wiki_views import available_views, transclusions


PREVIOUS_AUTHORED_COMMIT = "67c690fb6b32617f33947bd5de217fd2077dc6ef"
STORED_BASELINE_BINDING = {
    "schema_version": 1, "binding_type": "historical-stored-release",
    "previous_source_head_sha": PREVIOUS_AUTHORED_COMMIT,
    "previous_source_tree_sha": "a2bfb891b38ed0af5bce74142120f8d6a0ce7081",
    "previous_authored_seed_bytes": 2542913,
    "previous_authored_seed_sha256": "4715cafa65bdca206a8315d084a97d89b0b0275dbefe650f92b59e9c0c1f0e33",
    "baseline_seed_bytes": 2542511,
    "baseline_seed_sha256": "68f4ce8263570e4d28da8679c49f82a982d7e34d2b35fd1d3331d2431e05ed78",
    "baseline_corpus_sha256": "ea08accc34f121bfbf0279b8b59af55a1c4fde08ec39872dbc6e0ad4a4cbf0cc",
    "managed_title_count": 401,
    "historical_transform": "published-67c690f-terminal-lf-except-exact-titles",
    "exact_titles": ["Evidence and spoilers"],
    "removed_lf_counts": {"0": 1, "1": 399, "2": 1},
    "scope": "Reconstruct this exact independently observed release only; not a fresh live export or normalization authority.",
}
COHORT = ("being-8", "being-19", "being-26", "item-32", "item-84", "item-138",
          "item-139", "item-140", "item-248")
COMPATIBILITY = {
    "being-8": ("item-140", "item-32", "item-84"),
    "being-19": ("item-140", "item-32", "item-84", "item-138", "item-139"),
    "being-26": ("item-138", "item-139", "item-248"),
}
SETTINGS_KEYS = ("EnableUploads", "AllowCopyUploads", "AllowExternalImages",
                 "ReadOnly", "GroupPermissions", "CaptchaTriggers")


class PendingConsumerUpdate(RuntimeError):
    def __init__(self, message, consumer, owner, html, details=None):
        super().__init__(message)
        self.consumer, self.owner, self.html = consumer, owner, html
        self.details = details


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def baseline_metadata(raw):
    parse_document(raw, MAX_CATALOG_BYTES)
    return json.loads(raw.decode("utf-8"), parse_float=Decimal)


def only_pst(api, title, text, actor):
    result = api({"action": "parse", "title": title, "text": text, "contentmodel": "wikitext",
                  "onlypst": 1, "prop": "text", "assert": "user", "assertuser": actor["name"]}, post=True)
    transformed = result.get("parse", {}).get("text")
    if not isinstance(transformed, dict) or not isinstance(transformed.get("*"), str):
        raise RuntimeError("The only-PST response lacks its transformed text field.")
    return transformed["*"]


def validate_materialization_inputs(previous_authored, baseline, authored):
    for name, pages in (("previous authored", previous_authored), ("stored baseline", baseline), ("authored", authored)):
        if not isinstance(pages, dict):
            raise RuntimeError("Materialization requires an explicit " + name + " corpus.")
        if any(not isinstance(title, str) or not title or title_key(title) != title or not isinstance(text, str)
               for title, text in pages.items()):
            raise RuntimeError("Materialization has invalid or duplicate normalized " + name + " identities.")
    if previous_authored.keys() != baseline.keys() or not baseline.keys() <= authored.keys():
        raise RuntimeError("Materialization has missing or unknown previous-authored/stored baseline identities.")


def materialization_header(previous_authored, baseline, authored, desired, source_head, runtime, actor,
                           previous_source_head, evidence_kind):
    validate_materialization_inputs(previous_authored, baseline, authored)
    if any(not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head)
           for head in (previous_source_head, source_head)):
        raise RuntimeError("Materialization requires exact previous and current authored source commits.")
    if not isinstance(evidence_kind, str) or evidence_kind not in {"disposable-mediawiki", "synthetic-unit-fixture"}:
        raise RuntimeError("Storage materialization is not live execution authority.")
    return {
        "schema_version": 2, "receipt_type": "mediawiki-storage-materialization",
        "evidence_kind": evidence_kind, "acceptance": "terminal-crlf-only",
        "source_head_sha": source_head, "checkout_sha": source_head, "runtime": runtime, "actor": actor,
        "previous_source_head_sha": previous_source_head,
        "previous_authored_seed_sha256": hashlib.sha256(build_xml(previous_authored)).hexdigest(),
        "baseline_seed_sha256": hashlib.sha256(build_xml(baseline)).hexdigest(),
        "authored_seed_sha256": hashlib.sha256(build_xml(authored)).hexdigest(),
        "desired_seed_sha256": hashlib.sha256(build_xml(desired)).hexdigest(),
    }


def materialization_record(title, previous_authored, baseline, authored, desired):
    unchanged = title in previous_authored and previous_authored[title] == authored[title]
    classification = ("unchanged" if unchanged else "create" if title not in baseline
                      else "storage-noop" if desired[title] == baseline[title] else "update")
    return {
        "title": title, "classification": classification,
        "previous_authored_sha256": text_hash(previous_authored.get(title)),
        "baseline_sha256": text_hash(baseline.get(title)), "authored_sha256": text_hash(authored[title]),
        "desired_sha256": text_hash(desired[title]),
        "removed_suffix": None if unchanged else authored[title][len(desired[title]):],
        "only_pst_output": None if unchanged else desired[title],
    }


def verify_materialization(previous_authored, baseline, authored, desired, receipt, source_head, runtime, actor,
                           *, previous_source_head, evidence_kind):
    header = materialization_header(previous_authored, baseline, authored, desired, source_head, runtime, actor,
                                    previous_source_head, evidence_kind)
    if (not isinstance(receipt, dict) or set(receipt) != set(header) | {"pages"}
            or canonical_bytes({key: receipt[key] for key in header}) != canonical_bytes(header)):
        raise RuntimeError("Materialization source, runtime, actor, hash or schema pins differ.")
    if set(desired) != set(authored):
        raise RuntimeError("Materialization changed the complete managed title set.")
    if (not isinstance(receipt["pages"], list) or not all(isinstance(row, dict) for row in receipt["pages"])
            or [row.get("title") for row in receipt["pages"]] != sorted(authored)):
        raise RuntimeError("Materialization has incomplete or duplicate title records.")
    for row in receipt["pages"]:
        title = row["title"]
        text = authored[title]
        unchanged = title in previous_authored and previous_authored[title] == text
        expected = baseline[title] if unchanged else text.rstrip("\r\n")
        if desired[title] != expected:
            raise RuntimeError("Materialization changed more than approved terminal CR/LF or rewrote an unchanged page.")
        expected_row = materialization_record(title, previous_authored, baseline, authored, desired)
        if row != expected_row:
            raise RuntimeError("Materialization output, classification, suffix or per-title hashes differ.")


def materialize_desired(api, previous_authored, baseline, authored, source_head, runtime, actor,
                        *, previous_source_head, evidence_kind="disposable-mediawiki"):
    materialization_header(previous_authored, baseline, authored, {}, source_head, runtime, actor,
                           previous_source_head, evidence_kind)
    desired, records = {}, []
    for title, text in sorted(authored.items()):
        unchanged = title in previous_authored and previous_authored[title] == text
        output = baseline[title] if unchanged else only_pst(api, title, text, actor)
        if output != (baseline[title] if unchanged else text.rstrip("\r\n")):
            raise RuntimeError("Actual only-PST changed more than terminal CR/LF: " + title)
        desired[title] = output
        records.append(materialization_record(title, previous_authored, baseline, authored, desired))
    receipt = {**materialization_header(previous_authored, baseline, authored, desired, source_head, runtime, actor,
                                       previous_source_head, evidence_kind),
               "pages": records}
    verify_materialization(previous_authored, baseline, authored, desired, receipt, source_head, runtime, actor,
                           previous_source_head=previous_source_head, evidence_kind=evidence_kind)
    return desired, receipt


def managed_titles(api):
    return {row["title"] for namespace in (0, 14) for row in api({
        "action": "query", "list": "allpages", "apnamespace": namespace, "aplimit": "max",
    })["query"]["allpages"]}


def capture_installer_welcome(api, core_text, actor):
    if managed_titles(api) != {"Main Page"}:
        raise RuntimeError("Disposable bootstrap has unexpected preexisting managed pages.")
    page = next(iter(api({"action": "query", "titles": "Main Page", "prop": "revisions",
                          "rvprop": "ids|content|user", "rvslots": "main"})["query"]["pages"].values()))
    revision = page["revisions"][0]
    raw = revision["slots"]["main"]["*"]
    expected = only_pst(api, "Main Page", core_text, actor)
    if raw != expected or revision["parentid"] != 0 or revision["user"] != "MediaWiki default":
        raise RuntimeError("The disposable installer's welcome Main Page is not untouched; refusing deletion.")
    return {"title": page["title"], "pageid": page["pageid"], "revid": revision["revid"],
            "parentid": revision["parentid"], "user": revision["user"],
            "raw_sha256": text_hash(raw), "raw_wikitext": raw}


def settings_hash(value):
    if not isinstance(value, dict) or set(value) != set(SETTINGS_KEYS):
        raise RuntimeError("The effective-settings projection has unexpected keys.")
    if any(value[key] is not False for key in SETTINGS_KEYS[:3]):
        raise RuntimeError("A disabled-upload runtime invariant changed.")
    if value["ReadOnly"] is not None and not isinstance(value["ReadOnly"], (bool, str)) or not all(
        isinstance(value[key], dict) for key in ("GroupPermissions", "CaptchaTriggers")
    ):
        raise RuntimeError("The installed settings projection has unexpected value types: "
                           + ", ".join(key + "=" + type(value[key]).__name__ for key in SETTINGS_KEYS))
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def reconstruct_stored_baseline(previous_authored, previous_payload):
    binding = STORED_BASELINE_BINDING
    validate_materialization_inputs(previous_authored, previous_authored, previous_authored)
    if (len(previous_payload) != binding["previous_authored_seed_bytes"]
            or hashlib.sha256(previous_payload).hexdigest() != binding["previous_authored_seed_sha256"]
            or build_xml(previous_authored) != previous_payload
            or len(previous_authored) != binding["managed_title_count"]):
        raise RuntimeError("Previous authored corpus differs from the exact reviewed release seed.")
    exact = binding["exact_titles"]
    if (binding["historical_transform"] != "published-67c690f-terminal-lf-except-exact-titles"
            or len(set(exact)) != len(exact) or not set(exact) <= previous_authored.keys()):
        raise RuntimeError("The historical stored-baseline transform has unknown or duplicate identities.")
    # This exception is observed release evidence, not a generic MediaWiki storage rule.
    pages = {title: text if title in exact else text.rstrip("\n") for title, text in previous_authored.items()}
    removed = Counter(str(len(text) - len(pages[title])) for title, text in previous_authored.items())
    payload = build_xml(pages)
    if (dict(removed) != binding["removed_lf_counts"]
            or len(payload) != binding["baseline_seed_bytes"]
            or hashlib.sha256(payload).hexdigest() != binding["baseline_seed_sha256"]
            or hashlib.sha256(canonical_bytes(pages)).hexdigest() != binding["baseline_corpus_sha256"]):
        raise RuntimeError("Reconstructed stored baseline differs from the independently observed release binding.")
    return pages, payload


def reconstruct_baseline(root, workspace):
    tree = subprocess.check_output(["git", "rev-parse", PREVIOUS_AUTHORED_COMMIT + "^{tree}"],
                                   cwd=root, text=True).strip()
    if (tree != STORED_BASELINE_BINDING["previous_source_tree_sha"]
            or PREVIOUS_AUTHORED_COMMIT != STORED_BASELINE_BINDING["previous_source_head_sha"]):
        raise RuntimeError("The previous authored source tree differs from the release binding.")
    destination = workspace / "baseline-source"
    destination.mkdir()
    archive = subprocess.run(["git", "archive", PREVIOUS_AUTHORED_COMMIT], cwd=root,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for member in bundle:
            target = destination / member.name
            if not target.resolve().is_relative_to(destination.resolve()) or not (member.isdir() or member.isfile()):
                raise RuntimeError("The frozen baseline archive contains an unsafe entry.")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(bundle.extractfile(member).read())
    output = workspace / "previous-authored-seed.xml"
    subprocess.run([sys.executable, str(destination / "tools" / "build_wiki.py"),
                    "--fresh", "--output", str(output)], check=True, stdout=subprocess.PIPE)
    previous_payload = output.read_bytes()
    previous_authored = read_snapshot(output)
    pages, payload = reconstruct_stored_baseline(previous_authored, previous_payload)
    with (workspace / "baseline-seed.xml").open("xb") as stream:
        stream.write(payload)
    return (previous_authored, previous_payload, pages, payload,
            baseline_metadata((destination / "content" / "facts" / "catalog.json").read_bytes()))


def planned_order(baseline, desired, locations, baseline_prices, coins):
    cohort = [locations[identity] for identity in COHORT]
    allowed = {(locations[consumer], locations[owner]) for consumer, owners in COMPATIBILITY.items() for owner in owners}
    preserved = {locations[identity] for identity in baseline_prices | coins}
    pending = {title for title in desired if baseline.get(title) != desired[title]}
    if not set(baseline) <= set(desired) or not set(cohort) <= pending:
        raise RuntimeError("The rehearsal must preserve all baseline titles and include the complete cohort.")
    prerequisites = {}
    for title in pending:
        prerequisites[title] = {
            owner for owner, arguments in transclusions(desired[title])
            if arguments or not (owner in preserved or (title, owner) in allowed)
        }
        if title in cohort:
            prerequisites[title].update(cohort[:cohort.index(title)])
        if not prerequisites[title] <= desired.keys():
            raise RuntimeError("The planned sequence has an unknown selector prerequisite.")
    ready = {title for title in desired if baseline.get(title) == desired[title]}
    order = []
    while pending:
        candidates = sorted((title for title in pending if prerequisites[title] <= ready),
                            key=lambda title: (title in baseline, title))
        if not candidates:
            blocked = {title: sorted(prerequisites[title] - ready) for title in sorted(pending)}
            raise RuntimeError("Unresolved view-specific prerequisites: " + json.dumps(blocked))
        title = candidates[0]
        order.append(title)
        pending.remove(title)
        ready.add(title)
    return order


def projection_invocation(owner, parameters):
    return "{{:" + owner + "".join("|" + key + "=" + value for key, value in sorted(parameters.items())) + "}}"


class ProjectionDOM(HTMLParser):
    """Ordered visible cells/links for receipts, excluding implementation-specific URLs."""

    def __init__(self, title):
        super().__init__()
        self.title = title
        self.text = ""
        self.links = []
        self.non_wiki_links = []
        self.anchors = []
        self.rows = []
        self.wiki_links = []
        self.tables = []
        self.row = self.cell = self.link = None
        self.link_tag = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "table":
            self.tables.append([])
        elif tag == "tr":
            self.row = {"headers": list(self.tables[-1]) if self.tables else [], "cells": [], "ids": []}
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = {"text": "", "links": [], "anchors": []}
            self.row["cells"].append(self.cell)
            self.row["header"] = tag == "th"
        if identity := attrs.get("id"):
            self.anchors.append(identity)
            if self.row is not None:
                self.row["ids"].append(identity)
            if self.cell is not None:
                self.cell["anchors"].append(identity)
        if tag == "br":
            self.handle_data(" ")
        if tag == "a" or "selflink" in attrs.get("class", "").split():
            url = urllib.parse.urlsplit(attrs.get("href", ""))
            query = urllib.parse.parse_qs(url.query)
            selflink = "selflink" in attrs.get("class", "").split()
            href = attrs.get("href", "")
            if url.scheme or url.netloc or not (query.get("title") or href.startswith("#") or selflink):
                if href:
                    self.link = {"href": href, "text": ""}
                    self.link_tag = tag
                    self.non_wiki_links.append(self.link)
                    if self.cell is not None:
                        self.cell.setdefault("non_wiki_links", []).append(self.link)
                return
            target = query.get("title", [None])[0] or self.title
            if url.fragment:
                target = target.split("#", 1)[0] + "#" + urllib.parse.unquote(url.fragment)
            name, separator, fragment = target.partition("#")
            self.link = {"target": name.replace("_", " ") + separator + fragment, "text": ""}
            self.wiki_links.append({"target": self.link["target"].split("#", 1)[0],
                                    "redlink": "new" in attrs.get("class", "").split() or query.get("redlink") == ["1"],
                                    "href": href, "classes": attrs.get("class", "").split()})
            self.link_tag = tag
            self.links.append(self.link)
            if self.cell is not None:
                self.cell["links"].append(self.link)

    def handle_endtag(self, tag):
        if tag == self.link_tag:
            self.link = self.link_tag = None
        if tag in {"td", "th"}:
            self.cell = None
        if tag == "tr" and self.row is not None:
            if self.row.get("header") and self.tables:
                self.tables[-1] = [" ".join(cell["text"].split()) for cell in self.row["cells"]]
            else:
                self.rows.append(self.row)
            self.row = None
        if tag == "table" and self.tables:
            self.tables.pop()

    def handle_data(self, text):
        self.text += text
        if self.cell is not None:
            self.cell["text"] += text
        if self.link is not None:
            self.link["text"] += text

    def normalize(self):
        self.text = " ".join(self.text.split())
        for link in [*self.links, *self.non_wiki_links]:
            link["text"] = " ".join(link["text"].split())
        for row in self.rows:
            for cell in row["cells"]:
                cell["text"] = " ".join(cell["text"].split())
        return self


def dom(html, title):
    result = ProjectionDOM(title)
    result.feed(html)
    return result.normalize()


def check_pool_projection(html, pool, owner, locations, catalog, item=None, parse_title="Pool projection"):
    parsed = dom(html, parse_title)
    members = set(pool["eligible_item_ids"]) if item is None else {item} & set(pool["eligible_item_ids"])
    wanted = {"pool-item-" + pool["id"] + "-" + identity for identity in members}
    actual = [identity for identity in parsed.anchors if identity.startswith("pool-item-")]
    if set(actual) != wanted or len(actual) != len(wanted):
        raise RuntimeError("A pool view changed its exact membership.")
    for identity, condition in pool["item_conditions"].items():
        if (" ".join(condition.split()) in parsed.text) != (identity in members):
            raise RuntimeError("A pool view lost or leaked an item-specific story gate.")
    if item is not None:
        gate = pool["item_conditions"].get(item)
        expected = ((locations[item] + ": " + gate + " ") if gate else "") + pool["title"] + " (eligible)" if members else ""
        expected_links = ([locations[item]] if gate else []) + [owner + "#pool-" + pool["id"]] if members else []
        if (parsed.text != expected or parsed.rows or re.search(r"<(?:table|img|h[1-6])\b", html, re.I)
                or [link["target"] for link in parsed.links] != expected_links or parsed.non_wiki_links):
            raise RuntimeError("An item pool view changed its compact eligibility-only reference.")
    else:
        categories = {identity: group["title"] for group in catalog.get("taxonomy", {}).get("groups", [])
                      if group["index"] == "Items" for identity in group["members"]}
        if len(parsed.rows) != len(members):
            raise RuntimeError("A pool candidate table omitted or duplicated rows.")
        for row in parsed.rows:
            if len(row["ids"]) != 1 or row["ids"][0] not in wanted or len(row["cells"]) != 2:
                raise RuntimeError("A pool candidate table changed its two-column shape.")
            identity = row["ids"][0].removeprefix("pool-item-" + pool["id"] + "-")
            category = categories.get(identity)
            links = [locations[identity]]
            if identity in pool["item_conditions"]:
                links.append(owner + "#treasure-condition-" + identity)
            if ([link["target"] for link in row["cells"][0]["links"]] != links
                    or row["headers"] != ["Item", "Category"]
                    or row["cells"][1]["text"] != (category or "Item")
                    or [link["target"] for link in row["cells"][1]["links"]] != (["Category:" + category] if category else [])):
                raise RuntimeError("A pool candidate changed its item, category or condition link.")
    return parsed


def linked_titles(text):
    return {title_key(target.lstrip(":").split("#", 1)[0]) for target in re.findall(r"\[\[([^\]|]+)", text)
            if target.lstrip(":").split("#", 1)[0]}


def strip_colon_invocations(text):
    matches = list(re.finditer(r"\{\{:([^{}\n]+)\}\}", text))
    if len(matches) != text.count("{{:"):
        raise RuntimeError("Endpoint source contains unmatched or dynamic colon-inclusion syntax.")
    pieces, spans, previous = [], [], 0
    for match in matches:
        owner, arguments = transclusions(match.group())[0]
        start = len(text[:match.start()].encode("utf-8"))
        spans.append({
            "start_byte": start, "end_byte": start + len(match.group().encode("utf-8")),
            "invocation": match.group(), "owner": owner, "parameters": dict(arguments),
        })
        pieces.append(text[previous:match.start()])
        previous = match.end()
    pieces.append(text[previous:])
    return "".join(pieces), spans


class Rehearsal:
    def __init__(self, api, checks, baseline, desired, data, catalog, old_catalog, runtime, source_head,
                 *, incremental=False):
        self.incremental = incremental
        self.api, self.checks = api, checks
        self.baseline, self.desired, self.current = baseline, desired, dict(baseline)
        self.data, self.catalog = data, catalog
        self.locations = page_locations(data, catalog)
        self.entities = {title: identity for identity, title in self.locations.items()}
        self.old_prices = {row["entity"]: row["value"] for row in old_catalog["unit_prices"]["prices"]}
        self.prices = {row["entity"]: row["value"] for row in catalog["unit_prices"]["prices"]}
        self.coins = {row["entity"]: row for row in catalog["currency"]["coins"]}
        for identity, value in self.old_prices.items():
            if self.prices.get(identity) != value:
                raise RuntimeError(f"A preserved baseline standard price changed: {identity}: "
                                   f"{value!r} != {self.prices.get(identity)!r}")
        self.owners = entry_owners(data, self.locations, entry_relations(data, catalog), catalog)
        self.groups = recipe_groups([display_entry(row, catalog) for row in data["entries"] if row["kind"] == "recipe"])
        self.stations = {method: station for station in catalog["stations"] for method in station["methods"]}
        self.sources = {row["title"]: row for row in catalog["acquisition"]["sources"]}
        self.pools = {row["id"]: row for row in catalog["acquisition"]["pools"]}
        if incremental:
            from smoke_incremental import incremental_order
            self.order = incremental_order(baseline, desired)
        else:
            self.order = planned_order(baseline, desired, self.locations, self.old_prices.keys(), self.coins.keys())
        self.cohort = [] if incremental else [self.locations[identity] for identity in COHORT]
        self.allowed = {(self.locations[consumer], self.locations[owner])
                        for consumer, owners in COMPATIBILITY.items() for owner in owners} if not incremental else set()
        self.base_meta = None
        self.metadata = {}
        self.revisions = {}
        self.pageids = {}
        self.probes = []
        self.cache = {}
        self.prefixes = []
        self.compatibility = []
        self.snapshots = []
        self.settling = []
        self.link_candidates = {}
        self.endpoint_rows = {}
        self.endpoint_projections = {}
        self.provenance = {
            "schema_version": 1, "evidence_kind": "disposable-mediawiki",
            "source_head_sha": source_head, "checkout_sha": source_head,
            "baseline_seed_sha256": hashlib.sha256(build_xml(baseline)).hexdigest(),
            "desired_seed_sha256": hashlib.sha256(build_xml(desired)).hexdigest(), "runtime": runtime,
        }

    def refresh_metadata(self):
        previous_max = max(self.revisions, default=0)
        titles = sorted(self.current)
        for offset in range(0, len(titles), 50):
            seen = set()
            result = self.api({"action": "query", "titles": "|".join(titles[offset:offset + 50]),
                               "prop": "revisions", "rvprop": "ids|content", "rvslots": "main"})
            for page in result["query"]["pages"].values():
                title = page["title"]
                if self.incremental and (title not in titles[offset:offset + 50] or title in seen
                                         or "missing" in page or "invalid" in page):
                    raise RuntimeError("Incremental readback contains missing/duplicate/unknown identities.")
                seen.add(title)
                revision = page["revisions"][0]
                raw = revision["slots"]["main"]["*"]
                if raw != self.current[title]:
                    expected = self.current[title]
                    raise RuntimeError(f"Current text differs for {title}: lengths {len(raw)}/{len(expected)}, "
                                       f"hashes {text_hash(raw)}/{text_hash(expected)}, "
                                       f"tails {raw[-100:]!r}/{expected[-100:]!r}, "
                                       f"trailing-whitespace-only={raw.rstrip() == expected.rstrip()}")
                record = {"title": title, "pageid": page["pageid"], "revid": revision["revid"],
                          "parentid": revision["parentid"], "raw_sha256": text_hash(raw)}
                old = self.metadata.get(title)
                fingerprint = (title, record["pageid"], record["parentid"], record["raw_sha256"])
                if record["revid"] in self.revisions and self.revisions[record["revid"]] != fingerprint:
                    raise RuntimeError("A revision identity was reused for different page content.")
                if title in self.pageids and self.pageids[title] != record["pageid"]:
                    raise RuntimeError("A page identity moved during the rehearsal.")
                if old and old != record and (record["revid"] <= previous_max or record["parentid"] != old["revid"]):
                    raise RuntimeError("A prefix pointer did not advance from its exact prior revision.")
                if old is None and self.base_meta is not None and record["revid"] <= previous_max:
                    raise RuntimeError("A newly created title reused an earlier revision identity.")
                self.revisions[record["revid"]] = fingerprint
                self.pageids[title] = record["pageid"]
                self.metadata[title] = record
            if self.incremental and seen != set(titles[offset:offset + 50]):
                raise RuntimeError("Incremental readback omitted owned titles.")
        if self.base_meta is None:
            self.base_meta = dict(self.metadata)

    def dependency_revisions(self, templates):
        if not set(templates) <= self.metadata.keys():
            raise RuntimeError("A parser dependency falls outside the frozen managed titles.")
        return [{key: self.metadata[title][key] for key in ("title", "pageid", "revid", "raw_sha256")}
                for title in sorted(set(templates))]

    def validate_projection(self, owner, parameters, result, parse_title="Prefix projection"):
        html = result["text"]["*"]
        self.checks.check_parser_errors(html)
        templates = sorted(row["*"] for row in result.get("templates", []))
        if templates != [owner]:
            raise RuntimeError("A selected projection is not a parser-proven leaf: " + owner + str(parameters))
        parsed = dom(html, parse_title)
        view = parameters.get("view", "")
        identity = self.entities.get(owner)
        if not parameters:
            if identity in self.coins:
                rows = self.checks.RenderedRows("coin-", "coin-", page_title=parse_title)
                rows.feed(html)
                coin = self.coins[identity]
                wanted = [self.locations[identity], self.checks.scalar(coin["value_in_silver"]),
                          self.checks.scalar(coin["weight_grams"]) + " g", str(coin["stack_limit"])]
                if len(rows.rows) != 1 or [self.checks.plain(cell["text"]) for cell in rows.rows[0]["cells"]] != wanted:
                    raise RuntimeError("A default coin summary changed its four canonical cells.")
            elif identity in self.prices:
                if self.current[owner] == self.baseline.get(owner) and identity not in self.old_prices:
                    if parsed.text != "Not established":
                        raise RuntimeError("A scoped old unknown price leaked content or invented a value.")
                else:
                    self.checks.check_price_cell({"text": parsed.text}, self.prices[identity])
                if parsed.anchors or parsed.rows or any(link["text"] for link in parsed.links):
                    raise RuntimeError("A default price leaked article links, anchors or tables.")
            else:
                raise RuntimeError("An unregistered default inclusion was requested.")
        elif view == "recipes":
            station = next(row for row in self.catalog["stations"] if row["id"] == parameters["station"])
            expected = [group for group in self.groups if self.owners[group[0]["id"]] == owner
                        and any(row["details"]["station"] in station["methods"] for row in group)]
            rows = self.checks.RenderedRows(page_title=parse_title)
            rows.feed(html)
            if {frozenset(row["entries"]) for row in rows.rows} != {
                frozenset(row["id"] for row in group) for group in expected
            } or len(rows.rows) != len(expected):
                raise RuntimeError("A prerequisite recipe view has incorrect variant membership.")
            for row in rows.rows:
                group = next(group for group in expected if group[0]["id"] in row["entries"])
                self.checks.check_recipe_cells(row, group, self.locations, self.stations)
            expected_actions = {row["id"]: row for row in self.catalog.get("construction_recipes", [])
                                if self.locations[row["owner_item"]] == owner and row["station_id"] == station["id"]}
            actions = self.checks.RenderedRows("entry-construction-", "entry-", page_title=parse_title)
            actions.feed(html)
            if {key for row in actions.rows for key in row["entries"]} != expected_actions.keys() or len(actions.rows) != len(expected_actions):
                raise RuntimeError("A prerequisite in-place action view has incorrect membership.")
            for row in actions.rows:
                self.checks.check_construction_cells(row, expected_actions[next(iter(row["entries"]))], self.locations)
        elif view in {"offers", "loot"}:
            kind = "merchant" if view == "offers" else "loot"
            field = "item" if view == "offers" else "outcome"
            wanted = {"entry-" + row["id"] for row in self.data["entries"] if row["kind"] == kind
                      and self.owners[row["id"]] == owner and (row["details"][field] or "empty") == parameters["item"]}
            if view == "loot":
                wanted |= {"acquisition-" + row["id"] for row in self.sources.get(owner, {}).get("rows", [])
                           if row["item"] == parameters["item"]}
            prefixes = ("entry-merchant-",) if view == "offers" else ("entry-loot-", "entry-corpse-", "acquisition-")
            actual = [identity for identity in parsed.anchors if identity.startswith(prefixes)]
            if set(actual) != wanted or len(actual) != len(wanted) or not wanted:
                raise RuntimeError("A prerequisite source view changed its exact record membership.")
            if view == "offers" and "Unit price" in parsed.text:
                raise RuntimeError("A selected seller view exposed default-price recursion.")
            context = self.sources.get(owner, {}).get("loot_context")
            if view == "loot" and context and self.checks.plain(context) not in parsed.text:
                raise RuntimeError("A prerequisite source omitted its canonical shared qualification.")
        elif view == "pool":
            pool = self.pools[parameters["pool"]]
            check_pool_projection(html, pool, owner, self.locations, self.catalog, parameters.get("item"), parse_title)
        elif view == "stock":
            rules = {row["id"]: row for row in self.catalog.get("currency", {}).get("rules", [])}
            rule = rules.get("trade-stock-and-funds")
            if (owner != "Currency and trading" or parameters != {"view": "stock"} or rule is None
                    or parsed.text != self.checks.plain(rule["text"]) or parsed.rows or parsed.anchors
                    or parsed.links or parsed.non_wiki_links or re.search(r"<(?:table|img|h[1-6])\b", html, re.I)):
                raise RuntimeError("A prerequisite stock view changed its exact rule-only contract.")
        elif view == "pool-source":
            reference = next(row for row in self.sources[owner]["pool_refs"] if row["pool"] == parameters["pool"])
            if parsed.text != owner + ": " + self.checks.plain(reference["condition"]) or parsed.rows:
                raise RuntimeError("A prerequisite pool-source view changed its exact condition-only contract.")
        else:
            raise RuntimeError("An unregistered named inclusion was requested.")

    def probe(self, consumer, owner, arguments, fresh=False):
        parameters = dict(arguments)
        if owner not in self.current:
            raise RuntimeError("A required selector owner does not exist yet.")
        desired = self.current[owner] == self.desired[owner]
        if desired:
            kind = "desired-leaf-projection"
        elif not parameters and self.entities.get(owner) in self.old_prices.keys() | self.coins.keys():
            kind = "preserved-baseline-default"
        elif not parameters and (consumer, owner) in self.allowed:
            kind = "six-price-compatibility-only"
        else:
            raise RuntimeError("A required named view is not ready at this actual prefix.")
        if parameters.get("view", "") not in available_views(self.current[owner]):
            raise RuntimeError("A required view is not structurally declared by its current owner.")
        key = (owner, tuple(arguments), self.metadata[owner]["revid"])
        if key in self.cache and not fresh:
            return self.cache[key]
        invocation = projection_invocation(owner, parameters)
        expanded = self.api({"action": "expandtemplates", "title": "Prefix projection",
                             "text": invocation, "prop": "wikitext"}, post=True)["expandtemplates"]["wikitext"]
        render_text = "<table>" + invocation + "</table>" if parameters.get("view") == "recipes" else invocation
        result = self.api({"action": "parse", "title": "Prefix projection", "text": render_text,
                           "prop": "text|templates"}, post=True)["parse"]
        self.validate_projection(owner, parameters, result)
        evidence = {
            "id": len(self.probes), "owner": dict(self.metadata[owner]), "parameters": parameters, "kind": kind,
            "expanded_wikitext": expanded, "projection_sha256": text_hash(expanded),
            "html": result["text"]["*"], "render_context": "table" if parameters.get("view") == "recipes" else "block",
            "templates": sorted(row["*"] for row in result.get("templates", [])),
        }
        self.probes.append(evidence)
        self.cache[key] = evidence
        return evidence

    def inspect_consumer(self, title):
        result = self.api({"action": "parse", "page": title, "prop": "text|templates|links|revid"})["parse"]
        self.last_consumer_html = result["text"]["*"]
        if result.get("revid") != self.metadata[title]["revid"]:
            raise RuntimeError("A consumer parse is not bound to its captured current revision.")
        self.checks.check_parser_errors(result["text"]["*"])
        probes = [self.probe(title, owner, arguments) for owner, arguments in transclusions(self.current[title])]
        templates = sorted(row["*"] for row in result.get("templates", []))
        if set(templates) != {probe["owner"]["title"] for probe in probes}:
            raise RuntimeError("A full consumer has unexpected or missing transclusion dependencies: " + title)
        parsed = dom(result["text"]["*"], title)
        pending_links = sorted({link["target"] for link in parsed.wiki_links
                                if link["target"] in self.desired and link["target"] not in self.current})
        for link in parsed.wiki_links:
            if link["target"] in self.desired and link["redlink"] != (link["target"] not in self.current):
                if link["target"] in self.current and link["redlink"]:
                    raise PendingConsumerUpdate("A created target still has cached redlink HTML: " + title + " -> " + link["target"],
                                                title, link["target"], result["text"]["*"], {"link": link})
                raise RuntimeError("A consumer has a stale or dishonest planned-title link: " + title + " -> " + link["target"])
        for probe in probes:
            if not probe["parameters"]:
                continue
            selected = dom(probe["html"], probe.get("parse_title", "Prefix projection"))
            for row in selected.rows:
                ids = set(row["ids"])
                if ids and not any(ids <= set(actual["ids"]) and row["cells"] == actual["cells"] for actual in parsed.rows):
                    raise PendingConsumerUpdate("A cached consumer row differs from its current selected view: " + title + str(probe["parameters"]),
                                                title, probe["owner"]["title"], result["text"]["*"], {
                                                    "parameters": probe["parameters"], "row_ids": sorted(ids),
                                                    "expected_cells": row["cells"],
                                                    "observed_rows": [actual for actual in parsed.rows if ids & set(actual["ids"])],
                                                })
            if probe["parameters"]["view"] in {"pool-source", "stock"} and selected.text not in parsed.text:
                raise RuntimeError("A consumer omitted its source-owned condition or stock rule.")
        self.check_merchant_rows(title, parsed, result["text"]["*"])
        return {"consumer": dict(self.metadata[title]), "html_sha256": text_hash(result["text"]["*"]),
                "templates": templates, "dependency_revisions": self.dependency_revisions(templates),
                "probe_ids": [probe["id"] for probe in probes],
                "pending_planned_new_targets": pending_links,
                "links": [{"title": row["*"], "exists": "exists" in row} for row in result.get("links", [])]}

    def check_merchant_rows(self, title, parsed, html):
        for entry in self.data["entries"]:
            if entry["kind"] != "merchant" or self.owners[entry["id"]] != title:
                continue
            rows = [row for row in parsed.rows if "entry-" + entry["id"] in row["ids"]]
            if len(rows) != 1 or rows[0]["headers"].count("Unit price") != 1:
                raise RuntimeError("A current merchant lost its exact offer/price-column identity.")
            cell = rows[0]["cells"][rows[0]["headers"].index("Unit price")]
            item = entry["details"]["item"]
            owner = self.locations[item]
            if self.current[owner] == self.baseline.get(owner) and item not in self.old_prices:
                if (title, owner) not in self.allowed or cell["text"] != "Not established":
                    raise RuntimeError("An unknown merchant price escaped its eleven-edge compatibility scope.")
            else:
                if item not in self.old_prices and cell["text"] == "Not established":
                    raise PendingConsumerUpdate("An established price still has its old cached unknown value.",
                                                title, owner, html, {"entry_id": entry["id"],
                                                                   "expected_price": self.checks.scalar(self.prices[item]),
                                                                   "observed_cell": cell})
                self.checks.check_price_cell(cell, self.prices[item])

    def observe_consumers(self, titles, drain_jobs, job_status=None):
        deadline = time.monotonic() + 90
        original_api = self.api
        last_pending = None
        last_drain = None

        def remaining():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError("The 90-second consumer observation budget expired.")
            return seconds

        def bounded_api(parameters, **kwargs):
            result = original_api(parameters, timeout=min(30, remaining()), **kwargs)
            remaining()
            return result

        def diagnose(reason):
            queue = None
            if job_status is not None:
                try:
                    queue = job_status(timeout=5)
                except (TimeoutError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                    queue = {"unavailable": type(error).__name__}
            report = {
                "prefix_index": len(self.prefixes), "status": "failed", "reason": reason,
                "budget_seconds": 90, "queue_diagnostic_budget_seconds": 5, "queue": queue,
                "last_job_drain": last_drain,
                "last_observed_mismatch": None if last_pending is None else {
                    key: value for key, value in last_pending.items() if key != "html"
                },
            }
            self.settling.append(report)
            print("Settlement diagnostics:", json.dumps(report), flush=True)

        self.api = bounded_api
        try:
            for attempt in range(10):
                try:
                    observations = []
                    for title in sorted(titles):
                        remaining()
                        observations.append(self.inspect_consumer(title))
                        remaining()
                    if attempt:
                        self.settling.append({
                            "prefix_index": len(self.prefixes), "status": "settled", "attempt": attempt + 1,
                            "observed_at": self.api({"action": "query", "curtimestamp": 1})["curtimestamp"],
                            "consumers": sorted(titles),
                        })
                    return observations
                except PendingConsumerUpdate as error:
                    status = self.api({"action": "query", "titles": error.consumer + "|" + error.owner,
                                       "prop": "info|revisions", "rvprop": "ids|timestamp", "curtimestamp": 1})
                    last_pending = {
                        "prefix_index": len(self.prefixes), "status": "pending", "attempt": attempt + 1,
                        "observed_at": status["curtimestamp"], "reason": str(error), "details": error.details,
                        "consumer": dict(self.metadata[error.consumer]), "owner": dict(self.metadata[error.owner]),
                        "html": error.html, "html_sha256": text_hash(error.html),
                        "cache_timestamps": re.findall(r"(?:Cached time:|timestamp)\s*(\d{14})", error.html),
                        "page_info": [{key: row[key] for key in ("title", "pageid", "lastrevid", "touched", "revisions") if key in row}
                                      for row in sorted(status["query"]["pages"].values(), key=lambda row: row["title"])],
                    }
                    self.settling.append(last_pending)
                    if attempt == 9:
                        diagnose(str(error))
                        raise
                    time.sleep(min(2, remaining()))
                    remaining()
                    last_drain = drain_jobs(timeout=remaining())
                    remaining()
                    last_pending["job_drain"] = last_drain
                    last_pending["server_tick"] = self.checks.wait_for_server_tick(
                        self.api, minimum=last_pending["observed_at"],
                    )
                    remaining()
        except (TimeoutError, subprocess.TimeoutExpired) as error:
            diagnose(type(error).__name__ + ": " + str(error))
            raise
        finally:
            self.api = original_api

    def compatibility_observation(self, consumer, owner):
        projection = self.probe(consumer, owner, (), fresh=True)
        selected = dom(projection["html"], "Prefix projection")
        result = self.api({"action": "parse", "page": consumer, "prop": "text|templates|revid"})["parse"]
        if result.get("revid") != self.metadata[consumer]["revid"]:
            raise RuntimeError("A price consumer parse is not bound to its captured current revision.")
        self.checks.check_parser_errors(result["text"]["*"])
        parsed = dom(result["text"]["*"], consumer)
        entry = next(row for row in self.data["entries"] if row["kind"] == "merchant"
                     and self.owners[row["id"]] == consumer and self.locations[row["details"]["item"]] == owner)
        row = next(row for row in parsed.rows if "entry-" + entry["id"] in row["ids"])
        templates = sorted({item["*"] for item in result.get("templates", [])})
        observed = {
            "expanded_wikitext": projection["expanded_wikitext"], "price_text": selected.text,
            "price_links": selected.links, "price_anchors": selected.anchors,
            "headers": row["headers"], "cells": row["cells"],
            "projection_templates": projection["templates"], "templates": templates,
        }
        identities = {}
        for role, title in (("consumer", consumer), ("owner", owner)):
            identities[role] = {key: self.metadata[title][key] for key in ("title", "pageid", "revid", "raw_sha256")}
            identities[role].update(entity=self.entities[title],
                                    state="desired" if self.current[title] == self.desired[title] else "baseline")
        return {**identities, "parameters": {}, "observed": observed,
                "dependency_revisions": self.dependency_revisions(set(templates) | set(projection["templates"]))}

    def capture_cohort(self, index):
        observations = [self.compatibility_observation(consumer, owner) for consumer, owner in sorted(self.allowed)]
        dependencies = {row["title"] for observation in observations for row in observation["dependency_revisions"]}
        self.compatibility.append({"index": index, "applied_titles": self.cohort[:index], "observations": observations})
        self.snapshots.append({"index": index, "pages": [dict(self.metadata[title]) for title in sorted(dependencies | set(self.cohort))]})

    def capture_endpoint(self, state):
        # Independent endpoint captures are composed into mixed expectations; never copy intermediate observations.
        self.endpoint_rows[state] = {}
        self.endpoint_projections[state] = {}
        for consumer, owner in sorted(self.allowed):
            observation = self.compatibility_observation(consumer, owner)
            observed = observation["observed"]
            self.endpoint_rows[state][(consumer, owner)] = {
                key: observed[key] for key in ("headers", "cells", "templates")
            }
            self.endpoint_projections[state][owner] = {
                key: observed[key] for key in ("expanded_wikitext", "price_text", "price_links", "price_anchors", "projection_templates")
            }

    def capture_link_endpoint(self, endpoint):
        before = {title: dict(record) for title, record in self.metadata.items()}
        user = self.api({"action": "query", "meta": "userinfo"})["query"]["userinfo"]
        actor = {"id": user["id"], "name": user["name"]}
        if actor["id"] <= 0:
            raise RuntimeError("Endpoint candidates require the authenticated test operator context.")
        captures = {"revisions_before": before, "direct": [], "originals": [], "selected": [],
                    "unsupported": [], "discrepancies": [], "actor": actor}
        queries = {}
        for corpus in (self.baseline, self.desired):
            for consumer, text in corpus.items():
                for owner, arguments in transclusions(text):
                    queries.setdefault((owner, arguments), set()).add(consumer)
        if getattr(self, "incremental", False):
            for owner in self.registry["prices"].keys() | self.registry["coins"].keys():
                queries.setdefault((owner, ()), set())

        def targets(links):
            return {row["*"] for row in links if row["*"] in self.desired}

        def rendered(result, title, reference):
            html = result["text"]["*"]
            self.checks.check_parser_errors(html)
            parsed = dom(html, title)
            api_targets = targets(result.get("links", []))
            dom_targets = {row["target"] for row in parsed.wiki_links if row["target"] in self.desired}
            if api_targets != dom_targets:
                captures["discrepancies"].append({
                    "kind": "api-dom-targets", "reference": reference,
                    "api_only": sorted(api_targets - dom_targets), "dom_only": sorted(dom_targets - api_targets),
                })
            for link in parsed.wiki_links:
                if link["target"] in self.desired and link["redlink"] != (link["target"] not in self.current):
                    captures["discrepancies"].append({
                        "kind": "dom-existence", "reference": reference, "link": link,
                        "target_exists": link["target"] in self.current,
                    })
            return {"html": html, "links": result.get("links", []),
                    "templates": sorted({row["*"] for row in result.get("templates", [])}),
                    "dom_links": parsed.wiki_links, "non_wiki_links": parsed.non_wiki_links}

        selected = {}
        for (owner, arguments), consumers in sorted(queries.items()):
            parameters = dict(arguments)
            contexts = sorted({"Prefix projection", *consumers}, key=lambda title: (title != "Prefix projection", title))
            if owner not in self.current or parameters.get("view", "") not in available_views(self.current[owner]):
                captures["unsupported"].append({
                    "owner": owner, "parameters": parameters, "parse_titles": contexts,
                    "owner_revision": self.metadata.get(owner),
                    "reason": "owner-absent" if owner not in self.current else "view-not-declared",
                })
                continue
            if endpoint == "baseline" and parameters and not getattr(self, "incremental", False):
                raise RuntimeError("The reviewed baseline may expose only its genuine default contracts.")
            neutral = None
            invocation = projection_invocation(owner, parameters)
            parse_input = "<table>" + invocation + "</table>" if parameters.get("view") == "recipes" else invocation
            for title in contexts:
                expanded = self.api({"action": "expandtemplates", "title": title, "text": invocation,
                                     "prop": "wikitext", "assert": "user", "assertuser": actor["name"]}, post=True)["expandtemplates"]["wikitext"]
                result = self.api({"action": "parse", "title": title, "text": parse_input,
                                   "prop": "text|templates|links", "assert": "user", "assertuser": actor["name"]}, post=True)["parse"]
                self.validate_projection(owner, parameters, result, title)
                record = {
                    "owner": dict(self.metadata[owner]), "parameters": parameters, "parse_title": title,
                    "invocation": invocation, "expanded_wikitext": expanded, "projection_sha256": text_hash(expanded),
                    "parse_input": parse_input, "parse_input_sha256": text_hash(parse_input),
                    "render_context": "table" if parameters.get("view") == "recipes" else "block",
                    **rendered(result, title, {"kind": "selected", "owner": owner, "parameters": parameters, "parse_title": title}),
                }
                if neutral is None:
                    neutral = record
                elif (expanded != neutral["expanded_wikitext"] or targets(record["links"]) != targets(neutral["links"])):
                    captures["discrepancies"].append({
                        "kind": "projection-context", "owner": owner, "parameters": parameters, "parse_title": title,
                        "neutral_sha256": neutral["projection_sha256"], "context_sha256": record["projection_sha256"],
                        "neutral_targets": sorted(targets(neutral["links"])), "context_targets": sorted(targets(record["links"])),
                    })
                selected[(owner, arguments, title)] = record
                captures["selected"].append(record)

        for title, text in sorted(self.current.items()):
            transformed, spans = strip_colon_invocations(text)
            result = self.api({"action": "parse", "title": title, "text": transformed,
                               "prop": "text|templates|links", "assert": "user", "assertuser": actor["name"]}, post=True)["parse"]
            direct = {
                "consumer": dict(self.metadata[title]), "parse_title": title,
                "transformed_text": transformed, "transformed_sha256": text_hash(transformed),
                "removed_invocations": spans,
                **rendered(result, title, {"kind": "direct", "consumer": title}),
            }
            if direct["templates"]:
                raise RuntimeError("A span-exact direct endpoint preview still transcludes another page.")
            captures["direct"].append(direct)
            result = self.api({"action": "parse", "page": title, "prop": "text|templates|links|revid"})["parse"]
            if result.get("revid") != self.metadata[title]["revid"]:
                raise RuntimeError("An endpoint original parse is not bound to its captured revision.")
            original = {"consumer": dict(self.metadata[title]),
                        **rendered(result, title, {"kind": "original", "consumer": title})}
            captures["originals"].append(original)
            combined = targets(direct["links"])
            for owner, arguments in transclusions(text):
                key = (owner, arguments, title)
                if key not in selected:
                    raise RuntimeError("An endpoint consumer requires an unsupported selected view.")
                combined |= targets(selected[key]["links"])
            if combined != targets(original["links"]):
                captures["discrepancies"].append({
                    "kind": "direct-projected-union", "consumer": title, "combined_targets": sorted(combined),
                    "original_targets": sorted(targets(original["links"])),
                })
        self.refresh_metadata()
        after = {title: dict(record) for title, record in self.metadata.items()}
        user = self.api({"action": "query", "meta": "userinfo"})["query"]["userinfo"]
        if before != after or actor != {"id": user["id"], "name": user["name"]}:
            raise RuntimeError("An endpoint owner, consumer revision or parser user changed during read-only capture.")
        captures["revisions_after"] = after
        captures["candidate_promotion_blocked"] = bool(captures["discrepancies"])
        self.link_candidates[endpoint] = captures
        print(f"ENDPOINT_CANDIDATE {endpoint}: {len(captures['selected'])} context projections, "
              f"{len(captures['discrepancies'])} explicit discrepancies; independent review required.", flush=True)

    def run(self, save, wait_tick, drain_jobs, job_status, accept):
        self.refresh_metadata()
        self.capture_endpoint("baseline")
        self.capture_link_endpoint("baseline")
        baseline_observations = [self.inspect_consumer(title) for title in sorted(self.current)]
        self.prefixes.append({"index": 0, "saved": None, "prerequisites": [], "observations": baseline_observations,
                              "pending_new_link_edges": self.pending_link_edges()})
        self.capture_cohort(0)
        cohort_index = 0
        for index, title in enumerate(self.order, 1):
            prerequisites = [self.probe(title, owner, arguments) for owner, arguments in transclusions(self.desired[title])]
            wait_tick(self.api)
            revision_id = save(title, self.metadata, self.desired[title], prerequisites)
            self.current[title] = self.desired[title]
            drain_jobs()
            self.refresh_metadata()
            if revision_id != self.metadata[title]["revid"]:
                raise RuntimeError("The saved revision is not the observed current pointer.")
            affected = {title}
            affected.update(consumer for consumer, text in self.current.items()
                            if title in {owner for owner, _ in transclusions(text)} or title in linked_titles(text))
            observations = self.observe_consumers(affected, drain_jobs, job_status)
            self.prefixes.append({"index": index, "saved": dict(self.metadata[title]),
                                  "prerequisites": [probe["id"] for probe in prerequisites], "observations": observations,
                                  "pending_new_link_edges": self.pending_link_edges()})
            if title in self.cohort:
                if title != self.cohort[cohort_index]:
                    raise RuntimeError("The actual sequence violated the frozen compatibility cohort order.")
                cohort_index += 1
                self.capture_cohort(cohort_index)
            guard = {"prefix": self.prefixes[-1], "price_prefix": self.compatibility[-1],
                     "prerequisite_checks": prerequisites}
            if index < len(self.order):
                accept(index, guard)
            else:
                self.pending_final_guard = guard
            print(f"PREFIX_PROGRESS {index}/{len(self.order)} {title}", flush=True)
        if self.current != self.desired or cohort_index != 9:
            raise RuntimeError("The full planned sequence did not reach the exact desired corpus.")
        self.capture_endpoint("desired")
        self.capture_link_endpoint("desired")
        self.final_observations = [self.inspect_consumer(title) for title in sorted(self.current)]
        final_projections = {}
        for probe in list(self.probes):
            if probe["kind"] != "desired-leaf-projection":
                continue
            key = (probe["owner"]["title"], tuple(sorted(probe["parameters"].items())))
            if key not in final_projections:
                final_projections[key] = self.probe("", *key, fresh=True)
            final = final_projections[key]
            if probe["projection_sha256"] != final["projection_sha256"]:
                raise RuntimeError("A prerequisite leaf projection changed between its prefix and final desired state.")

    def pending_link_edges(self):
        return [{"page": title, "target": target} for title, text in sorted(self.current.items())
                for target in sorted(linked_titles(text) & (self.desired.keys() - self.current.keys()))]

    def artifacts(self):
        reviewed = {**self.provenance, "order": self.cohort,
                    "versions": {title: {"baseline": text_hash(self.baseline[title]), "desired": text_hash(self.desired[title])}
                                 for title in self.cohort},
                    "projections": {owner: {state: self.endpoint_projections[state][owner] for state in ("baseline", "desired")}
                                    for owner in self.cohort[3:]}, "prefixes": []}
        for prefix, snapshot in zip(self.compatibility, self.snapshots):
            expected = []
            for observation in prefix["observations"]:
                consumer, owner = observation["consumer"]["title"], observation["owner"]["title"]
                consumer_state, owner_state = observation["consumer"]["state"], observation["owner"]["state"]
                source = self.endpoint_rows[consumer_state][(consumer, owner)]
                cells = json.loads(json.dumps(source["cells"]))
                price_index = source["headers"].index("Unit price")
                price_source = self.endpoint_rows[owner_state][(consumer, owner)]
                cells[price_index] = json.loads(json.dumps(price_source["cells"][price_source["headers"].index("Unit price")]))
                projected = self.endpoint_projections[owner_state][owner]
                observed = {**projected, "headers": source["headers"], "cells": cells, "templates": source["templates"]}
                dependency_titles = sorted(set(observed["templates"]) | set(observed["projection_templates"]))
                expected.append({"consumer": consumer, "owner": owner, "observed": observed, "dependency_titles": dependency_titles})
                if observed != observation["observed"]:
                    raise RuntimeError("An actual intermediate price row differs from independently composed endpoint expectations.")
                boundaries = sorted((0, self.cohort.index(consumer) + 1, self.cohort.index(owner) + 1, 10))
                first, last = next((left, right - 1) for left, right in zip(boundaries, boundaries[1:])
                                   if left <= prefix["index"] < right)
                observation.update(
                    baseline_projection_sha256=text_hash(self.endpoint_projections["baseline"][owner]["expanded_wikitext"]),
                    desired_projection_sha256=text_hash(self.endpoint_projections["desired"][owner]["expanded_wikitext"]),
                    prefix_interval={"first": first, "last": last},
                )
            reviewed["prefixes"].append({
                "index": prefix["index"], "observations": expected,
                "context_hashes": {row["title"]: row["raw_sha256"] for row in snapshot["pages"] if row["title"] not in self.cohort},
            })
        return {
            "full-prefix-proof.json": {
                **self.provenance, "evidence_kind": "disposable-mediawiki",
                "scope": "complete-baseline-to-desired-rehearsal-not-live-authorization",
                "order": self.order, "prefixes": self.prefixes, "view_evidence": self.probes,
                "baseline_revisions": self.base_meta, "desired_revisions": self.metadata,
                "final_observations": self.final_observations,
                "default_contracts": {
                    "preserved_price_owners": sorted(self.locations[identity] for identity in self.old_prices),
                    "coin_owners": sorted(self.locations[identity] for identity in self.coins),
                    "compatibility_edges": [{"consumer": consumer, "owner": owner} for consumer, owner in sorted(self.allowed)],
                },
                "cohort_full_positions": [0, *[self.order.index(title) + 1 for title in self.cohort]],
            },
            "price-compatibility-receipt.json": {
                **self.provenance, "receipt_type": "default-price-prefix-compatibility",
                "coverage_scope": "six-price-transition-only", "evidence_kind": "disposable-mediawiki",
                "order": self.cohort, "prefixes": self.compatibility,
            },
            "price-expectations-candidate.json": reviewed,
            "price-prefix-snapshots.json": self.snapshots,
            "consumer-settling.json": {
                **self.provenance, "scope": "Observed deferred-cache reads before coherent prefix observation; never purge or overwrite observed DOM.",
                "events": self.settling,
            },
            "endpoint-link-view-candidates.json": {
                **self.provenance, "requires_independent_review": True,
                "scope": "Read-only disposable endpoint candidates, not trusted link contracts or live authority.",
                "span_encoding": "UTF-8 byte offsets, end exclusive; no other source transformation",
                "corpus_sha256": {"baseline": hashlib.sha256(canonical_bytes(self.baseline)).hexdigest(),
                                  "desired": hashlib.sha256(canonical_bytes(self.desired)).hexdigest()},
                "endpoints": self.link_candidates,
            },
            "migration-plan.json": plan_migration(self.baseline, self.baseline, self.desired),
        }
