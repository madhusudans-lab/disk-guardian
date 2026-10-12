"""The refusal list. Every delete and every quarantine move asks `blocked(path)` first."""
import os
from pathlib import Path

from diskguardian import drives, paths
from diskguardian.util import inside, norm

# Folders at the top of every drive that are never touched.
DRIVE_TOP = ("Windows", "Program Files", "Program Files (x86)", "ProgramData", "Users",
             "System Volume Information", "Recovery", "Boot", "EFI", "$Recycle.Bin",
             "Documents and Settings", "$WinREAgent", "Config.Msi", "PerfLogs")
DRIVE_FILES = ("pagefile.sys", "hiberfil.sys", "swapfile.sys", "bootmgr", "BOOTNXT", "DumpStack.log.tmp")
# Inside the system folders above, only the contents of these may be cleaned (and only by rules).
SYSTEM_ALLOWED = (r"Windows\Temp", r"Windows\SoftwareDistribution\Download",
                  r"Windows\SoftwareDistribution\DeliveryOptimization",
                  r"Windows\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache",
                  r"ProgramData\Microsoft\Windows\WER\ReportArchive",
                  r"ProgramData\Microsoft\Windows\WER\ReportQueue",
                  r"Program Files (x86)\Steam\steamapps\shadercache")
PROFILE_SHARED = ("public", "default", "default user", "all users")
SECRETS = (".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker")
DG_DIR = ".DiskGuardian"

_TOP = {x.lower() for x in DRIVE_TOP}
_FILES = {x.lower() for x in DRIVE_FILES}
_ALLOWED = [a.lower() for a in SYSTEM_ALLOWED]


def drive_roots():
    """Normalised roots of every drive we manage (test stand-ins are folders, not letters)."""
    found = {norm(d).rstrip("\\") + "\\" for d in drives.fixed()}
    found.add(norm(paths.system_drive()).rstrip("\\") + "\\")
    return sorted(found)


def blocked(path, automatic=True):
    """A reason string if deleting/moving `path` is forbidden, else None.

    automatic=True is for rule-driven cleaning: personal folders are off-limits inside too.
    automatic=False is for paths the user named: personal content may be quarantined, but never
    a personal folder itself or anything that contains one.
    """
    raw = str(path)
    if raw.startswith("\\\\?\\"):
        raw = raw[4:]
    forms = {os.path.abspath(raw)}
    try:
        forms.add(os.path.realpath(raw))  # resolves 8.3 names and links
    except OSError:
        pass
    for f in forms:
        why = _blocked_one(Path(f), automatic)
        if why:
            return why
    return None


def _blocked_one(p, automatic):
    n = norm(p)
    roots = drive_roots()
    if os.path.splitdrive(n)[1] in ("", "\\", "/") or n.rstrip("\\") + "\\" in roots:
        return "drive root"
    for d in [paths.data_dir()] + [Path(r) / DG_DIR for r in roots]:
        if inside(p, d) or inside(d, p):
            return "Disk Guardian's own data"
    home = paths.home()
    if inside(home, p):
        return "user profile"
    for s in SECRETS:
        if inside(p, home / s):
            return "protected (%s)" % s
    for f in paths.personal_folders():
        if inside(f, p):
            return "contains personal folder (%s)" % f
        if automatic and inside(p, f):
            return "personal folder (%s)" % f
    for root in roots:
        if n.startswith(root):
            why = _system_part(n[len(root):])
            if why:
                return why
    return None


def _system_part(rel):
    """Check a path relative to a drive root against the per-drive system names."""
    parts = rel.split("\\")
    first = parts[0]
    if len(parts) == 1 and first in _FILES:
        return "system file"
    if first not in _TOP:
        return None
    if first == "users":
        if len(parts) <= 2 or parts[1] in PROFILE_SHARED:
            return "Users folder"
        return None  # inside one person's profile; profile/personal checks already ran
    for a in _ALLOWED:
        if rel == a:
            return "system folder (only its contents may be cleaned)"
        if rel.startswith(a + "\\"):
            return None
    return "system folder (%s)" % first
