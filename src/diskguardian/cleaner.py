"""Run a tier of rules. Dry run unless yes=True. safe/cache items are deleted; review items are
quarantined; report-only rules are never touched."""
import os
import shutil
import subprocess
import time

from diskguardian import drives, quarantine, rules
from diskguardian.util import gb, log, remove, walk


def _free_total():
    return sum(drives.usage(d)["free"] for d in drives.fixed())


def clean(tier, only=None, yes=False, out=print):
    tiers = ["safe", "cache"] if tier == "all" else [tier]
    if tier == "review" and not only:
        out("Review items are real files: name them with --only <rule-id> (see the report).")
        return {"freed": 0, "failed": 0, "done": [], "planned": 0}
    results = rules.evaluate_all(tiers, only)
    specs = {r["id"]: r for r in rules.load()["rules"]}
    plan = [r for r in results if not r.get("report_only") and (
        r["size"] or (specs[r["id"]].get("command") and r["note"].startswith("via")))]
    skipped = [r for r in results if r.get("report_only") and r["size"]]
    for r in skipped:
        out("  %-44s %10s  report only: %s" % (r["name"], gb(r["size"]), r["why"]))
    planned = sum(r["size"] for r in plan)
    if not plan:
        out("Nothing to clean for tier %s." % tier)
        return {"freed": 0, "failed": 0, "done": [], "planned": 0}
    out("%s %s from %d rule(s):" % ("Cleaning" if yes else "Would clean", gb(planned), len(plan)))
    for r in plan:
        out("  %-44s %10s %s" % (r["name"], gb(r["size"]), r["note"]))
    if not yes:
        out("\nDry run. Add --yes to do it.")
        return {"freed": 0, "failed": 0, "done": [], "planned": planned}
    before = _free_total()
    failed, done = 0, []
    for r in plan:
        spec = specs[r["id"]]
        if r["tier"] == "review":
            batch = quarantine.move([i["path"] for i in r["items"]], "rule-" + r["id"], automatic=True, out=out)
            done.append("%s -> quarantine %s" % (r["name"], batch))
        elif spec.get("command"):
            done.append(_run_command(r, spec))
        elif spec.get("special") == "recycle_bin":
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
                           capture_output=True, timeout=600, creationflags=_NO_WINDOW)
            done.append(r["name"])
        else:
            cutoff = time.time() - spec.get("min_age_days", 0) * 86400
            fresh = [i for i in r["items"] if not spec.get("min_age_days") or walk(i["path"])[1] <= cutoff]
            bad = sum(0 if remove(i["path"]) else 1 for i in fresh)
            failed += bad
            done.append(r["name"] + (" (%d in use, skipped)" % bad if bad else ""))
    freed = max(_free_total() - before, 0)
    msg = "freed %s (%s)%s" % (gb(freed), ", ".join(done), "; %d items in use" % failed if failed else "")
    out("Done: " + msg)
    log("clean %s: %s" % (tier, msg))
    return {"freed": freed, "failed": failed, "done": done, "planned": planned}


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_command(r, spec):
    exe = shutil.which(spec["command"][0])
    if not exe:
        return "%s (not installed)" % r["name"]
    try:
        p = subprocess.run([exe] + spec["command"][1:], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=1800, creationflags=_NO_WINDOW,
                           env=dict(os.environ, UV_LOCK_TIMEOUT="30"))
    except (OSError, subprocess.TimeoutExpired) as e:
        return "%s (failed: %s)" % (r["name"], e)
    if p.returncode == 0:
        return r["name"]
    busy = "in-use" in (p.stderr or "") or "lock" in (p.stderr or "").lower()
    return r["name"] + (" (busy: another program is using it)" if busy else " (exit %s)" % p.returncode)
