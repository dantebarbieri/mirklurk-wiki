"""Explicit private inputs and guards for the existing disposable smoke pipeline."""

import copy
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import urllib.parse
from pathlib import Path

from build_wiki import build_pages, build_xml
from plan_migration import read_snapshot, text_hash
from smoke_prefix import (
    Rehearsal, canonical_bytes, dom, linked_titles, projection_invocation,
    strip_colon_invocations, validate_materialization_inputs,
)
from wiki_catalog import entry_owners, entry_relations, page_locations, title_key
from wiki_details import load_publication_inputs, parse_document
from wiki_render import display_entry, recipe_groups
from wiki_views import available_views, transclusions


CATALOG_FILES = ("game.json", "catalog.json", "acquisition.json", "entity_details.json", "illustrations.json")
INPUT_KIND = "disposable-incremental-inputs"


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise RuntimeError("Unsupported incremental " + label + " shape.")


def source_pin(root, pin, *, current=False):
    exact_keys(pin, ("head_sha", "tree_sha"), "source")
    if any(not isinstance(value, str) or not re.fullmatch("[0-9a-f]{40}", value) for value in pin.values()):
        raise RuntimeError("Incremental sources require exact commit/tree hashes.")
    actual = subprocess.check_output(["git", "rev-parse", pin["head_sha"] + "^{tree}"], cwd=root, text=True).strip()
    if actual != pin["tree_sha"]:
        raise RuntimeError("Incremental source tree pin differs.")
    if current:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        if head != pin["head_sha"]:
            raise RuntimeError("Incremental candidate is not the executing checkout.")
        subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=root, check=True)


def pinned_bytes(directory, pin):
    exact_keys(pin, ("path", "bytes", "sha256"), "file")
    if (not isinstance(pin["path"], str) or type(pin["bytes"]) is not int
            or not 0 < pin["bytes"] <= 32 * 1024 * 1024
            or not isinstance(pin["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", pin["sha256"])):
        raise RuntimeError("Invalid incremental file pin.")
    path = directory / pin["path"]
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Incremental input must be a regular private file.")
    with path.open("rb") as stream:
        raw = stream.read(pin["bytes"] + 1)
    if len(raw) != pin["bytes"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise RuntimeError("Incremental input bytes/hash differ.")
    return path, raw


def catalog_pins(root):
    return {name: hashlib.sha256((root / "content" / "facts" / name).read_bytes()).hexdigest()
            for name in CATALOG_FILES}


def reviewed_drift(previous, baseline):
    return {title: {"previous_authored_sha256": text_hash(previous[title]), "baseline_sha256": text_hash(baseline[title])}
            for title in sorted(previous) if previous[title] != baseline[title]}


def validate_owned(previous, baseline, authored, owned, community, drift_sha256):
    validate_materialization_inputs(previous, baseline, authored)
    for label, titles in (("owned", owned), ("community", community)):
        if (not isinstance(titles, list) or any(not isinstance(title, str) or not title or title_key(title) != title for title in titles)
                or titles != sorted(set(titles))):
            raise RuntimeError("Invalid incremental " + label + " title inventory.")
    if set(owned) != previous.keys() or set(owned) != baseline.keys():
        raise RuntimeError("Incremental owned titles are missing, deleted or unknown.")
    if set(community) & (baseline.keys() | authored.keys()):
        raise RuntimeError("Incremental community inventory contains an owned/create collision.")
    if digest(reviewed_drift(previous, baseline)) != drift_sha256:
        raise RuntimeError("Incremental baseline has unreviewed drift.")


def archive_source(root, head, destination):
    destination.mkdir()
    archive = subprocess.check_output(["git", "archive", head], cwd=root)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for member in bundle:
            target = destination / member.name
            if not target.resolve().is_relative_to(destination.resolve()) or not (member.isdir() or member.isfile()):
                raise RuntimeError("Unsafe previous-source archive member.")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(bundle.extractfile(member).read())


def load_incremental_inputs(root, workspace, path):
    raw = path.read_bytes()
    parse_document(raw, 4 * 1024 * 1024)
    binding = json.loads(raw)
    exact_keys(binding, ("schema_version", "kind", "previous_source", "candidate_source",
                         "previous_authored", "baseline", "authored", "provenance", "owned_titles",
                         "community_titles", "reviewed_drift_sha256", "catalog_inputs"), "input")
    if type(binding["schema_version"]) is not int or binding["schema_version"] != 1 or binding["kind"] != INPUT_KIND:
        raise RuntimeError("Unsupported incremental input version/kind.")
    source_pin(root, binding["previous_source"])
    source_pin(root, binding["candidate_source"], current=True)
    payloads, pages = {}, {}
    for key in ("previous_authored", "baseline", "authored"):
        source, payloads[key] = pinned_bytes(path.parent, binding[key])
        pages[key] = read_snapshot(source)
        if build_xml(pages[key]) != payloads[key]:
            raise RuntimeError("Incremental XML must use the canonical disposable synthetic identity format.")
    _, provenance = pinned_bytes(path.parent, binding["provenance"])
    parse_document(provenance, 32 * 1024 * 1024)
    validate_owned(pages["previous_authored"], pages["baseline"], pages["authored"],
                   binding["owned_titles"], binding["community_titles"], binding["reviewed_drift_sha256"])
    destination = workspace / "incremental-previous-source"
    archive_source(root, binding["previous_source"]["head_sha"], destination)
    generated = workspace / "incremental-previous-authored.xml"
    subprocess.run([sys.executable, str(destination / "tools" / "build_wiki.py"), "--fresh", "--output", str(generated)],
                   check=True, stdout=subprocess.PIPE)
    if generated.read_bytes() != payloads["previous_authored"]:
        raise RuntimeError("Previous authored XML differs from its pinned source generator.")
    previous_inputs = load_publication_inputs(destination)
    current_inputs = load_publication_inputs(root)
    if build_xml(build_pages(root, *current_inputs)) != payloads["authored"]:
        raise RuntimeError("Candidate authored XML differs from its pinned source generator.")
    if binding["catalog_inputs"] != {"previous": catalog_pins(destination), "candidate": catalog_pins(root)}:
        raise RuntimeError("Incremental catalog source pins differ.")
    public_binding = copy.deepcopy(binding)
    for key in (*payloads, "provenance"):
        public_binding[key].pop("path")
    public_binding["input_sha256"] = hashlib.sha256(raw).hexdigest()
    return pages, payloads, previous_inputs, public_binding


def incremental_order(baseline, desired):
    validate_materialization_inputs(baseline, baseline, desired)
    for corpus in (baseline, desired):
        for title, text in corpus.items():
            strip_colon_invocations(text)
            for owner, arguments in transclusions(text):
                if owner not in corpus or dict(arguments).get("view", "") not in available_views(corpus[owner]):
                    raise RuntimeError("Missing incremental owner/view edge: " + title + " -> " + owner)
    pending = {title for title in desired if baseline.get(title) != desired[title]}
    ready = desired.keys() - pending
    order = []
    while pending:
        candidates = sorted((title for title in pending
                             if {owner for owner, _ in transclusions(desired[title])} <= ready),
                            key=lambda title: (title in baseline, title))
        if not candidates:
            blocked = {title: sorted({owner for owner, _ in transclusions(desired[title])} - ready)
                       for title in sorted(pending)}
            raise RuntimeError("Affected incremental prerequisite cycle: " + json.dumps(blocked, sort_keys=True))
        title = candidates[0]
        order.append(title)
        ready.add(title)
        pending.remove(title)
    return order


def coverage(baseline, desired, order):
    expected = incremental_order(baseline, desired)
    if order != expected:
        raise RuntimeError("Incremental order omitted, resent or reordered an operation.")
    titles = {"create": sorted(desired.keys() - baseline.keys()),
              "update": sorted(title for title in baseline if baseline[title] != desired[title]),
              "preserved": sorted(title for title in baseline if baseline[title] == desired[title])}
    return {"titles": titles, "counts": {key: len(value) for key, value in titles.items()},
            "operations": len(order), "prefixes": len(order) + 1, "desired_titles": len(desired)}


def validate_native_plan(rehearsal, operations, preserved):
    summary = coverage(rehearsal.baseline, rehearsal.desired, rehearsal.order)
    metadata = rehearsal.metadata
    if set(metadata) != set(rehearsal.baseline):
        raise RuntimeError("Incremental native baseline metadata coverage differs.")
    for title, row in metadata.items():
        if row["raw_sha256"] != text_hash(rehearsal.baseline[title]):
            raise RuntimeError("Incremental native baseline raw differs.")
    if [row["title"] for row in operations] != rehearsal.order:
        raise RuntimeError("Incremental native operation coverage differs.")
    for index, row in enumerate(operations, 1):
        title = row["title"]
        expected = ({"page_id": metadata[title]["pageid"], "revision_id": metadata[title]["revid"],
                     "raw_sha256": metadata[title]["raw_sha256"]} if title in metadata
                    else {"page_id": 0, "revision_id": 0, "raw_sha256": None})
        prerequisites = [{"namespace": 14 if owner.startswith("Category:") else 0, "title": owner,
                          "raw_sha256": text_hash(rehearsal.desired[owner])}
                         for owner in sorted({owner for owner, _ in transclusions(rehearsal.desired[title])})]
        if (row["index"] != index or row["expected"] != expected
                or row["desired_sha256"] != text_hash(rehearsal.desired[title])
                or row["prerequisites"] != prerequisites or row["prerequisites_sha256"] != digest(prerequisites)):
            raise RuntimeError("Incremental native CAS/prerequisite plan differs.")
    expected_preserved = [{"namespace": 14 if title.startswith("Category:") else 0, "title": title,
                           "page_id": metadata[title]["pageid"], "revision_id": metadata[title]["revid"],
                           "raw_sha256": text_hash(rehearsal.baseline[title])}
                          for title in summary["titles"]["preserved"]]
    if preserved != expected_preserved:
        raise RuntimeError("Incremental native preserved coverage differs.")
    return summary


def validate_prefix_guard(rehearsal, index, guards):
    if (not isinstance(guards, dict) or guards.get("incremental_input_sha256") != rehearsal.binding["input_sha256"]
            or index < 1 or index > len(rehearsal.order) or len(rehearsal.prefixes) != index + 1
            or guards.get("prefix") != rehearsal.prefixes[index] or "prerequisite_checks" not in guards):
        raise RuntimeError("Missing or mismatched incremental prefix guard.")
    prefix = guards["prefix"]
    title = rehearsal.order[index - 1]
    expected = transclusions(rehearsal.desired[title])
    probes = guards["prerequisite_checks"]
    if (prefix["index"] != index or prefix["saved"] != rehearsal.metadata[title]
            or prefix["saved"]["raw_sha256"] != text_hash(rehearsal.desired[title])
            or [(row["owner"]["title"], tuple(sorted(row["parameters"].items()))) for row in probes] != expected
            or prefix["prerequisites"] != [row["id"] for row in probes]
            or any(row["owner"] != rehearsal.metadata[row["owner"]["title"]]
                   or row["owner"]["raw_sha256"] != text_hash(rehearsal.desired[row["owner"]["title"]]) for row in probes)):
        raise RuntimeError("Incremental prefix guard has wrong saved/prerequisite state.")
    if guards.get("default_probe_ids") != rehearsal.default_prefixes[index]:
        raise RuntimeError("Incremental prefix guard omitted its complete default checks.")
    owners = sorted(rehearsal.registry["prices"].keys() | rehearsal.registry["coins"].keys())
    defaults = guards["default_probe_ids"]
    if (len(defaults) != len(owners) or any(type(identity) is not int or not 0 <= identity < len(rehearsal.probes)
                                          for identity in defaults)):
        raise RuntimeError("Incremental prefix default evidence is incomplete.")
    for owner, identity in zip(owners, defaults):
        probe = rehearsal.probes[identity]
        if (probe["owner"] != rehearsal.metadata[owner] or probe["parameters"]
                or probe.get("parse_title") != "Prefix projection"):
            raise RuntimeError("Incremental default guard is not bound to its current owner/context.")
    affected = {title} | {consumer for consumer, text in rehearsal.current.items()
                          if title in {owner for owner, _ in transclusions(text)} or title in linked_titles(text)}
    if [row["consumer"]["title"] for row in prefix["observations"]] != sorted(affected):
        raise RuntimeError("Incremental prefix omitted affected consumer guards.")


def verify_native_completion(rehearsal, proof, accepted):
    summary = coverage(rehearsal.baseline, rehearsal.desired, rehearsal.order)
    if (len(rehearsal.prefixes) != summary["prefixes"] or len(accepted) != summary["operations"]
            or len(proof["operations"]) != summary["operations"]
            or [row["index"] for row in rehearsal.prefixes] != list(range(summary["prefixes"]))
            or [row["revision"]["title"] for row in accepted] != rehearsal.order):
        raise RuntimeError("Incremental native n/n+1 coverage differs.")
    for index, (operation, record) in enumerate(zip(proof["operations"], accepted), 1):
        if (operation["index"] != index or operation["accepted_sha256"] != digest(record)
                or operation["result"]["revision"] != record["revision"]
                or operation.get("prefix_guards", {}).get("prefix") != rehearsal.prefixes[index]):
            raise RuntimeError("Incremental native accepted operation/guard binding differs.")
    return summary


def default_registry(baseline, desired, previous_inputs, current_inputs):
    registries = []
    for data, catalog, _ in (previous_inputs, current_inputs):
        locations = page_locations(data, catalog)
        prices = {locations[row["entity"]]: {"entity": row["entity"], "value": str(row["value"])}
                  for row in catalog["unit_prices"]["prices"]}
        coins = {locations[row["entity"]]: {key: str(row[key]) for key in
                 ("entity", "value_in_silver", "weight_grams", "stack_limit")} for row in catalog["currency"]["coins"]}
        if prices.keys() & coins.keys():
            raise RuntimeError("A default owner has two registry contracts.")
        registries.append({"prices": prices, "coins": coins})
    if registries[0] != registries[1]:
        raise RuntimeError("Incremental default registry omitted or changed an established price/coin.")
    registry = registries[0]
    registered = registry["prices"].keys() | registry["coins"].keys()
    for corpus in (baseline, desired):
        actual = {owner for text in corpus.values() for owner, arguments in transclusions(text) if not arguments}
        if not actual <= registered or not registered <= corpus.keys():
            raise RuntimeError("Unresolved or unregistered incremental defaults.")
        if any("" not in available_views(corpus[owner]) for owner in registered):
            raise RuntimeError("An incremental default owner lost its default view.")
    return registry


def projection_signature(html, title):
    from smoke_deploy import RenderedGrids
    parsed = dom(html, title)
    media = RenderedGrids()
    media.feed(html)
    return {"text": parsed.text, "rows": parsed.rows, "anchors": parsed.anchors,
            "links": parsed.links, "non_wiki_links": parsed.non_wiki_links,
            "images": [{key: image.get(key) for key in ("src", "srcset", "alt", "width", "height")}
                       for image in media.images]}


class IncrementalRehearsal(Rehearsal):
    def __init__(self, api, checks, baseline, desired, data, catalog, old_catalog, runtime, source_head,
                 *, previous_inputs, binding):
        super().__init__(api, checks, baseline, desired, data, catalog, old_catalog, runtime, source_head,
                         incremental=True)
        self.binding = binding
        self.previous_inputs = previous_inputs
        self.registry = default_registry(baseline, desired, previous_inputs, (data, catalog, None))
        self.baseline_checker = copy.copy(self)
        old_data, old_catalog, _ = previous_inputs
        checker = self.baseline_checker
        checker.data, checker.catalog = old_data, old_catalog
        checker.locations = page_locations(old_data, old_catalog)
        checker.entities = {title: identity for identity, title in checker.locations.items()}
        checker.owners = entry_owners(old_data, checker.locations, entry_relations(old_data, old_catalog), old_catalog)
        checker.groups = recipe_groups([display_entry(row, old_catalog) for row in old_data["entries"] if row["kind"] == "recipe"])
        checker.stations = {method: row for row in old_catalog["stations"] for method in row["methods"]}
        checker.sources = {row["title"]: row for row in old_catalog["acquisition"]["sources"]}
        checker.pools = {row["id"]: row for row in old_catalog["acquisition"]["pools"]}
        self.baseline_contracts = {}
        self.default_endpoints = {}
        self.default_prefixes = []
        self.consumer_html = {}

    def validate_projection(self, owner, parameters, result, parse_title="Prefix projection"):
        if self.current[owner] == self.baseline.get(owner) and parameters.get("view") == "pool":
            checker = self.baseline_checker
            html = result["text"]["*"]
            self.checks.check_parser_errors(html)
            if sorted(row["*"] for row in result.get("templates", [])) != [owner]:
                raise RuntimeError("A baseline pool is not a parser-proven leaf.")
            pool = checker.pools[parameters["pool"]]
            members = set(pool["eligible_item_ids"]) if "item" not in parameters else {parameters["item"]} & set(pool["eligible_item_ids"])
            parsed = dom(html, parse_title)
            wanted = {"pool-item-" + pool["id"] + "-" + item for item in members}
            actual = [anchor for anchor in parsed.anchors if anchor.startswith("pool-item-")]
            if set(actual) != wanted or len(actual) != len(wanted) or len(parsed.rows) != len(wanted):
                raise RuntimeError("A baseline pool changed its exact membership.")
            for row in parsed.rows:
                if (len(row["cells"]) != 4 or len(set(row["ids"]) & wanted) != 1
                        or row["headers"] != ["Item", "Quantity", "Per-item probability", "Eligibility"]
                        or [cell["text"] for cell in row["cells"][1:3]] != ["Budget-dependent", "Not established"]):
                    raise RuntimeError("A baseline pool changed its four-cell quantity/probability contract.")
                item = next(iter(set(row["ids"]) & wanted)).removeprefix("pool-item-" + pool["id"] + "-")
                if [link["target"] for link in row["cells"][0]["links"]] != [checker.locations[item]]:
                    raise RuntimeError("A baseline pool changed its ordered item cell.")
            for item, condition in pool["item_conditions"].items():
                if (self.checks.plain(condition) in parsed.text) != (item in members):
                    raise RuntimeError("A baseline pool lost or leaked a story gate.")
        else:
            checker = self.baseline_checker if self.current[owner] == self.baseline.get(owner) else self
            Rehearsal.validate_projection(checker, owner, parameters, result, parse_title)
        if not parameters:
            parsed = dom(result["text"]["*"], parse_title)
            media = self.checks.RenderedGrids()
            media.feed(result["text"]["*"])
            identity = self.entities[owner]
            if identity in self.coins:
                coin = self.coins[identity]
                wanted = " ".join(("Coin Value in silver Weight Maximum stack", self.locations[identity],
                                   self.checks.scalar(coin["value_in_silver"]),
                                   self.checks.scalar(coin["weight_grams"]) + " g", str(coin["stack_limit"])))
                if (parsed.text != wanted or parsed.anchors != ["coin-" + identity]
                        or [link["target"] for link in parsed.links] != [owner] or parsed.non_wiki_links or media.images):
                    raise RuntimeError("An incremental default coin leaked article content.")
            else:
                if parsed.links or parsed.non_wiki_links or re.search(r"<(?:table|h[1-6])\b", result["text"]["*"], re.I):
                    raise RuntimeError("An incremental default price leaked article content.")
                denominations = [unit for amount, unit in re.findall(r"(\d+) (gold|silver|copper)", parsed.text) if int(amount)]
                if len(media.images) != len(denominations):
                    raise RuntimeError("A default price omitted a denomination icon or leaked another image.")
                for unit, image in zip(denominations, media.images):
                    filename = "Item-" + {"copper": "72", "silver": "73", "gold": "74"}[unit] + ".png"
                    source = urllib.parse.unquote(urllib.parse.urlsplit(image.get("src", "")).path)
                    if (not re.search(r"(?:^|/)(?:[0-9]+px-)?" + re.escape(filename) + "$", source)
                            or image.get("alt") != unit.capitalize() + " coin"
                            or image.get("width") != "20" or image.get("height") != "20"):
                        raise RuntimeError("A default price changed its exact denomination icon.")

    def probe(self, consumer, owner, arguments, fresh=False):
        if owner not in self.current or dict(arguments).get("view", "") not in available_views(self.current[owner]):
            raise RuntimeError("A required incremental owner/view is missing.")
        parameters = dict(arguments)
        context = consumer or "Prefix projection"
        metadata = self.metadata[owner]
        key = (owner, tuple(arguments), metadata["revid"], metadata["raw_sha256"], context)
        if key in self.cache and not fresh:
            return self.cache[key]
        invocation = projection_invocation(owner, parameters)
        expanded = self.api({"action": "expandtemplates", "title": context, "text": invocation,
                             "prop": "wikitext"}, post=True)["expandtemplates"]["wikitext"]
        render_text = "<table>" + invocation + "</table>" if parameters.get("view") == "recipes" else invocation
        result = self.api({"action": "parse", "title": context, "text": render_text,
                           "prop": "text|templates|links"}, post=True)["parse"]
        self.validate_projection(owner, parameters, result, context)
        signature = projection_signature(result["text"]["*"], context)
        contract_key = (owner, tuple(arguments), context)
        at_baseline = self.current[owner] == self.baseline.get(owner)
        if at_baseline or not parameters:
            contract = self.baseline_contracts.get(contract_key)
            if contract is None:
                raise RuntimeError("Missing measured baseline projection/context contract.")
            if ((at_baseline and contract["owner"] != metadata) or contract["expanded_wikitext"] != expanded
                    or projection_signature(contract["html"], context) != signature):
                raise RuntimeError("Baseline/default projection/context drifted from its measured B contract.")
        kind = ("desired-leaf-projection" if self.current[owner] == self.desired[owner]
                else "baseline-leaf-projection" if parameters else "preserved-baseline-default")
        evidence = {"id": len(self.probes), "owner": dict(metadata), "parameters": parameters, "kind": kind,
                    "expanded_wikitext": expanded, "projection_sha256": text_hash(expanded),
                    "html": result["text"]["*"], "render_context": "table" if parameters.get("view") == "recipes" else "block",
                    "templates": sorted(row["*"] for row in result.get("templates", [])), "parse_title": context}
        self.probes.append(evidence)
        self.cache[key] = evidence
        return evidence

    def capture_link_endpoint(self, endpoint):
        super().capture_link_endpoint(endpoint)
        captures = self.link_candidates[endpoint]
        if captures["discrepancies"]:
            raise RuntimeError("Incremental endpoint has link/context discrepancies.")
        if endpoint == "baseline":
            self.baseline_contracts = {
                (row["owner"]["title"], tuple(sorted(row["parameters"].items())), row["parse_title"]): row
                for row in captures["selected"]
            }

    def capture_defaults(self, endpoint):
        records = []
        for owner in sorted(self.registry["prices"].keys() | self.registry["coins"].keys()):
            records.append(self.probe("Prefix projection", owner, (), fresh=True)["id"])
        self.default_endpoints[endpoint] = records

    def capture_prefix_defaults(self, changed=None):
        self.default_prefixes.append([
            self.probe("Prefix projection", owner, (), fresh=owner == changed)["id"]
            for owner in sorted(self.registry["prices"].keys() | self.registry["coins"].keys())
        ])

    def inspect_consumer(self, title):
        record = super().inspect_consumer(title)
        self.consumer_html[record["html_sha256"]] = self.last_consumer_html
        parsed = dom(self.last_consumer_html, title)
        for identity in record["probe_ids"]:
            probe = self.probes[identity]
            if probe["parameters"].get("view") != "pool":
                continue
            selected = dom(probe["html"], title)
            if any(parsed.anchors.count(anchor) != selected.anchors.count(anchor) for anchor in selected.anchors):
                raise RuntimeError("A consumer omitted or duplicated its selected pool anchors.")
            if not selected.rows:
                links = selected.links
                if (selected.text not in parsed.text or
                        not any(parsed.links[offset:offset + len(links)] == links for offset in range(len(parsed.links) + 1))):
                    from smoke_prefix import PendingConsumerUpdate
                    raise PendingConsumerUpdate("A consumer lacks its current compact pool/context contract.",
                                                title, probe["owner"]["title"], self.last_consumer_html)
        return record

    def check_merchant_rows(self, title, parsed, html):
        checker = self.baseline_checker if self.current[title] == self.baseline.get(title) else self
        Rehearsal.check_merchant_rows(checker, title, parsed, html)

    def run(self, save, wait_tick, drain_jobs, job_status, accept):
        self.refresh_metadata()
        self.capture_link_endpoint("baseline")
        self.capture_defaults("baseline")
        self.capture_prefix_defaults()
        observations = [self.inspect_consumer(title) for title in sorted(self.current)]
        self.prefixes.append({"index": 0, "saved": None, "prerequisites": [], "observations": observations,
                              "pending_new_link_edges": self.pending_link_edges()})
        for index, title in enumerate(self.order, 1):
            prerequisites = [self.probe(title, owner, arguments, fresh=True)
                             for owner, arguments in transclusions(self.desired[title])]
            if any(self.current[owner] != self.desired[owner] for owner, _ in transclusions(self.desired[title])):
                raise RuntimeError("Incremental save has an owner not at D.")
            wait_tick(self.api)
            revision = save(title, self.metadata, self.desired[title], prerequisites)
            self.current[title] = self.desired[title]
            drain_jobs()
            self.refresh_metadata()
            if revision != self.metadata[title]["revid"]:
                raise RuntimeError("Incremental saved revision is not the current pointer.")
            affected = {title} | {consumer for consumer, text in self.current.items()
                                  if title in {owner for owner, _ in transclusions(text)} or title in linked_titles(text)}
            self.cache = {key: value for key, value in self.cache.items() if key[0] != title}
            self.capture_prefix_defaults(title)
            observations = self.observe_consumers(affected, drain_jobs, job_status)
            self.prefixes.append({"index": index, "saved": dict(self.metadata[title]),
                                  "prerequisites": [row["id"] for row in prerequisites], "observations": observations,
                                  "pending_new_link_edges": self.pending_link_edges()})
            guard = {"prefix": self.prefixes[-1], "prerequisite_checks": prerequisites,
                     "default_probe_ids": self.default_prefixes[-1],
                     "incremental_input_sha256": self.binding["input_sha256"]}
            if index < len(self.order):
                accept(index, guard)
            else:
                self.pending_final_guard = guard
        if self.current != self.desired:
            raise RuntimeError("Incremental rehearsal did not reach exact D.")
        self.capture_link_endpoint("desired")
        self.capture_defaults("desired")
        self.final_observations = [self.inspect_consumer(title) for title in sorted(self.current)]
        selected = {(row["owner"]["title"], tuple(sorted(row["parameters"].items())), row["parse_title"]): row
                    for row in self.link_candidates["desired"]["selected"]}
        for probe in self.probes:
            if probe["kind"] != "desired-leaf-projection":
                continue
            key = (probe["owner"]["title"], tuple(sorted(probe["parameters"].items())), probe["parse_title"])
            final = selected.get(key)
            if (final is None or probe["projection_sha256"] != final["projection_sha256"]
                    or projection_signature(probe["html"], key[2]) != projection_signature(final["html"], key[2])):
                raise RuntimeError("A desired prerequisite projection/context changed before the endpoint.")
        for title in self.baseline:
            if self.baseline[title] == self.desired[title] and self.base_meta[title] != self.metadata[title]:
                raise RuntimeError("An unchanged incremental page identity/raw changed.")

    def artifacts(self):
        result = {
            "full-prefix-proof.json": {
                **self.provenance, "scope": "complete-incremental-rehearsal-not-live-authorization",
                "order": self.order, "prefixes": self.prefixes, "view_evidence": self.probes,
                "baseline_revisions": self.base_meta, "desired_revisions": self.metadata,
                "final_observations": self.final_observations,
                "default_contracts": {"preserved_price_owners": sorted(self.registry["prices"]),
                                      "coin_owners": sorted(self.registry["coins"]), "compatibility_edges": []},
                "incremental": {"schema_version": 1, "kind": "disposable-incremental-envelope",
                                "inputs": self.binding, "coverage": coverage(self.baseline, self.desired, self.order),
                                "outcome": "rehearsed" if self.order else "no-publication",
                                "default_endpoint_probe_ids": self.default_endpoints,
                                "default_prefix_probe_ids": self.default_prefixes},
            },
            "endpoint-link-view-candidates.json": {
                **self.provenance, "requires_independent_review": True, "endpoints": self.link_candidates,
                "corpus_sha256": {"baseline": digest(self.baseline), "desired": digest(self.desired)},
            },
            "consumer-html.json": self.consumer_html,
            "consumer-settling.json": {**self.provenance, "events": self.settling},
        }
        return result
