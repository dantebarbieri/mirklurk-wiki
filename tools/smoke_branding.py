"""Site logo, favicon and home-screen icon checks for the disposable wiki, never a live publication path."""

import hashlib
from html.parser import HTMLParser
import struct
import urllib.parse
import urllib.request


BRANDING_IMAGES = {
    "MW_LOGO_URL": ("Synthetic-logo-128.png", 128, bytes((41, 73, 19, 255))),
    "MW_LOGO_ICON_URL": ("Synthetic-logo-256.png", 256, bytes((42, 73, 19, 255))),
    "MW_FAVICON_URL": ("Synthetic-favicon.png", 184, bytes((43, 73, 19, 255))),
    "MW_APPLE_TOUCH_ICON_URL": ("Synthetic-apple-touch-icon.png", 180, bytes((44, 73, 19, 255))),
}
ICON_LINKS = (("icon", "MW_FAVICON_URL"), ("apple-touch-icon", "MW_APPLE_TOUCH_ICON_URL"))


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.images, self.links = [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.images.append(dict(attrs))
        elif tag == "link":
            self.links.append(dict(attrs))


def branding_paths():
    paths = {}
    for variable, (filename, _, _) in BRANDING_IMAGES.items():
        # MediaWiki's default hashed image directories use the filename's MD5.
        digest = hashlib.md5(filename.encode(), usedforsecurity=False).hexdigest()
        paths[variable] = f"/images/{digest[0]}/{digest[:2]}/{filename}"
    return paths


def smoke_branding(api, base, paths, image_hashes, open_media=urllib.request.urlopen):
    general = api({"action": "query", "meta": "siteinfo", "siprop": "general"})["query"]["general"]
    if urllib.parse.urljoin(base, general.get("logo", "")) != base + paths["MW_LOGO_URL"]:
        raise RuntimeError("The legacy logo does not use its configured smaller raster.")
    with open_media(base + "/index.php?title=Main_Page&useskin=vector-2022", timeout=30) as response:
        rendered = Tags(response.read().decode("utf-8"))
    logos = [row for row in rendered.images if "mw-logo-icon" in row.get("class", "").split()]
    if (len(logos) != 1 or urllib.parse.urljoin(base, logos[0].get("src", "")) != base + paths["MW_LOGO_ICON_URL"]
            or logos[0].get("width") != "50" or logos[0].get("height") != "50"):
        raise RuntimeError("Vector 2022 did not render the configured logo in its 50px header slot.")
    for rel, variable in ICON_LINKS:
        hrefs = [urllib.parse.urljoin(base, row.get("href", "")) for row in rendered.links
                 if rel in row.get("rel", "").split()]
        if hrefs != [base + paths[variable]]:
            raise RuntimeError(f"The HTML {rel} link does not use the configured PNG.")
    for variable, (filename, size, _) in BRANDING_IMAGES.items():
        with open_media(base + paths[variable], timeout=30) as response:
            if response.status != 200 or response.headers.get_content_type() != "image/png":
                raise RuntimeError("A branding URL is not anonymously readable as PNG.")
            body = response.read()
        if (len(body) < 24 or body[:8] != b"\x89PNG\r\n\x1a\n" or body[12:16] != b"IHDR"
                or struct.unpack(">II", body[16:24]) != (size, size)
                or hashlib.sha256(body).hexdigest() != image_hashes[filename]):
            raise RuntimeError("A branding PNG differs from its configured dimensions or imported bytes.")
    print("Branding passed: Vector 2022 logo, legacy logo, favicon and apple-touch-icon links "
          "and anonymous exact PNG reads.")
