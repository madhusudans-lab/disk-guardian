# Disk Guardian (public) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the owner's single-PC `guardian.py` into a free, installable Windows 10/11 agent that cleans all fixed drives safely.

**Architecture:** Python package `diskguardian` (stdlib only) split into focused modules; PyInstaller builds a console exe and a windowed exe; Inno Setup wraps them into a per-user `setup.exe` that registers a Task Scheduler task and Start-menu shortcuts.

**Tech Stack:** Python 3.12 (stdlib, `unittest`), PyInstaller 6, Inno Setup 6, PowerShell 5.1, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-12-disk-guardian-public-design.md`

**Execution:** native (Claude implements engine tasks 1–8 and reviews everything); DeepSeek Harness drafts tasks 9–10 (installer, build, CI, README) and Claude reviews/fixes them. Owner said "finish it".

## Global Constraints

- Windows 10 1809+ (`MinVersion=10.0.17763`) and Windows 11, x64 only.
- Runtime: Python standard library only. No network calls except the optional AI endpoint.
- Zero cost: no paid services, no code signing.
- Every destructive command is a dry run unless `--yes`.
- Data dir `%LOCALAPPDATA%\DiskGuardian` (override `DISKGUARDIAN_HOME`); install dir `%LOCALAPPDATA%\Programs\DiskGuardian`.
- Never hard-code `C:`; use `%SystemDrive%`.
- Tests never touch real user folders: every test runs under a temp `DISKGUARDIAN_HOME` and fake profile.

## Review Focus

1. A rule glob on a second drive matching `D:\` itself or `D:\Users` → must be refused by `safety.check`, not deleted.
2. `quarantine` of a path on a drive where `X:\.DiskGuardian` cannot be created (read-only/permission) → item skipped with a message, nothing deleted.
3. Downloads moved to `D:\Downloads` → `old-installers` rule follows it; Documents moved to `D:\Docs` → still protected.
4. A junction inside a temp folder pointing at Documents → the junction is unlinked, the target is untouched.
5. Background `watch` run on a machine where PowerShell toast fails (e.g. Server Core, policy) → no crash, logged.

---

### Task 1: Package skeleton, paths, config

**Files:** Create `pyproject.toml`, `src/diskguardian/__init__.py`, `src/diskguardian/__main__.py`, `src/diskguardian/paths.py`, `src/diskguardian/config.py`, `src/diskguardian/util.py`, `tests/__init__.py`, `tests/helpers.py`, `tests/test_config.py`, `.gitignore`

**Produces:**
- `paths.data_dir() -> Path` (DISKGUARDIAN_HOME or `%LOCALAPPDATA%\DiskGuardian`), `paths.state_dir()`, `paths.reports_dir()`, `paths.logs_dir()`, `paths.home() -> Path` (env `DISKGUARDIAN_PROFILE` for tests, else `Path.home()`), `paths.system_drive() -> str` like `"C:\\"`, `paths.known_folder(name) -> Path|None` for Downloads/Documents/Desktop/Pictures/Videos/Music via `SHGetKnownFolderPath`, falling back to `home()/name`.
- `config.load() -> dict` merging `DEFAULTS` with `data_dir()/config.json`; writes defaults on first run.
- `util`: `GB, MB, gb(n)->str, now(), load_json, save_json, log(msg), norm(p), inside(child,parent), entries(d), walk(path)->(bytes,newest,count), remove(path)->bool, is_admin()` (ported verbatim from guardian.py).

- [ ] Tests: defaults written on first load; user value overrides default; `gb(5*GB)=="5.00 GB"`; `walk` on a temp tree returns byte total; `remove` of a junction leaves its target (Review Focus 4).
- [ ] Implement, run `python -m unittest -v`, commit.

### Task 2: Drives

**Files:** Create `src/diskguardian/drives.py`, `tests/test_drives.py`

**Produces:** `drives.fixed() -> list[str]` (e.g. `["C:\\","D:\\"]`, honours config `drives`/`exclude_drives`, env `DISKGUARDIAN_DRIVES` for tests), `drives.usage(d) -> {"drive","total","used","free"}`, `drives.levels(total, cfg) -> (warn_bytes, critical_bytes)` = `min(warn_free_gb*GB, 10% total)`, `min(critical_free_gb*GB, 5% total)`.

- [ ] Tests: system drive is in `fixed()`; env override respected; `levels(64*GB)` → (6.4 GB, 3.2 GB); `levels(1000*GB)` → (15 GB, 8 GB).
- [ ] Implement with `ctypes.windll.kernel32.GetLogicalDrives/GetDriveTypeW` (3 = fixed), commit.

### Task 3: Safety

**Files:** Create `src/diskguardian/safety.py`, `tests/test_safety.py`

**Consumes:** paths, drives, util. **Produces:** `safety.blocked(path, automatic=True) -> str|None`.

Refuse on every drive: root; `Windows`, `Program Files`, `Program Files (x86)`, `ProgramData` (allow list: `Windows\Temp`, `Windows\SoftwareDistribution\Download`, `Windows\SoftwareDistribution\DeliveryOptimization`, `ProgramData\Microsoft\Windows\WER`, `Windows\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache`); `Users` and its direct children; `System Volume Information`, `Recovery`, `Boot`, `EFI`, `$Recycle.Bin`, `pagefile.sys`, `hiberfil.sys`, `swapfile.sys`; never: home `.ssh/.gnupg/.aws`, data dir, every `X:\.DiskGuardian`; personal known folders (anything inside when automatic, any ancestor always). Check both `abspath` and `realpath` forms; strip `\\?\`.

- [ ] Tests (each a separate method): `C:\`, `D:\`, `D:\Users`, `D:\Users\bob`, `C:\Windows\System32`, `C:\Windows\Temp\x` allowed, `D:\Program Files\x`, `D:\$Recycle.Bin`, `D:\pagefile.sys`, data dir, `D:\.DiskGuardian\quarantine`, `home\.ssh`, Documents inside (automatic=True blocked, False allowed), Documents' parent blocked, moved Documents via `DISKGUARDIAN_KNOWN_DOCUMENTS` env override (Review Focus 3), `D:\Games\steamapps\shadercache\x` allowed.
- [ ] Implement, commit.

### Task 4: Rules

**Files:** Create `src/diskguardian/rules.py`, `src/diskguardian/data/rules.json`, `tests/test_rules.py`

**Produces:** `rules.load() -> dict` (bundled rules + optional `data_dir()/user-rules.json` appended), `rules.expand(pattern) -> list[str]` (expands `{drive}` over `drives.fixed()`, `{downloads}` via known folder, env vars; skips if a `%VAR%` stays unexpanded), `rules.evaluate(rule, admin) -> {id,name,tier,why,items:[{path,size}],size,note}`, `rules.evaluate_all(tiers=None, only=None) -> list`, `rules.tier_total(results, tier)`. Size cap: a rule whose total exceeds `cfg["rule_cap_gb"]` (50) returns no items and note `"over safety cap"`.

Rules JSON: port the 20 owner rules generalised (`C:\` → `%SystemRoot%`/`%ProgramData%`, Downloads → `{downloads}`), add: `delivery-opt` (safe, admin), `win-upgrade-leftovers` (`{drive}\$WINDOWS.~BT`, `{drive}\$Windows.~WS`, `{drive}\$GetCurrent`; review, admin, report-only), `windows-old` (`{drive}\Windows.old`, review, report-only), `firefox-cache` (cache), `steam-shader` (`{drive}\SteamLibrary\steamapps\shadercache\*`, `{drive}\*\Steam\steamapps\shadercache\*`; cache), `d3d-shader-cache` (`%LOCALAPPDATA%\D3DSCache\*`, cache), `nvidia-shader-cache` (`%LOCALAPPDATA%\NVIDIA\DXCache\*`, `%LOCALAPPDATA%\NVIDIA\GLCache\*`; cache). Recycle bin sizes `{drive}\$Recycle.Bin\S-*` across drives (special-cased; safety bypass only inside that special). Plus any DeerFlow-researched entries that pass review.

- [ ] Tests: `{drive}` expands across `DISKGUARDIAN_DRIVES=<tmpA>;<tmpB>`; a file in a fake temp older than `min_age_days` is an item, a fresh one is not; excluded names skipped; cap respected; rule matching a blocked path yields no item (Review Focus 1); bundled rules.json loads and every rule has id/name/tier/why.
- [ ] Implement, commit.

### Task 5: Quarantine

**Files:** Create `src/diskguardian/quarantine.py`, `tests/test_quarantine.py`

**Produces:** `quarantine.root_for(path) -> Path|None` (system drive → `data_dir()/quarantine`; other → `X:\.DiskGuardian\quarantine`, created hidden via `attrib +h`, None if it cannot be created), `quarantine.move(paths, label, automatic=False) -> str|None` batch id, `quarantine.batches() -> list` (all roots, manifests), `quarantine.summary()`, `quarantine.restore(batch) -> list[str]` messages, `quarantine.purge(days, batch=None) -> int` bytes. Batch dir per drive; manifests record `orig`, `stored`, `size`.

- [ ] Tests (fake drives = temp dirs; `DISKGUARDIAN_DRIVES`): move then restore round-trips content; restore skips if target exists; purge by age; blocked path skipped; unwritable root → skipped with message, original intact (Review Focus 2, simulate by patching `root_for` to return None).
- [ ] Implement, commit.

### Task 6: Clean + scan + report

**Files:** Create `src/diskguardian/cleaner.py`, `src/diskguardian/scan.py`, `tests/test_clean_scan.py`

**Produces:** `cleaner.clean(tier, only=None, yes=False, out=print) -> {"freed","failed","done","planned"}` (safe/cache delete; review → quarantine; commands via `shutil.which`; recycle bin via `Clear-RecycleBin -Force`), `scan.run(quick=False, quiet=False) -> dict` (per-drive usage list `drives`, rules, dirs, big_files, dev, growth, quarantine; writes `state/last_scan.json`, appends `state/history.jsonl`, writes `reports/latest.md`), `scan.summary_text(scan, cfg)`, `scan.last(full=True)`, `scan.dev_candidates(scan, cfg)`, `scan.dupes(roots, min_mb, out=print) -> int`.

Full scan roots: `home()` plus every fixed drive's top-level dirs except the safety-refused names, `Users` and Disk Guardian folders.

- [ ] Tests: dry run deletes nothing and reports planned size; `--yes` deletes safe items in fake temp; scan writes report containing each drive letter; dev folder with marker and old mtime appears in `dev_candidates`.
- [ ] Implement, commit.

### Task 7: Notify, AI, watch

**Files:** Create `src/diskguardian/notify.py`, `src/diskguardian/ai.py`, `src/diskguardian/watch.py`, `tests/test_watch.py`

**Produces:** `notify.toast(title, text) -> bool` (AppID `DiskGuardian.Agent`, fall back to PowerShell AppID; never raises; env `DISKGUARDIAN_NO_TOAST=1` records to `state/toasts.log` instead for tests), `ai.configured() -> bool`, `ai.ask(prompt) -> str|None` (POST `{base_url}/chat/completions`, 120 s timeout), `watch.run() -> list[str]` messages (lock file, auto-clean safe, purge, quick scan; full scan if last full > 24 h; per drive warn/critical once per day; growth alerts; weekly digest optional).

- [ ] Tests: low free (config `warn_free_gb` huge) → one toast recorded, second run same day → none; toast failure does not raise (Review Focus 5); `ai.ask` returns None when not configured.
- [ ] Implement, commit.

### Task 8: CLI + windowed entry

**Files:** Create `src/diskguardian/cli.py`, `src/diskguardian/explain.py`, `src/diskguardian/task.py`, `src/diskguardian/gui_entry.py`, `tests/test_cli.py`

**Produces:** `cli.main(argv=None) -> int` with all commands from spec §3; `explain.explain(path, refresh)`, `explain.advise()` (built-in folder table when AI is off); `task.install(exe) / remove() / status()` via `schtasks` XML (logon +5 min, every 6 h, `IgnoreNew`, battery allowed); `gui_entry.main()` redirects stdout to log, runs `cli.main`, shows the result as a toast (for `status`, `clean`, `deep-clean` which relaunches itself elevated via `ShellExecuteW runas`), `open-report` opens `latest.md` in Notepad.

- [ ] Tests: `cli.main(["status"])` prints a line per drive; `cli.main(["clean","--tier","safe"])` is a dry run; `config warn_free_gb 20` persists.
- [ ] Port `selftest.py` checks that still apply; run whole suite; commit.

### Task 9 (dsh draft, Claude review): Build + installer

**Files:** Create `packaging/diskguardian.spec` (two exes, `--onedir`, bundle `data/rules.json`), `packaging/installer.iss`, `build.ps1`, `packaging/icon.ico`.

Installer: `PrivilegesRequired=lowest`, `DefaultDirName={localappdata}\Programs\DiskGuardian`, `MinVersion=10.0.17763`, `ArchitecturesAllowed=x64compatible`, `ArchitecturesInstallIn64BitMode=x64compatible`, Start-menu icons with `AppUserModelID: "DiskGuardian.Agent"`, `[Run]` `task install` + `scan --quick`, `[UninstallRun]` `task remove`, uninstall code asks to delete data dir (warn if quarantine not empty).

- [ ] Install PyInstaller in `.venv` and Inno Setup 6 via winget; `./build.ps1` produces `dist\DiskGuardian-Setup-0.1.0.exe`; smoke test exe `status`, `scan --quick`; commit.

### Task 10 (dsh draft, Claude review): README, licence, CI

**Files:** `README.md` (install, SmartScreen, commands, free AI setups, safety), `LICENSE` (MIT), `.github/workflows/release.yml` (windows-latest: tests → build → release on `v*` with SHA-256).

- [ ] Review, commit.

### Task 11: Acceptance

- [ ] Install the built setup.exe on this PC; check task exists (`schtasks /query /tn DiskGuardian`), shortcuts present, forced low-space toast, multi-drive with `subst`, uninstall leaves no task/shortcuts. Final whole-branch review.
