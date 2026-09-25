"""Opt-in Docker integration test in an isolated, disposable Compose project."""

import argparse
import http.cookiejar
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from build_wiki import build_pages, build_xml, existing_titles, title_key
from wiki_details import load_publication_inputs


ROOT = Path(__file__).resolve().parents[1]


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

        def api(parameters, post=False):
            encoded = urllib.parse.urlencode(dict(format="json", **parameters)).encode()
            url = base + "/api.php" + ("" if post else "?" + encoded.decode())
            with opener.open(url, data=encoded if post else None, timeout=30) as response:
                value = json.load(response)
            if "error" in value:
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
            pages = build_pages(ROOT, *load_publication_inputs(ROOT))
            edit = api({"action": "edit", "title": "Main Page", "text": pages["Main Page"], "token": csrf}, post=True)
            if edit.get("edit", {}).get("result") != "Success":
                raise RuntimeError("Authenticated editing failed.")

            current = workspace / "current.xml"
            current.write_bytes(run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "dumpBackup", "--current"))
            excluded = existing_titles(current)
            missing = {title: text for title, text in pages.items() if title_key(title) not in excluded}
            run("exec", "-T", "mirklurk", "php", "maintenance/run.php", "importDump", input_bytes=build_xml(missing))
            indexed = api({"action": "query", "list": "allpages", "aplimit": "max"})["query"]["allpages"]
            if set(pages) != {page["title"] for page in indexed}:
                raise RuntimeError("Imported page titles differ from the deterministic bundle.")
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
            print("Disposable Docker smoke passed: install, health, access policy, CAPTCHA, seed, edit preservation.")
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
