"""Plan the File page moves that a File title rename needs. Dry run only.

Compares content/facts/illustrations.json at a git ref with the working tree,
matching records by their stable ID. Prints one ``File:Old|File:New`` line per
move, which is the input format of MediaWiki's ``maintenance/run.php
moveBatch``. Nothing here contacts a wiki; see docs/IMAGES.md for the
reviewed live procedure.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from wiki_data import SOURCE_ID, DataError

ROOT = Path(__file__).resolve().parents[1]
PATH = "content/facts/illustrations.json"


def titles(document):
    """Map (record ID, slot) to File title; the crop source has its own slot."""
    found = {}
    for row in document["illustrations"]:
        found[row["id"], "file"] = row["file_title"]
        if "cropped_from" in row:
            found[row["id"], "source"] = row["cropped_from"]["file_title"]
    return found


def without_titles(document):
    rows = []
    for row in document["illustrations"]:
        row = {key: value for key, value in row.items() if key != "file_title"}
        if "cropped_from" in row:
            row["cropped_from"] = {key: value for key, value in row["cropped_from"].items() if key != "file_title"}
        rows.append(row)
    return rows


def plan(old, new):
    """Old->new pairs for every retitled File; everything else must be unchanged."""
    if without_titles(old) != without_titles(new):
        raise DataError("only File titles may change in a rename; split other edits into their own change")
    before, after = titles(old), titles(new)
    if len(set(after.values())) != len(after):
        raise DataError("renamed File titles must stay unique")
    moves = sorted((before[key], after[key]) for key in before if before[key] != after[key])
    targets = {target for _, target in moves}
    if targets & set(before.values()):
        raise DataError("a new File title reuses an old one; moves would collide")
    for _, target in moves:
        if SOURCE_ID.search(target):
            raise DataError(f"{target}: name the File by its page title and role, not a source ID")
    return moves


def at_ref(ref):
    shown = subprocess.run(["git", "show", f"{ref}:{PATH}"], cwd=ROOT, capture_output=True, check=False)
    if shown.returncode:
        raise DataError(f"cannot read {PATH} at {ref}: {shown.stderr.decode(errors='replace').strip()}")
    return json.loads(shown.stdout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", required=True, help="git ref whose File titles are live on the wiki")
    parser.add_argument("--output", type=Path, help="write the move list here instead of stdout")
    args = parser.parse_args(argv)
    try:
        moves = plan(at_ref(args.base), json.loads((ROOT / PATH).read_text(encoding="utf-8")))
    except DataError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    text = "".join(f"{old}|{new}\n" for old, new in moves)
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    print(f"{len(moves)} File moves planned; dry run, no wiki was contacted.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
