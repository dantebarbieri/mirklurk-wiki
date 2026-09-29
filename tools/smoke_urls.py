"""Actual Apache/MediaWiki URL checks, only on the disposable loopback wiki."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrlMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.styles = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.styles.append(attrs["href"])


def config_value(html, name):
    match = re.search(r'"' + re.escape(name) + r'":("(?:[^"\\]|\\.)*"|\d+)', html)
    if not match:
        raise RuntimeError("Article HTML lacks " + name)
    return json.loads(match[1])


def smoke_urls(api, base, token, editor_password):
    if urllib.parse.urlsplit(base).hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("URL smoke may only write to the disposable localhost wiki.")
    opener = urllib.request.build_opener(NoRedirect())

    def request(path, method="GET", data=None):
        url = urllib.parse.urljoin(base, path)
        if not url.startswith(base + "/"):
            raise RuntimeError("URL smoke encountered a non-local target.")
        req = urllib.request.Request(url, method=method, data=data)
        try:
            response = opener.open(req, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read().decode("utf-8")

    def follow(path):
        for _ in range(5):
            status, headers, html = request(path)
            if status not in {301, 302, 303, 307, 308}:
                return status, html, urllib.parse.urljoin(base, path)
            path = urllib.parse.urljoin(base, headers["Location"])
        raise RuntimeError("Article routing exceeded five redirects.")

    def old_url(title, **query):
        return "/index.php?" + urllib.parse.urlencode({"title": title.replace(" ", "_"), **query})

    def check_article(html, title, revision):
        if (config_value(html, "wgPageName") != title.replace(" ", "_")
                or config_value(html, "wgRevisionId") != revision):
            raise RuntimeError("HTTP article title/revision differs from the API: " + title)

    def save(title, text):
        result = api({"action": "edit", "title": title, "text": text, "token": token,
                      "summary": "Disposable URL fixture"}, post=True).get("edit", {})
        if result.get("result") != "Success":
            raise RuntimeError("Could not save disposable URL fixture.")
        return result["newrevid"]

    general = api({"action": "query", "meta": "siteinfo", "siprop": "general"})["query"]["general"]
    if (general["articlepath"] != "/w/$1" or general["scriptpath"] != ""
            or general["script"] != "/index.php" or general["server"] != base):
        raise RuntimeError("Short article URLs changed the runtime origin or root script contract.")

    titles = [
        "URL smoke", "URL smoke & action=edit", "URL smoke + plus",
        "URL smoke 50% complete", "URL smoke question?mark", "URL smoke semi;colon",
        "URL smoke O'Brien (one)", "URL smoke caf\u00e9 \u96ea",
        "User:URL smoke/Subpage", "Category:URL smoke",
    ]
    revisions = {}
    for index, title in enumerate(titles):
        revisions[title] = save(title, f"Disposable URL fixture {index}.\n\n== Anchor ==\n\n[[URL smoke]]")
    first_revision = revisions[titles[0]]
    revisions[titles[0]] = save(titles[0], "Disposable revised URL fixture.\n\n== Anchor ==\n\n[[URL smoke + plus]]")
    pages = api({"action": "query", "titles": "|".join(titles), "prop": "info",
                 "inprop": "url"})["query"]["pages"]
    urls = {page["title"]: page["fullurl"] for page in pages.values()}
    if set(urls) != set(titles):
        raise RuntimeError("MediaWiki did not accept the exact punctuation/title fixtures.")

    for title in titles:
        canonical = urls[title]
        if not canonical.startswith(base + "/w/"):
            raise RuntimeError("MediaWiki generated a non-short article URL.")
        status, _, html = request(canonical)
        if status != 200:
            raise RuntimeError(f"Canonical URL failed ({status}): {canonical}")
        check_article(html, title, revisions[title])
        for query in ({}, {"action": "view"}):
            legacy = old_url(title, **query)
            for method in ("GET", "HEAD"):
                status, headers, body = request(legacy, method)
                if status != 301 or headers.get("Location") != canonical or (method == "HEAD" and body):
                    raise RuntimeError("Plain old view did not redirect exactly once: " + legacy)
            status, body, final = follow(legacy)
            if status != 200 or final != canonical:
                raise RuntimeError("Old/new article URLs do not converge.")
            check_article(body, title, revisions[title])
        status, _, body = request(canonical, "HEAD")
        if status != 200 or body:
            raise RuntimeError("Short URL HEAD changed status or sent a body.")
        # Encoded slashes are legal to the Apache router, decoded only by MediaWiki.
        encoded = base + "/w/" + urllib.parse.quote(title.replace(" ", "_"), safe="")
        status, body, _ = follow(encoded)
        if status != 200:
            raise RuntimeError("Encoded title URL failed: " + encoded)
        check_article(body, title, revisions[title])
        rest = "/rest.php/v1/page/" + urllib.parse.quote(title.replace(" ", "_"), safe="") + "/bare"
        status, headers, body = request(rest)
        if status != 200 or "application/json" not in headers.get("Content-Type", ""):
            raise RuntimeError("Root REST path-info did not survive: " + rest)
        record = json.loads(body)
        if record["title"] != title or record["latest"]["id"] != revisions[title]:
            raise RuntimeError("REST returned a different title/revision.")

    for root in ("/", "/index.php", "/w", "/w/"):
        status, html, final = follow(root)
        if status != 200 or final != general["base"]:
            raise RuntimeError("Root/empty article path did not reach the configured Main Page.")
        if config_value(html, "wgPageName") != general["mainpage"].replace(" ", "_"):
            raise RuntimeError("Root routing changed the main-page title.")
    title = titles[0]
    canonical = urls[title]
    for query in (
        {"action": "history"}, {"oldid": str(first_revision)},
        {"diff": str(revisions[title]), "oldid": str(first_revision)},
        {"action": "info"}, {"action": "raw"}, {"action": "render"},
        {"useskin": "vector"}, {"printable": "yes"}, {"redirect": "no"},
        {"uselang": "en"}, {"unknown": "a&b+c%20;d"},
    ):
        for path in (old_url(title, **query), canonical + "?" + urllib.parse.urlencode(query)):
            status, headers, body = request(path)
            if status != 200 or "Location" in headers:
                raise RuntimeError("A parameterized request was redirected or failed: " + path)
            if query.get("action") == "history" and 'id="pagehistory"' not in body:
                raise RuntimeError("History no longer displays revisions.")
            if "oldid" in query and "diff" not in query:
                check_article(body, title, first_revision)
            if "diff" in query and 'class="diff' not in body:
                raise RuntimeError("Diff did not render.")
            if query.get("action") == "raw" and "Disposable revised URL fixture" not in body:
                raise RuntimeError("Raw action no longer returns source.")
    for path in (old_url(title), canonical):
        status, headers, html = request(path, "POST", b"action=view")
        if status != 200 or "Location" in headers:
            raise RuntimeError("An article POST was redirected.")
        check_article(html, title, revisions[title])
    for query in ("title=URL_smoke&title=URL_smoke", "title=URL_smoke&action=view&action=view"):
        status, headers, _ = request("/index.php?" + query)
        if status != 200 or "Location" in headers:
            raise RuntimeError("Ambiguous duplicate parameters were canonicalized.")
    for page in ("Special:UserLogin", "Special:CreateAccount", "Special:Version"):
        for path in (old_url(page), "/w/" + page):
            status, headers, body = request(path)
            if status != 200 or "Location" in headers or not body:
                raise RuntimeError("Special page compatibility failed: " + page)
    for path in (old_url("Special:Search", search="nonexistent url smoke search", fulltext="1"),
                 "/w/Special:Search?search=nonexistent+url+smoke+search&fulltext=1"):
        status, _, body = request(path)
        if status != 200 or "mw-search" not in body:
            raise RuntimeError("Search endpoint no longer renders search results.")
    missing = "URL smoke missing"
    for path in (old_url(missing), "/w/URL_smoke_missing"):
        status, html, _ = follow(path)
        if status != 404:
            raise RuntimeError("Missing articles must remain HTTP 404.")
        check_article(html, missing, 0)
    # BadTitleError uses 404 in 1.43; %2526 must not become the existing '&' title.
    status, _, _ = request("/w/URL_smoke_%2526_action=edit")
    if status != 404:
        raise RuntimeError(f"A double-encoded invalid title returned {status}, not the upstream 404.")

    redirect_title = "URL smoke redirect"
    save(redirect_title, "#REDIRECT [[URL smoke]]")
    status, headers, _ = request(old_url(redirect_title))
    if status != 301 or headers.get("Location") != base + "/w/URL_smoke_redirect":
        raise RuntimeError("Legacy redirect-page URL skipped its native wiki redirect.")
    status, html, _ = follow(old_url(redirect_title))
    if status != 200 or config_value(html, "wgRedirectedFrom") != "URL_smoke_redirect":
        raise RuntimeError("Wiki redirects lost their redirected-from notice.")

    status, _, html = request(canonical)
    markup = UrlMarkup(html)
    if "/w/URL_smoke_%2B_plus" not in markup.links:
        raise RuntimeError("Native wikilinks did not generate encoded short article URLs.")
    if not markup.styles:
        raise RuntimeError("Article HTML did not expose ResourceLoader CSS.")
    for path in [*markup.styles, "/load.php?modules=startup&lang=en&only=scripts"]:
        if urllib.parse.urlsplit(path).path != "/load.php":
            raise RuntimeError("ResourceLoader moved out of the root.")
        status, headers, body = request(path)
        if (status != 200 or not body
                or not any(mime in headers.get("Content-Type", "") for mime in ("javascript", "text/css"))):
            raise RuntimeError("A root ResourceLoader script/style failed.")
    status, headers, _ = request("/resources/assets/poweredby_mediawiki.svg")
    if status != 200 or "image/svg+xml" not in headers.get("Content-Type", ""):
        raise RuntimeError("Root static assets stopped working.")
    smoke_url_editor(api, base, canonical, title, editor_password, old_url)
    print("URL HTTP/browser smoke passed: old/new title+revision identity, GET/HEAD redirects, roots, "
          "punctuation/Unicode/namespaces/subpages, query/actions/revisions, 404, REST, scripts/assets, "
          "fragments and login/edit/POST-save.", flush=True)


def smoke_url_editor(api, base, canonical, title, password, old_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(base + old_url(title) + "#Anchor", wait_until="networkidle")
            if page.url != canonical + "#Anchor" or not page.locator("#Anchor").count():
                raise RuntimeError("A browser fragment was lost on the legacy view redirect.")
            page.goto(base + old_url("Special:UserLogin", returnto=title, returntoquery="action=edit"),
                      wait_until="networkidle")
            page.locator("#wpName1").fill("TestEditor")
            page.locator("#wpPassword1").fill(password)
            page.locator("#wpLoginAttempt").click()
            page.wait_for_load_state("networkidle")
            page.wait_for_selector("#wpTextbox1")
            if page.evaluate("mw.config.get('wgUserName')") != "TestEditor":
                raise RuntimeError("Browser login did not retain the editor session.")
            # Short-path editing must use the same source editor and root form endpoint.
            page.goto(canonical + "?action=edit", wait_until="networkidle")
            text = page.locator("#wpTextbox1").input_value()
            form = page.locator("#editform")
            target = urllib.parse.urlsplit(form.get_attribute("action"))
            if target.path != "/index.php" or urllib.parse.parse_qs(target.query).get("action") != ["submit"]:
                raise RuntimeError("Source editor no longer posts to root index.php.")
            updated = text + "\n\nDisposable browser POST save."
            page.locator("#wpTextbox1").fill(updated)
            with page.expect_request(lambda req: req.method == "POST"
                                     and urllib.parse.urlsplit(req.url).path == "/index.php"):
                page.locator("#wpSave").click()
            page.wait_for_load_state("networkidle")
            page.wait_for_url(canonical + "*")
            if "Disposable browser POST save." not in page.locator(".mw-parser-output").inner_text():
                raise RuntimeError("Browser source edit was not saved and rendered.")
            live = next(iter(api({"action": "query", "titles": title, "prop": "revisions",
                                  "rvprop": "ids|content|user", "rvslots": "main"})["query"]["pages"].values()))
            revision = live["revisions"][0]
            if (revision["user"] != "TestEditor"
                    or revision["slots"]["main"]["*"].strip() != updated.strip()
                    or page.evaluate("mw.config.get('wgRevisionId')") != revision["revid"]):
                raise RuntimeError("Saved browser revision differs from the root API.")
        finally:
            browser.close()
