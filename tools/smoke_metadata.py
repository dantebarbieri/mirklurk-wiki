"""Metadata and native sitemap checks against the disposable wiki only."""

import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from build_wiki import build_xml
from smoke_urls import NoRedirect


SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
TITLE = 'Synthetic "quotes" & caf\u00e9'
LEAD = 'A "quoted" guide to caf\u00e9 & equipment.'


class Head(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.active = False
        self.meta = {}
        self.canonicals = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.active = True
        if not self.active:
            return
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property", attrs.get("name", ""))
            if key in self.meta:
                raise RuntimeError(f"Duplicate metadata: {key}")
            self.meta[key] = attrs.get("content", "")
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href"))

    def handle_endtag(self, tag):
        if tag == "head":
            self.active = False


def check_head(head, canonical, social=False, title=None, description=None, image=None, noindex=False):
    expected = [] if canonical is None else [canonical]
    if head.canonicals != expected:
        raise RuntimeError(f"Canonical mismatch: {head.canonicals!r} != {expected!r}")
    if noindex and "noindex" not in head.meta.get("robots", "").split(","):
        raise RuntimeError("Core noindex policy was lost.")
    if not social:
        if any(key.startswith(("og:", "twitter:")) or key == "description" for key in head.meta):
            raise RuntimeError("Nonshareable view leaked article metadata.")
        return
    for key, value in {"og:url": canonical, "og:title": title, "description": description,
                       "og:description": description, "twitter:card": "summary", "og:image": image}.items():
        if head.meta.get(key) != value:
            raise RuntimeError(f"{key} metadata mismatch: {head.meta.get(key)!r} != {value!r}")


def sitemap_locations(body, kind, origin):
    root = ET.fromstring(body)
    if root.tag != SITEMAP_NS + kind:
        raise RuntimeError("Invalid sitemap root/namespace.")
    locations = [node.text for node in root.iter(SITEMAP_NS + "loc")]
    if not locations or len(locations) != len(set(locations)):
        raise RuntimeError("Empty or duplicate sitemap locations.")
    for location in locations:
        if not location or not location.startswith(origin + "/") or urllib.parse.urlsplit(location).fragment:
            raise RuntimeError("Sitemap location is not a canonical URL at the runtime origin.")
    return locations


def import_fixtures(run, api, fixtures):
    reader_pages = {title: text for title, text in fixtures.items()
                    if ":" not in title or title.startswith("Category:")}
    run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "importDump",
        input_bytes=build_xml(reader_pages))
    csrf = api({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
    # Nonreader fixtures belong only in the disposable API, not the publication allowlist.
    for title, text in fixtures.items():
        if title not in reader_pages:
            api({"action": "edit", "title": title, "text": text, "token": csrf}, post=True)


def wait_for_http(read):
    for attempt in range(30):
        try:
            status, _, _ = read()
            if status in (200, 401, 403):
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == 29:
                raise
        time.sleep(1)
    raise RuntimeError("Disposable Apache did not become responsive after metadata configuration change.")


def smoke_metadata(run, api, base, image_path, drain_jobs, open_authenticated):
    fixtures = {
        TITLE: LEAD + "\n\n== Later ==\nNever use this section as the description.",
        "Synthetic metadata redirect": f"#REDIRECT [[{TITLE}]]",
        "Synthetic metadata hidden": "__NOINDEX__\nNot for search previews.",
        "Synthetic metadata long": " ".join(["word"] * 60),
        "Synthetic metadata caveat": "Research status: initializer notes.",
        "Category:Synthetic metadata": "Browse the synthetic guide.",
        "User:Synthetic metadata": "Not a public article preview.",
        "Talk:Synthetic metadata": "Not a public article preview.",
        "Template:Synthetic metadata": "Not a public article preview.",
    }
    import_fixtures(run, api, fixtures)
    drain_jobs(run)
    revision = next(iter(api({"action": "query", "titles": TITLE, "prop": "revisions",
                             "rvprop": "ids"})["query"]["pages"].values()))["revisions"][0]["revid"]
    refresh = ("exec", "-T", "--user", "www-data", "mirklurk", "php",
               "/usr/local/lib/mirklurk/refresh-sitemap.php")

    def get(path, origin=base, follow_redirects=True):
        # The custom-origin scenario changes canonical config, not the local HTTP listener.
        local = base + path.removeprefix(origin) if path.startswith(origin + "/") else base + path
        try:
            opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(NoRedirect())
            response = opener.open(local, timeout=30)
        except urllib.error.HTTPError as error:
            allowed = (401, 403, 404) if follow_redirects else (301, 302, 303, 307, 308, 401, 403, 404)
            if error.code not in allowed:
                raise
            response = error
        with response:
            return response.status, response.headers, response.read()

    def article(title, query=None):
        return "/index.php?" + urllib.parse.urlencode({"title": title, "metadata-smoke": "1", **(query or {})})

    def check_format(origin):
        info = api({"action": "query", "titles": "|".join(fixtures) + "|Items", "prop": "info",
                    "inprop": "url"})["query"]["pages"]
        urls = {page["title"]: page["canonicalurl"] for page in info.values()}
        description = "Browse equipment, materials and supplies. Item pages list stats, recipes, sellers and loot sources."
        for title, expected_description in [(TITLE, LEAD), ("Items", description),
                                             ("Category:Synthetic metadata", "Browse the synthetic guide.")]:
            status, _, body = get(article(title))
            if status != 200:
                raise RuntimeError("Reader article is not HTTP 200.")
            check_head(Head(body.decode()), urls[title], True, title, expected_description, origin + image_path)
        for title in ("Synthetic metadata long", "Synthetic metadata caveat"):
            head = Head(get(article(title))[2].decode())
            if "description" in head.meta or "og:description" in head.meta or head.meta.get("og:url") != urls[title]:
                raise RuntimeError("Unsafe lead was truncated or used as a description.")
        # Requests may contain arbitrary fields; metadata never copies the request URL.
        head = Head(get(article(TITLE, {"tracking": "do-not-share", "token": "synthetic-not-a-secret"}))[2].decode())
        check_head(head, urls[TITLE], True, TITLE, LEAD, origin + image_path)
        check_head(Head(get(article("Synthetic metadata redirect"))[2].decode()),
                   urls[TITLE], True, TITLE, LEAD, origin + image_path)
        check_head(Head(get(article("Synthetic metadata redirect", {"redirect": "no"}))[2].decode()),
                   urls["Synthetic metadata redirect"])
        for query in ({"oldid": revision}, {"diff": revision, "oldid": 0}, {"action": "edit"},
                      {"action": "submit"}, {"printable": "yes"}):
            check_head(Head(get(article(TITLE, query))[2].decode()), urls[TITLE], noindex=True)
        for action in ("history", "info"):
            action_url = api({"action": "expandtemplates", "text": "{{canonicalurl:" + TITLE
                              + "|action=" + action + "}}", "prop": "wikitext"})["expandtemplates"]["wikitext"]
            check_head(Head(get(article(TITLE, {"action": action}))[2].decode()),
                       action_url, noindex=True)
        for title in ("Synthetic metadata hidden", "User:Synthetic metadata",
                      "Talk:Synthetic metadata", "Template:Synthetic metadata"):
            check_head(Head(get(article(title))[2].decode()), urls[title],
                       noindex=title == "Synthetic metadata hidden")
        for title in ("Synthetic missing metadata", "Special:Search", "Special:UserLogin"):
            status, _, body = get(article(title, {"tracking": "do-not-share"}))
            check_head(Head(body.decode()), None, noindex=True)
            if title == "Synthetic missing metadata" and status != 404:
                raise RuntimeError("Missing page no longer returns HTTP 404.")
        run(*refresh)
        status, headers, index = get("/sitemap.xml")
        if status != 200 or headers.get_content_type() != "application/xml":
            raise RuntimeError("Sitemap index is not served as XML.")
        maps = sitemap_locations(index, "sitemapindex", origin)
        locations = []
        for url in maps:
            status, headers, body = get(url, origin)
            if status != 200 or headers.get_content_type() != "application/xml":
                raise RuntimeError("A sitemap shard is not served as XML.")
            locations.extend(sitemap_locations(body, "urlset", origin))
        if not {urls[TITLE], urls["Items"], urls["Category:Synthetic metadata"]} <= set(locations):
            raise RuntimeError("Sitemap lost canonical public articles/categories.")
        excluded = {urls[title] for title in fixtures if title.startswith(
            ("User:", "Talk:", "Template:")) or title in ("Synthetic metadata redirect", "Synthetic metadata hidden")}
        if excluded.intersection(locations):
            raise RuntimeError("Native sitemap included a redirect, noindex or unsuitable namespace.")
        # Both punctuation/Unicode and ordinary URLs must actually resolve.
        for title in (TITLE, "Items", "Category:Synthetic metadata"):
            status, _, body = get(urls[title], origin)
            if status != 200:
                raise RuntimeError("Sitemap article URL is not servable.")
            if Head(body.decode()).meta.get("og:url") != urls[title]:
                raise RuntimeError("The served sitemap URL lost its matching native canonical/social URL.")
        robots = get("/robots.txt")
        if (robots[0] != 200 or robots[1].get_content_type() != "text/plain"
                or f"Sitemap: {origin}/sitemap.xml\n" not in robots[2].decode()
                or "Disallow: /api.php\n" not in robots[2].decode()):
            raise RuntimeError("Robots discovery or crawler policy is missing.")
        # Probe a real private sibling of public/. Unknown root URLs may render a
        # wiki response instead of Apache's 404, so status alone is not a leak test.
        marker = b"synthetic-private-sitemap-marker"
        run("exec", "-T", "--user", "www-data", "mirklurk", "sh", "-c",
            "cat > /var/lib/mirklurk-sitemap/sitemap-private-probe.xml", input_bytes=marker)
        try:
            for path in ("/sitemap-private-probe.xml", "/public/sitemap-private-probe.xml",
                         "/sitemap/sitemap-private-probe.xml", "/refresh-sitemap.php"):
                _, _, body = get(path, follow_redirects=False)
                if marker in body or b"<?php" in body:
                    raise RuntimeError(f"Private sitemap content leaked through {path}.")
        finally:
            run("exec", "-T", "--user", "www-data", "mirklurk", "rm",
                "/var/lib/mirklurk-sitemap/sitemap-private-probe.xml")
        return index

    original_settings = run("exec", "-T", "mirklurk", "cat", "/var/www/html/LocalSettings.php")

    def settings(text):
        run("exec", "-T", "mirklurk", "sh", "-c", "cat > /var/www/html/LocalSettings.php",
            input_bytes=original_settings + text.encode())
        # Ensure the Apache workers do not retain old opcache settings.
        run("restart", "mirklurk")
        # A deliberately private wiki cannot pass the public API healthcheck.
        wait_for_http(lambda: get(article("Items")))

    try:
        baseline = check_format(base)
        run("exec", "-T", "mirklurk", "chmod", "0555", "/var/lib/mirklurk-sitemap/public")
        try:
            try:
                run(*refresh)
            except subprocess.CalledProcessError as error:
                if b"Cannot publish sitemap shard" not in error.stdout + error.stderr:
                    raise
            else:
                raise RuntimeError("Sitemap refresh unexpectedly wrote to read-only public storage.")
            if get("/sitemap.xml")[2] != baseline:
                raise RuntimeError("A shard publication failure replaced the previous complete index.")
        finally:
            run("exec", "-T", "mirklurk", "chmod", "0755", "/var/lib/mirklurk-sitemap/public")
        urls = {page["title"]: page["canonicalurl"] for page in api({
            "action": "query", "titles": TITLE + "|Items", "prop": "info", "inprop": "url",
        })["query"]["pages"].values()}
        with open_authenticated(base + article(TITLE), timeout=30) as response:
            check_head(Head(response.read().decode()), urls[TITLE])
        csrf = api({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
        revised = "The live editor's updated equipment guide."
        api({"action": "edit", "title": TITLE, "text": revised, "token": csrf}, post=True)
        head = Head(get(article(TITLE))[2].decode())
        if head.meta.get("description") != revised:
            raise RuntimeError("Description did not follow the current live edit.")
        api({"action": "edit", "title": TITLE, "text": fixtures[TITLE], "token": csrf}, post=True)
        settings("\n$wgArticleRobotPolicies['Items'] = 'noindex,follow';\n")
        try:
            run(*refresh)
        except subprocess.CalledProcessError as error:
            if b"reviewed main/category indexing policy" not in error.stdout + error.stderr:
                raise
        else:
            raise RuntimeError("Sitemap refresh did not refuse unsupported robot policy.")
        if get("/sitemap.xml")[2] != baseline:
            raise RuntimeError("A failed refresh replaced the served sitemap.")
        check_head(Head(get(article("Items"))[2].decode()), urls["Items"], noindex=True)
        settings("\n$wgGroupPermissions['*']['read'] = false;\n")
        check_head(Head(get(article("Items"))[2].decode()), None, noindex=True)
        try:
            run(*refresh)
        except subprocess.CalledProcessError as error:
            if b"reviewed main/category indexing policy" not in error.stdout + error.stderr:
                raise
        else:
            raise RuntimeError("Sitemap refresh did not refuse a private wiki.")
        settings("\n$wgExemptFromUserRobotsControl = [NS_MAIN];\n")
        try:
            run(*refresh)
        except subprocess.CalledProcessError as error:
            if b"reviewed main/category indexing policy" not in error.stdout + error.stderr:
                raise
        else:
            raise RuntimeError("Sitemap refresh did not refuse disabled author noindex controls.")
        # The real image/vhost uses /w/. Retain regression coverage for the old
        # query layout without the short-layout-only legacy-view redirect hook.
        settings("\n$wgArticlePath = '/index.php?title=$1';\n$wgHooks['MediaWikiPerformAction'] = [];\n")
        check_format(base)
        custom_origin = "https://wiki.example.invalid"
        run("exec", "-T", "mirklurk", "sh", "-c",
            "cat > /etc/apache2/conf-enabled/metadata-test-origin.conf",
            input_bytes=b"SetEnv MW_SERVER_URL https://wiki.example.invalid\n")
        settings("\n$wgServer = $wgCanonicalServer = 'https://wiki.example.invalid';\n")
        check_format(custom_origin)
    finally:
        run("exec", "-T", "mirklurk", "rm", "-f", "/etc/apache2/conf-enabled/metadata-test-origin.conf")
        settings("")
        run("up", "-d", "--wait", "mirklurk")
    print("Metadata passed: native canonicals, safe live lead previews, robots and atomic native sitemaps in both URL formats.")
