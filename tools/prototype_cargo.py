"""Opt-in synthetic Cargo experiment. Never deploys or publishes repository facts."""

import argparse
import hashlib
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

from prototype_cargo_checks import exercise
from sync_wiki import Api


ROOT = Path(__file__).resolve().parents[1]
CARGO_COMMIT = "b3cc797aa8a1575f7ce4a7c5b0a1979698d582f5"
CARGO_SHA256 = "005301a0f0fac395a9cec340fac0f229d9226974c3c26e80fff3c16015bd21af"


def prototype(artifacts, integrated=False):
    artifacts.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "cargo": "3.9.4", "commit": CARGO_COMMIT,
              "license": "GPL-2.0-or-later", "integrated": integrated, "checks": {}, "cache": []}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="mirklurk-cargo-") as folder:
        workspace = Path(folder)
        context = workspace / "context"
        (context / "deploy").mkdir(parents=True)
        for name in ("Dockerfile", "LocalSettings.template.php", "mirklurk-runtime.php",
                     "apache-short-urls.conf", "install.php", "healthcheck.php"):
            shutil.copyfile(ROOT / "deploy" / name, context / "deploy" / name)
        with urllib.request.urlopen(
            "https://codeload.github.com/wikimedia/mediawiki-extensions-Cargo/tar.gz/" + CARGO_COMMIT,
            timeout=120,
        ) as response:
            archive = response.read()
        if hashlib.sha256(archive).hexdigest() != CARGO_SHA256:
            raise RuntimeError("Cargo archive checksum differs from the reviewed pin.")
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(context, filter="data")
        (context / ("mediawiki-extensions-Cargo-" + CARGO_COMMIT)).rename(context / "Cargo")
        dockerfile = context / "deploy" / "Dockerfile"
        dockerfile.write_text(dockerfile.read_text() + """
COPY Cargo /var/www/html/extensions/Cargo
RUN printf '\\nwfLoadExtension("Cargo");\\n$wgJobRunRate = 0;\\n$wgShowExceptionDetails = true;\\n' >> /var/www/html/LocalSettings.php
""", encoding="utf-8")
        if integrated:
            shutil.copyfile(ROOT / "tools" / "prototype_cargo_hooks.php", context / "prototype_cargo_hooks.php")
            shutil.copyfile(ROOT / "tools" / "prototype_cargo_magic.php", context / "prototype_cargo_magic.php")
            dockerfile.write_text(dockerfile.read_text() + """
COPY prototype_cargo_hooks.php /var/www/html/prototype_cargo_hooks.php
COPY prototype_cargo_magic.php /var/www/html/prototype_cargo_magic.php
RUN php -l /var/www/html/prototype_cargo_hooks.php && printf '\\nrequire_once __DIR__ . "/prototype_cargo_hooks.php";\\n' >> /var/www/html/LocalSettings.php
""", encoding="utf-8")
        # Disable opportunistic jobs only to measure immediate vs job-drained behavior.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        environment = dict(os.environ, MIRKLURK_SECRETS_DIR=folder, MIRKLURK_DEV_PORT=str(port),
                           MW_READ_ONLY="", MW_LOGO_URL="", MW_LOGO_ICON_URL="", MW_FAVICON_URL="")
        for name in ("DB_PASSWORD", "DB_ROOT_PASSWORD", "SECRET_KEY", "UPGRADE_KEY", "ADMIN_PASSWORD"):
            path = workspace / ("MIRKLURK_" + name)
            path.write_text(secrets.token_hex(40))
            path.chmod(0o444)
        answer = secrets.token_hex(8)
        path = workspace / "MIRKLURK_CAPTCHA_QUESTIONS"
        path.write_text(json.dumps({"Type the temporary prototype word.": [answer]}))
        path.chmod(0o444)
        override = workspace / "compose.json"
        override.write_text(json.dumps({"services": {"mirklurk": {"build": {"context": str(context)}}}}))
        compose = ["docker", "compose", "--project-name", "mirklurk-cargo-" + secrets.token_hex(6),
                   "--file", str(ROOT / "deploy" / "compose.dev.yml"), "--file", str(override)]

        def run(*args, input_bytes=None, timeout=180):
            result = subprocess.run([*compose, *args], cwd=ROOT, env=environment, input=input_bytes,
                                    capture_output=True, timeout=timeout)
            if result.returncode:
                # Never print compose configuration or credentials.
                raise RuntimeError("Disposable command failed:\n"
                                   + (result.stdout + result.stderr).decode(errors="replace")[-8000:])
            return result.stdout.decode()

        def maintenance(*args):
            return run("exec", "-T", "mirklurk", "php", "maintenance/run.php", *args)

        try:
            run("config", "--quiet")
            run("build", "--pull", timeout=480)
            run("up", "-d", "--wait", "mirklurk-db")
            admin_file = workspace / "MIRKLURK_ADMIN_PASSWORD"
            run("run", "--rm", "--no-deps", "--volume", f"{admin_file}:/run/secrets/ADMIN:ro",
                "mirklurk", "php", "/usr/local/lib/mirklurk/install.php",
                "--admin", "WikiAdmin", "--password-file", "/run/secrets/ADMIN")
            run("run", "--rm", "--no-deps", "mirklurk", "php", "maintenance/run.php", "update", "--quick")
            run("up", "-d", "--wait", "mirklurk")
            base = f"http://localhost:{port}"
            admin = Api(base + "/api.php")
            admin.login("WikiAdmin", admin_file.read_text())
            info = admin.call({"action": "query", "meta": "siteinfo", "siprop": "general|extensions"})["query"]
            assert info["general"]["generator"] == "MediaWiki 1.43.9", info["general"]["generator"]
            assert any(e["name"] == "Cargo" and e["version"] == "3.9.4" for e in info["extensions"])
            report["mediawiki"] = info["general"]["generator"]
            report["database"] = run("exec", "-T", "mirklurk-db", "mariadb", "--version").strip()
            if "11.4.13" not in report["database"]:
                raise RuntimeError("Unexpected MariaDB version.")
            anonymous = Api(base + "/api.php")
            requests = anonymous.call({"action": "query", "meta": "authmanagerinfo",
                                       "amirequestsfor": "create"})["query"]["authmanagerinfo"]["requests"]
            captcha = next(r for r in requests if r["id"] == "CaptchaAuthenticationRequest")
            editor_password = secrets.token_hex(24)
            token = anonymous.call({"action": "query", "meta": "tokens", "type": "createaccount"})["query"]["tokens"]
            created = anonymous.call({
                "action": "createaccount", "username": "TestEditor", "password": editor_password,
                "retype": editor_password, "createreturnurl": base, "createtoken": token["createaccounttoken"],
                "captchaId": captcha["fields"]["captchaId"]["value"], "captchaWord": answer,
            }, post=True)
            assert created["createaccount"]["status"] == "PASS", "Prototype signup failed."
            exercise(admin, base, editor_password, maintenance, report, artifacts, integrated=integrated)
            report["status"] = "completed_with_limitations"
        except Exception as error:
            report["status"] = "failed"
            report["error"] = str(error)
            raise
        finally:
            report["elapsed_seconds"] = round(time.monotonic() - started, 2)
            (artifacts / "cargo-prototype.json").write_text(json.dumps(report, indent=2) + "\n")
            run("down", "--volumes", "--remove-orphans", timeout=120)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True, help="Create/destroy a disposable local wiki.")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--integrated", action="store_true", help="Enable disposable table-dependency/restore hooks.")
    args = parser.parse_args()
    prototype(args.artifacts, integrated=args.integrated)
