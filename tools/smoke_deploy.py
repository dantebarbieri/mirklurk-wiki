"""Opt-in Docker integration test in an isolated, disposable Compose project."""

import argparse
import http.cookiejar
import json
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser
from pathlib import Path

from build_wiki import build_pages, build_xml, existing_titles, title_key
from wiki_details import load_publication_inputs


ROOT = Path(__file__).resolve().parents[1]


class RenderedGrids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.grids = []
        self.active = False
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and "mirklurk-cell-grid" in attrs.get("class", "").split():
            self.active = True
            self.grids.append([])
        elif self.active and tag == "tr":
            self.grids[-1].append([])
        elif self.active and tag == "td":
            self.cell = {"attrs": attrs, "text": ""}
            self.grids[-1][-1].append(self.cell)

    def handle_endtag(self, tag):
        if tag == "table":
            self.active = False
        elif tag == "td":
            self.cell = None

    def handle_data(self, data):
        if self.active and self.cell is not None:
            self.cell["text"] += data


def smoke_reader_release(api, pages):
    for title, category in (("Nightmare", "Bugs"), ("Mirk Runner", "Rodents"),
                            ("Sceetler", "Scaalmyr"), ("Mudfin", "Aquatic creatures")):
        result = api({"action": "query", "titles": title, "prop": "categories"})["query"]["pages"]
        categories = next(iter(result.values())).get("categories", [])
        if "Category:" + category not in {row["title"] for row in categories}:
            raise RuntimeError("Imported category membership is missing.")
    for title in ("Thorns of Wackah", "Nightmare"):
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        parsed = RenderedGrids()
        parsed.feed(rendered)
        if not parsed.grids:
            raise RuntimeError("MediaWiki did not render the cell grid.")
        rows = parsed.grids[0]
        if title == "Thorns of Wackah":
            if len(rows) != 4 or any(len(row) != 2 for row in rows):
                raise RuntimeError("Thorns attack grid orientation changed.")
            if any(cell["text"].strip() != "1-4" for row in rows for cell in row):
                raise RuntimeError("Thorns attack cells lost their per-cell ranges.")
        else:
            holes = {(y, x) for y, row in enumerate(rows) for x, cell in enumerate(row)
                     if "grid-hole" in cell["attrs"].get("class", "")}
            if len(rows) != 7 or any(len(row) != 3 for row in rows) or holes != {(y, 2 if y % 2 == 0 else 0) for y in range(7)}:
                raise RuntimeError("Nightmare base-health shape lost its alternating holes.")
        for row in rows:
            for cell in row:
                if not cell["attrs"].get("aria-label", "").startswith("Row "):
                    raise RuntimeError("Grid cell accessibility labels were stripped.")
                if "grid-cell" in cell["attrs"].get("class", "") and "background" not in cell["attrs"].get("style", ""):
                    raise RuntimeError("Grid cell styling was stripped.")
    for title, expected in (
        ("Survivor's Field Kit", "2 gold"), ("Gurb-Gurb", "2 gold"),
        ("Fine Wool Socks", "50%"), ("Steel Hand Axe", "AP"),
    ):
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        if expected not in rendered:
            raise RuntimeError("Reader-facing coin, percentage or AP formatting did not survive parsing.")
    for title in ("Poison", "Sharp", "Blunt", "Force", "Piercing", "Fire", "Weak", "Action points"):
        if title not in pages:
            raise RuntimeError("A required canonical guide is missing.")


def refreshed_transclusion(run, api, title, expected, forbidden_anchor):
    # Imports and edits enqueue deferred link updates; allow their bounded completion.
    for attempt in range(10):
        run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "runJobs", "--maxjobs", "1000")
        rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
        if forbidden_anchor in rendered:
            raise RuntimeError("Selective transclusion leaked the full owner article.")
        if expected in rendered:
            return rendered
        if attempt < 9:
            time.sleep(2)
    raise RuntimeError(f"The {title} view did not refresh its owner value after ten job-drain checks.")


def cache_diagnostics(api, title, owner, rendered):
    state = api({"action": "query", "titles": title + "|" + owner, "prop": "info|revisions",
                 "rvprop": "ids|timestamp", "curtimestamp": 1})
    print("Transclusion timestamps:", json.dumps({
        "server": state["curtimestamp"],
        "cached": re.findall(r"(?:Cached time:|timestamp)\s*(\d{14})", rendered),
        "pages": [{key: page[key] for key in ("title", "touched", "lastrevid", "revisions")}
                  for page in state["query"]["pages"].values()],
    }), flush=True)


def smoke_thumbnail(run, api, base):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    # Original solid-color RGB pixels; no fixture or game image is read.
    pixel = bytes((37, 149, 211))
    signature = b"\x89PNG\r\n\x1a\n"
    original = (
        signature
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 32, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + pixel * 64) * 32))
        + chunk(b"IEND", b"")
    )
    run("exec", "-T", "--user", "www-data", "mirklurk", "mkdir", "/tmp/mirklurk-smoke-images")
    run(
        "exec", "-T", "--user", "www-data", "mirklurk", "php", "-r",
        "$image = stream_get_contents(STDIN); "
        "if (file_put_contents('/tmp/mirklurk-smoke-images/Synthetic-thumbnail.png', $image) !== strlen($image)) "
        "{ throw new RuntimeException('Synthetic PNG staging failed.'); }",
        input_bytes=original,
    )
    imported = run(
        "exec", "-T", "--user", "www-data", "mirklurk", "php", "maintenance/run.php",
        "importImages", "/tmp/mirklurk-smoke-images", "--extensions", "png",
        "--user", "WikiAdmin", "--skip-dupes",
        "--comment", "Original synthetic solid-color PNG generated only for this disposable test.",
    )
    if b"Added: 1" not in imported.splitlines() or any(
        line.startswith((b"Failed:", b"Skipped:", b"Overwritten:")) for line in imported.splitlines()
    ):
        raise RuntimeError("The synthetic CLI image import did not add exactly one new file.")
    result = api({
        "action": "query", "titles": "File:Synthetic-thumbnail.png", "prop": "imageinfo",
        "iiprop": "url|size|mime", "iiurlwidth": 16,
    })
    page = next(iter(result["query"]["pages"].values()))
    info = page.get("imageinfo", [{}])[0]
    if info.get("mime") != "image/png" or (info.get("width"), info.get("height")) != (64, 32):
        raise RuntimeError("The CLI-imported synthetic PNG is missing or has incorrect dimensions.")
    if (info.get("thumbwidth"), info.get("thumbheight")) != (16, 8):
        raise RuntimeError("MediaWiki did not generate the requested 16x8 thumbnail.")
    thumbnail_url = info.get("thumburl")
    if not thumbnail_url or thumbnail_url == info["url"]:
        raise RuntimeError("The thumbnail URL is missing or falls back to the original image.")
    for url, expected_size in ((info["url"], (64, 32)), (thumbnail_url, (16, 8))):
        if urllib.parse.urlsplit(url)[:2] != urllib.parse.urlsplit(base)[:2]:
            raise RuntimeError("The synthetic image URL points outside the disposable wiki.")
        # A fresh opener proves anonymous HTTP access, independent of the API session.
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200 or response.headers.get_content_type() != "image/png":
                raise RuntimeError("The synthetic image could not be read as a PNG over HTTP.")
            body = response.read()
        if len(body) < 24 or body[:8] != signature or body[12:16] != b"IHDR":
            raise RuntimeError("The served image is not a PNG with a dimension header.")
        if struct.unpack(">II", body[16:24]) != expected_size:
            raise RuntimeError("The served image dimensions differ from the requested size.")
        if expected_size == (64, 32) and body != original:
            raise RuntimeError("The served original differs from the synthetic imported bytes.")
        decoded = run(
            "exec", "-T", "--user", "www-data", "mirklurk", "/usr/bin/convert",
            "png:-", "-depth", "8", "rgb:-", input_bytes=body,
        )
        if decoded != pixel * (expected_size[0] * expected_size[1]):
            raise RuntimeError("The served PNG did not decode to the expected resized RGB pixels.")
    print("Synthetic CLI import and anonymous PNG reads passed: original 64x32, decoded thumbnail 16x8.")


def smoke():
    project = "mirklurk-smoke-" + secrets.token_hex(6)
    with tempfile.TemporaryDirectory(prefix="mirklurk-smoke-") as folder:
        workspace = Path(folder)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        environment = dict(os.environ, MIRKLURK_SECRETS_DIR=folder, MIRKLURK_DEV_PORT=str(port), MW_READ_ONLY="")
        for name in ("DB_PASSWORD", "DB_ROOT_PASSWORD", "SECRET_KEY", "UPGRADE_KEY", "ADMIN_PASSWORD"):
            destination = workspace / ("MIRKLURK_" + name)
            destination.write_text(secrets.token_hex(40), encoding="utf-8")
            destination.chmod(0o444)
        question = "Type the temporary test word."
        questions = workspace / "MIRKLURK_CAPTCHA_QUESTIONS"
        questions.write_text(json.dumps({question: [secrets.token_hex(8)]}), encoding="utf-8")
        questions.chmod(0o444)
        compose = ["docker", "compose", "--project-name", project, "--file", str(ROOT / "deploy" / "compose.dev.yml")]

        def run(*args, input_bytes=None):
            return subprocess.run(
                [*compose, *args], cwd=ROOT, env=environment, input=input_bytes,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            ).stdout

        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        base = f"http://localhost:{port}"

        def api(parameters, post=False, expected_error=None):
            encoded = urllib.parse.urlencode(dict(format="json", **parameters)).encode()
            url = base + "/api.php" + ("" if post else "?" + encoded.decode())
            with opener.open(url, data=encoded if post else None, timeout=30) as response:
                value = json.load(response)
            if expected_error is not None:
                if value.get("error", {}).get("code") != expected_error:
                    raise RuntimeError(f"API request did not fail with the expected {expected_error} error.")
            elif "error" in value:
                raise RuntimeError(f"API request failed: {value['error'].get('code', 'unknown')}")
            return value

        try:
            run("config", "--quiet")
            run("build", "--pull")
            run("up", "-d", "--wait", "mirklurk-db")
            password_file = workspace / "MIRKLURK_ADMIN_PASSWORD"
            install = (
                "run", "--rm", "--no-deps", "--volume",
                f"{password_file}:/run/secrets/MIRKLURK_ADMIN_PASSWORD:ro",
                "mirklurk", "php", "/usr/local/lib/mirklurk/install.php",
                "--admin", "WikiAdmin", "--password-file", "/run/secrets/MIRKLURK_ADMIN_PASSWORD",
            )
            run(*install)
            try:
                run(*install)
            except subprocess.CalledProcessError:
                pass
            else:
                raise RuntimeError("Installer did not refuse the already populated database.")
            run("up", "-d", "--wait", "mirklurk")
            try:
                image_help = run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "importImages", "--help")
            except subprocess.CalledProcessError as error:
                if error.returncode != 1:
                    raise
                # MediaWiki 1.43's maintenance help deliberately exits with status 1.
                image_help = error.stdout + error.stderr
            if not all(flag in image_help for flag in (
                b"Usage: php maintenance/run.php importImages", b"--dry", b"--comment-ext", b"--skip-dupes",
            )):
                raise RuntimeError("The pinned image does not expose the documented operator image-import options.")
            rights = api({"action": "query", "meta": "userinfo", "uiprop": "rights"})["query"]["userinfo"]["rights"]
            if not {"read", "createaccount"} <= set(rights) or "edit" in rights:
                raise RuntimeError("Anonymous permissions violate the public-read/account-edit policy.")
            general = api({"action": "query", "meta": "siteinfo", "siprop": "general"})["query"]["general"]
            if "uploadsenabled" in general:
                raise RuntimeError("Web uploads are unexpectedly enabled.")
            smoke_thumbnail(run, api, base)
            with opener.open(base + "/index.php?title=Special:CreateAccount", timeout=30) as response:
                registration = response.read().decode()
            if 'name="captchaWord"' not in registration or question not in registration:
                raise RuntimeError("Open registration did not render the configured CAPTCHA.")
            requests = api({
                "action": "query", "meta": "authmanagerinfo", "amirequestsfor": "create",
            })["query"]["authmanagerinfo"]["requests"]
            captcha = next((request for request in requests if request["id"] == "CaptchaAuthenticationRequest"), None)
            if captcha is None:
                raise RuntimeError("The account-creation API did not require a CAPTCHA.")
            create_token = api({
                "action": "query", "meta": "tokens", "type": "createaccount",
            })["query"]["tokens"]["createaccounttoken"]
            editor_password = secrets.token_hex(24)
            creation = api({
                "action": "createaccount", "username": "TestEditor",
                "password": editor_password, "retype": editor_password,
                "createreturnurl": base, "createtoken": create_token,
                "captchaId": captcha["fields"]["captchaId"]["value"],
                "captchaWord": json.loads(questions.read_text(encoding="utf-8"))[question][0],
            }, post=True)
            if creation.get("createaccount", {}).get("status") != "PASS":
                raise RuntimeError("Open self-registration with the configured CAPTCHA failed.")
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            token = api({"action": "query", "meta": "tokens", "type": "login"})["query"]["tokens"]["logintoken"]
            login = api({
                "action": "login", "lgname": "WikiAdmin",
                "lgpassword": password_file.read_text(encoding="utf-8"), "lgtoken": token,
            }, post=True)
            if login.get("login", {}).get("result") != "Success":
                raise RuntimeError("The freshly created administrator cannot log in.")
            csrf = api({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
            api({
                "action": "upload", "filename": "Web-upload-must-stay-disabled.png", "token": csrf,
            }, post=True, expected_error="uploaddisabled")
            pages = build_pages(ROOT, *load_publication_inputs(ROOT))
            edit = api({"action": "edit", "title": "Main Page", "text": pages["Main Page"], "token": csrf}, post=True)
            if edit.get("edit", {}).get("result") != "Success":
                raise RuntimeError("Authenticated editing failed.")

            current = workspace / "current.xml"
            current.write_bytes(run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "dumpBackup", "--current"))
            excluded = existing_titles(current)
            missing = {title: text for title, text in pages.items() if title_key(title) not in excluded}
            run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "importDump", input_bytes=build_xml(missing))
            indexed = []
            for namespace in (0, 14):
                indexed.extend(api({"action": "query", "list": "allpages", "apnamespace": namespace,
                                    "aplimit": "max"})["query"]["allpages"])
            if set(pages) != {page["title"] for page in indexed}:
                raise RuntimeError("Imported page titles differ from the deterministic bundle.")
            run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "runJobs", "--maxjobs", "1000")
            smoke_reader_release(api, pages)
            for title, expected_links in {
                "Items": {"Wood Buckler", "Turnip (item)"},
                "NPCs": {"Captain Eir", "Magus Clay", "Ranger Bhato"},
                "Nature": {"Turnip (nature)"},
                "Skills": {"Strider", "Focused Mind"},
            }.items():
                parsed_links = api({"action": "parse", "page": title, "prop": "links"})["parse"]["links"]
                if not expected_links <= {link["*"] for link in parsed_links if link["ns"] == 0}:
                    raise RuntimeError("MediaWiki did not resolve the encyclopedia's canonical entity links.")
            redirect = api({"action": "query", "titles": "Getting started", "redirects": "1"})["query"].get("redirects", [])
            if not any(row["from"] == "Getting started" and row["to"] == "Research policy" for row in redirect):
                raise RuntimeError("The reviewed guidance compatibility redirect was not imported correctly.")
            for title, anchor in {"Strider": "entry-skill-0-0-mechanics", "Ranger Bhato": "entity-being-12"}.items():
                rendered = api({"action": "parse", "page": title, "prop": "text"})["parse"]["text"]["*"]
                if f'id="{anchor}"' not in rendered:
                    raise RuntimeError("MediaWiki did not render the entity page's primary record anchor.")
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            token = api({"action": "query", "meta": "tokens", "type": "login"})["query"]["tokens"]["logintoken"]
            login = api({
                "action": "login", "lgname": "TestEditor", "lgpassword": editor_password, "lgtoken": token,
            }, post=True)
            if login.get("login", {}).get("result") != "Success":
                raise RuntimeError("A self-registered editor cannot log in.")
            editor = api({"action": "query", "meta": "userinfo", "uiprop": "rights|groups"})["query"]["userinfo"]
            if "edit" not in editor["rights"] or "sysop" in editor["groups"]:
                raise RuntimeError("The ordinary registered-editor permissions are incorrect.")
            csrf = api({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
            price_title = "Longbow (Cypress)"
            original_item = pages[price_title]
            if original_item.count("<onlyinclude>") != 1 or original_item.count("</onlyinclude>") != 1:
                raise RuntimeError("The item does not expose exactly one canonical price block.")
            before_price, _, rest = original_item.partition("<onlyinclude>")
            _, _, after_price = rest.partition("</onlyinclude>")
            cached_merchant = api({"action": "parse", "page": "Ranger Bhato", "prop": "text"})["parse"]["text"]["*"]
            if "111.23 silver" in cached_merchant or 'id="entity-item-105"' in cached_merchant:
                raise RuntimeError("The merchant price-edit precondition is invalid.")
            cache_diagnostics(api, "Ranger Bhato", price_title, cached_merchant)
            updated_item = before_price + "<onlyinclude>111.23 silver</onlyinclude>" + after_price
            price_edit = api({"action": "edit", "title": price_title, "text": updated_item, "token": csrf}, post=True)
            if price_edit.get("edit", {}).get("result") != "Success":
                raise RuntimeError("A registered editor cannot update the canonical item price.")
            try:
                refreshed_transclusion(run, api, "Ranger Bhato", "111.23 silver", 'id="entity-item-105"')
            except RuntimeError:
                rendered = api({"action": "parse", "page": "Ranger Bhato", "prop": "text"})["parse"]["text"]["*"]
                cache_diagnostics(api, "Ranger Bhato", price_title, rendered)
                print("Remaining jobs:", run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "showJobs").decode(), flush=True)
                raise
            item_html = api({"action": "parse", "page": price_title, "prop": "text"})["parse"]["text"]["*"]
            if "111.23 silver" not in item_html or 'id="entity-item-105"' not in item_html or 'id="Stats"' not in item_html:
                raise RuntimeError("Selective price transclusion removed the item's normal full article.")
            coin_title = "Copper Coin"
            coin_text = pages[coin_title].replace("<nowiki>25</nowiki> g", "<nowiki>26</nowiki> g")
            if coin_text == pages[coin_title]:
                raise RuntimeError("The synthetic coin-weight edit did not target its canonical value.")
            cached_currency = api({"action": "parse", "page": "Currency and trading", "prop": "text"})["parse"]["text"]["*"]
            if "25 g" not in cached_currency or 'id="entity-item-72"' in cached_currency:
                raise RuntimeError("The coin-weight edit precondition is invalid.")
            coin_edit = api({"action": "edit", "title": coin_title, "text": coin_text, "token": csrf}, post=True)
            if coin_edit.get("edit", {}).get("result") != "Success":
                raise RuntimeError("A registered editor cannot update a coin-owned weight.")
            refreshed_transclusion(run, api, "Currency and trading", "26 g", 'id="entity-item-72"')
            api({
                "action": "upload", "filename": "Web-upload-must-stay-disabled.png", "token": csrf,
            }, post=True, expected_error="uploaddisabled")
            preserved = "Original live edit for the disposable integration test."
            edit = api({"action": "edit", "title": "Game mechanics", "text": preserved, "token": csrf}, post=True)
            if edit.get("edit", {}).get("result") != "Success":
                raise RuntimeError("An ordinary self-registered editor cannot save a page.")
            current.write_bytes(run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "dumpBackup", "--current"))
            excluded = existing_titles(current)
            missing = {title: text for title, text in pages.items() if title_key(title) not in excluded}
            if missing:
                raise RuntimeError("Additive reimport unexpectedly includes an existing title.")
            run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "importDump", input_bytes=build_xml(missing))
            parsed = api({"action": "parse", "page": "Game mechanics", "prop": "wikitext"})
            if parsed["parse"]["wikitext"]["*"] != preserved:
                raise RuntimeError("Additive reimport changed a live edit.")
            print(
                "Disposable Docker smoke passed: install, health, access policy, CAPTCHA, seed, "
                "edit preservation, CLI image import, resized thumbnail, web uploads disabled."
            )
        except subprocess.CalledProcessError as error:
            # The child only receives mounted secret paths, never literal secrets in argv.
            sys.stderr.write(error.stdout.decode(errors="replace"))
            sys.stderr.write(error.stderr.decode(errors="replace"))
            raise
        finally:
            run("down", "--volumes", "--remove-orphans")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, action="store_true", help="Create and remove test-only Docker resources")
    parser.parse_args()
    smoke()


if __name__ == "__main__":
    main()
