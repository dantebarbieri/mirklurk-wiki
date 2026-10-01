"""Disposable check that VisualEditor is offered on ordinary pages but not shared-data owners."""

import re
import time
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


def smoke_discussions(api, base, csrf, open_url):
    """Requires a signed-in account behind `api`; proves the reply tool and its tables work."""
    talk = "Talk:Synthetic discussion"
    saved = api({
        "action": "edit", "title": talk, "createonly": 1, "token": csrf, "summary": "Discussion smoke",
        "text": "== Synthetic topic ==\nA synthetic opening comment. ~~~~\n",
    }, post=True)
    if saved.get("edit", {}).get("result") != "Success":
        raise RuntimeError("The discussion smoke could not create a talk page.")
    with open_url(base + "/w/" + urllib.parse.quote(talk.replace(" ", "_")), timeout=30) as response:
        if "ext-discussiontools-init-replylink" not in response.read().decode():
            raise RuntimeError("Talk pages do not offer DiscussionTools reply links.")

    def comments(items):
        for item in items:
            if item.get("type") == "comment":
                yield item
            yield from comments(item.get("replies", []))

    info = api({"action": "discussiontoolspageinfo", "page": talk, "prop": "threaditemshtml"})
    opening = next(comments(info["discussiontoolspageinfo"]["threaditemshtml"]), None)
    if opening is None:
        raise RuntimeError("DiscussionTools found no comment on the synthetic talk page.")
    reply = api({
        "action": "discussiontoolsedit", "paction": "addcomment", "page": talk,
        "commentid": opening["id"], "wikitext": "A synthetic reply.", "token": csrf,
    }, post=True)
    if reply.get("discussiontoolsedit", {}).get("result") != "success":
        raise RuntimeError("The DiscussionTools reply tool could not save a reply.")
    text = api({"action": "parse", "page": talk, "prop": "wikitext"})["parse"]["wikitext"]["*"]
    if not re.search(r"^:A synthetic reply\. \[\[User:", text, re.MULTILINE):
        raise RuntimeError("The DiscussionTools reply was not saved as an indented, signed comment.")
    # Both queries read the extensions' own tables, which a missed schema update leaves absent.
    for _ in range(10):
        found = api({"action": "discussiontoolsfindcomment", "idorname": opening["id"]})
        if any(row.get("title") == talk for row in found["discussiontoolsfindcomment"]):
            break
        time.sleep(1)
    else:
        raise RuntimeError("DiscussionTools did not persist comment permalinks.")
    api({"action": "query", "meta": "notifications"})["query"]["notifications"]
    print(f"Discussion smoke: replied on {talk}; permalinks and notifications available.", flush=True)
