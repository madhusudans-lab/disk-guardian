import json
import os

from diskguardian import config, drives, paths
from diskguardian.util import GB, gb, remove, walk
from tests.helpers import FakeMachine, junction


class ConfigTests(FakeMachine):
    def test_defaults_written_on_first_load(self):
        cfg = config.load()
        self.assertEqual(cfg["quarantine_days"], 7)
        self.assertTrue((self.data / "config.json").exists())

    def test_user_value_overrides_default_and_nested_merge(self):
        (self.data / "config.json").write_text(json.dumps({"warn_free_gb": 40, "ai": {"model": "m"}}))
        cfg = config.load()
        self.assertEqual(cfg["warn_free_gb"], 40)
        self.assertEqual(cfg["ai"]["model"], "m")
        self.assertEqual(cfg["ai"]["base_url"], "")

    def test_set_value_parses_and_rejects_unknown(self):
        config.set_value("warn_free_gb", "20")
        config.set_value("ai.base_url", "http://localhost:11434/v1")
        cfg = config.load()
        self.assertEqual(cfg["warn_free_gb"], 20)
        self.assertEqual(cfg["ai"]["base_url"], "http://localhost:11434/v1")
        with self.assertRaises(KeyError):
            config.set_value("nope", "1")


class UtilTests(FakeMachine):
    def test_gb_format(self):
        self.assertEqual(gb(5 * GB), "5.00 GB")
        self.assertEqual(gb(10 * 1024 * 1024), "10 MB")

    def test_walk_counts_bytes(self):
        self.make(self.drive_a / "x" / "a.bin", 1000)
        self.make(self.drive_a / "x" / "sub" / "b.bin", 500)
        self.assertEqual(walk(self.drive_a / "x")[0], 1500)

    def test_remove_junction_keeps_target(self):
        docs = self.profile / "Documents"
        self.make(docs / "precious.txt")
        link = self.temp / "link"
        if not junction(link, docs):
            self.skipTest("cannot create junction here")
        self.assertEqual(walk(link)[0], 0, "walk must not follow junctions")
        self.assertTrue(remove(link))
        self.assertTrue((docs / "precious.txt").exists())


class DriveTests(FakeMachine):
    def test_env_override(self):
        self.assertEqual(drives.fixed(), [str(self.drive_a), str(self.drive_b)])

    def test_real_detection_includes_system_drive(self):
        os.environ.pop("DISKGUARDIAN_DRIVES")
        self.assertIn(paths.system_drive().upper(), [d.upper() for d in drives.fixed()])

    def test_levels_scale_for_small_drives(self):
        cfg = config.load()
        warn, crit = drives.levels(64 * GB, cfg)
        self.assertAlmostEqual(warn / GB, 6.4)
        self.assertAlmostEqual(crit / GB, 3.2)
        warn, crit = drives.levels(1000 * GB, cfg)
        self.assertEqual((warn / GB, crit / GB), (15, 8))

    def test_level_of(self):
        cfg = config.load()
        self.assertEqual(drives.level_of({"total": 500 * GB, "free": 5 * GB}, cfg), "critical")
        self.assertEqual(drives.level_of({"total": 500 * GB, "free": 10 * GB}, cfg), "warn")
        self.assertIsNone(drives.level_of({"total": 500 * GB, "free": 100 * GB}, cfg))
