"""Reviewed landmark metadata and synthetic-only presentation regressions."""

import copy
import hashlib
import io
import json
import struct
import sys
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from smoke_deploy import LANDMARK_IMAGES, check_seller_context, smoke_npc_locations, smoke_reader_release, synthetic_image_specs
from smoke_prefix import dom
from test_views import expand_selective_view
from wiki_catalog import category_definitions, page_locations, validate_catalog
from wiki_data import DataError
from wiki_details import load_publication_inputs, parse_illustrations
from wiki_render import build_pages, icon, image_for


LANDMARKS = {
    "being-12": ("Ranger-Bhato-hut-exterior.png", "c25cc3db9e4414f8ff9c4349dd6d5b094ff52c2cdd109024dca721beb88b8d7a"),
    "being-26": ("Gurb-Gurb-hollow-exterior.png", "0d6c1233ce177559e4a4246619300fe10db86ecb2c1ab30651dbcb2918932c6f"),
    "being-33": ("Ihar-shipwreck-exterior.png", "fae9cbf6070fdccd29c765dddd31e160b2c92c75911ecaab5f641881fa702d53"),
}


class LandmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.catalog, cls.details = load_publication_inputs(ROOT)
        cls.pages = build_pages(ROOT, cls.data, cls.catalog, cls.details)
        cls.locations = page_locations(cls.data, cls.catalog)
        cls.images = {row["entity"]: row for row in cls.data["illustrations"] if row.get("role") == "location"}

    def test_exact_native_landmarks_are_supplementary_not_portraits(self):
        self.assertEqual(set(self.images), set(LANDMARKS))
        self.assertEqual(len(self.data["illustrations"]), 329)
        for identity, (filename, digest) in LANDMARKS.items():
            image = self.images[identity]
            self.assertEqual(image["id"], identity + "-location-illustration")
            self.assertEqual(image["file_title"], "File:" + filename)
            self.assertEqual(image["sha256"], digest)
            self.assertEqual(image["creator"], "Edym Pixels")
            self.assertEqual(image["rights_status"], "approved")
            self.assertIn("2026-09-26", image["rights_note"])
            self.assertTrue(any(".frame0" in row["key"] for row in image["evidence"]))
            page = self.pages[self.locations[identity]]
            portrait = image_for(identity, self.data["illustrations"])
            self.assertEqual(portrait["file_title"], "File:" + identity.capitalize() + ".png")
            self.assertEqual(page.count("[[" + portrait["file_title"] + "|thumb|"), 1)
            self.assertEqual(page.count("[[File:" + filename + "|thumb|220px|"), 1)
            location_section = page.split("== Location and access ==", 1)[1].split("== Stats ==", 1)[0]
            self.assertIn("[[File:" + filename, location_section)
            self.assertNotIn(portrait["file_title"], location_section)
            self.assertIn(digest, self.pages["Source provenance"])
            self.assertNotIn(digest, page)

    def test_every_primary_lookup_ignores_contextual_order_and_pending_portraits(self):
        entities = {row["id"]: row for row in self.data["entities"]}
        for identity, exterior in self.images.items():
            portrait = image_for(identity, self.data["illustrations"])
            for pictures in ([exterior, portrait], [portrait, exterior]):
                self.assertIs(image_for(identity, pictures), portrait)
                self.assertIn(portrait["file_title"], icon(identity, pictures, entities, self.locations))
                self.assertNotIn(exterior["file_title"], icon(identity, pictures, entities, self.locations))
            self.assertIsNone(image_for(identity, [exterior]))
            pending = dict(portrait, rights_status="pending")
            self.assertIsNone(image_for(identity, [exterior, pending]))
        data = dict(self.data, illustrations=list(reversed(self.data["illustrations"])))
        self.assertEqual(build_pages(ROOT, data, self.catalog, self.details), self.pages)

    def test_location_prose_keeps_generation_qualifications_and_existing_journal_owners(self):
        bhato = self.pages["Ranger Bhato"]
        self.assertIn("[[Captain Eir|<nowiki>Captain Eir</nowiki>]]", bhato)
        self.assertIn("neighboring area", bhato)
        self.assertIn("not the nearby ancient cellar", bhato)
        self.assertIn("[[Quests and journal#entry-journal-7|", bhato)
        self.assertIn("only if the world has no Drowned Fen area", self.pages["Gurb-Gurb"])
        self.assertIn("five white dots", self.pages["Gurb-Gurb"])
        self.assertIn("one-time discovery cue, not a message on every return", self.pages["Gurb-Gurb"])
        self.assertIn("Smoke rises separately in play", self.pages["Gurb-Gurb"])
        ihar = self.pages["Ihar"].split("== Location and access ==", 1)[1].split("== Stats ==", 1)[0]
        self.assertIn("Broken Fen shoreline", ihar)
        self.assertIn("Placement can fail", ihar)
        self.assertIn("not guaranteed in every Broken Fen area", ihar)
        self.assertNotIn("smoke", ihar.lower())
        self.assertNotIn("popup", ihar.lower())
        self.assertIn("== NPC location evidence ==", self.pages["Source provenance"])

    def test_filtered_sellers_link_to_new_location_without_copying_prose_or_stale_nulls(self):
        profiles = {row["entity"]: row["location"] for row in self.catalog["classifications"] if "location" in row}
        for identity, location in profiles.items():
            owner = self.locations[identity]
            self.assertNotIn("Location: Not established", self.pages[owner])
            for offer in self.data["entries"]:
                if offer["kind"] != "merchant" or offer["details"]["merchant"] != identity:
                    continue
                rendered = expand_selective_view(self.pages[owner], {"view": "offers", "item": offer["details"]["item"]})
                selected = dom(rendered, "Filtered seller")
                self.assertIn({"target": owner + "#Location_and_access", "text": "Location and access"}, selected.links)
                self.assertNotIn("Location: Not established", selected.text)
                for paragraph in location["paragraphs"]:
                    self.assertNotIn(paragraph, selected.text)
                self.assertNotIn(self.images[identity]["file_title"], rendered)
                check_seller_context(
                    {"templates": [{"*": owner}], "text": {"*": rendered}},
                    owner, offer["details"]["item"], selected.text, location_page=owner,
                )
        historical = {row["details"]["location"] for row in self.data["entries"]
                      if row["kind"] == "merchant" and row["details"]["merchant"] in {"being-26", "being-33"}}
        self.assertEqual(historical, {None})

    def test_pending_location_art_never_emits_a_file_link_or_replaces_the_portrait(self):
        data = copy.deepcopy(self.data)
        for image in data["illustrations"]:
            if image.get("role") == "location":
                image.update(rights_status="pending", creator=None, sha256=None, rights_basis=None, rights_note=None)
        pages = build_pages(ROOT, data, self.catalog, self.details)
        for identity, (filename, _) in LANDMARKS.items():
            page = pages[self.locations[identity]]
            self.assertNotIn("[[File:" + filename, page)
            self.assertNotIn("[[:File:" + filename, page)
            self.assertIn("[[File:" + identity.capitalize() + ".png|thumb|", page)
            self.assertIn("No reviewed picture is available yet.", page)

    def test_location_images_reject_unreviewed_roles_owners_duplicates_and_rights(self):
        base = {key: value for key, value in self.data.items() if key != "illustrations"}
        for change in (
            {"role": "portrait"}, {"role": None}, {"entity": "missing"}, {"entity": "item-8"},
            {"entity": "being-8"}, {"creator": None}, {"sha256": "invalid"},
            {"rights_status": "assumed"}, {"evidence": []},
        ):
            with self.subTest(change=change):
                image = dict(self.images["being-12"], **change)
                with self.assertRaises(DataError):
                    parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [image]}).encode(), base, self.catalog)
        original = self.images["being-12"]
        duplicate = dict(original, id="duplicate-location", file_title="File:Duplicate-location.png")
        with self.assertRaisesRegex(DataError, "one location illustration"):
            parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [original, duplicate]}).encode(), base, self.catalog)
        without_owner = copy.deepcopy(self.catalog)
        next(row for row in without_owner["classifications"] if row["entity"] == "being-12").pop("location")
        for validate in (
            lambda: parse_illustrations(json.dumps({"schema_version": 1, "illustrations": [original]}).encode(), base, without_owner),
            lambda: build_pages(ROOT, self.data, without_owner, self.details),
        ):
            with self.assertRaisesRegex(DataError, "reviewed NPC location owner"):
                validate()

    def test_location_text_requires_bounded_original_prose_and_its_own_evidence(self):
        for change in (
            {"paragraphs": []}, {"paragraphs": ["x"] * 4}, {"paragraphs": ["x" * 801]},
            {"paragraphs": "Not a list"}, {"confidence": "guessed"}, {"evidence": []},
            {"related_entities": ["missing"]}, {"related_entities": ["being-6", "being-6"]},
            {"related_entities": ["being-12"]},
        ):
            with self.subTest(change=change):
                catalog = copy.deepcopy(self.catalog)
                next(row for row in catalog["classifications"] if row["entity"] == "being-12")["location"].update(change)
                with self.assertRaises(DataError):
                    validate_catalog(catalog, self.data)
        catalog = copy.deepcopy(self.catalog)
        owner = next(row for row in catalog["classifications"] if row["entity"] == "being-12")
        owner["kind"] = "creature"
        with self.assertRaisesRegex(DataError, "requires an NPC"):
            validate_catalog(catalog, self.data)
        owner["kind"] = "npc"
        owner["location"]["paragraphs"] = ["</nowiki><script>Not executable.</script>"]
        page = build_pages(ROOT, self.data, catalog, self.details)["Ranger Bhato"]
        self.assertIn("&lt;/nowiki&gt;&lt;script&gt;", page)
        self.assertNotIn("<script>", page)

    def test_merchant_category_uses_actual_offers_not_every_npc(self):
        merchants = {row["details"]["merchant"] for row in self.data["entries"] if row["kind"] == "merchant"}
        category = category_definitions(self.data, self.catalog)["Merchants"]
        self.assertEqual(set(category["members"]), merchants)
        self.assertEqual(merchants, set(self.catalog["currency"]["standard_merchants"]))
        self.assertEqual(category["parents"], ["NPCs"])
        self.assertEqual(len(merchants), 6)
        self.assertNotIn("being-34", merchants)
        self.assertIn("== Trading rules ==", self.pages["Category:Merchants"])
        self.assertEqual(self.pages["Category:Merchants"].count("{{:Currency and trading|view=stock}}"), 1)

    def test_seller_smoke_keeps_filtered_views_leaf_and_checks_stock_rule_references(self):
        stock = "Listed wares do not run out, and merchants have unlimited buying funds."
        reference = '<a href="/index.php?title=Category:Merchants#Trading_rules">Shared trading rules</a>'
        result = {"templates": [{"*": "Merchant"}], "text": {"*": ""}}
        check_seller_context(result, "Merchant", "item-0", "", stock)
        full = dict(result, text={"*": reference})
        check_seller_context(full, "Merchant", None, "Shared trading rules", stock)
        check_seller_context({"templates": [{"*": "Merchant"}]}, "Merchant", "item-0", "Quantity is not established.")
        for templates in ([], ["Currency and trading"], ["Merchant", "Currency and trading"], ["Merchant", "Item"],
                          ["Merchant", "Currency and trading", "Copper Coin"]):
            with self.assertRaises(RuntimeError):
                check_seller_context(dict(result, templates=[{"*": title} for title in templates]), "Merchant", "item-0", "", stock)
        for text in (stock, "Shared trading rules", "Shared stock and merchant-funds rules", "Unit price", "Quantity is not established."):
            with self.assertRaises(RuntimeError):
                check_seller_context(result, "Merchant", "item-0", text, stock)
        for rendered in ("", reference * 2, reference.replace("Category:Merchants", "Category:NPCs"),
                         reference.replace("#Trading_rules", "")):
            with self.assertRaises(RuntimeError):
                check_seller_context(dict(full, text={"*": rendered}), "Merchant", None, "Shared trading rules", stock)
        with self.assertRaises(RuntimeError):
            check_seller_context(full, "Merchant", "item-0", "Shared trading rules", stock)
        location = '<a href="/index.php?title=Merchant#Location_and_access">Location and access</a>'
        for rendered, text in (("", ""), (location, "Location: Not established"),
                               (location.replace("Merchant#", "Other#"), "Location and access")):
            with self.assertRaisesRegex(RuntimeError, "reviewed location"):
                check_seller_context(dict(result, text={"*": rendered}), "Merchant", "item-0", text, location_page="Merchant")

    def test_synthetic_landmarks_keep_native_sizes_and_do_not_require_upscaling(self):
        specs = synthetic_image_specs(self.data)
        self.assertEqual(LANDMARK_IMAGES, {
            "Ranger-Bhato-hut-exterior.png": (48, 48),
            "Gurb-Gurb-hollow-exterior.png": (80, 128),
            "Ihar-shipwreck-exterior.png": (128, 96),
        })
        for filename, size in LANDMARK_IMAGES.items():
            self.assertEqual(specs[filename][:2], size)
            self.assertEqual(specs[filename][3], 32)

    def test_runtime_checks_actual_portraits_landmark_imgs_and_served_native_bytes(self):
        def chunk(kind, body):
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

        bodies, hashes, parses, infos = {}, {}, {}, {}
        for identity, (filename, _) in LANDMARKS.items():
            width, height = LANDMARK_IMAGES[filename]
            pixels = (b"\0" + b"\x44\x99\x11" * width) * height
            body = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))
            url = "https://example.invalid/images/" + filename
            bodies[url] = body
            hashes[filename] = hashlib.sha256(body).hexdigest()
            portrait = identity.capitalize() + ".png"
            parses[self.locations[identity]] = {"images": [filename, portrait], "text": {"*":
                f'<img src="{url}" width="{width}" height="{height}" />'
                f'<img src="https://example.invalid/images/{portrait}" />'}}
            infos["File:" + filename] = {"url": url, "thumburl": url, "width": width, "height": height, "mime": "image/png"}

        def run_case(changed_parses=None, changed_infos=None, changed_bodies=None):
            responses = parses if changed_parses is None else changed_parses
            metadata = infos if changed_infos is None else changed_infos
            payloads = bodies if changed_bodies is None else changed_bodies
            reads = []

            def api(query):
                if query["action"] == "parse":
                    return {"parse": responses[query["page"]]}
                self.assertEqual(query["iiurlwidth"], 220)
                return {"query": {"pages": {"1": {"imageinfo": [metadata[query["titles"]]]}}}}

            def open_media(url, timeout):
                self.assertEqual(timeout, 30)
                reads.append(url)
                response = io.BytesIO(payloads[url])
                response.status = 200
                response.headers = SimpleNamespace(get_content_type=lambda: "image/png")
                return response

            smoke_npc_locations(api, self.data, self.catalog, hashes, open_media)
            self.assertEqual(len(reads), 6)

        run_case()
        no_thumb_metadata = copy.deepcopy(infos)
        for info in no_thumb_metadata.values():
            info.pop("thumburl")
        run_case(changed_infos=no_thumb_metadata)
        for change in (
            lambda page: page["text"].update({"*": ""}),
            lambda page: page["text"].update({"*": page["text"]["*"].split("/>", 1)[0] + "/>"}),
            lambda page: page["text"].update({"*": page["text"]["*"].replace('width="48"', 'width="220"')}),
            lambda page: page["text"].update({"*": page["text"]["*"].replace("images/Ranger", "wrong/Ranger")}),
            lambda page: page.update(images=["Being-12.png"]),
        ):
            altered = copy.deepcopy(parses)
            change(altered["Ranger Bhato"])
            with self.assertRaises(RuntimeError):
                run_case(changed_parses=altered)
        altered = copy.deepcopy(infos)
        altered["File:Ranger-Bhato-hut-exterior.png"]["width"] = 49
        with self.assertRaisesRegex(RuntimeError, "native PNG metadata"):
            run_case(changed_infos=altered)
        altered_bodies = dict(bodies)
        altered_bodies[infos["File:Ranger-Bhato-hut-exterior.png"]["url"]] += b"changed"
        with self.assertRaisesRegex(RuntimeError, "exact native import"):
            run_case(changed_bodies=altered_bodies)

    def test_reader_release_invokes_location_image_verification(self):
        with patch("smoke_deploy.smoke_category_memberships"), patch(
            "smoke_deploy.smoke_npc_locations", side_effect=RuntimeError("location checkpoint")
        ) as verify:
            with self.assertRaisesRegex(RuntimeError, "location checkpoint"):
                smoke_reader_release(None, self.pages, self.data, self.catalog, self.details, {})
            verify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
