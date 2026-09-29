"""Actual native template-menu add/remove interactions; no API-authored record fallback."""

from prototype_cargo_fixtures import FIELDS
from prototype_cargo_checks import revision, rows, source, store


def exercise_gui(admin, page, open_visual, save_visual, freshness, reader_query, report, artifacts):
    owner = "Prototype GUI owner"
    reader = "Prototype GUI station"
    prose = "Native GUI author prose."
    store(admin, owner, prose)
    store(admin, reader, reader_query("Stations HOLDS 'Prototype GUI station'"))
    freshness("GUI empty reader warmed", {reader: [(owner, False)]})
    original_rows = rows(admin)
    history = []

    def verify(summary, count):
        saved = revision(admin, owner)
        assert saved["user"] == "TestEditor" and saved["comment"] == summary
        assert "visualeditor" in saved["tags"]
        owned = rows(admin, "_pageName='Prototype GUI owner'")
        assert len(owned) == count, owned
        current = source(admin, owner)
        assert prose in current and "onlyinclude" not in current and "#switch" not in current
        history.append({"summary": summary, "revision": saved["revid"], "source": current, "records": owned})
        freshness(summary, {reader: [(owner, count > 0)]})
        return owned, current

    def insert(variant, ap, condition):
        open_visual(owner)
        paragraph = page.locator(".ve-ce-documentNode .ve-ce-paragraphNode").last
        paragraph.click()
        page.keyboard.press("Control+End")
        page.keyboard.press("Enter")
        page.locator(".ve-ui-toolbar-group-insert .oo-ui-popupToolGroup-handle").click()
        page.locator(".oo-ui-tool-name-transclusion .oo-ui-tool-link").click()
        dialog = page.locator(".ve-ui-mwTemplateDialog")
        dialog.locator(".ve-ui-mwTemplatePlaceholderPage input").fill("Prototype record")
        dialog.locator(".ve-ui-mwTransclusionDialog-addButton").click()
        values = {
            "variant": variant, "product": "Synthetic GUI product", "quantity": "1", "ap": ap,
            "ingredients": "Synthetic fiber = 4\nSynthetic resin = 2\nSynthetic water = 1\n"
                           "Synthetic salt = 1\nSynthetic leaf = 3",
            "stations": reader, "merchants": "Prototype trader", "condition": condition,
        }
        for name, value in values.items():
            dialog.get_by_label(FIELDS[name][0], exact=True).fill(value)
        page.screenshot(path=str(artifacts / ("cargo-insert-" + variant + ".png")), animations="disabled")
        dialog.locator(".oo-ui-processDialog-actions-primary .oo-ui-buttonElement-button").click()
        summary = "Native GUI add " + variant
        save_visual(summary)
        owned, current = verify(summary, 1 if variant == "gui-base" else 2)
        row = next(row for row in owned if row["Variant"] == variant)
        assert row["AP"] == ap and row["Inputs"] == values["ingredients"] and row["Requirement"] == condition
        assert row["Stations"] == reader and row["Quantity"] == "1"
        return owned, current

    first_rows, first_source = insert("gui-base", "4", "When the synthetic quest is active.")
    insert("gui-rain", "5", "Only during synthetic rain.")
    for remaining in (1, 0):
        open_visual(owner)
        page.locator(".ve-ce-documentNode .prototype-record").last.hover(force=True)
        page.locator('.ve-ce-focusableNode-highlight[title="Prototype record"]').last.click()
        page.keyboard.press("Backspace")
        summary = "Native GUI remove variant" if remaining else "Native GUI remove last record"
        save_visual(summary)
        owned, current = verify(summary, remaining)
        if remaining:
            assert owned == first_rows and current.strip() == first_source.strip(), (first_source, current)
        else:
            assert current.strip() == prose, current
    assert rows(admin) == original_rows
    report["native_gui"] = history
    report["checks"]["native_gui_add_variant_remove_last_record"] = True
