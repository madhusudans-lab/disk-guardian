"""User settings: defaults merged with %LOCALAPPDATA%\\DiskGuardian\\config.json."""
from diskguardian import paths
from diskguardian.util import load_json, save_json

DEFAULTS = {
    "warn_free_gb": 15,          # warn when a drive has less free (capped at 10 % of its size)
    "critical_free_gb": 8,       # critical below this (capped at 5 % of its size)
    "growth_alert_gb": 3,        # alert when a folder grows this much between full scans
    "auto_clean_safe": True,     # background task deletes the "safe" tier
    "quarantine_days": 7,
    "big_file_mb": 1024,
    "dev_idle_days": 45,
    "rule_cap_gb": 50,           # a rule matching more than this is treated as a mistake
    "full_scan_hours": 24,       # background task walks all drives at most this often
    "weekly_digest": False,
    "weekly_digest_day": 6,      # 0=Mon .. 6=Sun
    "toast": True,
    "drives": "auto",            # or a list like ["C:\\", "D:\\"]
    "exclude_drives": [],
    "ai": {"base_url": "", "model": "", "api_key": ""},
}


def path():
    return paths.data_dir() / "config.json"


def load():
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    user = load_json(path(), {})
    for k, v in user.items():
        if isinstance(cfg.get(k), dict) and isinstance(v, dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    if not path().exists():
        try:
            save_json(path(), cfg)
        except OSError:
            pass
    return cfg


def set_value(key, raw):
    """`config ai.model llama3.2` style update; numbers and booleans are parsed."""
    user = load_json(path(), {})
    value = _parse(raw)
    if "." in key:
        top, sub = key.split(".", 1)
        if top not in DEFAULTS or not isinstance(DEFAULTS[top], dict) or sub not in DEFAULTS[top]:
            raise KeyError(key)
        user.setdefault(top, {})[sub] = value
    else:
        if key not in DEFAULTS:
            raise KeyError(key)
        user[key] = value
    save_json(path(), user)
    return value


def _parse(raw):
    low = raw.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    for t in (int, float):
        try:
            return t(raw)
        except ValueError:
            pass
    if raw.startswith("["):
        return [x.strip() for x in raw.strip("[]").split(",") if x.strip()]
    return raw
