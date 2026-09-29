"""Native sidebar checks for the disposable wiki, never a live publication path."""

from pathlib import Path
import urllib.parse

from wiki_data import read_authored


ROOT = Path(__file__).resolve().parents[1]
SIDEBAR_TITLE = "MediaWiki:Sidebar"
SIDEBAR_LINKS = {
    "Main page": "Main Page",
    "Items": "Items",
    "Bestiary": "Bestiary",
    "NPCs": "NPCs",
    "Merchants": "Merchants",
    "Crafting and workstations": "Crafting",
    "Survival and game mechanics": "Game mechanics",
    "Random page": "Special:Random",
    "Editing help": "Help:Editing",
    "Recent changes": "Special:RecentChanges",
}


def sidebar_text():
    return read_authored(ROOT, SIDEBAR_TITLE, "Sidebar.wiki", directory="interface", limit=2 * 1024)


def article_url(base, article_path, title):
    return urllib.parse.urljoin(base, article_path.replace("$1", urllib.parse.quote(title.replace(" ", "_"), safe=":/")))


def install_sidebar_fixture(api, base, token):
    if urllib.parse.urlsplit(base).hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("Sidebar smoke may only edit the disposable localhost wiki.")
    rights = api({"action": "query", "meta": "userinfo", "uiprop": "rights"})["query"]["userinfo"]["rights"]
    if "editinterface" not in rights:
        raise RuntimeError("The disposable sidebar installer needs an operator with editinterface.")
    pages = api({"action": "query", "titles": SIDEBAR_TITLE + "|Help:Editing"})["query"]["pages"]
    by_title = {page["title"]: page for page in pages.values()}
    if "missing" not in by_title[SIDEBAR_TITLE]:
        raise RuntimeError("Refusing to overwrite an existing disposable sidebar.")
    if "missing" in by_title["Help:Editing"]:
        # The independent editing-help PR owns the article, not this navigation PR.
        result = api({"action": "edit", "title": "Help:Editing", "createonly": "1",
                      "text": "Disposable navigation target; the editing-help release supplies the article.",
                      "summary": "Disposable editing-help target, not publication content", "token": token}, post=True)
        if result.get("edit", {}).get("result") != "Success":
            raise RuntimeError("The disposable editing-help target could not be saved.")
        print("Sidebar smoke: synthetic Help:Editing target only; live activation still requires the help release.",
              flush=True)
    text = sidebar_text()
    result = api({"action": "edit", "title": SIDEBAR_TITLE, "text": text, "createonly": "1",
                  "summary": "Disposable operator installation of reviewed sidebar", "token": token}, post=True)
    if result.get("edit", {}).get("result") != "Success":
        raise RuntimeError("The disposable sidebar artifact could not be saved.")
    stored = api({"action": "query", "titles": SIDEBAR_TITLE, "prop": "revisions",
                  "rvprop": "content", "rvslots": "main"})["query"]["pages"]
    if next(iter(stored.values()))["revisions"][0]["slots"]["main"]["*"].strip() != text.strip():
        raise RuntimeError("MediaWiki did not store the exact reviewed sidebar.")


def smoke_navigation(page, api, base, folder, name):
    page.goto(base + "/index.php?" + urllib.parse.urlencode({"title": "Main Page", "useskin": "vector-2022"}),
              wait_until="networkidle")
    menu = page.locator("#vector-main-menu")
    if not menu.is_visible():
        page.get_by_role("button", name="Main menu", exact=True).click()
    menu.wait_for(state="visible")
    article_path = api({"action": "query", "meta": "siteinfo", "siprop": "general"})["query"]["general"]["articlepath"]
    info = api({"action": "query", "titles": "|".join(SIDEBAR_LINKS.values()),
                "prop": "info"})["query"]["pages"]
    by_title = {row["title"]: row for row in info.values()}
    for label, title in SIDEBAR_LINKS.items():
        target = by_title[title]
        if target["ns"] != -1 and ("missing" in target or "redirect" in target):
            raise RuntimeError("Sidebar target is not an existing canonical article: " + title)
        link = menu.get_by_role("link", name=label, exact=True)
        if link.count() != 1 or not link.is_visible():
            raise RuntimeError("Native sidebar lost its unique visible link: " + label)
        actual = urllib.parse.urljoin(base, link.get_attribute("href"))
        expected = article_url(base, article_path, title)
        if urllib.parse.unquote(actual) != urllib.parse.unquote(expected):
            raise RuntimeError("Native sidebar link does not resolve to its internal title: " + title)
        link.focus()
        if not link.evaluate("(element) => element === document.activeElement"):
            raise RuntimeError("Native sidebar link is not keyboard-focusable: " + label)
    if menu.get_by_role("link", name="Help about MediaWiki", exact=True).count():
        raise RuntimeError("The sidebar still points contributors to external MediaWiki help.")
    if page.locator("#vector-page-tools").get_by_role(
            "link", name="Special pages", exact=True, include_hidden=True).count() != 1:
        raise RuntimeError("The native community toolbox was removed.")
    page.screenshot(path=str(Path(folder) / (name + "-navigation.png")), full_page=True)
    menu.get_by_role("link", name="Editing help", exact=True).press("Enter")
    page.wait_for_url(article_url(base, article_path, "Help:Editing"))
    if page.locator("#firstHeading").inner_text().strip() != "Help:Editing":
        raise RuntimeError("Keyboard navigation did not open the editing-help article.")
