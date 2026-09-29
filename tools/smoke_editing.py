"""Real VisualEditor/Parsoid and source editing on the disposable wiki only."""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from smoke_display import check_parser_errors
from wiki_display import DISPLAY_FILES
from wiki_views import filtered_row, html_table, selective_view


SIMPLE = "User:TestEditor/Visual editor smoke"
OWNER = "Editor fixture/Owner"
MERCHANT = "Editor fixture/Merchant"
SCROLL = ('<div class="mirklurk-scroll" role="group" tabindex="0" '
          'aria-label="Table (scroll horizontally)" style="max-width:100%;overflow-x:auto;">\n')


def editor_fixtures():
    recipe = ('{{Recipe row|anchors=<span id="synthetic-recipe"></span>'
              '|ingredients={{Item|Plant Fiber|quantity=4}}|output={{Item|Bandage|quantity=1}}'
              '|methods=Synthetic station|ap=2|conditions=Synthetic condition.}}\n')
    recipes = SCROLL + html_table(
        ["Inputs", "Output", "Method", "Cost", "Conditions"],
        [selective_view(filtered_row(recipe, "station", ["Synthetic station"]), "recipes")],
    ) + "</div>\n"
    ware = ('{{Ware row|anchors=<span id="synthetic-ware"></span>|seller=Synthetic seller'
            '|item=Iron Hand Axe|price=<noinclude>{{:' + OWNER + '}}</noinclude>}}\n')
    wares = SCROLL + html_table(
        ["Seller", "Item", "Price"], [filtered_row(ware, "item", ["Iron Hand Axe"])], normal_only=(2,),
    ) + "</div>\n"
    return {
        SIMPLE: ("Synthetic editor introduction.\n\n{{Item|Plant Fiber|quantity=4}}\n\n{{Creature|Sceetler}}"
                 "\n\n{{Coins|1234}}\n\n{{Health grid|0,1,0;1,4,1;0,1,0}}"
                 "\n\n{{Attack grid|0-1,0,0-1;0,1-2,0;0-1,0,0-1|label=Melee attack}}"
                 "\n\nSynthetic uncertain claim.{{Unverified}}\n"),
        OWNER: ("Synthetic owner introduction.\n\n== Price ==\n"
                + selective_view("{{Coins|1234}}", "price", True)
                + "\n\n== Recipe ==\n" + recipes + "\n"),
        MERCHANT: "Synthetic merchant introduction.\n\n" + selective_view(wares, "sellers") + "\n",
    }


def revision(api, title):
    pages = api({"action": "query", "prop": "revisions", "titles": title,
                 "rvprop": "ids|content|user|comment|tags", "rvslots": "main"})["query"]["pages"]
    return next(iter(pages.values()))["revisions"][0]


def source(api, title):
    return revision(api, title)["slots"]["main"]["*"]


def projections(api):
    views = {
        "price": "{{:" + OWNER + "}}",
        "recipe": SCROLL + html_table(["Inputs", "Output", "Method", "Cost", "Conditions"],
                                     ["{{:" + OWNER + "|view=recipes|station=Synthetic station}}"]) + "</div>",
        "wrong station": SCROLL + html_table(["Inputs", "Output", "Method", "Cost", "Conditions"],
                                            ["{{:" + OWNER + "|view=recipes|station=Other station}}"]) + "</div>",
        "seller": "{{:" + MERCHANT + "|view=sellers|item=Iron Hand Axe}}",
        "wrong item": "{{:" + MERCHANT + "|view=sellers|item=Bandage}}",
    }
    result = {}
    for name, text in views.items():
        html = api({"action": "parse", "title": "Editor projection", "text": text, "prop": "text"},
                   post=True)["parse"]["text"]["*"]
        check_parser_errors(html)
        if "<templatedata" in html or "mw-templatedata" in html:
            raise RuntimeError("Template metadata leaked into a transcluded reader view.")
        result[name] = re.sub(r"<!--.*?-->", "", html, flags=re.S).strip()
    if ("synthetic-recipe" not in result["recipe"] or "synthetic-recipe" in result["wrong station"]
            or "synthetic-ware" not in result["seller"] or "synthetic-ware" in result["wrong item"]
            or "mirklurk-coin" in result["seller"] or "mirklurk-coin" not in result["price"]):
        raise RuntimeError("The selective-view fixture does not exercise its price and row filters.")
    return result


def smoke_editing(api, base, token, editor_password, pages, artifact_dir):
    from playwright.sync_api import sync_playwright

    if urllib.parse.urlsplit(base).hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("Editor smoke may only edit the disposable localhost wiki.")
    folder = Path(artifact_dir)
    folder.mkdir(parents=True, exist_ok=True)
    fixtures = editor_fixtures()
    for title, text in fixtures.items():
        saved = api({"action": "edit", "title": title, "text": text, "token": token,
                     "summary": "Disposable synthetic editor fixture"}, post=True)
        if saved.get("edit", {}).get("result") != "Success":
            raise RuntimeError("Cannot create the disposable editor fixture.")
    titles = [title for title in DISPLAY_FILES if title.startswith("Template:")]
    metadata = api({"action": "templatedata", "titles": "|".join(titles)})["pages"]
    actual = {row["title"]: row for row in metadata.values()}
    for title in titles:
        expected = json.loads(re.search(r"<templatedata>(.*?)</templatedata>", pages[title], re.S)[1])
        row = actual.get(title, {})
        if "notemplatedata" in row or set(row.get("params", {})) != set(expected["params"]):
            raise RuntimeError("Live TemplateData has missing or incorrect parameters for " + title)
        for name, spec in expected["params"].items():
            param = row["params"][name]
            if param.get("label", {}).get("en") != spec["label"] or param.get("type") != spec["type"]:
                raise RuntimeError("Live TemplateData labels/types differ from the authored metadata.")
    # Exercise Apache's actual selected virtual host and encoded slash handling,
    # through the published high port, not just the container filesystem.
    for title in (SIMPLE, OWNER):
        url = base + "/rest.php/v1/page/" + urllib.parse.quote(title, safe="") + "/html"
        with urllib.request.urlopen(url, timeout=60) as response:
            html = response.read().decode()
            if response.status != 200 or "Synthetic" not in html:
                raise RuntimeError("Encoded-slash REST HTML failed through the published container port.")

    # Parsoid's selective serializer must preserve the original revision source.
    for title in (*fixtures, "Iron Hand Axe", "Copper Coin", "Gurb-Gurb", "Bandage"):
        before = source(api, title)
        parsed = api({"action": "visualeditor", "paction": "parse", "page": title}, timeout=120)["visualeditor"]
        if parsed.get("result") != "success" or not parsed.get("content"):
            raise RuntimeError("The integrated Parsoid client cannot open " + title)
        serialized = api({
            "action": "visualeditoredit", "paction": "serialize", "page": title,
            "html": parsed["content"], "oldid": parsed["oldid"], "etag": parsed["etag"], "token": token,
        }, post=True, timeout=120)["visualeditoredit"]
        if serialized.get("result") != "success" or serialized.get("content", "").strip() != before.strip():
            raise RuntimeError("No-change Parsoid round trip altered source on " + title)
    initial_views = projections(api)
    report = {"parsoid_no_change": [*fixtures, "Iron Hand Axe", "Copper Coin", "Gurb-Gurb", "Bandage"]}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1050})
        page = context.new_page()
        page.set_default_timeout(60000)

        def url(title, **params):
            return base + "/index.php?" + urllib.parse.urlencode({"title": title, **params})

        def browser_api(params):
            response = context.request.post(base + "/api.php", form={"format": "json", **params})
            if not response.ok:
                raise RuntimeError("Disposable browser API HTTP request failed.")
            return response.json()

        def open_editor(title, first_edit=False):
            page.goto(base + "/w/" + urllib.parse.quote(title.replace(" ", "_"), safe=":"), wait_until="networkidle")
            if page.locator("#ca-edit a").inner_text() != "Edit source":
                raise RuntimeError("Logged-in source editing is not discoverable.")
            page.locator("#ca-ve-edit a").click()
            page.wait_for_function("window.ve?.init?.target?.active && ve.init.target.getSurface()")
            if first_edit:
                page.locator(".ve-init-mw-welcomeDialog").get_by_role("button", name="Start editing", exact=True).click()
            page.wait_for_function("ve.init.target.active && !ve.init.target.activating && !ve.init.target.welcomeDialog")
            page.locator(".ve-ce-documentNode").wait_for(state="visible")
            page.evaluate("""() => {
                window.editorClicks = [];
                document.addEventListener('click', e => window.editorClicks.push({
                    tag: e.target.tagName, classes: e.target.className,
                    text: e.target.textContent.slice(0, 100)
                }), true);
            }""")

        def append_prose(text):
            paragraph = page.locator(".ve-ce-documentNode .ve-ce-paragraphNode").first
            paragraph.click()
            page.keyboard.press("End")
            page.keyboard.insert_text(text)

        def save_visual(summary):
            page.locator(".ve-ui-toolbar-saveButton").click()
            dialog = page.locator(".ve-ui-mwSaveDialog")
            dialog.locator("textarea").fill(summary)
            dialog.get_by_role("button", name="Review your changes", exact=True).click()
            page.wait_for_function("ve.init.target.saveDialog.hasDiff && !ve.init.target.saveDialog.isPending()")
            page.screenshot(path=str(folder / "editor-review.png"))
            with page.expect_response(lambda response: "/api.php" in response.url
                                      and "paction=save" in (response.request.post_data or "")) as saving:
                dialog.locator(".oo-ui-processDialog-actions-primary .oo-ui-buttonElement-button").click()
            value = saving.value.json().get("visualeditoredit", {})
            if value.get("result") != "success":
                raise RuntimeError("VisualEditor save failed: " + json.dumps(value))
            page.wait_for_function("!window.ve?.init?.target?.active")

        try:
            page.goto(url(SIMPLE), wait_until="networkidle")
            anonymous = browser_api({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
            denied = browser_api({"action": "visualeditoredit", "paction": "save", "page": SIMPLE,
                                  "wikitext": "Anonymous must not write.", "token": anonymous})
            if "error" not in denied or source(api, SIMPLE).strip() != fixtures[SIMPLE].strip():
                raise RuntimeError("The visual edit API allowed an anonymous write.")
            page.goto(url("Special:UserLogin"), wait_until="networkidle")
            page.locator("#wpName1").fill("TestEditor")
            page.locator("#wpPassword1").fill(editor_password)
            page.locator("#wpLoginAttempt").click()
            page.wait_for_function("mw.config.get('wgUserName') === 'TestEditor'")
            user = browser_api({"action": "query", "meta": "userinfo", "uiprop": "rights|groups"})["query"]["userinfo"]
            if "edit" not in user["rights"] or "sysop" in user["groups"] or "bot" in user["groups"]:
                raise RuntimeError("Browser editing must use an ordinary self-registered account.")

            open_editor(SIMPLE, first_edit=True)
            page.locator(".ve-ce-documentNode .ve-ce-mwTransclusionNode").first.click()
            page.locator(".ve-ui-mwTransclusionContextItem").get_by_role("button", name="Edit", exact=True).click()
            dialog = page.locator(".ve-ui-mwTemplateDialog")
            dialog.get_by_label("Quantity", exact=True).fill("5")
            if not dialog.get_by_label("Item", exact=True).count():
                raise RuntimeError("The template dialog did not show its TemplateData item field.")
            page.screenshot(path=str(folder / "editor-template-fields.png"))
            dialog.locator(".oo-ui-processDialog-actions-primary .oo-ui-buttonElement-button").click()
            append_prose(" Synthetic visual edit.")
            save_visual("Synthetic visual prose and template parameter edit")
            saved = revision(api, SIMPLE)
            text = saved["slots"]["main"]["*"]
            if (saved["user"] != "TestEditor" or "visualeditor" not in saved["tags"]
                    or saved["comment"] != "Synthetic visual prose and template parameter edit"
                    or "Synthetic visual edit." not in text or "quantity=5" not in text):
                raise RuntimeError("Visual editing did not save prose, template arguments, author, tag and summary.")
            for call in re.findall(r"\{\{(?:Creature|Coins|Health grid|Attack grid|Unverified)[^\n]*?\}\}", fixtures[SIMPLE]):
                if call not in text:
                    raise RuntimeError("An untouched display template was flattened by visual editing.")
            report["browser_template_edit"] = True

            time.sleep(21)  # Preserve the real three-edits/minute newcomer limit.
            before = source(api, OWNER)
            open_editor(OWNER)
            append_prose(" Synthetic prose-only change.")
            save_visual("Synthetic prose edit beside selective data")
            after = source(api, OWNER)
            if after.replace(" Synthetic prose-only change.", "").strip() != before.strip():
                raise RuntimeError("A visual prose edit changed the wrapped selective owner source.")
            if projections(api) != initial_views:
                raise RuntimeError("A visual prose edit changed a price or filtered reader view.")
            report["browser_selective_prose"] = True

            # Source editing is the documented route for the selective data itself.
            time.sleep(21)
            page.goto(url(OWNER, action="edit"), wait_until="networkidle")
            textarea = page.locator("#wpTextbox1")
            original = textarea.input_value()
            updated = original.replace("|ap=2|", "|ap=3|")
            if updated == original:
                raise RuntimeError("Source fallback could not find the nested recipe cost.")
            textarea.fill(updated)
            page.locator("#wpSummary").fill("Synthetic source edit of canonical recipe")
            page.locator("#wpPreview").click()
            page.locator("#wikiPreview").wait_for(state="visible")
            if "3 base" not in page.locator("#wikiPreview").inner_text():
                raise RuntimeError("Source preview did not show the updated canonical AP.")
            page.locator("#wpSave").click()
            page.wait_for_function("mw.config.get('wgAction') === 'view'")
            if source(api, OWNER).strip() != updated.strip():
                raise RuntimeError("The source form did not preserve the complete selective structure.")
            views = projections(api)
            if views["recipe"] == initial_views["recipe"] or "3 base" not in re.sub(r"<[^>]+>", "", views["recipe"]):
                raise RuntimeError("The source-edited canonical AP did not propagate to its filtered view.")
            if any(views[key] != initial_views[key] for key in views if key != "recipe"):
                raise RuntimeError("The source edit changed an unrelated selective projection.")
            report["source_preview_save_and_projection"] = True

            # A VE save is still subject to ConfirmEdit, not an alternate write bypass.
            time.sleep(21)
            csrf = browser_api({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
            before = source(api, SIMPLE)
            challenged = browser_api({
                "action": "visualeditoredit", "paction": "save", "page": SIMPLE, "token": csrf,
                "wikitext": before + "\n[https://example.invalid Synthetic external link]",
            })
            if not challenged.get("visualeditoredit", {}).get("edit", {}).get("captcha"):
                raise RuntimeError("A VisualEditor link addition did not require the configured CAPTCHA.")
            if source(api, SIMPLE) != before:
                raise RuntimeError("An unsolved CAPTCHA nevertheless saved the page.")
            report["anonymous_denied_and_captcha_enforced"] = True
            page.goto(url("Help:Editing"), wait_until="networkidle")
            if not page.locator("#ca-ve-edit a").count() or "Start small" not in page.locator("#mw-content-text").inner_text():
                raise RuntimeError("The ordinary help article was not published in its editable namespace.")
            page.screenshot(path=str(folder / "editor-help.png"), full_page=True)
            (folder / "editing.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        except Exception:
            # Screenshot only the disposable wiki; never persist browser cookies or login traces.
            if "Special:UserLogin" not in urllib.parse.unquote(page.url):
                page.screenshot(path=str(folder / "editor-failure.png"), full_page=True)
                state = page.evaluate("""() => ({
                    active: window.ve?.init?.target?.active,
                    activating: window.ve?.init?.target?.activating,
                    clicks: window.editorClicks,
                    dialogs: [...document.querySelectorAll('[role=dialog]')].map(e => ({
                        classes: e.className, text: e.innerText
                    })),
                    nodes: [...document.querySelectorAll('.ve-ce-documentNode .ve-ce-mwTransclusionNode')]
                        .map(e => ({classes: e.className, text: e.innerText}))
                })""")
                (folder / "editor-failure.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            raise
        finally:
            context.close()
            browser.close()
    print("Editor smoke: ordinary-account visual open/template edit/review/save; exact selective round trips; "
          "source preview/save/propagation; encoded-slash REST; anonymous denial and CAPTCHA passed.", flush=True)
