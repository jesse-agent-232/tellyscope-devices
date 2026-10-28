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

    def test_an_active_entry_wins_over_a_commented_copy_above_it(self):
        d = build.parse_list("# T (SDK 30)\n\n# Removed before\n# com.a.b\n# com.c.d\n\n# Junk\ncom.a.b\n")
        self.assertEqual(d["groups"], [
            {"title": "Removed before", "packages": [{"pkg": "com.c.d", "optional": True}]},
            {"title": "Junk", "packages": [{"pkg": "com.a.b"}]},
        ])

    def test_two_commented_copies_keep_the_first(self):
        d = build.parse_list("# T (SDK 30)\n\n# First\n# com.a.b  # one\n\n# Second\n# com.a.b  # two\n")
        self.assertEqual(d["groups"], [{"title": "First", "packages": [{"pkg": "com.a.b", "note": "one", "optional": True}]}])

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


class KeepCommit(unittest.TestCase):
    def device(self, commit, packages=("com.acme.reporter",)):
        return {"schema": 1, "id": "acme-55", **build.parse_list("\n".join(packages)),
                "source": {"repo": build.UPSTREAM, "path": "examples/acme-55/debloat.txt", "commit": commit}}

    def test_an_unchanged_list_keeps_its_old_commit(self):
        self.assertEqual(build.keep_commit(self.device("new"), self.device("old"))["source"]["commit"], "old")

    def test_a_changed_or_new_list_takes_the_new_commit(self):
        changed = self.device("new", ("com.acme.reporter", "com.acme.updater"))
        self.assertEqual(build.keep_commit(changed, self.device("old"))["source"]["commit"], "new")
        self.assertEqual(build.keep_commit(self.device("new"), None)["source"]["commit"], "new")


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


class Lists(unittest.TestCase):
    """lists/ and logos/: the app drops an entry it can't read, so check has to catch it first."""

    def setUp(self):
        import shutil
        import tempfile
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        for d in ("lists", "logos"):
            shutil.copytree(build.ROOT / d, self.root / d)
        self.real, build.ROOT = build.ROOT, self.root
        self.addCleanup(setattr, build, "ROOT", self.real)

    def edit(self, name, change):
        import json
        path = self.root / "lists" / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_the_committed_lists_and_logos_pass(self):
        self.assertEqual(build.check_lists(), [])

    def test_the_index_lists_every_list_and_logo(self):
        build.ROOT = self.real
        index = build.build_index()
        self.assertEqual(sorted(index["lists"]), sorted(build.LISTS))
        self.assertEqual(sorted(index["logos"]), sorted(f.stem for f in (self.real / "logos").glob("*.png")))

    def test_a_bad_service_is_caught(self):
        def bad(d):
            d["groups"][0]["services"][0].update({"color": "red", "packages": ["com.netflix.ninja; reboot"]})
        self.edit("streaming", bad)
        errors = "\n".join(build.check_lists())
        self.assertIn("'color' must be #RRGGBB", errors)
        self.assertIn("not a package name", errors)

    def test_a_missing_or_unused_logo_is_caught(self):
        self.edit("streaming", lambda d: d["groups"][0]["services"][0].update({"logo": "nosuchlogo"}))
        errors = "\n".join(build.check_lists())
        self.assertIn("logos/nosuchlogo.png is missing", errors)
        self.assertIn("no service in lists/streaming.json uses it", errors)

    def test_a_launcher_cannot_ask_for_an_accessibility_service(self):
        self.edit("launchers", lambda d: d["launchers"][0].update({"accessibility": True}))
        self.assertIn("unknown keys ['accessibility']", "\n".join(build.check_lists()))

    def test_an_oversized_logo_is_caught(self):
        big = build.PNG + b"\x00\x00\x00\x0dIHDR" + (1000).to_bytes(4, "big") + (40).to_bytes(4, "big")
        (self.root / "logos" / "netflix.png").write_bytes(big)
        self.assertIn("1000x40 is over 288x120", "\n".join(build.check_lists()))


if __name__ == "__main__":
    unittest.main()
