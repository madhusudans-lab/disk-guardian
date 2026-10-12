import os

from diskguardian.safety import blocked
from tests.helpers import FakeMachine


class SafetyTests(FakeMachine):
    def assertBlocked(self, p, automatic=True):
        self.assertIsNotNone(blocked(p, automatic), "should be refused: %s" % p)

    def assertAllowed(self, p, automatic=True):
        self.assertIsNone(blocked(p, automatic), "should be allowed: %s" % p)

    def test_real_drive_roots(self):
        self.assertBlocked("C:\\")
        self.assertBlocked("D:\\")

    def test_stand_in_drive_root(self):
        self.assertBlocked(self.drive_a)

    def test_system_folders_on_every_drive(self):
        for d in (self.drive_a, self.drive_b):
            for name in ("Windows", "Program Files", "ProgramData", "System Volume Information",
                         "$Recycle.Bin", "Recovery", "Users"):
                self.assertBlocked(d / name)
                self.assertBlocked(d / name / "x")
            self.assertBlocked(d / "pagefile.sys")
            self.assertBlocked(d / "Users" / "bob")
            self.assertBlocked(d / "Users" / "Public" / "x")

    def test_real_system_folders(self):
        self.assertBlocked(r"C:\Windows\System32")
        self.assertBlocked(r"C:\Program Files\App")
        self.assertBlocked(r"C:\Windows\Temp")  # the folder itself
        self.assertAllowed(r"C:\Windows\Temp\old.tmp")
        self.assertAllowed(r"C:\Windows\SoftwareDistribution\Download\abc")

    def test_steam_shadercache_allowed_inside_program_files(self):
        self.assertAllowed(self.drive_b / "Program Files (x86)" / "Steam" / "steamapps" / "shadercache" / "123")
        self.assertBlocked(self.drive_b / "Program Files (x86)" / "Steam" / "steamapps" / "common")

    def test_ordinary_folder_on_second_drive_allowed(self):
        self.assertAllowed(self.drive_b / "Games" / "steamapps" / "shadercache" / "x")

    def test_own_data_and_quarantine(self):
        self.assertBlocked(self.data)
        self.assertBlocked(self.data / "quarantine" / "x")
        self.assertBlocked(self.drive_b / ".DiskGuardian" / "quarantine" / "x")

    def test_profile_and_secrets(self):
        self.assertBlocked(self.profile)
        self.assertBlocked(self.profile.parent)
        self.assertBlocked(self.profile / ".ssh" / "id_ed25519")
        self.assertAllowed(self.temp / "junk.tmp")

    def test_personal_folders(self):
        docs = self.profile / "Documents"
        self.assertBlocked(docs, automatic=False)
        self.assertBlocked(docs / "cv.docx", automatic=True)
        self.assertAllowed(docs / "cv.docx", automatic=False)

    def test_moved_documents_still_protected(self):
        moved = self.drive_b / "MyDocs"
        moved.mkdir()
        os.environ["DISKGUARDIAN_KNOWN_DOCUMENTS"] = str(moved)
        self.assertBlocked(moved / "thesis.docx", automatic=True)
        self.assertBlocked(moved, automatic=False)
        # the default location keeps its protection after a redirect
        self.assertBlocked(self.profile / "Documents", automatic=False)
        self.assertBlocked(self.profile / "Documents" / "old.docx", automatic=True)

    def test_long_path_prefix(self):
        self.assertBlocked("\\\\?\\C:\\Windows\\System32")
