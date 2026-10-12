import json
import os
from unittest import mock

from diskguardian import ai, cleaner, cli, explain, notify, scan, task, watch
from tests.helpers import FakeMachine


def quiet(*_):
    pass


class CleanScanTests(FakeMachine):
    def test_dry_run_deletes_nothing(self):
        f = self.make(self.local / "CrashDumps" / "app.dmp", 5000)
        res = cleaner.clean("safe", out=quiet)
        self.assertTrue(f.exists())
        self.assertGreaterEqual(res["planned"], 5000)

    def test_yes_deletes_safe_items_but_not_fresh_temp(self):
        dump = self.make(self.local / "CrashDumps" / "app.dmp", 5000)
        old = self.make(self.temp / "olddir" / "x.tmp", 100, age_days=10)
        new = self.make(self.temp / "newdir" / "x.tmp", 100)
        cleaner.clean("safe", yes=True, out=quiet)
        self.assertFalse(dump.exists())
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_cache_tier_on_second_drive(self):
        f = self.make(self.drive_b / "SteamLibrary" / "steamapps" / "shadercache" / "570" / "s.bin")
        cleaner.clean("cache", only={"steam-shader"}, yes=True, out=quiet)
        self.assertFalse(f.exists())
        self.assertTrue((self.drive_b / "SteamLibrary" / "steamapps").exists())

    def test_review_tier_quarantines(self):
        f = self.make(self.profile / "Downloads" / "setup.exe", 100, age_days=40)
        cleaner.clean("review", only={"old-installers"}, yes=True, out=quiet)
        self.assertFalse(f.exists())
        self.assertEqual(len(list((self.data / "quarantine").glob("*/manifest.json"))) +
                         len(list((self.profile / ".DiskGuardian").glob("*"))), 1)

    def test_scan_report_lists_every_drive(self):
        s = scan.run(quick=False, quiet=True)
        self.assertEqual(len(s["drives"]), 2)
        text = scan.report_path().read_text(encoding="utf-8")
        self.assertIn(str(self.drive_a), text)
        self.assertIn(str(self.drive_b), text)
        self.assertTrue(scan.history_path().exists())

    def test_idle_dev_folder_found_on_second_drive(self):
        proj = self.drive_b / "code" / "oldapp"
        self.make(proj / "package.json", 10, age_days=100)
        nm = proj / "node_modules" / "big.bin"
        self.make(nm, 60 * 1024 * 1024, age_days=100)
        s = scan.run(quiet=True)
        cand = scan.dev_candidates(s, {"dev_idle_days": 45})
        self.assertEqual([os.path.basename(c["path"]) for c in cand], ["node_modules"])


class WatchTests(FakeMachine):
    def toasts(self):
        p = self.data / "state" / "toasts.log"
        return p.read_text(encoding="utf-8").splitlines() if p.exists() else []

    def test_low_space_toast_once_per_day(self):
        (self.data / "config.json").write_text(json.dumps({"warn_free_gb": 10 ** 9, "critical_free_gb": 0}))
        with mock.patch("diskguardian.drives.levels", return_value=(10 ** 18, 0)):
            msgs = watch.run()
            self.assertTrue(any("Low space" in m for m in msgs), msgs)
            self.assertEqual(len(self.toasts()), 1)
            watch.run()
        self.assertEqual(len(self.toasts()), 1)

    def test_quiet_when_nothing_happens(self):
        with mock.patch("diskguardian.drives.levels", return_value=(0, 0)):
            self.assertEqual(watch.run(), [])
        self.assertEqual(self.toasts(), [])

    def test_toast_failure_does_not_raise(self):
        os.environ.pop("DISKGUARDIAN_NO_TOAST")
        with mock.patch("subprocess.run", side_effect=OSError("no powershell")):
            self.assertFalse(notify.toast("t", "x"))

    def test_toast_text_never_reaches_the_command_line(self):
        os.environ.pop("DISKGUARDIAN_NO_TOAST")
        evil = "D:\\x\u2019; Remove-Item C:\\important; \u2019 grew"
        with mock.patch("subprocess.run") as run:
            run.return_value.returncode = 0
            notify.toast("Disk Guardian", evil)
        argv, kwargs = run.call_args[0][0], run.call_args[1]
        self.assertNotIn("Remove-Item", " ".join(argv))
        self.assertIn("Remove-Item", kwargs["env"]["DG_TOAST_XML"])

    def test_watch_survives_errors(self):
        with mock.patch("diskguardian.scan.run", side_effect=RuntimeError("boom")):
            self.assertEqual(watch.run(), [])
        self.assertFalse((self.data / "state" / "watch.lock").exists())


class CliTests(FakeMachine):
    def run_cli(self, *argv):
        lines = []
        code = cli.main(list(argv), out=lambda *a: lines.append(" ".join(map(str, a))))
        return code, "\n".join(lines)

    def test_status_lists_drives(self):
        code, text = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn(str(self.drive_a), text)
        self.assertIn(str(self.drive_b), text)

    def test_clean_default_is_dry_run(self):
        f = self.make(self.local / "CrashDumps" / "x.dmp")
        _, text = self.run_cli("clean")
        self.assertIn("Dry run", text)
        self.assertTrue(f.exists())

    def test_config_set_and_unknown(self):
        self.assertEqual(self.run_cli("config", "warn_free_gb", "20")[0], 0)
        self.assertEqual(json.loads((self.data / "config.json").read_text())["warn_free_gb"], 20)
        self.assertEqual(self.run_cli("config", "bogus", "1")[0], 1)

    def test_quarantine_dry_run_shows_refusal(self):
        _, text = self.run_cli("quarantine", str(self.drive_a / "Windows"))
        self.assertIn("REFUSED", text)

    def test_quarantine_and_restore_via_cli(self):
        f = self.make(self.drive_b / "old.iso", 10)
        _, text = self.run_cli("quarantine", str(f), "--yes")
        batch = text.split("batch: ")[1].strip()
        self.assertFalse(f.exists())
        self.assertEqual(self.run_cli("restore", batch)[0], 0)
        self.assertTrue(f.exists())

    def test_explain_builtin_without_ai(self):
        d = self.drive_b / "proj" / "node_modules"
        d.mkdir(parents=True)
        code, text = self.run_cli("explain", str(d))
        self.assertEqual(code, 0)
        self.assertIn("CACHE", text)

    def test_ai_off_by_default(self):
        self.assertFalse(ai.configured())
        self.assertIsNone(ai.ask("hi"))

    def test_advise_writes_file(self):
        scan.run(quick=True, quiet=True)
        self.assertEqual(explain.advise(out=quiet), 0)
        self.assertTrue(list((self.data / "reports").glob("advice-*.md")))

    def test_task_xml_is_well_formed(self):
        import xml.dom.minidom
        x = task.xml("C:\\P\\diskguardian-w.exe", "watch", "PC\\me & you")
        xml.dom.minidom.parseString(x.replace('encoding="UTF-16"', 'encoding="UTF-8"').encode("utf-8"))
        self.assertIn("PT6H", x)
        self.assertIn("&amp;", x)
