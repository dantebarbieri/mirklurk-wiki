"""Browser/API assertions for the isolated Cargo experiment, not production publishing."""

import html
import json
import re
import time
import urllib.parse
import urllib.request

from prototype_cargo_fixtures import MODULE, MOVED, NEW_OWNER, OWNER, READERS, TEMPLATE, pages, query, record
from sync_wiki import Api, sync


def revision(api, title):
    result = api.call({"action": "query", "prop": "revisions", "titles": title,
                       "rvprop": "ids|content|user|comment|tags", "rvslots": "main"})["query"]["pages"][0]
    return result.get("revisions", [None])[0]


def source(api, title):
    return revision(api, title)["slots"]["main"]["content"]


def store(api, title, text, **extra):
    result = api.call({"action": "edit", "title": title, "text": text, "token": api.csrf(),
                       "summary": "Synthetic Cargo prototype", **extra}, post=True)["edit"]
    assert result["result"] == "Success", "Synthetic page save failed."


def rows(api, where=""):
    result = api.call({
        "action": "cargoquery", "tables": "PrototypeRecords",
        "fields": "_pageName=Owner,_pageID=PageID,Variant,Product,Quantity,AP,Inputs,Ingredients,Stations,Merchants,Requirement",
        "where": where, "order_by": "_pageName,Variant", "limit": "100",
    })
    return [r["title"] for r in result["cargoquery"]]


def visible(text):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", text)).split())


def cached_reader(base, title):
    with urllib.request.urlopen(base + "/w/" + urllib.parse.quote(title.replace(" ", "_"), safe=""), timeout=60) as r:
        return visible(r.read().decode())


def exercise(admin, base, password, maintenance, report, artifacts, integrated=False):
    from playwright.sync_api import sync_playwright

    assert urllib.parse.urlsplit(base).hostname == "localhost", "Disposable localhost required."
    fixtures = pages()
    if integrated:
        fixtures[TEMPLATE] = fixtures[TEMPLATE].replace(
            "<includeonly>", "<includeonly>{{#prototype_owner:}}", 1)
    for title, text in fixtures.items():
        store(admin, title, text, **({"contentmodel": "Scribunto"} if title == MODULE else {}))

    def jobs():
        started = time.monotonic()
        before = maintenance("showJobs").strip()
        output = maintenance("runJobs", "--maxjobs", "500", "--maxtime", "60")
        assert "ERROR" not in output and " failed" not in output, output
        after = maintenance("showJobs").strip()
        return {"before": before, "after": after, "output": output[-2000:],
                "seconds": round(time.monotonic() - started, 3)}

    def recreate():
        start = time.monotonic()
        command = "Cargo:prototypeRebuild" if integrated else "Cargo:cargoRecreateData"
        output = maintenance(command, "--table", "PrototypeRecords", "--quiet")
        report.setdefault("rebuild_output", []).append(output)
        assert "Error:" not in output and "skipping" not in output, output
        return round(time.monotonic() - start, 3)

    jobs()
    declaration = admin.call({"action": "parse", "page": TEMPLATE, "prop": "text"})["parse"]["text"]
    assert 'class="error"' not in declaration, visible(declaration)
    properties = admin.call({"action": "query", "titles": TEMPLATE, "prop": "pageprops"})["query"]["pages"][0]
    assert properties.get("pageprops", {}).get("CargoTableName") == "PrototypeRecords", properties
    recreate()
    assert rows(admin) == [], "Empty index expected before authoring."
    def reader_query(condition):
        text = query(condition)
        return text.replace("#cargo_query:tables=PrototypeRecords", "#prototype_query:") if integrated else text

    for title, condition in READERS.items():
        store(admin, title, reader_query(condition))
    jobs()
    for title in READERS:
        assert "No matching records." in cached_reader(base, title)

    def freshness(label, expected):
        """Observe normal HTTP cache before jobs, after jobs, then an explicit purge if needed."""
        entry = {"event": label, "readers": {}}
        for title, needles in expected.items():
            entry["readers"][title] = {
                "before_jobs": all((needle in cached_reader(base, title)) == present for needle, present in needles)
            }
        entry["jobs"] = jobs()
        for title, needles in expected.items():
            observed = entry["readers"][title]
            text = cached_reader(base, title)
            observed["after_jobs"] = all((needle in text) == present for needle, present in needles)
            if integrated:
                assert observed["after_jobs"], (label, title, text[-1500:])
            if not observed["after_jobs"]:
                admin.call({"action": "purge", "titles": title}, post=True)
                text = cached_reader(base, title)
                observed["after_explicit_purge"] = all((needle in text) == present for needle, present in needles)
                assert observed["after_explicit_purge"], (label, title, text[-1500:])
        report["cache"].append(entry)

    editor = Api(base + "/api.php")
    editor.login("TestEditor", password)
    assert "sysop" not in editor.call({"action": "query", "meta": "userinfo", "uiprop": "groups"})["query"]["userinfo"]["groups"]
    assert "edit" not in Api(base + "/api.php").call(
        {"action": "query", "meta": "userinfo", "uiprop": "rights"})["query"]["userinfo"]["rights"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1050})
        page = context.new_page()
        page.set_default_timeout(45000)
        last_save = 0

        def edit_delay():
            nonlocal last_save
            time.sleep(max(0, 21 - (time.monotonic() - last_save)))
            last_save = time.monotonic()

        def url(title, **params):
            return base + "/index.php?" + urllib.parse.urlencode({"title": title, **params})

        def wiki_save(title, text, summary):
            edit_delay()
            store(editor, title, text, summary=summary)
            saved = revision(admin, title)
            assert saved["user"] == "TestEditor" and saved["comment"] == summary
            assert saved["slots"]["main"]["content"].strip() == text.strip()
            return saved

        def open_visual(title, entry=None):
            if entry is None:
                page.goto(url(title), wait_until="networkidle")
                page.locator("#ca-ve-edit a").click()
            else:
                entry.click()
            page.wait_for_function("window.ve?.init?.target?.active && ve.init.target.getSurface()")
            assert page.evaluate("mw.config.get('wgPageName')") == title.replace(" ", "_")
            page.wait_for_function("Boolean(ve.init.target.welcomeDialogPromise)")
            if page.evaluate("Boolean(ve.init.target.welcomeDialog)"):
                page.locator(".ve-init-mw-welcomeDialog").get_by_role("button", name="Start editing", exact=True).click()
            page.wait_for_function("ve.init.target.active && !ve.init.target.activating && !ve.init.target.welcomeDialog")

        def select_record():
            page.locator(".ve-ce-documentNode .prototype-record").first.hover(force=True)
            page.locator('.ve-ce-focusableNode-highlight[title="Prototype record"]').first.click()
            page.locator(".ve-ui-mwTransclusionContextItem").get_by_role("button", name="Edit", exact=True).click()
            return page.locator(".ve-ui-mwTemplateDialog")

        def save_visual(summary):
            edit_delay()
            page.locator(".ve-ui-toolbar-saveButton").click()
            dialog = page.locator(".ve-ui-mwSaveDialog")
            dialog.locator("textarea:visible").fill(summary)
            dialog.get_by_role("button", name="Review your changes", exact=True).click()
            page.wait_for_function("ve.init.target.saveDialog.hasDiff && !ve.init.target.saveDialog.isPending()")
            with page.expect_response(lambda r: "/api.php" in r.url
                                      and b'name="paction"\r\n\r\nsave\r\n' in (r.request.post_data_buffer or b"")) as saving:
                dialog.locator(".oo-ui-processDialog-actions-primary .oo-ui-buttonElement-button").click()
            assert saving.value.json().get("visualeditoredit", {}).get("result") == "success"
            page.wait_for_function("!window.ve?.init?.target?.active")

        def expect_owner_link(title):
            page.goto(url("Prototype new station"), wait_until="networkidle")
            links = page.locator(".prototype-result").get_by_role("link", name="Edit data", exact=True)
            hrefs = [urllib.parse.urlsplit(link.get_attribute("href")) for link in links.all()]
            targets = [(href.path, urllib.parse.parse_qs(href.query)) for href in hrefs]
            assert any(params.get("veaction") == ["edit"] and (
                path == "/w/" + title.replace(" ", "_")
                or path == "/index.php" and [value.replace("_", " ") for value in params.get("title", [])] == [title]
            ) for path, params in targets), targets

        try:
            page.goto(url("Special:UserLogin"), wait_until="networkidle")
            page.locator("#wpName1").fill("TestEditor")
            page.locator("#wpPassword1").fill(password)
            page.locator("#wpLoginAttempt").click()
            page.wait_for_function("window.mw?.config.get('wgUserName') === 'TestEditor'")
            text = "Synthetic author prose.\n\n" + record() + "\n\n" + record(
                variant="rain", ap="3", stations="Prototype camp")
            wiki_save(OWNER, text, "Create two synthetic variants")
            report["initial_owner_html"] = admin.call({"action": "parse", "page": OWNER, "prop": "text"})["parse"]["text"]
            assert 'class="error"' not in report["initial_owner_html"], visible(report["initial_owner_html"])
            initial = rows(admin)
            assert len(initial) == 2 and {r["Owner"] for r in initial} == {OWNER}, initial
            assert all("Synthetic leaf" in r["Ingredients"] and "Synthetic resin = 2" in r["Inputs"] for r in initial)
            report["checks"]["two_variants_five_ingredients_indexed"] = True
            freshness("create first owner", {
                "Prototype bench": [(OWNER, True)],
                "Synthetic resin": [(OWNER, True)],
                "Prototype trader": [(OWNER, True)],
            })
            populated_reader = "Prototype populated reader"
            store(admin, populated_reader, reader_query("Stations HOLDS 'Prototype bench'"))
            assert "AP 2" in cached_reader(base, populated_reader)
            page.goto(url("Prototype bench"), wait_until="networkidle")
            data_link = page.locator(".prototype-result").get_by_role("link", name="Edit data", exact=True).first
            assert urllib.parse.parse_qs(urllib.parse.urlsplit(data_link.get_attribute("href")).query)["veaction"] == ["edit"]
            before = revision(admin, OWNER)
            open_visual(OWNER, entry=data_link)
            dialog = select_record()
            assert dialog.get_by_label("Ingredients and quantities", exact=True).input_value().count("\n") == 4
            assert not dialog.get_by_label(re.compile("routing|selector|filter", re.I)).count()
            dialog.get_by_label("AP", exact=True).fill("7")
            dialog.get_by_label("Output quantity", exact=True).fill("2")
            page.wait_for_function("!ve.init.target.getSurface().getDialogs().getCurrentWindow().isPending()")
            page.screenshot(path=str(artifacts / "cargo-fields.png"), animations="disabled")
            dialog.locator(".oo-ui-processDialog-actions-primary .oo-ui-buttonElement-button").click()
            save_visual("Visual synthetic record edit")
            saved = revision(admin, OWNER)
            expected = text.replace("|quantity=1|ap=2|", "|quantity=2|ap=7|", 1).strip()
            assert source(admin, OWNER).strip() == expected, source(admin, OWNER)
            assert saved["revid"] != before["revid"] and saved["user"] == "TestEditor"
            assert saved["comment"] == "Visual synthetic record edit" and "visualeditor" in saved["tags"]
            assert [r["AP"] for r in rows(admin) if r["Variant"] == "base"] == ["7"]
            report["checks"]["native_field_edit_owner_revision"] = True
            freshness("visual value edit", {
                "Prototype bench": [("AP 7", True), ("AP 2", False)],
                populated_reader: [("AP 7", True), ("AP 2", False)],
            })
            open_visual(OWNER)
            dialog = select_record()
            dialog.get_by_label("AP", exact=True).fill("8")
            dialog.locator(".oo-ui-processDialog-actions-primary .oo-ui-buttonElement-button").click()
            save_visual("Second visual synthetic record edit")
            expected = expected.replace("|ap=7|", "|ap=8|", 1)
            assert source(admin, OWNER).strip() == expected, source(admin, OWNER)
            assert [r["AP"] for r in rows(admin) if r["Variant"] == "base"] == ["8"]
            report["checks"]["second_visual_save_no_source_churn"] = True
            if integrated:
                from prototype_cargo_gui import exercise_gui
                exercise_gui(admin, page, open_visual, save_visual, freshness, reader_query, report, artifacts)

            # GUI preview, unsaved visual draft and anonymous arbitrary parsing must not store facts.
            snapshot = rows(admin)
            before = revision(admin, OWNER)
            page.goto(url(OWNER, action="edit"), wait_until="networkidle")
            page.locator("#wpTextbox1").fill(source(admin, OWNER).replace("|ap=8|", "|ap=99|"))
            page.locator("#wpPreview").click()
            page.locator("#wikiPreview").wait_for(state="visible")
            assert "AP 99" in page.locator("#wikiPreview").inner_text()
            assert rows(admin) == snapshot and revision(admin, OWNER) == before
            open_visual(OWNER)
            dialog = select_record()
            dialog.get_by_label("AP", exact=True).fill("98")
            dialog.locator(".oo-ui-processDialog-actions-primary .oo-ui-buttonElement-button").click()
            assert rows(admin) == snapshot and revision(admin, OWNER) == before
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(url(OWNER), wait_until="networkidle")
            anonymous = Api(base + "/api.php")
            anonymous.call({"action": "parse", "title": OWNER, "text": record(ap="97"), "prop": "text"}, post=True)
            admin.call({"action": "parse", "oldid": before["revid"], "prop": "text"})
            assert rows(admin) == snapshot and revision(admin, OWNER) == before
            report["checks"]["preview_visual_draft_anonymous_parse_no_writes"] = True

            store(admin, "Prototype reused view", reader_query("Stations HOLDS 'Prototype bench'"))
            jobs()
            assert rows(admin) == snapshot, "A reused view registered a duplicate authoritative row."
            report["checks"]["reuse_does_not_store"] = True
            # Negative control: current-style raw owner transclusion is NOT a supported index reader.
            unsafe_reader = "Prototype unsupported raw transclusion"
            store(admin, unsafe_reader, "{{:" + OWNER + "}}")
            report["raw_owner_transclusion_extra_rows"] = len(rows(admin)) - len(snapshot)
            assert report["raw_owner_transclusion_extra_rows"] == 2
            admin.call({"action": "delete", "title": unsafe_reader, "token": admin.csrf(),
                        "reason": "Remove synthetic negative control"}, post=True)
            assert rows(admin) == snapshot

            # No Git owner list changes: author a previously unknown page after caching empty reader results.
            wiki_save(NEW_OWNER, "Another author's prose.\n\n" + record(
                variant="new", stations="Prototype new station"), "New owner and station through wiki editing")
            assert {r["Owner"] for r in rows(admin, "Stations HOLDS 'Prototype new station'")} == {NEW_OWNER}
            freshness("new owner discovered by previously empty query", {
                "Prototype new station": [(NEW_OWNER, True)],
                "Prototype trader": [(NEW_OWNER, True), (OWNER, True)],
            })
            report["checks"]["unknown_owner_new_station_discovery"] = True

            changed = source(admin, OWNER).split("\n\n" + record(variant="rain", ap="3", stations="Prototype camp"))[0]
            assert changed != source(admin, OWNER), "Could not remove the synthetic variant."
            changed = changed.replace("Prototype bench;Prototype camp", "Prototype new station")
            changed = changed.replace("Synthetic resin = 2", "Synthetic crystal = 8")
            wiki_save(OWNER, changed, "Change station and ingredient; remove rain variant")
            current = rows(admin)
            assert len(current) == 2 and all(r["Variant"] != "rain" for r in current)
            assert {r["Owner"] for r in rows(admin, "Ingredients HOLDS 'Synthetic resin'")} == {NEW_OWNER}
            assert rows(admin, "Stations HOLDS 'Prototype bench'") == []
            assert {r["Owner"] for r in rows(admin, "Ingredients HOLDS 'Synthetic crystal'")} == {OWNER}
            freshness("change relationship and remove row", {
                "Prototype bench": [(OWNER, False)],
                populated_reader: [(OWNER, False)],
                "Prototype new station": [(OWNER, True), (NEW_OWNER, True)],
                "Synthetic resin": [(OWNER + " -", False), (NEW_OWNER, True)],
            })
            report["checks"]["relation_change_and_row_removal"] = True

            before = revision(admin, OWNER)
            sync_report = sync(admin, {OWNER: "Stale repository text."}, "repo-sync: synthetic ownership",
                               apply=True, log=lambda _: None)
            assert [r["title"] for r in sync_report["skipped"]] == [OWNER]
            assert revision(admin, OWNER) == before and rows(admin) == current
            report["checks"]["normal_sync_preserves_human_owner"] = True

            admin.call({"action": "move", "from": OWNER, "to": MOVED, "token": admin.csrf(),
                        "reason": "Synthetic lifecycle proof"}, post=True)
            moved_rows = rows(admin)
            report["move_immediate_rows"] = moved_rows
            report["move_jobs"] = jobs()
            report["move_after_jobs_rows"] = rows(admin)
            if {r["Owner"] for r in rows(admin)} != {MOVED, NEW_OWNER}:
                assert not integrated, "Automatic owner move indexing failed."
                report["move_rebuild_required"] = True
                recreate()
            moved_rows = rows(admin)
            assert {r["Owner"] for r in moved_rows} == {MOVED, NEW_OWNER}, moved_rows
            assert source(admin, MOVED) == before["slots"]["main"]["content"]
            assert next(r["PageID"] for r in moved_rows if r["Owner"] == MOVED) == next(
                r["PageID"] for r in current if r["Owner"] == OWNER)
            freshness("rename owner", {"Prototype new station": [(MOVED, True), (OWNER + " -", False)]})
            expect_owner_link(MOVED)
            admin.call({"action": "delete", "title": MOVED, "token": admin.csrf(),
                        "reason": "Synthetic lifecycle proof"}, post=True)
            assert {r["Owner"] for r in rows(admin)} == {NEW_OWNER}
            freshness("delete owner", {"Prototype new station": [(MOVED, False), (NEW_OWNER, True)]})
            admin.call({"action": "undelete", "title": MOVED, "token": admin.csrf(),
                        "reason": "Synthetic lifecycle proof"}, post=True)
            report["checks"]["restore_immediate_rows"] = len(rows(admin))
            report["restore_jobs"] = jobs()
            report["checks"]["restore_after_jobs_rows"] = len(rows(admin))
            if {r["Owner"] for r in rows(admin)} != {MOVED, NEW_OWNER}:
                assert not integrated, "Automatic restored owner indexing failed."
                report["restore_rebuild_required"] = True
                recreate()
            assert {r["Owner"] for r in rows(admin)} == {MOVED, NEW_OWNER}, "Restore was not recoverable from current source."
            freshness("restore owner", {"Prototype new station": [(MOVED, True), (NEW_OWNER, True)]})
            expect_owner_link(MOVED)
            report["checks"]["move_delete_restore"] = True

            before_rebuild = rows(admin)
            owners_before = {title: revision(admin, title) for title in (MOVED, NEW_OWNER)}
            report["rebuild_seconds"] = recreate()
            assert rows(admin) == before_rebuild, (before_rebuild, rows(admin))
            assert {title: revision(admin, title) for title in owners_before} == owners_before
            freshness("drop and rebuild from live revisions", {
                "Prototype new station": [(MOVED, True), (NEW_OWNER, True)],
                "Prototype bench": [(MOVED, False)],
            })
            report["checks"]["rebuild_identical_no_source_changes"] = True
            report["final_rows"] = rows(admin)
            report["owner_sources"] = {title: source(admin, title) for title in owners_before}
            query_seconds = []
            for _ in range(10):
                started = time.monotonic()
                assert len(rows(admin, "Stations HOLDS 'Prototype new station'")) == 2
                query_seconds.append(round(time.monotonic() - started, 4))
            report["query_seconds_two_records"] = query_seconds
            report["ux_limits"] = [
                "TemplateData field edits are visual; add/remove variants are tested through the ordinary editor API, not a GUI.",
                "Ingredients support arbitrary line count, but Item = quantity is paired-text notation, not repeatable controls.",
                "Stations/merchants use semicolon-separated titles; no production autocomplete or uniqueness validation.",
                "Only query renderers are safe read-only reuse. Direct owner transclusion indexes copies and must be migrated.",
                "No production schema migration, Page Forms installation, or original raw-table fix is included.",
            ]
            report["acceptance_limits"] = {
                "automatic_cached_reader_freshness": all(
                    value["after_jobs"] for event in report["cache"] for value in event["readers"].values()),
                "lifecycle_without_rebuild": not (report.get("move_rebuild_required")
                                                 or report.get("restore_rebuild_required")),
                "native_add_remove_gui_proved": bool(report["checks"].get("native_gui_add_variant_remove_last_record")),
                "raw_owner_transclusion_safe": False,
            }
        except Exception:
            if "Special:UserLogin" not in urllib.parse.unquote(page.url):
                page.screenshot(path=str(artifacts / "cargo-failure.png"), full_page=True)
            raise
        finally:
            context.close()
            browser.close()
