"""`explain <folder>` and `advise`. Built-in answers work offline; AI (optional) adds detail."""
import datetime as dt
import fnmatch
import os

from diskguardian import ai, config, paths, rules, scan
from diskguardian.util import gb, load_json, norm, now, save_json, walk

# (glob on the lower-cased path, verdict, explanation). First match wins.
KNOWN = [
    ("*\\appdata\\local\\temp*", "SAFE", "Temporary files. Old ones are cleaned automatically (safe tier)."),
    ("*\\windows\\temp*", "SAFE", "Windows temporary files. Cleaned by Deep clean (administrator)."),
    ("*\\softwaredistribution\\download*", "SAFE", "Installed Windows Update payloads. Cleaned by Deep clean."),
    ("*\\windows\\winsxs*", "KEEP", "Windows component store. Never delete by hand; use Settings > System > Storage > Temporary files, or `Dism /Online /Cleanup-Image /StartComponentCleanup` as administrator."),
    ("*\\windows\\installer*", "KEEP", "Needed to repair and uninstall programs. Deleting files here breaks uninstallers."),
    ("*\\windows.old*", "CACHE", "Your previous Windows. Needed only to roll back. Remove it with Settings > System > Storage > Temporary files > Previous Windows installation(s)."),
    ("*\\$windows.~bt*", "CACHE", "Windows upgrade files. Remove with Settings > System > Storage > Temporary files."),
    ("*\\hiberfil.sys", "KEEP", "Hibernation file. To shrink or remove it, run `powercfg /hibernate off` as administrator (disables hibernate and Fast Startup)."),
    ("*\\pagefile.sys", "KEEP", "Virtual memory. Manage it in System Properties > Advanced > Performance > Virtual memory; do not delete."),
    ("*\\system volume information*", "KEEP", "System Restore points. Shrink with System Protection > Configure > Max Usage."),
    ("*\\node_modules", "CACHE", "JavaScript dependencies. Rebuilt with `npm install`. Idle ones: `diskguardian dev`."),
    ("*\\.venv", "CACHE", "Python virtual environment. Rebuilt from requirements. Idle ones: `diskguardian dev`."),
    ("*\\appdata\\local\\docker*", "KEEP", "Docker Desktop data (images, containers). Shrink with `docker system prune` and Docker Desktop's Troubleshoot > Clean / Purge data."),
    ("*\\appdata\\local\\packages\\*", "KEEP", "Data of a Microsoft Store app. Reset the app in Settings > Apps instead of deleting."),
    ("*\\steamapps\\common*", "KEEP", "Installed Steam games. Uninstall games from Steam to free space."),
    ("*\\steamapps\\shadercache*", "CACHE", "Steam shader cache; rebuilt per game."),
    ("*\\onedrive*", "KEEP", "Your OneDrive files. Free space with right-click > Free up space (files stay in the cloud)."),
    ("*\\.cache\\huggingface*", "CACHE", "Downloaded AI models. Re-downloaded when a program needs them."),
    ("*\\.gradle*", "CACHE", "Gradle build cache; rebuilt on the next build."),
    ("*\\.nuget\\packages*", "CACHE", ".NET package cache; restored on the next build."),
    ("*\\npm-cache*", "CACHE", "npm download cache; re-downloaded on demand."),
    ("*\\programdata\\package cache*", "KEEP", "Installers kept by Visual Studio and others for repair/uninstall. Do not delete by hand."),
    ("*\\downloads*", "REVIEW", "Your downloads. Old installers are listed as 'review' items and can be quarantined."),
]


def builtin(target):
    t = norm(target)
    for r in rules.load()["rules"]:
        for pat in r.get("paths", []):
            for concrete in rules.expand(pat):
                if fnmatch.fnmatch(t, norm(concrete)) or fnmatch.fnmatch(t, norm(os.path.dirname(concrete))):
                    verdict = {"safe": "SAFE", "cache": "CACHE", "review": "REVIEW"}[r["tier"]]
                    return "%s: %s. %s (rule `%s`)" % (verdict, r["name"], r["why"], r["id"])
    # Exact folder names (node_modules, hiberfil.sys...) beat broad prefixes (anything under Temp).
    for pat, verdict, text in sorted(KNOWN, key=lambda k: k[0].endswith("*")):
        if fnmatch.fnmatch(t, pat):
            return "%s: %s" % (verdict, text)
    return None


def explain(target, refresh=False, out=print):
    target = os.path.abspath(target)
    know_path = paths.state_dir() / "knowledge.json"
    know = load_json(know_path, {})
    key = norm(target)
    if key in know and not refresh:
        k = know[key]
        out("[from %s, %s]\n%s" % (k["by"], k["time"], k["answer"]))
        return 0
    size, newest, files = walk(target)
    answer, by = builtin(target), "built-in rules"
    if ai.configured():
        listing = []
        try:
            for e in sorted(os.scandir(target), key=lambda e: e.name)[:40]:
                listing.append(e.name + ("/" if e.is_dir(follow_symlinks=False) else ""))
        except OSError:
            pass
        q = ("On Windows, what is the folder %s ? Size %s, %d files, last change %s. Top entries: %s. "
             "Which program creates it, is it safe to delete or shrink, and what is the right way (an app setting or "
             "command is better than deleting by hand)? Under 150 words. Start with one verdict: SAFE / CACHE / KEEP."
             % (target, gb(size), files, dt.datetime.fromtimestamp(newest).strftime("%Y-%m-%d") if newest else "?",
                ", ".join(listing) or "(none)"))
        got = ai.ask(q)
        if got:
            answer, by = got, "AI (%s)" % config.load()["ai"]["model"]
    if not answer:
        out("%s: %s in %d files. Disk Guardian has no built-in note for this folder.\n"
            "Tip: turn on the optional free AI to explain any folder (see README: Optional AI)." % (target, gb(size), files))
        return 1
    know[key] = {"time": now().isoformat(timespec="seconds"), "by": by, "answer": answer, "size": size}
    save_json(know_path, know)
    out("%s (%s)\n%s" % (target, gb(size), answer))
    return 0


def advise(out=print):
    cfg = config.load()
    s = scan.last(out=out)
    steps = []
    for tier, how in (("safe", "Clean junk now"), ("cache", "Clean caches")):
        t = rules.tier_total(s["rules"], tier)
        if t >= 100 * 1024 ** 2:
            steps.append("%s: %s (Start menu > Disk Guardian > %s)" % ({"safe": "Junk", "cache": "Caches"}[tier], gb(t), how))
    if any(r["note"] == "needs administrator" for r in s["rules"]):
        steps.append("Windows temp/update caches were not checked: run Deep clean (administrator).")
    dc = scan.dev_candidates(s, cfg)
    if dc:
        steps.append("Idle developer folders: %s (`diskguardian dev --yes`, restorable)" % gb(sum(x["size"] for x in dc)))
    for r in s["rules"]:
        if r["tier"] == "review" and r["size"]:
            steps.append("%s: %s. %s" % (r["name"], gb(r["size"]), r["why"]))
    for b in s.get("big_files", [])[:5]:
        steps.append("Big file %s `%s` (%d days old): delete or move it if you no longer need it." % (gb(b["size"]), b["path"], b["age_days"]))
    text = "\n".join("%d. %s" % (i + 1, x) for i, x in enumerate(steps)) or "Nothing worth doing right now."
    if ai.configured():
        rep = scan.report_path().read_text(encoding="utf-8") if scan.report_path().exists() else ""
        got = ai.ask("Here is a Windows disk report:\n\n%s\n\nGive a short prioritized plan to free space: for each "
                     "step the size gained, the risk, and how to do it. Real user files must go to quarantine "
                     "(`diskguardian quarantine <path> --yes`). Under 250 words." % rep[:12000])
        if got:
            text += "\n\nAI advice:\n" + got
    out(text)
    p = paths.reports_dir() / ("advice-%s.md" % now().strftime("%Y%m%d-%H%M%S"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Disk Guardian advice\n\n_%s, based on scan %s_\n\n%s\n" % (now().isoformat(timespec="seconds"), s["time"], text),
                 encoding="utf-8")
    return 0
