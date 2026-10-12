"""Small helpers shared by every module. Filesystem walks never follow links or junctions."""
import ctypes
import datetime as dt
import json
import os
import shutil
import stat
from pathlib import Path

from diskguardian import paths

GB, MB = 1024 ** 3, 1024 ** 2
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def gb(n):
    return "%.2f GB" % (n / GB) if n >= 0.1 * GB else "%.0f MB" % (n / MB)


def now():
    return dt.datetime.now()


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def log(msg):
    try:
        d = paths.logs_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / ("%s.log" % now().strftime("%Y%m"))).open("a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def norm(p):
    s = str(p)
    if s.startswith("\\\\?\\"):
        s = s[4:]
    return os.path.normcase(os.path.abspath(s))


def inside(child, parent):
    c, p = norm(child), norm(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def entries(d):
    """[(DirEntry, stat)] of a folder without links/junctions; [] if unreadable."""
    out = []
    try:
        with os.scandir(d) as it:
            for e in it:
                try:
                    s = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not getattr(s, "st_file_attributes", 0) & REPARSE and not stat.S_ISLNK(s.st_mode):
                    out.append((e, s))
    except OSError:
        pass
    return out


def is_link(st):
    return bool(getattr(st, "st_file_attributes", 0) & REPARSE) or stat.S_ISLNK(st.st_mode)


def walk(path):
    """(bytes, newest_mtime, file_count) of a file or folder. Never follows links/junctions."""
    total, newest, count = 0, 0.0, 0
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return 0, 0.0, 0
    if is_link(st):
        return 0, st.st_mtime, 0
    if not stat.S_ISDIR(st.st_mode):
        return st.st_size, st.st_mtime, 1
    stack = [str(path)]
    while stack:
        for e, s in entries(stack.pop()):
            if stat.S_ISDIR(s.st_mode):
                stack.append(e.path)
            else:
                total += s.st_size
                count += 1
                newest = max(newest, s.st_mtime)
    return total, newest or st.st_mtime, count


def remove(path):
    """Delete a file/folder. Links are unlinked, never followed. Returns True if gone."""
    p = str(path)

    def retry(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    try:
        st = os.stat(p, follow_symlinks=False)
    except OSError:
        return True
    try:
        if is_link(st):
            # A directory junction/symlink is removed with rmdir; this never touches the target.
            try:
                os.rmdir(p)
            except OSError:
                os.unlink(p)
        elif stat.S_ISDIR(st.st_mode):
            _rmtree(p, retry)
        else:
            try:
                os.remove(p)
            except PermissionError:
                os.chmod(p, stat.S_IWRITE)
                os.remove(p)
    except OSError:
        pass
    return not os.path.lexists(p)


def _rmtree(p, retry):
    try:
        shutil.rmtree(p, onexc=retry)
    except TypeError:  # Python < 3.12
        shutil.rmtree(p, onerror=lambda f, t, e: retry(f, t, e))
