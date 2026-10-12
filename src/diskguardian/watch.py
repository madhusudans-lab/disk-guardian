"""The background cycle run by the scheduled task. Quiet unless there is news."""
import datetime as dt
import os
import time

from diskguardian import cleaner, config, drives, notify, paths, quarantine, rules, scan
from diskguardian.util import GB, gb, load_json, log, now, save_json


def _sent_path():
    return paths.state_dir() / "sent.json"


def _once_today(key):
    """True the first time `key` is seen today (and remembers it)."""
    sent = load_json(_sent_path(), {})
    today = now().strftime("%Y-%m-%d")
    if sent.get(key) == today:
        return False
    sent[key] = today
    save_json(_sent_path(), sent)
    return True


def _full_scan_due(prev, cfg):
    t = prev.get("full_time")
    if not t:
        return True
    try:
        return now() - dt.datetime.fromisoformat(t) >= dt.timedelta(hours=cfg["full_scan_hours"])
    except ValueError:
        return True


def run():
    cfg = config.load()
    lock = paths.state_dir() / "watch.lock"
    paths.state_dir().mkdir(parents=True, exist_ok=True)
    if lock.exists() and time.time() - lock.stat().st_mtime < 3600:
        return []
    lock.write_text(str(os.getpid()))
    try:
        return _cycle(cfg)
    except Exception as e:  # the background task must never crash loudly
        log("watch error: %r" % e)
        return []
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _cycle(cfg):
    msgs = []
    prev = load_json(scan.last_scan_path(), {})
    prev_free = {u["drive"]: u["free"] for u in prev.get("drives", [])}
    if cfg["auto_clean_safe"]:
        res = cleaner.clean("safe", yes=True, out=lambda *_: None)
        if res["freed"] >= 0.5 * GB:
            msgs.append("Cleaned %s of junk automatically." % gb(res["freed"]))
    freed_q = quarantine.purge(cfg["quarantine_days"])
    if freed_q:
        msgs.append("Emptied %s of quarantine older than %d days." % (gb(freed_q), cfg["quarantine_days"]))
    s = scan.run(quick=not _full_scan_due(prev, cfg), quiet=True)
    dropped = sum(max(prev_free.get(u["drive"], u["free"]) - u["free"], 0) for u in s["drives"])
    for g in s.get("growth", []):
        # Folder sizes flap (permissions, restores); real growth also eats free space.
        if g["delta"] >= cfg["growth_alert_gb"] * GB and dropped >= 0.5 * g["delta"]:
            msgs.append("%s grew by %s." % (g["path"], gb(g["delta"])))
    low = []
    for u in s["drives"]:
        lvl = drives.level_of(u, cfg)
        if lvl and _once_today("%s:%s" % (lvl, u["drive"])):
            low.append((lvl, u))
    for lvl, u in sorted(low, key=lambda x: x[0] != "critical"):
        msgs.insert(0, "%s %s: only %s free." % ("Critically low space on" if lvl == "critical" else "Low space on",
                                                 drives.label(u["drive"]), gb(u["free"])))
    weekly = cfg.get("weekly_digest") and now().weekday() == cfg["weekly_digest_day"] and _once_today("digest")
    if low or weekly:
        cache = rules.tier_total(s["rules"], "cache")
        if cache >= 0.5 * GB:
            msgs.append("%s of caches can be cleared: Start menu > Disk Guardian > Clean caches." % gb(cache))
    if weekly and not low:
        msgs.insert(0, "Weekly check: %s free across %d drive(s)." % (gb(sum(u["free"] for u in s["drives"])), len(s["drives"])))
    if msgs:
        log("watch: " + " | ".join(msgs))
        if cfg.get("toast", True):
            notify.toast("Disk Guardian", " ".join(msgs))
    return msgs
