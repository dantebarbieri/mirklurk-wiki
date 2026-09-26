"""Synthetic unit cases only; real prefix evidence requires the disposable runtime."""

import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from smoke_deploy import RenderedRows, item_links
from smoke_prefix import COHORT, canonical_bytes, dom, linked_titles, planned_order, settings_hash


class PrefixTests(unittest.TestCase):
    def fixture(self):
        locations = {identity: identity for identity in COHORT}
        baseline = {title: "Baseline" for title in locations.values()}
        desired = {title: "Desired" for title in locations.values()}
        for title in COHORT[3:]:
            desired[title] += "{{:New source|view=loot|item=" + title + "}}"
        desired["New source"] = "[[Later source]]"
        desired["Later source"] = "[[New source]]"
        return baseline, desired, locations

    def test_complete_order_prioritizes_ready_creates_and_preserves_cohort(self):
        baseline, desired, locations = self.fixture()
        order = planned_order(baseline, desired, locations, set(), set())
        self.assertEqual(set(order), set(desired))
        self.assertEqual(order[:2], ["Later source", "New source"])
        self.assertEqual([title for title in order if title in COHORT], list(COHORT))

    def test_named_prerequisite_cycle_is_not_waived_as_a_link_cycle(self):
        baseline, desired, locations = self.fixture()
        desired["New source"] = "{{:Later source|view=loot|item=item-32}}"
        desired["Later source"] = "{{:New source|view=loot|item=item-32}}"
        with self.assertRaisesRegex(RuntimeError, "Unresolved"):
            planned_order(baseline, desired, locations, set(), set())

    def test_only_exact_eleven_default_price_edges_can_use_old_unknowns(self):
        baseline, desired, locations = self.fixture()
        desired["being-8"] += "{{:item-32}}"
        self.assertEqual([title for title in planned_order(baseline, desired, locations, set(), set()) if title in COHORT], list(COHORT))
        desired["being-8"] += "{{:item-248}}"
        with self.assertRaisesRegex(RuntimeError, "Unresolved"):
            planned_order(baseline, desired, locations, set(), set())
        desired["being-8"] = "{{:item-32|view=price}}"
        with self.assertRaisesRegex(RuntimeError, "Unresolved"):
            planned_order(baseline, desired, locations, set(), set())

    def test_baseline_price_preservation_is_not_a_named_view_waiver(self):
        baseline, desired, locations = self.fixture()
        desired["being-8"] = "{{:item-248}}"
        planned_order(baseline, desired, locations, {"item-248"}, set())
        desired["being-8"] = "{{:item-248|view=offers}}"
        with self.assertRaisesRegex(RuntimeError, "Unresolved"):
            planned_order(baseline, desired, locations, {"item-248"}, set())

    def test_deletions_and_incomplete_cohort_fail(self):
        baseline, desired, locations = self.fixture()
        desired.pop("item-248")
        with self.assertRaises(RuntimeError):
            planned_order(baseline, desired, locations, set(), set())
        baseline, desired, locations = self.fixture()
        desired["item-248"] = baseline["item-248"]
        with self.assertRaises(RuntimeError):
            planned_order(baseline, desired, locations, set(), set())

    def test_settings_hash_is_exact_nonsecret_typed_canonical_json(self):
        value = {"EnableUploads": False, "AllowCopyUploads": False, "AllowExternalImages": False,
                 "ReadOnly": "", "GroupPermissions": {"user": {"edit": True}}, "CaptchaTriggers": {"edit": False}}
        self.assertEqual(settings_hash(value), hashlib.sha256(canonical_bytes(value)).hexdigest())
        changed = copy.deepcopy(value)
        changed["ReadOnly"] = False
        self.assertNotEqual(settings_hash(changed), settings_hash(value))
        changed["ReadOnly"] = None
        self.assertNotEqual(settings_hash(changed), settings_hash(value))
        for key, invalid in (("Extra", False), ("EnableUploads", 0), ("GroupPermissions", [])):
            changed = {**value, key: invalid}
            with self.assertRaises(RuntimeError):
                settings_hash(changed)
        self.assertEqual(canonical_bytes({"b": "\u00e9", "a": True}), b'{"a":true,"b":"\xc3\xa9"}')
        with self.assertRaises(ValueError):
            canonical_bytes({"invalid": float("nan")})

    def test_ordered_price_dom_preserves_fragment_and_redlink_state(self):
        parsed = dom('<table><tr><th>Item</th><th>Unit price</th></tr>'
                     '<tr><td><span id="entry-merchant-x"></span>'
                     '<a class="new" href="/index.php?title=New_item&amp;redlink=1" title="New item (page does not exist)">New item</a>'
                     '<a href="#Some_anchor">Self</a></td><td>2 gold</td></tr></table>', "Example owner")
        self.assertEqual(parsed.rows[0]["headers"], ["Item", "Unit price"])
        self.assertEqual(parsed.rows[0]["ids"], ["entry-merchant-x"])
        self.assertEqual(parsed.links, [{"target": "New item", "text": "New item"},
                                        {"target": "Example owner#Some_anchor", "text": "Self"}])
        self.assertEqual(parsed.wiki_links[0], {"target": "New item", "redlink": True})
        self.assertEqual(parsed.rows[0]["cells"][1]["text"], "2 gold")

    def test_recipe_identity_uses_canonical_href_not_redlink_tooltip(self):
        parsed = RenderedRows()
        parsed.feed('<table><tr><td><span id="entry-recipe-example"></span>'
                    '<a class="new" href="/index.php?title=Twine&amp;redlink=1" title="Twine (page does not exist)">Twine</a> x 8'
                    '</td></tr></table>')
        self.assertEqual(item_links(parsed.rows[0]["cells"][0], {"item-92": "Twine"}), ["Twine"])

    def test_ordinary_links_are_recorded_separately_from_selectors(self):
        self.assertEqual(linked_titles("[[New_source#Details|label]] {{:Owner|view=loot}} [[Existing]]"),
                         {"New source", "Existing"})


if __name__ == "__main__":
    unittest.main()
