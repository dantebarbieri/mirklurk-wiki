"""Build deterministic MediaWiki XML; never connect to or modify a live wiki."""

import argparse
import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from wiki_catalog import title_key
from wiki_data import DataError
from wiki_details import load_publication_inputs
from wiki_render import build_pages, literal, profile_value


EXPORT_NS = "http://www.mediawiki.org/xml/export-0.11/"
EXPORT_NAMESPACES = {EXPORT_NS, "http://www.mediawiki.org/xml/export-0.10/"}
SEED_TIMESTAMP = "2000-01-01T00:00:00Z"
ET.register_namespace("", EXPORT_NS)


def existing_titles(path):
    try:
        document = ET.parse(path)
    except (ET.ParseError, OSError) as error:
        raise DataError("existing export is unreadable or malformed XML") from error
    root = document.getroot()
    namespace = root.tag.removeprefix("{").split("}", 1)[0]
    if namespace not in EXPORT_NAMESPACES or root.tag != f"{{{namespace}}}mediawiki":
        raise DataError("existing export must be a MediaWiki 0.10/0.11 XML export")
    prefix = f"{{{namespace}}}"
    if root.find(f"{prefix}siteinfo") is None:
        raise DataError("existing export has no siteinfo; use a complete current-page dump")
    titles = set()
    for page in root.findall(f"{prefix}page"):
        title = page.findtext(f"{prefix}title")
        page_namespace = page.findtext(f"{prefix}ns")
        if not title or not title.strip() or page_namespace is None or not page_namespace.isdecimal():
            raise DataError("existing export has an invalid page title or namespace")
        if page_namespace == "0":
            titles.add(title_key(title))
    return titles


def build_xml(pages):
    def element(parent, tag, text=None, **attributes):
        child = ET.SubElement(parent, f"{{{EXPORT_NS}}}{tag}", attributes)
        if text is not None:
            child.text = text
        return child

    root = ET.Element(f"{{{EXPORT_NS}}}mediawiki", {"version": "0.11", "{http://www.w3.org/XML/1998/namespace}lang": "en"})
    siteinfo = element(root, "siteinfo")
    element(siteinfo, "sitename", "MirkLurk Wiki")
    element(siteinfo, "dbname", "mirklurk")
    element(siteinfo, "generator", "MirkLurk curated repository seed")
    element(siteinfo, "case", "first-letter")
    namespaces = element(siteinfo, "namespaces")
    element(namespaces, "namespace", "", key="0", case="first-letter")
    for identifier, title in enumerate(sorted(pages), 1):
        page = element(root, "page")
        element(page, "title", title)
        element(page, "ns", "0")
        element(page, "id", str(identifier))
        revision = element(page, "revision")
        element(revision, "id", str(identifier))
        element(revision, "timestamp", SEED_TIMESTAMP)
        contributor = element(revision, "contributor")
        element(contributor, "username", "Repository seed")
        element(revision, "comment", "Original repository seed; evidence and rights caveats apply.")
        element(revision, "origin", str(identifier))
        element(revision, "model", "wikitext")
        element(revision, "format", "text/x-wiki")
        element(
            revision, "text", pages[title],
            **{"{http://www.w3.org/XML/1998/namespace}space": "preserve",
               "bytes": str(len(pages[title].encode("utf-8")))},
        )
        number = int.from_bytes(hashlib.sha1(pages[title].encode("utf-8"), usedforsecurity=False).digest())
        digest = ""
        while number:
            number, remainder = divmod(number, 36)
            digest = "0123456789abcdefghijklmnopqrstuvwxyz"[remainder] + digest
        element(revision, "sha1", digest.rjust(31, "0"))
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fresh", action="store_true", help="Build all titles for a verified fresh wiki only")
    mode.add_argument("--existing-export", type=Path, help="Complete current-page XML dump; omit all existing titles")
    parser.add_argument("--output", required=True, type=Path, help="New output file; existing files are never overwritten")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        data, catalog, details = load_publication_inputs(root)
        pages = build_pages(root, data, catalog, details)
        total = len(pages)
        excluded = existing_titles(args.existing_export) if args.existing_export else set()
        pages = {title: text for title, text in pages.items() if title_key(title) not in excluded}
        payload = build_xml(pages)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(payload)
    except (DataError, OSError) as error:
        print(f"Seed build failed: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {len(pages)} pages; omitted {total - len(pages)} existing titles.")
    print("No live wiki was contacted. Freeze edits and follow docs/IMPORTING.md before import.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
