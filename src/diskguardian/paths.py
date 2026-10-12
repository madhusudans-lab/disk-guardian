"""Where things live. Every path can be redirected by environment variables so tests never
touch a real profile:

  DISKGUARDIAN_HOME            data dir (config, state, reports, logs, system-drive quarantine)
  DISKGUARDIAN_PROFILE         stands in for the user's home folder
  DISKGUARDIAN_KNOWN_<NAME>    stands in for a known folder, e.g. DISKGUARDIAN_KNOWN_DOCUMENTS
"""
import ctypes
import os
import sys
import uuid
from pathlib import Path

# Windows known-folder ids (KNOWNFOLDERID).
KNOWN_FOLDERS = {
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
}
PERSONAL_NAMES = ("documents", "desktop", "pictures", "videos", "music")


def data_dir():
    env = os.environ.get("DISKGUARDIAN_HOME")
    if env:
        return Path(env)
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "DiskGuardian"


def state_dir():
    return data_dir() / "state"


def reports_dir():
    return data_dir() / "reports"


def logs_dir():
    return data_dir() / "logs"


def home():
    return Path(os.environ.get("DISKGUARDIAN_PROFILE") or Path.home())


def system_drive():
    return os.environ.get("SystemDrive", "C:").rstrip("\\/") + "\\"


def _shell_known_folder(guid):
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    u = uuid.UUID(guid)
    g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    out = ctypes.c_wchar_p()
    shell32, ole32 = ctypes.windll.shell32, ctypes.windll.ole32
    if shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
        return None
    try:
        return out.value
    finally:
        ole32.CoTaskMemFree(out)


def known_folder(name):
    """Real location of a user folder (it may have been moved to another drive)."""
    env = os.environ.get("DISKGUARDIAN_KNOWN_" + name.upper())
    if env:
        return Path(env)
    if not os.environ.get("DISKGUARDIAN_PROFILE") and sys.platform == "win32":
        try:
            p = _shell_known_folder(KNOWN_FOLDERS[name])
            if p:
                return Path(p)
        except (OSError, AttributeError, KeyError):
            pass
    return home() / name.capitalize()


def personal_folders():
    """User data folders: automatic rules never reach inside, nothing may delete them."""
    # Both where Windows says the folder is (it may be redirected to OneDrive or another drive)
    # and the default spot in the profile, which still holds personal files after a redirect.
    found = [known_folder(n) for n in PERSONAL_NAMES]
    found += [home() / n.capitalize() for n in PERSONAL_NAMES]
    found += [home() / n for n in ("OneDrive", "Dropbox", "Google Drive", "iCloudDrive")]
    od = os.environ.get("OneDrive")
    if od and not os.environ.get("DISKGUARDIAN_PROFILE"):
        found.append(Path(od))
    return found


def resource(name):
    """A file bundled with the package (works from source and inside PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    bundled = base / "diskguardian" / name
    return bundled if bundled.exists() else Path(__file__).resolve().parent / name
