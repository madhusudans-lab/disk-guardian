"""A fake machine under a temp dir: profile, data dir and two stand-in "drives".
No test touches the real profile, the real drives or the real Disk Guardian data."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

ENV_KEYS = ("DISKGUARDIAN_HOME", "DISKGUARDIAN_PROFILE", "DISKGUARDIAN_DRIVES", "DISKGUARDIAN_NO_TOAST",
            "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "DISKGUARDIAN_KNOWN_DOCUMENTS",
            "DISKGUARDIAN_KNOWN_DOWNLOADS")


class FakeMachine(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        self.tmp = Path(tempfile.mkdtemp(prefix="dg-test-"))
        self.profile = self.tmp / "profile"
        self.data = self.tmp / "data"
        self.drive_a = self.tmp / "driveA"
        self.drive_b = self.tmp / "driveB"
        for d in (self.profile, self.data, self.drive_a, self.drive_b):
            d.mkdir()
        self.local = self.profile / "AppData" / "Local"
        self.roaming = self.profile / "AppData" / "Roaming"
        self.temp = self.local / "Temp"
        for d in (self.local, self.roaming, self.temp, self.profile / "Documents", self.profile / "Downloads"):
            d.mkdir(parents=True, exist_ok=True)
        os.environ.update({
            "DISKGUARDIAN_HOME": str(self.data),
            "DISKGUARDIAN_PROFILE": str(self.profile),
            "DISKGUARDIAN_DRIVES": "%s;%s" % (self.drive_a, self.drive_b),
            "DISKGUARDIAN_NO_TOAST": "1",
            "TEMP": str(self.temp), "TMP": str(self.temp),
            "LOCALAPPDATA": str(self.local), "APPDATA": str(self.roaming),
            "USERPROFILE": str(self.profile),
        })
        for k in ("DISKGUARDIAN_KNOWN_DOCUMENTS", "DISKGUARDIAN_KNOWN_DOWNLOADS"):
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, path, size=1024, age_days=0):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        if age_days:
            t = time.time() - age_days * 86400
            os.utime(path, (t, t))
        return path


def junction(link, target):
    """Directory junction (no admin needed). Returns False if it could not be made."""
    import subprocess
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    return r.returncode == 0
