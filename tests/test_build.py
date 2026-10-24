import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build  # noqa: E402

LIST = """\
# Acme Vision 55 projector (model AV55, device acmeone, MediaTek), Android TV 11 (SDK 30),
# build AV.1.2.3 release-keys.
#
# Stock launcher: com.google.android.tvlauncher. Notes that mention com.example.prose (in prose) stay out.
#
# DO NOT DISABLE on Acme (projector hardware):
# com.acme.keystone                    # keystone correction
# com.acme.hdmi

# Telemetry and feedback
com.acme.reporter                      # usage reporter
com.google.android.feedback
# com.acme.updater                     # firmware updater, kept

# Kept on this unit: uncomment if you don't use them
# com.netflix.ninja
com.acme.reporter                      # listed twice upstream by mistake
"""


class ParseList(unittest.TestCase):
    def setUp(self):
        self.d = build.parse_list(LIST)

    def test_header(self):
        self.assertEqual(self.d["name"], "Acme Vision 55 projector")
        self.assertEqual(self.d["tested"], {"os": "Android TV 11", "sdk": 30, "build": "AV.1.2.3"})
        self.assertEqual(self.d["launcher"], "com.google.android.tvlauncher")

    def test_keep_comes_from_a_do_not_disable_heading(self):
        self.assertEqual([p["pkg"] for p in self.d["keep"]], ["com.acme.keystone", "com.acme.hdmi"])
        self.assertEqual(self.d["keep"][0]["note"], "keystone correction")
        self.assertNotIn("optional", self.d["keep"][0])

    def test_groups(self):
        g = self.d["groups"][0]
        self.assertEqual(g["title"], "Telemetry and feedback")
        self.assertEqual(g["packages"], [
            {"pkg": "com.acme.reporter", "note": "usage reporter"},
            {"pkg": "com.google.android.feedback"},
            {"pkg": "com.acme.updater", "note": "firmware updater, kept", "optional": True},
        ])

    def test_commented_under_an_uncomment_heading_is_optional_not_keep(self):
        g = self.d["groups"][1]
        self.assertEqual(g["packages"], [{"pkg": "com.netflix.ninja", "optional": True}])

    def test_prose_never_becomes_a_package(self):
        names = [p["pkg"] for g in self.d["groups"] for p in g["packages"]]
        self.assertNotIn("com.example.prose", names)

    def test_a_name_listed_twice_keeps_its_first_entry(self):
        names = [p["pkg"] for g in self.d["groups"] for p in g["packages"]]
        self.assertEqual(names.count("com.acme.reporter"), 1)

    def test_keep_wins_over_a_list_entry(self):
        d = build.parse_list("# T (SDK 30)\n\n# Do not disable:\n# com.a.b\n\n# Junk\ncom.a.b\ncom.c.d\n")
        self.assertEqual([p["pkg"] for p in d["keep"]], ["com.a.b"])
        self.assertEqual([p["pkg"] for g in d["groups"] for p in g["packages"]], ["com.c.d"])

    def test_build_is_an_id_not_the_next_word(self):
        for prose, want in [
            ("Android TV 14, firmware UKR1.260308 Build UKR1.260308, incremental 3272", "UKR1.260308"),
            ("Same board and firmware build as examples/tcl-c755-google-tv", None),
            ("the build is the same. Android 11 (SDK 30), build RP1A.200720.011", "RP1A.200720.011"),
            ("Android 9 (PPR1.180610.011), build date 20230208, locale zh-CN", None),
        ]:
            d = build.parse_list(f"# {prose}\n\n# Junk\ncom.a.b\n")
            self.assertEqual(d["tested"]["build"], want, prose)

    def test_shell_metacharacters_are_not_package_names(self):
        d = build.parse_list("# T\n\n# Bad\ncom.a.b;reboot\n$(reboot)\ncom.ok.one\n")
        self.assertEqual([p["pkg"] for g in d["groups"] for p in g["packages"]], ["com.ok.one"])
        for bad in ("com.a.b;reboot", "com.a b", "-x.y", "a", "com.a.b\n"):
            self.assertIsNone(build.PACKAGE.fullmatch(bad), bad)


class Index(unittest.TestCase):
    def test_every_device_is_listed_and_unmatched_ones_have_null_match(self):
        index = build.build_index()
        files = sorted(f.name for f in (build.ROOT / "devices").glob("*.json"))
        self.assertEqual([d["file"] for d in index["devices"]], [f"devices/{f}" for f in files])
        by_id = {d["id"]: d for d in index["devices"]}
        for d in index["devices"]:
            matched = (build.ROOT / "match" / f"{d['id']}.json").is_file()
            self.assertEqual(d["match"] is not None, matched, d["id"])
        self.assertIsNone(by_id["xgimi-horizon-s-pro"]["match"])
        self.assertEqual(by_id["philips-55oled708"]["match"]["manufacturer"], ["TPV"])


class RealLists(unittest.TestCase):
    """The committed devices/ files must still parse to the shape the app reads."""

    def test_every_device_file(self):
        import json
        files = sorted((build.ROOT / "devices").glob("*.json"))
        for f in files:
            with self.subTest(file=f.name):
                d = json.loads(f.read_text(encoding="utf-8"))
                self.assertEqual(d["schema"], build.SCHEMA)
                self.assertEqual(d["id"] + ".json", f.name)
                self.assertTrue(d["groups"] or d["keep"])
                for g in d["groups"]:
                    for p in g["packages"]:
                        self.assertRegex(p["pkg"], "^" + build.PACKAGE.pattern + "$")


if __name__ == "__main__":
    unittest.main()
