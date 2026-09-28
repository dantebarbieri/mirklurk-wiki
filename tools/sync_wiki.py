"""Publish the generated pages to a live MediaWiki through its web API.

Dry run by default: reports what would change without logging in. With --apply,
it creates missing pages and updates pages whose latest revision came from the
publishing automation. Pages last edited by anyone else are never overwritten;
they are skipped and listed for a manual merge.
"""

import argparse
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
from wiki_render import build_pages


ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PREFIX = "repo-sync:"
# Edit summaries written by this tool and by the publication workflows it replaced.
AUTOMATION_SUMMARIES = (SUMMARY_PREFIX, "native-publication/v1:", "Publish reviewed ", "Original repository seed")
# MediaWiki's installer and maintenance identities; nobody can log in as these.
SYSTEM_USERS = {"MediaWiki default", "Maintenance script"}
DEFAULT_ACCOUNTS = ("WikiAdmin",)
BATCH = 50
PHP_WHITESPACE = " \t\n\r\0\x0b"
USER_AGENT = "MirkLurkWikiSync/1 (+https://github.com/dantebarbieri/mirklurk-wiki)"
OWNER = re.compile(r"\{\{:([^{}|\n]+)")
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


def automation_owned(revision, accounts):
    user = revision.get("user") or ""
    if user in SYSTEM_USERS or user.startswith("imported>"):
        return True
    return user in accounts and (revision.get("comment") or "").startswith(AUTOMATION_SUMMARIES)


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
            if page.get("ns") != (14 if title.startswith("Category:") else 0):
                raise SyncError(f"{title} resolved to an unexpected namespace.")
            if page.get("missing"):
                live[title] = None
                continue
            revision = page["revisions"][0]
            slot = revision.get("slots", {}).get("main", {})
            readable = not slot.get("texthidden") and slot.get("contentmodel", "wikitext") == "wikitext"
            live[title] = {
                "revid": revision["revid"], "timestamp": revision.get("timestamp", ""),
                "user": revision.get("user"), "comment": revision.get("comment", ""),
                "text": slot.get("content") if readable else None,
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


def owners(text):
    return {title_key(owner.strip()) for owner in OWNER.findall(text)}


def links(text):
    # [[Category:X]] is a membership, which MediaWiki renders fresh on every view.
    return {title_key(target.strip()) for colon, target in LINK.findall(text)
            if target.strip() and (colon or not target.lstrip().lower().startswith("category:"))}


def write_order(titles, pages):
    """Transcluded owners before their readers where possible.

    Merchants and items include views of each other, so some pages are saved
    before an owner; stale_renderings() lists them for a re-render afterwards.
    """
    pending = set(titles)
    needs = {title: owners(pages[title]) - {title} for title in pending}
    order = []
    while pending:
        ready = [title for title in sorted(pending) if not needs[title] & pending]
        batch = ready or [min(pending)]
        order.extend(batch)
        pending.difference_update(batch)
    return order


def stale_renderings(texts, written, created):
    """Pages rendered before an owner they include was saved, or before a page they link to existed.

    MediaWiki 1.43 null edits re-render without advancing page_touched, and bot passwords
    cannot purge, so staleness follows this run's write order rather than timestamps.
    """
    position = {title: index for index, title in enumerate(written)}
    stale = []
    for title, text in sorted(texts.items()):
        mine = position.get(title, -1)
        targets = ((owners(text) & position.keys()) | (links(text) & created)) - {title}
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
    params = {"action": "edit", "title": title, "text": text, "summary": summary}
    if current is None:
        params["createonly"] = "1"
    else:
        params.update(nocreate="1", baserevid=str(current["revid"]))
    outcome = edit(api, params)
    if outcome.get("result") != "Success":
        raise ApiError(str(outcome.get("result", "failure")).lower(), "MediaWiki did not accept the edit")
    if current is not None and outcome.get("oldrevid") not in (None, current["revid"]):
        # Someone saved in between and MediaWiki merged both edits. Put their revision back,
        # without the repo-sync marker, so later runs keep skipping the page.
        edit(api, {"action": "edit", "title": title, "undo": str(outcome["newrevid"]),
                   "undoafter": str(outcome["oldrevid"]), "nocreate": "1",
                   "summary": "Restore an edit saved during a sync; merge the generated text by hand"})
        raise ApiError("editconflict", "saved by someone else during the sync; their revision was restored")
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


def sync(api, pages, summary, accounts=(), apply=False, log=print, adopt=()):
    if not summary.startswith(SUMMARY_PREFIX):
        raise SyncError(f"Edit summaries must start with {SUMMARY_PREFIX!r} so later runs recognize them.")
    if apply and not api.username:
        raise SyncError("Log in before applying changes.")
    unnormalized = sorted(title for title in pages if title_key(title) != title)
    if unnormalized:
        raise SyncError("Generated titles must be normalized: " + ", ".join(unnormalized[:5]))
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
        "created": [], "updated": [], "conflicts": [], "errors": [], "refresh": [], "refreshed": [],
        "unverified": [],
    }
    order = write_order(report["create"] + report["update"], pages)
    written, created = [], set()
    for title in order if apply else []:
        try:
            save(api, title, pages[title], live[title], summary)
        except ApiError as error:
            if error.code == "readonly":
                raise SyncError(f"The wiki is read-only ({error}); nothing further was written.") from None
            bucket = "conflicts" if error.code in CONFLICTS else "errors"
            report[bucket].append({"title": title, "error": str(error)})
            log(f"{bucket[:-1]}: {title}: {error}")
            continue
        written.append(title)
        created.update([title] if actions[title] == "create" else [])
        report["created" if actions[title] == "create" else "updated"].append(title)
        log(f"{actions[title]}d: {title}")
    if not apply:
        # Preview the refreshes the planned writes would cause.
        written, created = order, set(report["create"])
    current = fetch_live(api, pages) if apply and written else live
    texts = {title: pages[title] if title in written else row["text"]
             for title, row in current.items() if title in written or (row and row["text"] is not None)}
    # Pages people edited last are left to MediaWiki's job queue.
    report["refresh"] = [title for title in stale_renderings(texts, written, created)
                         if title in written or automation_owned(current[title], accounts)]
    for title in report["refresh"] if apply else []:
        try:
            # A null edit re-renders the page. It only saves a revision when the stored text still
            # has trailing whitespace that an edit would trim (pages imported rather than edited).
            edit(api, {"action": "edit", "title": title, "appendtext": "", "nocreate": "1", "summary": summary})
            report["refreshed"].append(title)
        except ApiError as error:
            report["errors"].append({"title": title, "error": f"refresh failed: {error}"})
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
        ("Errors", [f"{row['title']}: {row['error']}" for row in report["errors"]]),
        ("Saved text differs from the generated page", report["unverified"]),
        ("Would create" if dry else "Created", report["create"] if dry else report["created"]),
        ("Would update" if dry else "Updated", report["update"] if dry else report["updated"]),
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
        for row in report["errors"][:20]:
            print(f"::error title=Wiki sync::{row['title']}: {row['error']}")
    if args.report:
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
    return 1 if report["errors"] or report["unverified"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
