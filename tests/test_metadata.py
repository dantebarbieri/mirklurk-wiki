import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from smoke_metadata import Head, check_head, sitemap_locations


class MetadataAssertionsTests(unittest.TestCase):
    def test_html_entities_and_unicode(self):
        head = Head('<html><head><link rel="canonical" href="https://wiki.example.invalid/?a=1&amp;b=2">'
                    '<meta property="og:title" content="&quot;A&quot; &amp; caf\u00e9">'
                    '</head><body><meta name="description" content="Not head"></body></html>')
        self.assertEqual(head.canonicals, ["https://wiki.example.invalid/?a=1&b=2"])
        self.assertEqual(head.meta, {"og:title": '"A" & caf\u00e9'})

    def test_duplicate_and_leaked_metadata_fail(self):
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            Head('<head><meta name="description"><meta name="description"></head>')
        with self.assertRaisesRegex(RuntimeError, "leaked"):
            check_head(Head('<head><meta property="og:url" content="/x"></head>'), None)
        with self.assertRaisesRegex(RuntimeError, "noindex"):
            check_head(Head("<head></head>"), None, noindex=True)

    def test_native_sitemap_url_shapes(self):
        origin = "http://localhost:8089"
        for path in ("/index.php?title=A_%26_B", "/w/A_%26_B"):
            xml = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                   f"<url><loc>{origin}{path}</loc></url></urlset>")
            self.assertEqual(sitemap_locations(xml, "urlset", origin), [origin + path])
        for xml in (
            "<urlset/>",
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://wrong.example.invalid/w/Items</loc></url></urlset>',
        ):
            with self.assertRaises(RuntimeError):
                sitemap_locations(xml, "urlset", origin)


if __name__ == "__main__":
    unittest.main()
