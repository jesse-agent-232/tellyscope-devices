import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import icons  # noqa: E402

# Smallest valid headers: a 1x1 PNG and a 96x96 lossless WebP.
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8L\x00\x00\x00\x00\x2f" + ((95 | 95 << 14).to_bytes(4, "little"))


def png(width, height):
    return PNG[:16] + width.to_bytes(4, "big") + height.to_bytes(4, "big") + PNG[24:]


def pack(entries, index=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        if index is not None:
            z.writestr("index.json", json.dumps(index))
        for name, data in entries.items():
            z.writestr(name, data)
    return out.getvalue()


def index(icons_):
    return {"schema": 1, "name": "Test", "icons": icons_}


class ImageSize(unittest.TestCase):
    def test_png_and_webp_headers(self):
        self.assertEqual(icons.image_size(png(1280, 720)), (1280, 720))
        self.assertEqual(icons.image_size(WEBP), (96, 96))

    def test_anything_else_is_none(self):
        self.assertIsNone(icons.image_size(b"<svg xmlns='http://www.w3.org/2000/svg'/>"))
        self.assertIsNone(icons.image_size(b""))


class Paths(unittest.TestCase):
    def test_hostile_paths_are_refused(self):
        for path in ["../evil.png", "a/../../evil.png", "/etc/x.png", "a\\b.png", "https://host/x.png",
                     "http://host/x.png", "file:///x.png", "icons//x.png", "./x.png", "x.svg", "x.png.exe", ""]:
            with self.subTest(path=path):
                self.assertIsNotNone(icons.path_problem(path))

    def test_plain_relative_paths_pass(self):
        for path in ["icons/netflix.webp", "repo-abc123/icons/1280x720/kodi.png"]:
            self.assertIsNone(icons.path_problem(path))


class Zips(unittest.TestCase):
    def test_good_pack(self):
        data = pack({"icons/a.webp": WEBP}, index({"com.example.app": "icons/a.webp"}))
        self.assertEqual(icons.check_zip(data), [])

    def test_zip_slip_entry_is_refused(self):
        data = pack({"../../a.webp": WEBP}, index({"com.example.app": "../../a.webp"}))
        self.assertTrue(icons.check_zip(data))

    def test_bad_package_is_refused(self):
        data = pack({"a.webp": WEBP}, index({"com.example.app; reboot": "a.webp"}))
        self.assertTrue(icons.check_zip(data))

    def test_missing_entry_and_missing_index(self):
        self.assertTrue(icons.check_zip(pack({}, index({"com.example.app": "a.webp"}))))
        self.assertEqual(icons.check_zip(pack({"a.webp": WEBP})), ["no index.json at the root"])

    def test_zip_bomb_is_refused(self):
        data = pack({"a.webp": WEBP, "pad.bin": b"\0" * (icons.MAX_UNPACKED + 1)},
                    index({"com.example.app": "a.webp"}))
        self.assertLess(len(data), icons.MAX_DOWNLOAD)
        self.assertEqual(icons.check_zip(data), [f"unpacks to over {icons.MAX_UNPACKED} bytes"])

    def test_too_many_entries(self):
        data = pack({f"{i}.webp": WEBP for i in range(icons.MAX_ENTRIES + 1)})
        self.assertTrue(icons.check_zip(data)[0].endswith(f"over {icons.MAX_ENTRIES}"))

    def test_oversized_image_is_refused(self):
        data = pack({"a.png": png(8000, 8000)}, index({"com.example.app": "a.png"}))
        self.assertEqual(icons.check_zip(data), ["a.png: 8000x8000, over 4096 px"])

    def test_svg_in_disguise_is_refused(self):
        data = pack({"a.png": b"<svg/>"}, index({"com.example.app": "a.png"}))
        self.assertEqual(icons.check_zip(data), ["a.png: not a PNG or WebP"])

    def test_unknown_schema(self):
        data = pack({"a.webp": WEBP}, {"schema": 2, "icons": {"com.example.app": "a.webp"}})
        self.assertEqual(icons.check_zip(data), ["schema is 2, expected 1"])


class Appfilter(unittest.TestCase):
    def test_banner_maps_to_square_glyph_and_first_entry_wins(self):
        text = """
        <item component="ComponentInfo{com.netflix.ninja/com.netflix.ninja.MainActivity}" drawable="netflix_banner"/>
        <item component="ComponentInfo{com.netflix.ninja/other.Activity}" drawable="other_banner"/>
        <item component="ComponentInfo{bad pkg/x.Y}" drawable="x"/>
        """
        self.assertEqual(icons.appfilter(text), {"com.netflix.ninja": "netflix"})


class Committed(unittest.TestCase):
    def test_committed_packs_pass(self):
        self.assertEqual(icons.check_zip((icons.ICONS / "corebuilds.zip").read_bytes()), [])
        minimalist = json.loads((icons.ICONS / "minimalist.json").read_text(encoding="utf-8"))
        self.assertTrue(minimalist["archive"].startswith("https://"))
        self.assertIn(minimalist["commit"], minimalist["archive"])


if __name__ == "__main__":
    unittest.main()
