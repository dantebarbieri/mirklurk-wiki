"""Disposable check that VisualEditor is offered on ordinary pages but not shared-data owners."""

import re
import urllib.parse

SHARED_MARKUP = re.compile(r"<\s*/?\s*(?:onlyinclude|includeonly|noinclude)\b", re.IGNORECASE)
NOTICE = "supplies shared data that other pages display"


def smoke_editor_selection(api, base, csrf, pages, open_url):
    """Requires a signed-in, ordinary-preference account behind `api` and `open_url`."""
    owner = next(title for title in sorted(pages) if ":" not in title and SHARED_MARKUP.search(pages[title]))
    ordinary = "Weather"
    if SHARED_MARKUP.search(pages[ordinary]):
        raise RuntimeError("The ordinary editor fixture unexpectedly carries shared-data markup.")

    def html(title, query=""):
        url = base + "/w/" + urllib.parse.quote(title.replace(" ", "_")) + query
        with open_url(url, timeout=30) as response:
            return response.read().decode()

    view = html(ordinary)
    if 'id="ca-ve-edit"' not in view or "wgVisualEditorDisabledByHook" in view:
        raise RuntimeError("Ordinary pages do not offer VisualEditor to signed-in editors.")
    parsed = api({"action": "visualeditor", "paction": "parse", "page": ordinary})["visualeditor"]
    if parsed.get("result") != "success" or "<body" not in parsed.get("content", ""):
        raise RuntimeError("The integrated Parsoid client did not load an ordinary page for visual editing.")
    if NOTICE in html(ordinary, "?action=edit"):
        raise RuntimeError("Ordinary pages show the shared-data source-editing notice.")

    view = html(owner)
    if 'id="ca-ve-edit"' in view or '"wgVisualEditorDisabledByHook":true' not in view:
        raise RuntimeError(f"Shared-data owner {owner} still offers VisualEditor.")
    if "mw-editsection-visualeditor" in view and ".mw-editsection-visualeditor" not in view:
        raise RuntimeError("Shared-data owners still show visual section-edit links.")
    if NOTICE not in html(owner, "?action=edit"):
        raise RuntimeError("Shared-data owners do not explain why they use the source editor.")
    before = api({"action": "query", "prop": "revisions", "titles": owner, "rvprop": "ids"})["query"]["pages"]
    rejected = api({
        "action": "visualeditoredit", "paction": "save", "page": owner, "wikitext": "Replaced.",
        "summary": "Must be rejected", "token": csrf,
    }, post=True, expected_error="rawmessage")
    if NOTICE not in rejected["error"].get("info", ""):
        raise RuntimeError("The VisualEditor save refusal does not explain source editing.")
    after = api({"action": "query", "prop": "revisions", "titles": owner, "rvprop": "ids"})["query"]["pages"]
    if before != after:
        raise RuntimeError("A refused VisualEditor save changed a shared-data owner.")
    print(f"Editor smoke: VisualEditor on {ordinary}; source-only on {owner}.", flush=True)
