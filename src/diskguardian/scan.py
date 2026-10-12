"""Measure everything on every fixed drive and write the report."""
import hashlib
import json
import os
import stat
import time
from pathlib import Path

from diskguardian import config, drives, paths, quarantine, rules, safety
from diskguardian.util import GB, MB, entries, gb, inside, is_admin, load_json, log, now, save_json, walk

SKIP_TOP = {x.lower() for x in safety.DRIVE_TOP} | {safety.DG_DIR.lower(), "windows.old", "$windows.~bt",
                                                    "$windows.~ws", "$getcurrent"}


def last_scan_path():
    return paths.state_dir() / "last_scan.json"


def history_path():
    return paths.state_dir() / "history.jsonl"


def report_path():
    return paths.reports_dir() / "latest.md"


def scan_roots():
    """Home folder plus every fixed drive's top-level folders, minus system ones."""
    roots = [paths.home()]
    for d in drives.fixed():
        for e, s in entries(d):
            if stat.S_ISDIR(s.st_mode) and e.name.lower() not in SKIP_TOP:
                roots.append(Path(e.path))
    return roots


def scan_tree(roots, cfg, dev_names, markers):
    """One pass: folder sizes (>=100 MB, depth<=4), big files, dev artifacts."""
    big_min = cfg["big_file_mb"] * MB
    dirs, bigs, devs = {}, [], []

    def has_marker(project, name, folder):
        m = markers.get(name)
        return not m or os.path.exists(os.path.join(project, m)) or os.path.exists(os.path.join(folder, m))

    def rec(path, depth, in_appdata):
        total = 0
        for e, s in entries(path):
            if stat.S_ISDIR(s.st_mode):
                if e.name == safety.DG_DIR:
                    continue
                if (e.name in dev_names and not in_appdata and has_marker(path, e.name, e.path)
                        and not safety.blocked(e.path, automatic=False)):
                    size = walk(e.path)[0]
                    total += size
                    if size >= 50 * MB:
                        devs.append({"path": e.path, "size": size, "project": path,
                                     "idle_days": project_idle_days(path, dev_names)})
                    continue
                total += rec(e.path, depth + 1, in_appdata or e.name.lower() == "appdata")
            else:
                total += s.st_size
                if s.st_size >= big_min:
                    bigs.append({"path": e.path, "size": s.st_size,
                                 "age_days": int((time.time() - s.st_mtime) / 86400)})
        if depth <= 4 and total >= 100 * MB:
            dirs[path] = total
        return total

    seen = set()
    for r in roots:
        key = os.path.normcase(str(r))
        if key in seen or any(inside(r, s) for s in seen):
            continue
        seen.add(key)
        rec(str(r), 1, False)
    bigs.sort(key=lambda b: -b["size"])
    devs.sort(key=lambda d: -d["size"])
    return dirs, bigs, devs


def project_idle_days(project, dev_names, max_depth=3):
    """Days since anything in a project (outside dependency folders) changed; None if unknown."""
    newest, stack = 0.0, [(project, 0)]
    while stack:
        d, depth = stack.pop()
        for e, s in entries(d):
            if stat.S_ISDIR(s.st_mode):
                if depth < max_depth and e.name not in dev_names and e.name != ".git":
                    stack.append((e.path, depth + 1))
            else:
                newest = max(newest, s.st_mtime)
    return int((time.time() - newest) / 86400) if newest else None


def run(quick=False, quiet=False, out=print):
    cfg = config.load()
    t0 = time.time()
    rdata = rules.load()
    usage = [drives.usage(d) for d in drives.fixed(cfg)]
    results = rules.evaluate_all()
    prev = load_json(last_scan_path(), {})
    dirs, bigs, devs = {}, [], []
    if not quick:
        dirs, bigs, devs = scan_tree(scan_roots(), cfg, set(rdata.get("dev_artifacts", [])),
                                     rdata.get("dev_markers", {}))
    growth = []
    if dirs and prev.get("dirs"):
        for p, size in dirs.items():
            delta = size - prev["dirs"].get(p, 0)
            # Report the deepest folder that explains the growth, not every parent of it.
            if delta >= 0.5 * GB and not any(q != p and inside(q, p) and dirs.get(q, 0) - prev["dirs"].get(q, 0) >= delta * 0.9
                                             for q in dirs):
                growth.append({"path": p, "delta": delta, "size": size})
        growth.sort(key=lambda g: -g["delta"])
    s = {"time": now().isoformat(timespec="seconds"), "seconds": round(time.time() - t0, 1),
         "admin": is_admin(), "drives": usage, "rules": results, "quick": quick,
         "full_time": _full_time(prev, quick),
         "dirs": dirs or prev.get("dirs", {}), "big_files": bigs[:40] if not quick else prev.get("big_files", []),
         "dev": devs if not quick else prev.get("dev", []), "growth": growth,
         "quarantine": quarantine.summary()}
    save_json(last_scan_path(), s)
    with history_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps({"time": s["time"], "drives": {u["drive"]: u["free"] for u in usage},
                            "free": sum(u["free"] for u in usage),
                            "reclaim": {t: rules.tier_total(results, t) for t in ("safe", "cache", "review")}}) + "\n")
    write_report(s, cfg)
    log("scan%s: free %s, safe %s, cache %s (%ss)" % (
        " quick" if quick else "", gb(sum(u["free"] for u in usage)), gb(rules.tier_total(results, "safe")),
        gb(rules.tier_total(results, "cache")), s["seconds"]))
    if not quiet:
        out(summary_text(s, cfg))
        out("\nFull report: %s" % report_path())
    return s


def _full_time(prev, quick):
    return prev.get("full_time") if quick else now().isoformat(timespec="seconds")


def last(full=True, out=print):
    s = load_json(last_scan_path(), None)
    if not s or (full and not s.get("full_time")):
        out("(no full scan yet, scanning all drives now; this can take a few minutes...)")
        s = run(quick=False, quiet=True)
    return s


def dev_candidates(s, cfg):
    return [x for x in s.get("dev", []) if (x.get("idle_days") or 0) >= cfg["dev_idle_days"]]


def drive_line(u, cfg):
    lvl = drives.level_of(u, cfg)
    pct = 100 * u["free"] // u["total"] if u["total"] else 0
    flag = {"critical": "  CRITICALLY LOW", "warn": "  low"}.get(lvl, "")
    return "Drive %s %s free of %s (%d%%)%s" % (drives.label(u["drive"]), gb(u["free"]), gb(u["total"]), pct, flag)


def summary_text(s, cfg):
    lines = [drive_line(u, cfg) for u in s["drives"]]
    res = s["rules"]
    for tier, label in (("safe", "Safe junk"), ("cache", "Caches"), ("review", "Needs review")):
        lines.append("  %-13s %10s" % (label, gb(rules.tier_total(res, tier))))
        for r in sorted((r for r in res if r["tier"] == tier and (r["size"] or r["note"])), key=lambda r: -r["size"]):
            lines.append("      %-44s %10s  %s" % (r["name"], gb(r["size"]), r["note"]))
    dc = dev_candidates(s, cfg)
    if dc:
        lines.append("  Idle dev folders (%d+ days): %s in %d folders  -> diskguardian dev" % (
            cfg["dev_idle_days"], gb(sum(x["size"] for x in dc)), len(dc)))
    if s.get("big_files"):
        lines.append("  Big files (>=%d MB): %d  -> diskguardian big" % (cfg["big_file_mb"], len(s["big_files"])))
    for g in s.get("growth", [])[:5]:
        lines.append("  GREW +%s since last scan: %s" % (gb(g["delta"]), g["path"]))
    q = s.get("quarantine") or {}
    if q.get("count"):
        lines.append("  Quarantine: %s in %d batches (frees space when purged after %d days)" % (
            gb(q["size"]), q["count"], cfg["quarantine_days"]))
    if not s.get("admin"):
        lines.append("  (not administrator: Windows temp and update caches not checked; use Deep clean)")
    return "\n".join(lines)


def write_report(s, cfg):
    md = ["# Disk Guardian report", "",
          "_%s, scan took %ss%s_" % (s["time"], s["seconds"], " (quick: folder sizes are from the last full scan)" if s["quick"] else ""),
          "", "## Drives", ""]
    md += ["- " + drive_line(u, cfg) for u in s["drives"]]
    md += ["", "## Reclaimable", "", "| Tier | Item | Size | Note |", "|---|---|---|---|"]
    order = {"safe": 0, "cache": 1, "review": 2}
    for r in sorted(s["rules"], key=lambda r: (order[r["tier"]], -r["size"])):
        if r["size"] or r["note"]:
            md.append("| %s | %s (`%s`) | %s | %s |" % (r["tier"], r["name"], r["id"], gb(r["size"]),
                                                       r["why"] if r.get("report_only") else (r["note"] or r["why"])))
    md += ["", "Clean with the Start-menu shortcuts, or: `diskguardian clean --tier safe --yes`, "
           "`diskguardian clean --tier cache --yes`, `diskguardian clean --tier review --only <id> --yes` "
           "(review items go to the quarantine and can be restored).", ""]
    if s.get("growth"):
        md += ["## Grew since last scan", ""] + ["- +%s `%s` (now %s)" % (gb(g["delta"]), g["path"], gb(g["size"]))
                                                for g in s["growth"][:10]] + [""]
    top = sorted(s.get("dirs", {}).items(), key=lambda kv: -kv[1])
    leaves = [(p, z) for p, z in top if not any(q != p and inside(q, p) and z2 >= 0.5 * z for q, z2 in top)][:25]
    if leaves:
        md += ["## Biggest folders", ""] + ["- %s `%s`" % (gb(z), p) for p, z in leaves] + [""]
    if s.get("big_files"):
        md += ["## Big files", ""] + ["- %s `%s` (%d days old)" % (gb(b["size"]), b["path"], b["age_days"])
                                      for b in s["big_files"][:25]] + [""]
    dc = dev_candidates(s, cfg)
    if dc:
        md += ["## Idle developer folders (rebuilt by npm/pip/uv install)", ""] + [
            "- %s `%s` (project idle %d days)" % (gb(x["size"]), x["path"], x["idle_days"]) for x in dc[:25]] + [
            "", "Quarantine them all: `diskguardian dev --yes`", ""]
    q = s.get("quarantine") or {}
    if q.get("count"):
        md += ["## Quarantine", "", "%s in %d batches. `diskguardian qlist`, `restore <batch>`, `purge`. "
               "Space is freed only when a batch is purged." % (gb(q["size"]), q["count"]), ""]
    p = report_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(md), encoding="utf-8")
    return p


def dupes(roots, min_mb, out=print):
    """Print groups of identical files; return wasted bytes. Read-only."""
    by_size = {}
    for r in roots:
        for d, sub, files in os.walk(r):
            sub[:] = [x for x in sub if x not in ("AppData", "node_modules", ".git", safety.DG_DIR)
                      and x.lower() not in SKIP_TOP]
            for f in files:
                p = os.path.join(d, f)
                try:
                    st = os.stat(p, follow_symlinks=False)
                except OSError:
                    continue
                if st.st_size >= min_mb * MB and not (getattr(st, "st_file_attributes", 0) & 0x400):
                    by_size.setdefault(st.st_size, []).append(p)

    def digest(p, limit=None):
        h = hashlib.blake2b(digest_size=16)
        with open(p, "rb") as fh:
            read = 0
            while chunk := fh.read(4 * MB):
                h.update(chunk)
                read += len(chunk)
                if limit and read >= limit:
                    break
        return h.hexdigest()

    waste = 0
    for size, group in sorted(by_size.items(), reverse=True):
        if len(group) < 2:
            continue
        same = {}
        for p in group:
            try:
                same.setdefault((digest(p, 8 * MB), digest(p)), []).append(p)
            except OSError:
                pass
        for g in same.values():
            if len(g) > 1:
                waste += size * (len(g) - 1)
                out("%s x%d" % (gb(size), len(g)))
                for p in g:
                    out("    %s" % p)
    out("Duplicate waste: %s. Quarantine the extra copies with: diskguardian quarantine <path> --yes" % gb(waste))
    return waste
