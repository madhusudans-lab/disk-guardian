"""Cleanup rules: bundled data/rules.json plus optional user-rules.json in the data dir."""
import fnmatch
import glob
import os
import shutil
import time

from diskguardian import config, drives, paths, safety
from diskguardian.util import GB, gb, load_json, norm, walk


def load():
    data = load_json(paths.resource("data/rules.json"), {})
    if not data.get("rules"):
        raise SystemExit("ERROR: bundled rules.json is missing or empty")
    extra = load_json(paths.data_dir() / "user-rules.json", {})
    known = {r["id"] for r in data["rules"]}
    for r in extra.get("rules", []):
        if {"id", "name", "tier", "paths"} <= set(r) and r["tier"] in ("safe", "cache", "review") and r["id"] not in known:
            data["rules"].append(r)
    return data


def expand(pattern):
    """Concrete glob patterns for one rule path, or [] if a variable is unset (never guess)."""
    if "{downloads}" in pattern:
        pattern = pattern.replace("{downloads}", str(paths.known_folder("downloads")))
    if "%TEMP%" in pattern.upper():
        temp = os.environ.get("TEMP", "")
        if os.path.basename(temp.rstrip("\\/")).lower() not in ("temp", "tmp"):
            return []  # TEMP redirected somewhere unusual: do not sweep it
    expanded = os.path.expandvars(pattern)
    if "%" in expanded:
        return []
    if "{drive}" in expanded:
        return [expanded.replace("{drive}", d.rstrip("\\") + "\\") for d in drives.fixed()]
    return [expanded]


def _matches(rule):
    seen = []
    keys = set()
    for pat in rule.get("paths", []):
        for concrete in expand(pat):
            for m in glob.glob(concrete, include_hidden=True):
                k = norm(m)
                if k not in keys:
                    keys.add(k)
                    seen.append(m)
    return seen


def evaluate(rule, admin, cfg=None):
    """{id, name, tier, why, items:[{path,size}], size, note} for one rule, measured live."""
    cfg = cfg or config.load()
    out = {"id": rule["id"], "name": rule["name"], "tier": rule["tier"], "why": rule.get("why", ""),
           "items": [], "size": 0, "note": "", "report_only": bool(rule.get("report_only"))}
    if rule.get("requires") == "admin" and not admin:
        out["note"] = "needs administrator"
        return out
    if rule.get("special") == "recycle_bin":
        for d in drives.fixed(cfg):
            for b in glob.glob(os.path.join(d, "$Recycle.Bin", "S-*"), include_hidden=True):
                out["size"] += walk(b)[0]
        return out
    if rule.get("command"):
        # Prune commands free an unknown share of the store: show the store size, count nothing.
        store = sum(walk(p)[0] for sp in rule.get("size_paths", []) for p in expand(sp))
        if shutil.which(rule["command"][0]):
            out["note"] = "via `%s` (store is %s, frees only unused parts)" % (" ".join(rule["command"]), gb(store))
        else:
            out["note"] = "%s not installed" % rule["command"][0]
        return out
    cutoff = time.time() - rule.get("min_age_days", 0) * 86400
    for m in _matches(rule):
        name = os.path.basename(m.rstrip("\\/"))
        if any(fnmatch.fnmatch(name.lower(), x.lower()) for x in rule.get("exclude", [])):
            continue
        if rule.get("must_contain") and not os.path.exists(os.path.join(m, rule["must_contain"])):
            continue
        if not rule.get("report_only") and safety.blocked(m, automatic=True):
            continue
        size, newest, _ = walk(m)
        if rule.get("min_age_days") and newest > cutoff:
            continue
        if size:
            out["items"].append({"path": m, "size": size})
            out["size"] += size
    out["items"].sort(key=lambda i: -i["size"])
    if out["report_only"] and out["size"]:
        out["note"] = "report only"
    if out["size"] > cfg.get("rule_cap_gb", 50) * GB and not out["report_only"]:
        out.update(items=[], note="over safety cap (%s): not cleaned, check it by hand" % gb(out["size"]))
    return out


def evaluate_all(tiers=None, only=None, admin=None):
    from diskguardian.util import is_admin
    admin = is_admin() if admin is None else admin
    cfg = config.load()
    res = []
    for r in load()["rules"]:
        if (tiers and r["tier"] not in tiers) or (only and r["id"] not in only):
            continue
        res.append(evaluate(r, admin, cfg))
    return res


def tier_total(results, tier):
    return sum(r["size"] for r in results if r["tier"] == tier and not r.get("report_only"))
