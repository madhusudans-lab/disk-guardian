"""Disk Guardian command line. Everything that changes files is a dry run until you add --yes."""
import argparse
import json
import os
import sys

from diskguardian import __version__, cleaner, config, drives, explain, paths, quarantine, rules, scan, task, watch
from diskguardian.util import GB, gb, load_json, now


def _fix_stdio():
    for s in (sys.stdout, sys.stderr):
        if s is not None and hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def status_text():
    cfg = config.load()
    lines = [scan.drive_line(drives.usage(d), cfg) for d in drives.fixed(cfg)]
    s = load_json(scan.last_scan_path(), None)
    if s:
        safe, cache = rules.tier_total(s["rules"], "safe"), rules.tier_total(s["rules"], "cache")
        parts = [("%s of junk" % gb(safe)) if safe >= 0.1 * GB else "",
                 ("%s of caches" % gb(cache)) if cache >= 0.1 * GB else ""]
        parts = [x for x in parts if x]
        lines.append(("%s can be cleared." % " and ".join(parts)) if parts else "Nothing worth cleaning right now.")
        try:
            import datetime as dt
            hours = (now() - dt.datetime.fromisoformat(s["time"])).total_seconds() / 3600
            lines.append("Last check %s ago." % ("%d minutes" % (hours * 60) if hours < 1 else "%.0f hours" % hours))
        except (KeyError, ValueError):
            pass
    else:
        lines.append("No scan yet: run `diskguardian scan`.")
    return "\n".join(lines)


def parser():
    ap = argparse.ArgumentParser(prog="diskguardian", description=__doc__)
    ap.add_argument("--version", action="version", version="Disk Guardian " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="free space on every drive")
    s = sub.add_parser("scan", help="measure all drives and write the report")
    s.add_argument("--quick", action="store_true", help="rules only, skip the full folder walk")
    s = sub.add_parser("clean", help="clean a tier (dry run unless --yes)")
    s.add_argument("--tier", choices=["safe", "cache", "review", "all"], default="safe", help="all = safe + cache")
    s.add_argument("--only", help="comma-separated rule ids")
    s.add_argument("--yes", action="store_true")
    sub.add_parser("dev", help="idle node_modules/.venv/... folders").add_argument("--yes", action="store_true")
    sub.add_parser("big", help="biggest files on all drives").add_argument("-n", type=int, default=25)
    s = sub.add_parser("dupes", help="find duplicate files (read-only)")
    s.add_argument("roots", nargs="*")
    s.add_argument("--min-mb", type=int, default=50)
    s = sub.add_parser("explain", help="what is this folder and can it go?")
    s.add_argument("path")
    s.add_argument("--refresh", action="store_true")
    sub.add_parser("advise", help="prioritized cleanup plan from the last scan")
    s = sub.add_parser("quarantine", help="move files/folders into the restorable quarantine")
    s.add_argument("paths", nargs="+")
    s.add_argument("--label", default="manual")
    s.add_argument("--yes", action="store_true")
    sub.add_parser("qlist", help="list quarantine batches")
    sub.add_parser("restore", help="put a quarantine batch back").add_argument("batch")
    s = sub.add_parser("purge", help="delete quarantine batches past their retention")
    s.add_argument("--batch", help="delete this batch now")
    s.add_argument("--yes", action="store_true")
    sub.add_parser("history", help="free space over time").add_argument("-n", type=int, default=20)
    s = sub.add_parser("config", help="show settings, or set one: config warn_free_gb 20")
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")
    sub.add_parser("watch", help="one background cycle (what the scheduled task runs)")
    sub.add_parser("task", help="manage the scheduled task").add_argument("action", choices=["install", "remove", "status"])
    return ap


def main(argv=None, out=print):
    _fix_stdio()
    args = parser().parse_args(argv)
    cfg = config.load()
    c = args.cmd
    if c == "status":
        out(status_text())
    elif c == "scan":
        scan.run(quick=args.quick, out=out)
    elif c == "clean":
        cleaner.clean(args.tier, set(args.only.split(",")) if args.only else None, args.yes, out=out)
    elif c == "dev":
        s = scan.last(out=out)
        dc = [x for x in scan.dev_candidates(s, cfg) if os.path.exists(x["path"])]
        if not dc:
            out("No developer folders idle for %d+ days." % cfg["dev_idle_days"])
            return 0
        for x in dc:
            out("%10s  idle %4dd  %s" % (gb(x["size"]), x["idle_days"], x["path"]))
        out("Total %s. Rebuild later with npm/pip/uv install, or restore from quarantine." % gb(sum(x["size"] for x in dc)))
        if args.yes:
            names = set(rules.load().get("dev_artifacts", []))
            idle = [x for x in dc if (scan.project_idle_days(x["project"], names) or 0) >= cfg["dev_idle_days"]]
            out("batch: %s" % quarantine.move([x["path"] for x in idle], "dev-artifacts", out=out))
        else:
            out("Dry run. Add --yes to quarantine them.")
    elif c == "big":
        for b in scan.last(out=out).get("big_files", [])[:args.n]:
            out("%10s  %4dd  %s" % (gb(b["size"]), b["age_days"], b["path"]))
    elif c == "dupes":
        roots = args.roots or [str(paths.home())] + [d for d in drives.fixed(cfg) if d.upper() != paths.system_drive().upper()]
        scan.dupes(roots, args.min_mb, out=out)
    elif c == "explain":
        return explain.explain(args.path, args.refresh, out=out)
    elif c == "advise":
        return explain.advise(out=out)
    elif c == "quarantine":
        if not args.yes:
            from diskguardian import safety
            from diskguardian.util import walk
            for p in args.paths:
                why = safety.blocked(p, automatic=False)
                out("  would quarantine %s (%s)%s" % (p, gb(walk(p)[0]), "  REFUSED: " + why if why else ""))
            out("Dry run. Add --yes to move them into the quarantine (restorable for %d days)." % cfg["quarantine_days"])
        else:
            batch = quarantine.move(args.paths, args.label, out=out)
            out("batch: %s" % batch if batch else "Nothing was moved.")
    elif c == "qlist":
        for line in quarantine.listing(cfg["quarantine_days"]):
            out(line)
    elif c == "restore":
        return 0 if quarantine.restore(args.batch, out=out) else 1
    elif c == "purge":
        if args.batch and not args.yes:
            out("Purging a batch early deletes it for good. Add --yes.")
            return 1
        out("Purged %s." % gb(quarantine.purge(cfg["quarantine_days"], args.batch)))
    elif c == "history":
        h = scan.history_path()
        rows = [json.loads(x) for x in h.read_text(encoding="utf-8").splitlines()[-args.n:]] if h.exists() else []
        for r in rows:
            out("%s  free %9s  junk %9s  caches %9s" % (r["time"], gb(r["free"]), gb(r["reclaim"]["safe"]), gb(r["reclaim"]["cache"])))
    elif c == "config":
        if not args.key:
            shown = dict(cfg, ai=dict(cfg["ai"], api_key="***" if cfg["ai"].get("api_key") else ""))
            out(json.dumps(shown, indent=1))
            out("File: %s" % config.path())
        elif args.value is None:
            out("Usage: diskguardian config <key> <value>")
            return 1
        else:
            try:
                out("%s = %r" % (args.key, config.set_value(args.key, args.value)))
            except KeyError:
                out("Unknown setting %r. Known: %s" % (args.key, ", ".join(sorted(config.DEFAULTS))))
                return 1
    elif c == "watch":
        for m in watch.run():
            out(m)
    elif c == "task":
        return {"install": task.install, "remove": task.remove, "status": task.status}[args.action](out=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
