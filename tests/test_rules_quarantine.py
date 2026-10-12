import json
import os
from unittest import mock

from diskguardian import quarantine, rules
from tests.helpers import FakeMachine


def rule(**kw):
    base = {"id": "t", "name": "test", "tier": "safe", "paths": [], "why": "w"}
    base.update(kw)
    return base


class RuleTests(FakeMachine):
    def test_bundled_rules_are_well_formed(self):
        data = rules.load()
        ids = [r["id"] for r in data["rules"]]
        self.assertEqual(len(ids), len(set(ids)))
        for r in data["rules"]:
            self.assertTrue({"id", "name", "tier", "why"} <= set(r), r)
            self.assertIn(r["tier"], ("safe", "cache", "review"))

    def test_drive_placeholder_expands_on_every_drive(self):
        got = rules.expand("{drive}SteamLibrary\\x")
        self.assertEqual(got, [str(self.drive_a) + "\\SteamLibrary\\x", str(self.drive_b) + "\\SteamLibrary\\x"])

    def test_unset_variable_is_never_guessed(self):
        self.assertEqual(rules.expand("%DG_NOT_SET_ANYWHERE%\\*"), [])

    def test_downloads_follows_moved_folder(self):
        moved = self.drive_b / "Downloads"
        os.environ["DISKGUARDIAN_KNOWN_DOWNLOADS"] = str(moved)
        self.assertEqual(rules.expand("{downloads}\\*.exe"), [str(moved) + "\\*.exe"])

    def test_min_age_and_exclude(self):
        self.make(self.temp / "old" / "a.tmp", age_days=10)
        self.make(self.temp / "new" / "a.tmp")
        self.make(self.temp / "keep.lock", age_days=10)
        r = rules.evaluate(rule(paths=["%TEMP%\\*"], min_age_days=3, exclude=["*.lock"]), admin=False)
        names = sorted(os.path.basename(i["path"]) for i in r["items"])
        self.assertEqual(names, ["old"])

    def test_rule_on_second_drive_finds_items(self):
        self.make(self.drive_b / "SteamLibrary" / "steamapps" / "shadercache" / "570" / "s.bin", 4096)
        r = rules.evaluate(rule(tier="cache", paths=["{drive}SteamLibrary\\steamapps\\shadercache\\*"]), admin=False)
        self.assertEqual(r["size"], 4096)

    def test_rule_matching_blocked_path_yields_nothing(self):
        (self.drive_b / "Users").mkdir()
        self.make(self.drive_b / "Users" / "f.txt")
        r = rules.evaluate(rule(paths=["{drive}*"]), admin=False)
        paths_ = [os.path.basename(i["path"]) for i in r["items"]]
        self.assertNotIn("Users", paths_)

    def test_size_cap(self):
        self.make(self.temp / "big.bin", 2048)
        with mock.patch("diskguardian.config.load", return_value={"rule_cap_gb": 1e-9}):
            r = rules.evaluate(rule(paths=["%TEMP%\\*"]), admin=False, cfg={"rule_cap_gb": 1e-9})
        self.assertEqual(r["items"], [])
        self.assertIn("cap", r["note"])

    def test_admin_rule_skipped_without_admin(self):
        r = rules.evaluate(rule(paths=["%TEMP%\\*"], requires="admin"), admin=False)
        self.assertEqual(r["note"], "needs administrator")

    def test_user_rules_appended(self):
        (self.data / "user-rules.json").write_text(json.dumps({"rules": [rule(id="mine", paths=["x"])]}))
        self.assertIn("mine", [r["id"] for r in rules.load()["rules"]])


class QuarantineTests(FakeMachine):
    def test_round_trip_on_second_drive(self):
        f = self.make(self.drive_b / "Old" / "setup.exe", 3000)
        batch = quarantine.move([f.parent], "test", out=lambda *_: None)
        self.assertFalse(f.exists())
        self.assertTrue((self.drive_b / ".DiskGuardian" / os.environ["USERNAME"] / "quarantine" / batch).exists())
        self.assertEqual(quarantine.summary()["size"], 3000)
        self.assertTrue(quarantine.restore(batch, out=lambda *_: None))
        self.assertTrue(f.exists())
        self.assertEqual(quarantine.batches(), [])

    def test_restore_skips_when_target_exists(self):
        f = self.make(self.drive_a / "a.zip")
        batch = quarantine.move([f], "t", out=lambda *_: None)
        self.make(f, 5)  # something new took its place
        msgs = []
        quarantine.restore(batch, out=msgs.append)
        self.assertTrue(any("SKIP" in m for m in msgs))
        self.assertEqual(f.stat().st_size, 5)

    def test_purge_by_age(self):
        f = self.make(self.drive_a / "a.zip", 100)
        batch = quarantine.move([f], "t", out=lambda *_: None)
        self.assertEqual(quarantine.purge(days=7), 0)
        self.assertEqual(quarantine.purge(days=0), 100)
        self.assertEqual(quarantine.batches(), [])
        self.assertIsNotNone(batch)

    def test_blocked_path_not_moved(self):
        d = self.drive_a / "Windows"
        self.make(d / "x.dll")
        msgs = []
        self.assertIsNone(quarantine.move([d], "t", out=msgs.append))
        self.assertTrue((d / "x.dll").exists())

    def _plant(self, batch_dir, items):
        batch_dir.mkdir(parents=True, exist_ok=True)
        (batch_dir / "manifest.json").write_text(json.dumps(
            {"batch": batch_dir.name, "created": "2000-01-01T00:00:00", "label": "x", "items": items}))

    def test_planted_manifest_cannot_delete_outside_its_batch(self):
        victim = self.make(self.drive_a / "Photos" / "wedding.jpg", 10)
        q = self.data / "quarantine" / "20000101-000000-evil"
        self._plant(q, [{"orig": str(victim), "stored": str(victim), "size": 10}])
        self.assertEqual(quarantine.batches(), [])
        quarantine.purge(days=0)
        self.assertTrue(victim.exists())

    def test_junctioned_batch_is_ignored(self):
        from tests.helpers import junction
        victim = self.make(self.drive_a / "Photos" / "0" / "wedding.jpg", 10)
        q = self.data / "quarantine"
        q.mkdir(parents=True)
        link = q / "20000101-000000-evil"
        if not junction(link, self.drive_a / "Photos"):
            self.skipTest("cannot create junction here")
        (self.drive_a / "Photos" / "manifest.json").write_text(json.dumps(
            {"batch": "evil", "created": "2000-01-01T00:00:00", "label": "x",
             "items": [{"orig": str(self.drive_b / "x"), "stored": str(link / "0" / "wedding.jpg"), "size": 10}]}))
        quarantine.purge(days=0)
        self.assertTrue(victim.exists())

    def test_restore_refuses_unsafe_target(self):
        q = self.data / "quarantine" / "20000101-000000-evil"
        stored = self.make(q / "0" / "evil.exe", 10)
        self._plant(q, [{"orig": str(self.drive_a / "Windows" / "evil.exe"), "stored": str(stored), "size": 10}])
        self.assertFalse(quarantine.restore("evil", out=lambda *_: None))
        self.assertFalse((self.drive_a / "Windows" / "evil.exe").exists())

    def test_shared_drive_folder_is_private(self):
        f = self.make(self.drive_b / "a.iso")
        quarantine.move([f], "t", out=lambda *_: None)
        import subprocess
        acl = subprocess.run(["icacls", str(self.drive_b / ".DiskGuardian" / os.environ["USERNAME"])],
                             capture_output=True, text=True).stdout
        self.assertNotIn("Users:", acl)
        self.assertNotIn("Everyone", acl)

    def test_no_quarantine_folder_possible_leaves_file(self):
        f = self.make(self.drive_b / "a.iso")
        msgs = []
        with mock.patch("diskguardian.quarantine.root_for", return_value=None):
            self.assertIsNone(quarantine.move([f], "t", out=msgs.append))
        self.assertTrue(f.exists())
        self.assertIn("nothing was changed", msgs[0])
