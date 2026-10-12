"""Restorable quarantine. One per drive, so a move is an instant rename and never a copy:
system drive -> <data dir>\\quarantine, any other drive X: -> hidden X:\\.DiskGuardian\\quarantine.
Moving files into quarantine frees no space until they are purged.
"""
import datetime as dt
import os
import subprocess
from pathlib import Path

from diskguardian import drives, paths, safety
from diskguardian.util import gb, load_json, log, norm, now, remove, save_json, walk


def _drive_of(p):
    """The managed drive root that holds `p` (longest match, so test stand-ins work)."""
    n = norm(p)
    best = None
    for r in safety.drive_roots():
        if n.startswith(r) and (best is None or len(r) > len(best)):
            best = r
    return best


def root_for(path):
    """Quarantine folder on the same drive as `path`, or None if one cannot be made there."""
    d = _drive_of(path)
    if d is None:
        return None
    if d == norm(paths.system_drive()):
        q = paths.data_dir() / "quarantine"
    else:
        q = Path(d) / safety.DG_DIR / "quarantine"
    try:
        new = not q.parent.exists()
        q.mkdir(parents=True, exist_ok=True)
        if new and q.parent.name == safety.DG_DIR:
            subprocess.run(["attrib", "+h", str(q.parent)], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return q


def all_roots():
    found = [paths.data_dir() / "quarantine"]
    for r in safety.drive_roots():
        q = Path(r) / safety.DG_DIR / "quarantine"
        if q.exists():
            found.append(q)
    return found


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
            if data and data.get("items"):
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
