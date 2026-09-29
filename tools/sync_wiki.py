"""Publish the generated pages to a live MediaWiki through its web API.

Dry run by default: reports what would change without logging in. With --apply,
it creates missing pages and updates pages whose latest revision came from the
publishing automation. Pages last edited by anyone else are skipped and listed
for a manual merge; only an explicit --adopt replaces them.
"""

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from wiki_data import title_key
from wiki_details import load_publication_inputs
from wiki_display import DISPLAY_TITLES, content_model, dependencies, page_namespace, validate_display_dependencies
from wiki_render import build_pages, validate_reader_pages
from wiki_views import available_views, transclusions


ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PREFIX = "repo-sync:"
# Every sync save ends its summary with a hash of the text it meant to store.
STAMP = re.compile(r" text:([0-9a-f]{32})$")
# Summaries of the publication workflows this tool replaced; no new ones are written.
LEGACY_SUMMARIES = ("native-publication/v1:", "Publish reviewed ", "Original repository seed")
# MediaWiki's installer and maintenance identities; nobody can log in as these.
SYSTEM_USERS = {"MediaWiki default", "Maintenance script"}
DEFAULT_ACCOUNTS = ("WikiAdmin",)
BATCH = 50
PHP_WHITESPACE = " \t\n\r\0\x0b"
USER_AGENT = "MirkLurkWikiSync/1 (+https://github.com/dantebarbieri/mirklurk-wiki)"
LINK = re.compile(r"\[\[(:?)([^\[\]|#\n]+)")
FILE = re.compile(r"\[\[(?:File|Image):([^\[\]|#\n]+)", re.IGNORECASE)
CONFLICTS = {"editconflict", "articleexists", "missingtitle"}
RATE_LIMIT_WAIT = 15
RATE_LIMIT_RETRIES = 8


class SyncError(RuntimeError):
    pass


class ApiError(SyncError):
    def __init__(self, code, info=""):
        super().__init__(f"{code}: {info}" if info else code)
        self.code = code


class Api:
    """Minimal MediaWiki Action API client with its own cookie session."""

    def __init__(self, url, timeout=60, retries=3, opener=None):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.path.endswith("/api.php"):
            raise SyncError("The API URL must be an http(s) URL ending in /api.php.")
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self.opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.username = None
        self.rights = set()
        self.token = None

    def call(self, params, post=False, retry=True):
        payload = urllib.parse.urlencode(
            {**params, "format": "json", "formatversion": "2", "errorformat": "plaintext"}).encode()
        attempts = self.retries if retry else 1
        for attempt in range(attempts):
            request = urllib.request.Request(
                self.url if post else self.url + "?" + payload.decode(),
                data=payload if post else None, headers={"User-Agent": USER_AGENT})
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    result = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                    raise ApiError("http", f"HTTP {error.code} from the wiki API") from None
            except (urllib.error.URLError, OSError, ValueError) as error:
                if attempt + 1 >= attempts:
                    raise ApiError("http", f"{type(error).__name__} contacting the wiki API") from None
            time.sleep(2 ** attempt)
        errors = result.get("errors") or ([result["error"]] if "error" in result else [])
        if errors:
            raise ApiError(errors[0].get("code", "unknown"), errors[0].get("text") or errors[0].get("info", ""))
        return result

    def login(self, username, password):
        token = self.call({"action": "query", "meta": "tokens", "type": "login"})["query"]["tokens"]["logintoken"]
        outcome = self.call({"action": "login", "lgname": username, "lgpassword": password, "lgtoken": token},
                            post=True, retry=False)["login"]
        if outcome.get("result") != "Success":
            raise SyncError(f"MediaWiki rejected the login for {username} ({outcome.get('result', 'unknown')}).")
        self.username = outcome["lgusername"]
        self.token = None
        self.rights = set(self.call({"action": "query", "meta": "userinfo", "uiprop": "rights"})
                          ["query"]["userinfo"].get("rights", []))
        missing = {"edit", "createpage"} - self.rights
        if missing:
            raise SyncError(f"{self.username} lacks {', '.join(sorted(missing))}; check the bot password grants.")
        return self.username

    def csrf(self):
        if self.token is None:
            self.token = self.call({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
        return self.token


def normalize(text):
    """Mirror MediaWiki's pre-save trailing-whitespace and line-ending normalization."""
    return text.rstrip(PHP_WHITESPACE).replace("\r\n", "\n").replace("\r", "\n")


def stamp(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:32]


def automation_owned(revision, accounts):
    user = revision.get("user") or ""
    if user in SYSTEM_USERS or user.startswith("imported>"):
        return True
    comment = revision.get("comment") or ""
    if user not in accounts:
        return False
    if comment.startswith(SUMMARY_PREFIX):
        # A sync revision only counts while it still holds the text it was stamped with,
        # so a save that MediaWiki merged with someone's concurrent edit stays theirs.
        match = STAMP.search(comment)
        return bool(match) and revision.get("text") is not None and match.group(1) == stamp(revision["text"])
    return comment.startswith(LEGACY_SUMMARIES)


def fetch_live(api, titles):
    """Latest revision of each title, or None when the page does not exist."""
    live = {}
    ordered = sorted(titles)
    for start in range(0, len(ordered), BATCH):
        batch = ordered[start:start + BATCH]
        query = api.call({
            "action": "query", "prop": "revisions", "rvprop": "ids|timestamp|user|comment|content",
            "rvslots": "main", "titles": "|".join(batch),
        }, post=True).get("query", {})
        aliases = {row["to"]: row["from"] for row in query.get("normalized", [])}
        for page in query.get("pages", []):
            title = aliases.get(page.get("title"), page.get("title"))
            if page.get("invalid") or title not in batch:
                raise SyncError(f"The wiki returned an invalid or unexpected title: {title!r}")
            if page.get("ns") != page_namespace(title):
                raise SyncError(f"{title} resolved to an unexpected namespace.")
            if page.get("missing"):
                live[title] = None
                continue
            revision = page["revisions"][0]
            slot = revision.get("slots", {}).get("main", {})
            model = slot.get("contentmodel", "wikitext")
            if title in DISPLAY_TITLES and model != content_model(title):
                raise SyncError(f"{title} has content model {model!r}; expected {content_model(title)}. No pages written.")
            readable = not slot.get("texthidden") and model == content_model(title)
            live[title] = {
                "revid": revision["revid"], "timestamp": revision.get("timestamp", ""),
                "user": revision.get("user"), "comment": revision.get("comment", ""),
                "text": slot.get("content") if readable else None,
                "contentmodel": model,
            }
        if set(batch) - live.keys():
            raise SyncError("The wiki omitted requested pages: " + ", ".join(sorted(set(batch) - live.keys())))
    return live


def bot_accounts(api, live):
    """Latest editors who belong to MediaWiki's bot group (only bureaucrats can grant it)."""
    users = sorted({row["user"] for row in live.values() if row and row.get("user")
                    and row["user"] not in SYSTEM_USERS and not row["user"].startswith("imported>")})
    bots = set()
    for start in range(0, len(users), BATCH):
        query = api.call({"action": "query", "list": "users", "usprop": "groups",
                          "ususers": "|".join(users[start:start + BATCH])}, post=True).get("query", {})
        bots.update(row["name"] for row in query.get("users", []) if "bot" in row.get("groups", []))
    return bots


def plan_changes(pages, live, accounts, adopt=()):
    actions = {}
    for title in sorted(pages):
        current = live.get(title)
        if current is None:
            actions[title] = "create"
        elif current["text"] is not None and normalize(current["text"]) == normalize(pages[title]):
            actions[title] = "unchanged"
        elif current["text"] is not None and (automation_owned(current, accounts) or title in adopt):
            actions[title] = "update"
        else:
            actions[title] = "skip"
    return actions


def owners(text, title=""):
    return dependencies(text, title.startswith("Module:"))


def links(text):
    # [[Category:X]] is a membership, which MediaWiki renders fresh on every view.
    return {title_key(target.strip()) for colon, target in LINK.findall(text)
            if target.strip() and (colon or not target.lstrip().lower().startswith("category:"))}


def missing_views(text, sources):
    """(owner, view) pairs this page includes that the owners' current text does not provide."""
    return sorted({(owner, dict(arguments).get("view", "")) for owner, arguments in transclusions(text)
                   if dict(arguments).get("view", "") not in available_views(sources.get(owner) or "")})


def write_order(titles, pages):
    """Transcluded owners before their readers where possible.

    Merchants and items include views of each other, so some pages are saved
    before an owner; stale_renderings() lists them for a re-render afterwards.
    """
    pending = set(titles)
    needs = {title: owners(pages[title], title) - {title} for title in pending}
    order = []
    while pending:
        ready = [title for title in sorted(pending) if not needs[title] & pending]
        if ready:
            def tier(title):
                return 0 if title.startswith("Module:") else 1 if title.startswith("Template:") else 2
            first = min(tier(title) for title in ready)
            ready = [title for title in ready if tier(title) == first]
        batch = ready or [min(pending)]
        order.extend(batch)
        pending.difference_update(batch)
    return order


def stale_renderings(texts, written, created):
    """Pages rendered before a page they include was saved, or before a page they link to existed.

    Inclusion is transitive: a view that itself includes another page shows that page's text
    too. MediaWiki 1.43 null edits re-render without advancing page_touched, and bot passwords
    cannot purge, so staleness follows this run's write order rather than timestamps.
    """
    position = {title: index for index, title in enumerate(written)}
    direct = {title: owners(text, title) - {title} for title, text in texts.items()}
    linked = {title: links(text) for title, text in texts.items()}

    def included(title):
        seen, stack = set(), list(direct[title])
        while stack:
            owner = stack.pop()
            if owner not in seen and owner != title:
                seen.add(owner)
                stack.extend(direct.get(owner, ()))
        return seen

    stale = []
    for title, text in sorted(texts.items()):
        mine = position.get(title, -1)
        shown = included(title)
        # A page also shows the links inside the views it includes.
        seen_links = linked[title].union(*(linked.get(owner, ()) for owner in shown))
        targets = (shown & position.keys()) | ((seen_links & created) - {title})
        if any(position[target] > mine for target in targets):
            stale.append(title)
    return stale


def edit(api, params):
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return api.call({**params, "token": api.csrf(), "assert": "user", "bot": "1",
                             "watchlist": "nochange"}, post=True, retry=False).get("edit", {})
        except ApiError as error:
            if error.code == "badtoken":
                api.token = None
            elif error.code == "ratelimited" and attempt < RATE_LIMIT_RETRIES:
                time.sleep(RATE_LIMIT_WAIT)
            else:
                raise
    raise SyncError("Edit retries were exhausted.")


def save(api, title, text, current, summary):
    """Save text as the automation; with the text just read, this is a guarded null edit."""
    params = {"action": "edit", "title": title, "text": text, "summary": f"{summary} text:{stamp(text)}",
              "contentmodel": content_model(title),
              "contentformat": "text/plain" if content_model(title) == "Scribunto" else "text/x-wiki"}
    if current is None:
        params["createonly"] = "1"
    else:
        params.update(nocreate="1", baserevid=str(current["revid"]))
    outcome = edit(api, params)
    if outcome.get("result") != "Success":
        raise ApiError(str(outcome.get("result", "failure")).lower(), "MediaWiki did not accept the edit")
    if current is not None and outcome.get("oldrevid") not in (None, current["revid"]):
        # Someone saved in between and MediaWiki merged both edits. The merged text no longer
        # matches this save's stamp, so later runs treat the page as that person's edit.
        raise ApiError("editconflict", "saved by someone else during the sync; MediaWiki kept both edits")
    return outcome.get("newrevid") or (current or {}).get("revid")


def missing_files(api, pages):
    names = sorted({"File:" + name.strip() for text in pages.values() for name in FILE.findall(text)})
    missing = []
    for start in range(0, len(names), BATCH):
        batch = names[start:start + BATCH]
        query = api.call({"action": "query", "prop": "imageinfo", "iiprop": "size",
                          "titles": "|".join(batch)}, post=True).get("query", {})
        aliases = {row["to"]: row["from"] for row in query.get("normalized", [])}
        missing += [aliases.get(page["title"], page["title"]) for page in query.get("pages", [])
                    if not page.get("imagerepository")]
    return sorted(missing)


def runtime_preflight(api, pages, apply):
    """No page writes: inspect registration, then exercise the actual Lua engine on apply."""
    if not DISPLAY_TITLES & pages.keys():
        return
    query = api.call({"action": "query", "meta": "siteinfo", "siprop": "extensions|namespaces"})["query"]
    extensions = {row["name"] for row in query.get("extensions", [])}
    namespaces = {int(key): row for key, row in query.get("namespaces", {}).items()}
    if not {"Scribunto", "ParserFunctions"} <= extensions or any(
        namespaces.get(number, {}).get("canonical") != name or namespaces[number].get("case") != "first-letter"
        for number, name in ((10, "Template"), (828, "Module"))
    ):
        raise SyncError("Display templates require deployed Scribunto, ParserFunctions and canonical Template/Module namespaces. No pages written.")
    info = api.call({"action": "paraminfo", "modules": "edit"})
    parameters = info.get("paraminfo", {}).get("modules", [{}])[0].get("parameters", [])
    models = next((row.get("type", []) for row in parameters if row.get("name") == "contentmodel"), [])
    if "Scribunto" not in models or "wikitext" not in models:
        raise SyncError("The target edit API does not support Scribunto and wikitext content models. No pages written.")
    if apply:
        # The extension's console compiles an unsaved module and executes in its sandbox.
        # It only caches a debug session; it never saves a page or runs an edit action.
        for title in sorted(title for title in pages if content_model(title) == "Scribunto"):
            probe = api.call({"action": "scribunto-console", "title": title,
                              "content": pages[title], "question": "print('mirklurk-display-runtime-ok')",
                              "token": api.csrf()}, post=True)
            if probe.get("type") != "normal" or probe.get("print", "").strip() != "mirklurk-display-runtime-ok":
                raise SyncError(f"The deployed Scribunto Lua engine failed its unsaved-module probe for {title}. No pages written.")


def sync(api, pages, summary, accounts=(), apply=False, log=print, adopt=()):
    if not summary.startswith(SUMMARY_PREFIX):
        raise SyncError(f"Edit summaries must start with {SUMMARY_PREFIX!r} so later runs recognize them.")
    if apply and not api.username:
        raise SyncError("Log in before applying changes.")
    unnormalized = sorted(title for title in pages if title_key(title) != title)
    if unnormalized:
        raise SyncError("Generated titles must be normalized: " + ", ".join(unnormalized[:5]))
    validate_display_dependencies(pages)
    runtime_preflight(api, pages, apply)
    adopt = {title_key(title) for title in adopt}
    if adopt - pages.keys():
        raise SyncError("Only generated pages can be adopted: " + ", ".join(sorted(adopt - pages.keys())))
    accounts = {*DEFAULT_ACCOUNTS, *accounts, *([api.username] if api.username else [])}
    live = fetch_live(api, pages)
    accounts |= bot_accounts(api, live)
    actions = plan_changes(pages, live, accounts, adopt)
    report = {
        "mode": "apply" if apply else "dry-run", "summary": summary,
        "counts": {action: sum(value == action for value in actions.values())
                   for action in ("create", "update", "unchanged", "skip")},
        "create": [title for title, action in actions.items() if action == "create"],
        "update": [title for title, action in actions.items() if action == "update"],
        "skipped": [{"title": title, "user": live[title]["user"], "timestamp": live[title]["timestamp"],
                     "revid": live[title]["revid"]} for title, action in actions.items() if action == "skip"],
        "created": [], "updated": [], "conflicts": [], "errors": [], "blocked": [], "refresh": [],
        "refreshed": [], "unverified": [],
        # Matching text leaves no revision to take over; adopt these again once their text changes.
        "adopt_pending": sorted(title for title in adopt if actions[title] == "unchanged"
                                and not automation_owned(live[title], accounts)),
    }
    order = write_order(report["create"] + report["update"], pages)
    # Each page's text as the wiki will serve it; a dry run assumes every planned save succeeds.
    sources = {title: row["text"] for title, row in live.items() if row and row["text"] is not None}
    planned, written, created = set(order), [], set()
    unavailable = {title for title in DISPLAY_TITLES & pages.keys() if actions[title] == "skip"}

    def publish(title):
        planned.discard(title)
        if apply:
            try:
                save(api, title, pages[title], live[title], summary)
            except ApiError as error:
                if error.code == "readonly":
                    raise SyncError(f"The wiki is read-only ({error}); nothing further was written.") from None
                bucket = "conflicts" if error.code in CONFLICTS else "errors"
                detail = str(error)
                if error.code == "http":
                    detail += "; the save may still have happened, so the next run re-checks this page"
                report[bucket].append({"title": title, "error": detail})
                if title in DISPLAY_TITLES:
                    unavailable.add(title)
                log(f"{bucket[:-1]}: {title}: {detail}")
                return
            report["created" if actions[title] == "create" else "updated"].append(title)
            log(f"{actions[title]}d: {title}")
        sources[title] = pages[title]
        written.append(title)
        created.update([title] if actions[title] == "create" else [])

    def missing(title):
        needed = [] if content_model(title) == "Scribunto" else missing_views(pages[title], {**sources, title: pages[title]})
        seen, stack = {title}, list(owners(pages[title], title))
        while stack:
            owner = stack.pop()
            if owner in seen:
                continue
            seen.add(owner)
            if owner.startswith(("Template:", "Module:")):
                if owner in unavailable:
                    needed.append((owner, "reviewed display definition"))
                    continue
                if owner in planned or owner not in sources:
                    needed.append((owner, "display definition"))
                    continue
            source = pages.get(owner, "") if owner in planned else sources.get(owner, "")
            stack.extend(owners(source, owner))
        return sorted(set(needed))

    queue = order
    while queue:
        waiting, progress = [], False
        for title in queue:
            needed = missing(title)
            pending = [pair for pair in needed if pair[0] in planned and pair[0] not in unavailable]
            if len(pending) < len(needed):
                # An owner that will not be published this run lacks the view; a later run retries.
                planned.discard(title)
                if title in DISPLAY_TITLES:
                    unavailable.add(title)
                needs = [f"{owner} ({view or 'default'} view)" for owner, view in needed if (owner, view) not in pending]
                report["blocked"].append({"title": title, "needs": needs})
                log(f"blocked: {title}: needs {', '.join(needs)}")
                progress = True
            elif pending:
                waiting.append(title)
            else:
                publish(title)
                progress = True
        if waiting and not progress:
            # These only wait on each other (a cycle): save one now; the refresh re-renders it.
            publish(waiting.pop(0))
        queue = waiting
    for title in written:
        if missing(title):
            report["errors"].append({"title": title, "error": "saved ahead of an owner whose save then failed; "
                                     "it shows " + ", ".join(owner for owner, _ in missing(title)) + " without the view"})
    current = fetch_live(api, pages) if apply and written else live
    texts = {title: pages[title] if title in written else row["text"]
             for title, row in current.items() if title in written or (row and row["text"] is not None)}
    # Pages people edited last are left to MediaWiki's job queue. A real run trusts only the fresh
    # re-read, so a page deleted or taken over by a person since its save is not touched.
    report["refresh"] = [title for title in stale_renderings(texts, written, created)
                         if (not apply and title in written) or (current.get(title) and current[title]["text"] is not None
                                                                 and automation_owned(current[title], accounts))]
    for title in report["refresh"] if apply else []:
        try:
            # Re-saving the text just read re-renders the page. baserevid turns a concurrent save
            # into a conflict or no-op; a revision only appears when an import left trailing whitespace.
            save(api, title, current[title]["text"], current[title], summary)
            report["refreshed"].append(title)
        except ApiError as error:
            bucket = "conflicts" if error.code in CONFLICTS else "errors"
            report[bucket].append({"title": title, "error": f"refresh: {error}"})
    report["unverified"] = [title for title in (written if apply else [])
                            if current[title] is None or current[title]["text"] is None
                            or normalize(current[title]["text"]) != normalize(pages[title])]
    report["missing_files"] = missing_files(api, pages)
    return report


def markdown(report, api_url):
    counts = report["counts"]
    dry = report["mode"] == "dry-run"
    lines = [
        f"### Wiki sync ({report['mode']})", "", f"{api_url} · `{report['summary']}`", "",
        "| Create | Update | Unchanged | Skipped (edited by a person) |", "| --- | --- | --- | --- |",
        f"| {counts['create']} | {counts['update']} | {counts['unchanged']} | {counts['skip']} |", "",
    ]
    if dry:
        lines += [f"{len(report['refresh'])} dependent pages would be re-rendered.", ""]
    else:
        lines += [f"Created {len(report['created'])}, updated {len(report['updated'])}, "
                  f"refreshed {len(report['refreshed'])} dependent pages.", ""]
    sections = (
        ("Skipped: latest revision is not from this automation", [
            f"{row['title']} (last edited by {row['user'] or 'a hidden user'}, {row['timestamp']})"
            for row in report["skipped"]]),
        ("Conflicts: edited while this run was saving", [f"{row['title']}: {row['error']}" for row in report["conflicts"]]),
        ("Blocked: includes a view or display definition its owner does not publish yet",
         [f"{row['title']}: needs {', '.join(row['needs'])}" for row in report["blocked"]]),
        ("Errors", [f"{row['title']}: {row['error']}" for row in report["errors"]]),
        ("Saved text differs from the generated page", report["unverified"]),
        ("Adoption waits for a change: these already match the repository", report["adopt_pending"]),
        ("Would create" if dry else "Created", report["create"] if dry else report["created"]),
        ("Would update" if dry else "Updated", report["update"] if dry else report["updated"]),
        ("Would re-render" if dry else "Re-rendered", report["refresh"] if dry else report["refreshed"]),
        ("Referenced images not on the wiki yet (import them separately)", report["missing_files"]),
    )
    for heading, rows in sections:
        if rows:
            lines += [f"<details><summary>{heading} ({len(rows)})</summary>", "",
                      *(f"- {row}" for row in rows), "", "</details>", ""]
    return "\n".join(lines)


def source_revision():
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"][:12]
    try:
        return subprocess.run(["git", "describe", "--always", "--dirty", "--abbrev=12"], cwd=ROOT, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=os.environ.get("MIRKLURK_API_URL"),
                        help="Wiki api.php URL (default: $MIRKLURK_API_URL)")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes; needs MIRKLURK_BOT_USERNAME and MIRKLURK_BOT_PASSWORD")
    parser.add_argument("--summary", help="Edit summary (default: 'repo-sync: <commit>')")
    parser.add_argument("--automation-account", action="append", default=[],
                        help="Another account whose repo-sync edits may be updated (repeatable)")
    parser.add_argument("--adopt", action="append", default=[],
                        help="Replace these pages even though a person edited them last; separate titles with |")
    parser.add_argument("--report", type=Path, help="Also write the JSON report to this new file")
    args = parser.parse_args(argv)
    if not args.api:
        parser.error("set --api or MIRKLURK_API_URL")
    username = os.environ.get("MIRKLURK_BOT_USERNAME", "")
    password = os.environ.get("MIRKLURK_BOT_PASSWORD", "")
    if args.apply and not (username and password):
        print("--apply needs MIRKLURK_BOT_USERNAME and MIRKLURK_BOT_PASSWORD.", file=sys.stderr)
        return 2
    summary = args.summary or f"{SUMMARY_PREFIX} {source_revision()}"
    accounts = [*args.automation_account, *([username.split("@", 1)[0]] if username else [])]
    adopt = [title.strip() for value in args.adopt for title in value.split("|") if title.strip()]
    try:
        data, catalog, details = load_publication_inputs(ROOT)
        pages = build_pages(ROOT, data, catalog, details)
        validate_reader_pages(pages)
        api = Api(args.api)
        if args.apply:
            print(f"Logged in as {api.login(username, password)}.", flush=True)
            if "noratelimit" not in api.rights:
                print("Warning: this account is limited to about ten edits a minute; "
                      "see the bot account setup in docs/PUBLISHING.md.", flush=True)
        report = sync(api, pages, summary, accounts, apply=args.apply, adopt=adopt)
    except (SyncError, OSError, ValueError) as error:
        print(f"Wiki sync failed: {error}", file=sys.stderr)
        return 1
    text = markdown(report, args.api)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(text + "\n")
        for row in report["skipped"][:20]:
            print(f"::warning title=Not overwritten::{row['title']} was last edited by {row['user']}; merge it by hand.")
        for row in report["blocked"][:20]:
            print(f"::warning title=Not published yet::{row['title']} needs {', '.join(row['needs'])}.")
        for row in report["errors"][:20]:
            print(f"::error title=Wiki sync::{row['title']}: {row['error']}")
    if args.report:
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
    return 1 if report["errors"] or report["unverified"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
