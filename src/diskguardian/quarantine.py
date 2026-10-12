"""Restorable quarantine. One per drive, so a move is an instant rename and never a copy:
system drive -> <data dir>\\quarantine, any other drive X: -> hidden X:\\.DiskGuardian\\quarantine.
Moving files into quarantine frees no space until they are purged.
"""
import ctypes
import datetime as dt
import os
import subprocess
from pathlib import Path

from diskguardian import drives, paths, safety
from diskguardian.util import gb, inside, is_link, load_json, log, norm, now, remove, save_json, walk


def _drive_of(p):
    """The managed drive root that holds `p` (longest match, so test stand-ins work)."""
    n = norm(p)
    best = None
    for r in safety.drive_roots():
        if n.startswith(r) and (best is None or len(r) > len(best)):
            best = r
    return best


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_SID = []


def _user_sid():
    if not _SID:
        try:
            r = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True,
                               timeout=30, creationflags=_NO_WINDOW)
            _SID.append(r.stdout.strip().split(",")[-1].strip('"') if r.returncode == 0 else "")
        except (OSError, subprocess.SubprocessError):
            _SID.append("")
    return _SID[0]


def _owner_sid(path):
    """String SID of the owner of `path`, or None."""
    try:
        advapi, kernel = ctypes.windll.advapi32, ctypes.windll.kernel32
    except AttributeError:
        return None
    owner, sd, text = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_wchar_p()
    if advapi.GetNamedSecurityInfoW(ctypes.c_wchar_p(str(path)), 1, 1, ctypes.byref(owner),
                                     None, None, None, ctypes.byref(sd)) != 0:
        return None
    try:
        if not advapi.ConvertSidToStringSidW(owner, ctypes.byref(text)):
            return None
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.LocalFree(sd)


def _no_links(path, stop):
    """True if no folder from `stop` down to `path` is a junction/symlink."""
    p, stop = Path(path), Path(stop)
    chain = [p] + [x for x in p.parents if inside(x, stop)]
    for x in chain:
        try:
            if is_link(os.stat(x, follow_symlinks=False)):
                return False
        except OSError:
            continue
    return True


def _private_ok(user_dir):
    """A per-user quarantine on a shared drive must be ours, real, and not a link."""
    if not _no_links(user_dir, user_dir.parent.parent):
        return False
    me = _user_sid()
    return bool(me) and _owner_sid(user_dir) == me


def _lock(user_dir):
    """Only this user and SYSTEM may open the folder (other local accounts cannot plant files)."""
    me = _user_sid()
    if not me:
        return False
    r = subprocess.run(["icacls", str(user_dir), "/inheritance:r", "/grant:r",
                        "*%s:(OI)(CI)F" % me, "*S-1-5-18:(OI)(CI)F"],
                       capture_output=True, timeout=60, creationflags=_NO_WINDOW)
    return r.returncode == 0


def _shared_root(d):
    return Path(d) / safety.DG_DIR / (os.environ.get("USERNAME") or "user")


def root_for(path):
    """Quarantine folder on the same drive as `path`, or None if one cannot be made there safely."""
    d = _drive_of(path)
    if d is None:
        return None
    if d == norm(paths.system_drive()):
        q = paths.data_dir() / "quarantine"  # inside the private profile
        try:
            q.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return q
    user_dir = _shared_root(d)
    try:
        top_new = not user_dir.parent.exists()
        if not user_dir.exists():
            user_dir.mkdir(parents=True)
            if not _lock(user_dir):
                return None
        if top_new:
            subprocess.run(["attrib", "+h", str(user_dir.parent)], capture_output=True, timeout=30,
                           creationflags=_NO_WINDOW)
        if not _private_ok(user_dir):
            return None
        q = user_dir / "quarantine"
        q.mkdir(exist_ok=True)
        return q if _no_links(q, user_dir) else None
    except (OSError, subprocess.SubprocessError):
        return None


def all_roots():
    found = [paths.data_dir() / "quarantine"]
    for r in safety.drive_roots():
        user_dir = _shared_root(r)
        if (user_dir / "quarantine").exists() and _private_ok(user_dir):
            found.append(user_dir / "quarantine")
    return found


def _trusted(item, batch_dir):
    """A manifest entry is used only if its stored copy really lives inside its own batch folder
    (no links on the way) and its original location passes the normal safety check."""
    stored = item.get("stored", "")
    orig = item.get("orig", "")
    if not stored or not orig or not inside(stored, batch_dir) or not _no_links(stored, batch_dir):
        return False
    try:
        if not inside(os.path.realpath(stored), os.path.realpath(batch_dir)):
            return False
    except OSError:
        return False
    return safety.blocked(orig, automatic=False) is None


def _batch_id(label):
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:40]
    return "%s-%s" % (now().strftime("%Y%m%d-%H%M%S"), safe)


def move(paths_, label, automatic=False, out=print):
    """Move items into quarantine. Returns the batch id, or None if nothing moved."""
    batch = _batch_id(label)
    manifests = {}  # quarantine root -> manifest
    for i, p in enumerate(paths_):
        p = os.path.abspath(str(p))
        why = safety.blocked(p, automatic=automatic)
        if why:
            out("  SKIP %s: %s" % (p, why))
            continue
        if not os.path.lexists(p):
            continue
        q = root_for(p)
        if q is None:
            out("  SKIP %s: no quarantine folder could be made on its drive (nothing was changed)" % p)
            continue
        size = walk(p)[0]
        bdir = q / batch
        dest = bdir / str(i) / os.path.basename(p.rstrip("\\/"))
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(p, dest)  # same volume: atomic, never a half-done copy
        except OSError as e:
            out("  FAIL %s: %s (in use? close the program and retry)" % (p, e.strerror or e))
            try:
                dest.parent.rmdir()
                bdir.rmdir()
            except OSError:
                pass
            continue
        m = manifests.setdefault(str(q), {"batch": batch, "created": now().isoformat(timespec="seconds"),
                                         "label": label, "items": []})
        m["items"].append({"orig": p, "stored": str(dest), "size": size})
        save_json(bdir / "manifest.json", m)
        out("  quarantined %s (%s)" % (p, gb(size)))
    if not manifests:
        return None
    n = sum(len(m["items"]) for m in manifests.values())
    log("quarantine %s: %d items" % (batch, n))
    return batch


def batches():
    """Every batch on every drive. A batch spread over drives shows as one entry per drive."""
    out = []
    for root in all_roots():
        for m in sorted(root.glob("*/manifest.json")):
            data = load_json(m, None)
            if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not _no_links(m.parent, root):
                continue
            items = [it for it in data["items"] if isinstance(it, dict) and _trusted(it, m.parent)]
            if len(items) != len(data["items"]):
                log("quarantine %s: ignored %d untrusted manifest entries" % (m.parent, len(data["items"]) - len(items)))
            data["items"] = items
            if items:
                data["dir"] = str(m.parent)
                data["size"] = sum(x["size"] for x in data["items"])
                out.append(data)
    out.sort(key=lambda b: b["batch"])
    return out


def summary():
    b = batches()
    return {"count": len({x["batch"] for x in b}), "size": sum(x["size"] for x in b)}


def _age_days(b):
    try:
        return (now() - dt.datetime.fromisoformat(b["created"])).days
    except (KeyError, ValueError):
        return 0


def restore(batch, out=print):
    found = [x for x in batches() if batch == x["batch"] or batch in x["batch"]]
    ids = sorted({x["batch"] for x in found})
    if not ids:
        out("No batch matches %r (see: diskguardian qlist)" % batch)
        return False
    if len(ids) > 1:
        out("Several batches match %r: %s" % (batch, ", ".join(ids)))
        return False
    for x in found:
        for it in x["items"]:
            if os.path.lexists(it["orig"]):
                out("  SKIP (something exists there now): %s" % it["orig"])
                continue
            try:
                os.makedirs(os.path.dirname(it["orig"]), exist_ok=True)
                os.rename(it["stored"], it["orig"])
                out("  restored %s" % it["orig"])
            except OSError as e:
                out("  FAIL %s: %s" % (it["orig"], e.strerror or e))
        left = [it for it in x["items"] if os.path.lexists(it["stored"])]
        if left:
            save_json(Path(x["dir"]) / "manifest.json", {k: v for k, v in dict(x, items=left).items() if k not in ("dir", "size")})
        else:
            remove(x["dir"])
    log("restore %s" % ids[0])
    return True


def purge(days, batch=None):
    """Delete batches older than `days` (or the named batch). Returns bytes freed."""
    freed = 0
    for x in batches():
        if (batch and batch in x["batch"]) or (not batch and _age_days(x) >= days):
            left = [it for it in x["items"] if not remove(it["stored"])]
            freed += sum(it["size"] for it in x["items"] if it not in left)
            if left:  # keep the manifest so locked leftovers are retried next time
                save_json(Path(x["dir"]) / "manifest.json", {k: v for k, v in dict(x, items=left).items() if k not in ("dir", "size")})
                log("purge %s: %d items still locked" % (x["batch"], len(left)))
            else:
                remove(x["dir"])
                log("purged %s (%s)" % (x["batch"], gb(x["size"])))
    return freed


def listing(days):
    lines = []
    for x in batches():
        lines.append("%s  %8s  %d items  age %dd (purged at %dd)  [%s]" % (
            x["batch"], gb(x["size"]), len(x["items"]), _age_days(x), days, drives.label(_drive_of(x["dir"]) or "?")))
        for it in x["items"][:5]:
            lines.append("     %s" % it["orig"])
    return lines or ["Quarantine is empty."]
