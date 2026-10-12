"""Local fixed drives (C:, D:, ...). USB sticks, network shares, CD and RAM drives are skipped.

DISKGUARDIAN_DRIVES="X:\\;Y:\\" (or temp folders, for tests) overrides detection.
"""
import ctypes
import os
import shutil
import string

from diskguardian import config, paths
from diskguardian.util import GB

DRIVE_FIXED = 3


def _detect():
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        get_type = ctypes.windll.kernel32.GetDriveTypeW
    except (AttributeError, OSError):
        return [paths.system_drive()]
    found = []
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            root = letter + ":\\"
            if get_type(ctypes.c_wchar_p(root)) == DRIVE_FIXED:
                found.append(root)
    return found or [paths.system_drive()]


def _canon(d):
    d = str(d).strip()
    if len(d) == 2 and d[1] == ":":
        d += "\\"
    return d


def fixed(cfg=None):
    env = os.environ.get("DISKGUARDIAN_DRIVES")
    if env:
        return [_canon(d) for d in env.split(";") if d.strip()]
    cfg = cfg or config.load()
    chosen = cfg.get("drives", "auto")
    found = _detect() if chosen == "auto" else [_canon(d) for d in chosen]
    skip = {_canon(d).upper() for d in cfg.get("exclude_drives", [])}
    return [d for d in found if d.upper() not in skip]


def usage(d):
    try:
        u = shutil.disk_usage(d)
        return {"drive": d, "total": u.total, "used": u.used, "free": u.free}
    except OSError:
        return {"drive": d, "total": 0, "used": 0, "free": 0}


def levels(total, cfg):
    """(warn_bytes, critical_bytes): fixed GB levels, scaled down for small drives."""
    return (min(cfg["warn_free_gb"] * GB, 0.10 * total),
            min(cfg["critical_free_gb"] * GB, 0.05 * total))


def level_of(u, cfg):
    warn, crit = levels(u["total"], cfg)
    if u["total"] and u["free"] < crit:
        return "critical"
    if u["total"] and u["free"] < warn:
        return "warn"
    return None


def label(d):
    """'C:' for a real drive, the folder itself for a test stand-in."""
    d = str(d)
    return d[:2].upper() if len(d) <= 3 else d
